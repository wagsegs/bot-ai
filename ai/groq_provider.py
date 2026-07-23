import logging

from openai import AsyncOpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

from ai.action_planner import ActionPlanner
from config import GROQ_API_KEY

logger = logging.getLogger("botkun.groq")

MODEL = "llama-3.3-70b-versatile"


class GroqProvider:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        self.planner = ActionPlanner()
        self.status = "ready"
        self._last_token_count: int | None = None

    @property
    def last_token_count(self) -> int | None:
        return self._last_token_count

    async def chat(self, messages: list[dict]) -> dict:
        logger.info("Groq request: model=%s", MODEL)
        try:
            response = await self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.9,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                self._last_token_count = getattr(usage, "total_tokens", None)

            response_text = ""
            if response.choices:
                response_text = getattr(response.choices[0].message, "content", "") or ""

            self.status = "ready"
            parsed = self.planner.parse_response(response_text)
            return parsed
        except AuthenticationError as exc:
            self.status = "auth_error"
            logger.error("Groq auth error: %s", exc)
            raise
        except RateLimitError as exc:
            self.status = "rate_limited"
            logger.warning("Groq rate limit: %s", exc)
            raise
        except APIConnectionError as exc:
            self.status = "network_error"
            logger.error("Groq connection error: %s", exc)
            raise
        except APIStatusError as exc:
            self.status = "provider_error"
            logger.error("Groq API error: %s", exc)
            raise
        except Exception as exc:
            self.status = "provider_error"
            logger.error("Groq unexpected error: %s", exc)
            raise
