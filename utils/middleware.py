import ast
import asyncio
import json
import logging
import random
import re
from collections import deque
from datetime import datetime, timedelta

from openai import AuthenticationError, APIConnectionError, APIStatusError, RateLimitError

logger = logging.getLogger("mi_bombo.middleware")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class AIRequestMiddleware:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[asyncio.Future[dict]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._request_history: deque[datetime] = deque(maxlen=20)
        self._token_history: deque[tuple[datetime, int]] = deque(maxlen=12)
        self._user_request_history: dict[str, deque[datetime]] = {}
        self._user_cooldowns: dict[str, datetime] = {}
        self._cooldown_until: datetime | None = None
        self._last_warning: dict[str, datetime] = {}
        self._failure_count = 0
        self._lock = asyncio.Lock()
        self._runtime_stats = {
            "successful_requests": 0,
            "failed_requests": 0,
            "retries": 0,
            "repaired_outputs": 0,
            "rate_limit_errors": 0,
            "average_response_ms": 0.0,
            "queue_size": 0,
            "cooldown_activations": 0,
        }
        self._response_times: deque[float] = deque(maxlen=25)
        self._recent_rate_limits: deque[datetime] = deque(maxlen=6)
        self._recovery_instruction = (
            "Your previous response leaked formatting or internal data. "
            "Reply ONLY with natural Discord chat. Never output JSON, metadata, tool fields, XML, YAML, role labels, or code."
        )

    def _log(self, message: str, level: int = logging.INFO) -> None:
        if level == logging.DEBUG:
            logger.debug(message)
        elif level == logging.WARNING:
            logger.warning(message)
        elif level == logging.ERROR:
            logger.error(message)
        else:
            logger.info(message)

    def _prune_history(self, history: deque[datetime]) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=15)
        while history and history[0] < cutoff:
            history.popleft()

    def _prune_token_history(self) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=15)
        while self._token_history and self._token_history[0][0] < cutoff:
            self._token_history.popleft()

    def _prune_rate_limit_history(self) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=20)
        while self._recent_rate_limits and self._recent_rate_limits[0] < cutoff:
            self._recent_rate_limits.popleft()

    def _get_load_state(self) -> str:
        now = datetime.utcnow()
        self._prune_history(self._request_history)
        self._prune_token_history()
        self._prune_rate_limit_history()
        recent_requests = len(self._request_history)
        recent_tokens = sum(tokens for _, tokens in self._token_history)
        if self._cooldown_until and now < self._cooldown_until:
            return "cooldown"
        if self._recent_rate_limits and len(self._recent_rate_limits) >= 2:
            return "slow"
        if recent_requests >= 8 or recent_tokens >= 8000 or self._queue.qsize() >= 4:
            return "very_high"
        if recent_requests >= 5 or recent_tokens >= 4000 or self._queue.qsize() >= 2:
            return "high"
        if recent_requests >= 3 or self._queue.qsize() >= 1:
            return "medium"
        return "normal"

    def _record_request(self) -> None:
        self._request_history.append(datetime.utcnow())

    def _record_token_usage(self, total_tokens: int | None) -> None:
        if total_tokens is None:
            return
        self._token_history.append((datetime.utcnow(), int(total_tokens)))

    def _record_success(self, response_ms: float) -> None:
        self._runtime_stats["successful_requests"] += 1
        self._response_times.append(response_ms)
        self._runtime_stats["average_response_ms"] = round(sum(self._response_times) / len(self._response_times), 2)
        self._log("=== AI MIDDLEWARE === request completed", logging.DEBUG)

    def _record_failure(self) -> None:
        self._runtime_stats["failed_requests"] += 1

    def _record_retry(self) -> None:
        self._runtime_stats["retries"] += 1

    def _record_repair(self) -> None:
        self._runtime_stats["repaired_outputs"] += 1

    def _record_rate_limit(self) -> None:
        self._runtime_stats["rate_limit_errors"] += 1
        self._recent_rate_limits.append(datetime.utcnow())
        if len(self._recent_rate_limits) >= 3:
            self._activate_cooldown(seconds=8 + min(12, 4 * (len(self._recent_rate_limits) - 2)))
            self._runtime_stats["cooldown_activations"] += 1
            self._log("=== AI MIDDLEWARE === slow mode activated", logging.WARNING)

    def _activate_cooldown(self, seconds: int = 20) -> None:
        self._cooldown_until = datetime.utcnow() + timedelta(seconds=seconds)
        self._log("=== AI MIDDLEWARE === cooldown activated", logging.WARNING)

    def _get_spam_state(self, user_id: str | None) -> tuple[str, float | None]:
        if not user_id:
            return "allow", None

        cooldown_until = self._user_cooldowns.get(user_id)
        if cooldown_until and datetime.utcnow() < cooldown_until:
            return "block", None

        history = self._user_request_history.setdefault(user_id, deque(maxlen=12))
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=12)
        while history and history[0] < cutoff:
            history.popleft()
        history.append(now)
        count = len(history)

        if count <= 5:
            return "allow", None
        if count <= 8:
            return "delay", random.uniform(0.6, 0.9)
        if count <= 12:
            return "delay", random.uniform(1.2, 1.8)

        self._user_cooldowns[user_id] = datetime.utcnow() + timedelta(seconds=8)
        return "block", None

    async def _apply_load_delay(self, state: str) -> None:
        if state == "normal":
            return
        if state == "medium":
            await asyncio.sleep(random.uniform(0.5, 0.8))
            return
        if state == "high":
            await asyncio.sleep(random.uniform(0.9, 1.4))
            return
        if state == "very_high":
            await asyncio.sleep(random.uniform(1.3, 2.0))
            return
        if state == "slow":
            await asyncio.sleep(random.uniform(1.0, 1.8))
            return

    def _looks_like_leaked_format(self, text: str) -> bool:
        lowered = text.lower()
        if not lowered:
            return False
        if lowered in {"null", "undefined", "none"}:
            return True
        if re.fullmatch(r"[\[\]\{\}\s]+", lowered):
            return True
        if "```" in lowered:
            return True
        if re.search(r"</?[a-zA-Z][^>]*>", lowered):
            return True
        if re.search(r"\b(?:assistant|system|user)\s*:", lowered):
            return True
        if re.search(r"(?<![a-z])(?:text|send_gif|gif_query)\s*:", lowered):
            return True
        if re.search(r"\[(?:text|send_gif|gif_query)\]:", lowered):
            return True
        return False

    def _try_parse_mapping(self, text: str) -> dict | None:
        if not text or not isinstance(text, str):
            return None
        candidate = text.strip()
        if not candidate:
            return None
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(candidate)
            except (ValueError, SyntaxError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _collect_visible_reply(self, text: str) -> list[str]:
        visible_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower() in {"null", "undefined", "none"}:
                continue
            if re.fullmatch(r"[\[\]\{\}\s]+", stripped):
                continue
            if stripped.startswith("```") or stripped.endswith("```"):
                continue
            if re.match(r"^\[(?:text|send_gif|gif_query)\]:", stripped, flags=re.I):
                continue
            if re.match(r'^(?:"?(?:text|send_gif|gif_query)"?\s*:)', stripped):
                continue
            if re.search(r"</?[a-zA-Z][^>]*>", stripped):
                cleaned = re.sub(r"</?[^>]+>", "", stripped).strip()
                if cleaned:
                    visible_lines.append(cleaned)
                continue
            prefix_match = re.match(r"(?i)^(assistant|system|user)\s*:\s*(.+)$", stripped)
            if prefix_match and prefix_match.group(2).strip():
                visible_lines.append(prefix_match.group(2).strip())
                continue
            if stripped.startswith("{") and stripped.endswith("}") and ":" in stripped:
                parsed = self._try_parse_mapping(stripped)
                if parsed is not None:
                    reply_value = parsed.get("reply") or parsed.get("text") or parsed.get("message")
                    if isinstance(reply_value, str) and reply_value.strip():
                        visible_lines.append(reply_value.strip())
                        continue
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                continue
            visible_lines.append(stripped)
        return visible_lines

    def _validate_output_text(self, text: str | None, fallback: str | None = None) -> str:
        fallback_message = fallback or "nah my brain lagged for a sec 💀"
        if not text or not isinstance(text, str):
            return fallback_message

        raw_text = text.strip()
        if not raw_text:
            return fallback_message

        parsed_mapping = self._try_parse_mapping(raw_text)
        if parsed_mapping is not None:
            reply_value = parsed_mapping.get("reply") or parsed_mapping.get("text") or parsed_mapping.get("message")
            if isinstance(reply_value, str) and reply_value.strip():
                repaired = reply_value.strip()
                if repaired != raw_text:
                    self._record_repair()
                    self._log("=== AI MIDDLEWARE === output repaired", logging.WARNING)
                return repaired

        visible_lines = self._collect_visible_reply(raw_text)
        if visible_lines:
            cleaned = "\n".join(visible_lines).strip()
            if cleaned and not self._looks_like_leaked_format(cleaned):
                if cleaned != raw_text:
                    self._record_repair()
                    self._log("=== AI MIDDLEWARE === output repaired", logging.WARNING)
                return cleaned

        if self._looks_like_leaked_format(raw_text):
            self._log("=== AI MIDDLEWARE === output rejected", logging.WARNING)
            return fallback_message

        return raw_text

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            self._runtime_stats["queue_size"] = self._queue.qsize()
            self._log(f"=== AI MIDDLEWARE === queue length {self._queue.qsize()}", logging.DEBUG)
            try:
                request_fn = item.get("request_fn")
                retry_request_fn = item.get("retry_request_fn")
                fallback_message = item.get("fallback_message")
                future = item.get("future")
                started_at = datetime.utcnow()

                result = await asyncio.wait_for(request_fn(), timeout=30.0)
                validated_reply = self._validate_output_text(result.get("reply"), fallback_message)
                if not validated_reply or validated_reply == fallback_message:
                    self._record_retry()
                    self._log("=== AI MIDDLEWARE === output failed validation; retrying once", logging.WARNING)
                    retry_result = await asyncio.wait_for(retry_request_fn() if retry_request_fn is not None else request_fn(), timeout=30.0)
                    validated_reply = self._validate_output_text(retry_result.get("reply"), fallback_message)
                    result = retry_result
                if validated_reply != result.get("reply"):
                    result["reply"] = validated_reply
                if not result.get("reply"):
                    self._record_failure()
                    self._log("=== AI MIDDLEWARE === output rejected", logging.WARNING)
                    result["reply"] = fallback_message or "nah my brain lagged for a sec 💀"
                if result.get("gif_category") and not result.get("reply"):
                    result["gif_category"] = None
                if not future.done():
                    future.set_result(result)
                self._record_success((datetime.utcnow() - started_at).total_seconds() * 1000)
            except asyncio.TimeoutError:
                self._record_failure()
                self._log("=== AI MIDDLEWARE === request timed out", logging.ERROR)
                if not future.done():
                    future.set_result({"reply": fallback_message or "nah my brain lagged for a sec 💀", "gif_category": None})
            except RateLimitError:
                self._record_rate_limit()
                self._record_failure()
                self._log("=== AI MIDDLEWARE === rate limit error", logging.WARNING)
                if not future.done():
                    future.set_result({"reply": fallback_message or "nah my brain lagged for a sec 💀", "gif_category": None})
            except Exception as exc:
                self._record_failure()
                self._log(f"=== AI MIDDLEWARE === request failed: {exc}", logging.ERROR)
                if not future.done():
                    future.set_result({"reply": fallback_message or "nah my brain lagged for a sec 💀", "gif_category": None})
            finally:
                self._queue.task_done()

    async def request(self, request_fn, *, user_id: str | None = None, fallback_message: str | None = None, retry_request_fn=None) -> dict:
        async with self._lock:
            state = self._get_load_state()
            if state == "cooldown":
                self._log("=== AI MIDDLEWARE === cooldown activated", logging.WARNING)
                return {"reply": fallback_message or "🎬 Director: \"Cut! Too many actors are trying to improvise at once.\"", "gif_category": None}

            spam_state, spam_delay = self._get_spam_state(user_id)
            if spam_state == "delay" and spam_delay is not None:
                self._log("=== AI MIDDLEWARE === spam detection", logging.DEBUG)
                await asyncio.sleep(spam_delay)
            elif spam_state == "block":
                self._log("=== AI MIDDLEWARE === spam detection", logging.WARNING)
                return {"reply": random.choice(["🎥 Studio's rendering the current scene... give us a second.", "📽️ The production crew is catching up. Hang tight."]), "gif_category": None}

            self._record_request()
            self._log(f"=== AI MIDDLEWARE === rate limiter state={state} queue_length={self._queue.qsize()}", logging.DEBUG)
            await self._apply_load_delay(state)

            if state in {"high", "very_high", "slow"}:
                self._log(f"=== AI MIDDLEWARE === queued request queue_length={self._queue.qsize() + 1}", logging.DEBUG)

        result_future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        await self._queue.put({"request_fn": request_fn, "retry_request_fn": retry_request_fn, "fallback_message": fallback_message, "future": result_future})
        self._runtime_stats["queue_size"] = self._queue.qsize()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

        try:
            result = await result_future
        except Exception:
            result = {"reply": fallback_message or "nah my brain lagged for a sec 💀", "gif_category": None}
        return result

    def get_stats(self) -> dict[str, object]:
        self._runtime_stats["queue_size"] = self._queue.qsize()
        return dict(self._runtime_stats)
