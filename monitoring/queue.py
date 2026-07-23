import asyncio
import logging
import random
from datetime import datetime
from typing import Callable, Awaitable

from openai import AuthenticationError, APIConnectionError, APIStatusError, RateLimitError

from monitoring.rate_limit import RateLimiter

logger = logging.getLogger("botkun.queue")

OVERFLOW_QUEUE_SIZE = 20
FALLBACK_REPLIES = [
    "nah my brain lagged for a sec 💀",
    "brain lag",
    "thinking machine exploded",
]

RECOVERY_INSTRUCTION = (
    "Your previous response leaked formatting or internal data. "
    "Reply ONLY with natural Discord chat. Never output JSON, metadata, tool fields, XML, YAML, role labels, or code."
)


class RequestQueue:
    """Queue Groq requests instead of rejecting; overflow drops new requests."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._rate_limiter = RateLimiter()
        self._response_times: list[float] = []
        self._last_error: str | None = None
        self._stats = {
            "successful_requests": 0,
            "failed_requests": 0,
            "retries": 0,
            "repaired_outputs": 0,
            "rate_limit_errors": 0,
            "average_response_ms": 0.0,
            "queue_size": 0,
            "overflow_drops": 0,
        }

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_stats(self) -> dict:
        self._stats["queue_size"] = self._queue.qsize()
        self._stats["current_rate"] = self._rate_limiter.current_rate()
        return dict(self._stats)

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            self._stats["queue_size"] = self._queue.qsize()
            future = item["future"]
            request_fn = item["request_fn"]
            retry_fn = item.get("retry_request_fn")
            fallback = item.get("fallback_message") or random.choice(FALLBACK_REPLIES)
            validate_fn = item.get("validate_fn")

            started = datetime.utcnow()
            try:
                wait = self._rate_limiter.wait_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)

                self._rate_limiter.record()
                result = await asyncio.wait_for(request_fn(), timeout=30.0)

                if validate_fn:
                    validated = validate_fn(result.get("reply"), fallback)
                    if validated != result.get("reply"):
                        self._stats["repaired_outputs"] += 1
                    if not validated or validated == fallback:
                        self._stats["retries"] += 1
                        retry_call = retry_fn or request_fn
                        result = await asyncio.wait_for(retry_call(), timeout=30.0)
                        if validate_fn:
                            validated = validate_fn(result.get("reply"), fallback)
                            if validated != result.get("reply"):
                                self._stats["repaired_outputs"] += 1
                            result["reply"] = validated
                    else:
                        result["reply"] = validated

                if not result.get("reply"):
                    result["reply"] = fallback

                if not future.done():
                    future.set_result(result)
                elapsed = (datetime.utcnow() - started).total_seconds() * 1000
                self._response_times.append(elapsed)
                if len(self._response_times) > 25:
                    self._response_times = self._response_times[-25:]
                self._stats["average_response_ms"] = round(
                    sum(self._response_times) / len(self._response_times), 2
                )
                self._stats["successful_requests"] += 1
            except RateLimitError as exc:
                self._stats["rate_limit_errors"] += 1
                self._stats["failed_requests"] += 1
                self._last_error = str(exc)
                if not future.done():
                    future.set_result({"reply": fallback, "gif_category": None, "actions": []})
            except (asyncio.TimeoutError, AuthenticationError, APIConnectionError, APIStatusError, Exception) as exc:
                self._stats["failed_requests"] += 1
                self._last_error = str(exc)
                logger.error("Request failed: %s", exc)
                if not future.done():
                    future.set_result({"reply": fallback, "gif_category": None, "actions": []})
            finally:
                self._queue.task_done()

    async def enqueue(
        self,
        request_fn: Callable[[], Awaitable[dict]],
        *,
        user_id: str | None = None,
        fallback_message: str | None = None,
        retry_request_fn: Callable[[], Awaitable[dict]] | None = None,
        validate_fn=None,
        spam_block: bool = False,
    ) -> dict:
        if spam_block:
            self._stats["overflow_drops"] += 1
            return {"reply": "", "gif_category": None, "actions": [], "dropped": True}

        async with self._lock:
            if self._queue.qsize() >= OVERFLOW_QUEUE_SIZE:
                self._stats["overflow_drops"] += 1
                return {"reply": "", "gif_category": None, "actions": [], "dropped": True}

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        await self._queue.put({
            "request_fn": request_fn,
            "retry_request_fn": retry_request_fn,
            "fallback_message": fallback_message,
            "validate_fn": validate_fn,
            "future": future,
        })
        self._stats["queue_size"] = self._queue.qsize()

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

        try:
            return await future
        except Exception:
            self._stats["failed_requests"] += 1
            return {"reply": "", "gif_category": None, "actions": [], "dropped": True}
