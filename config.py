import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
KLIPY_KEY = os.getenv("KLIPY_KEY", "")
BOT_NAME = os.getenv("BOT_NAME", "Nova")
RESPONSE_DELAY_MIN = float(os.getenv("RESPONSE_DELAY_MIN", "3"))
RESPONSE_DELAY_MAX = float(os.getenv("RESPONSE_DELAY_MAX", "8"))
RESPONSE_DELAY_HEAVY_MIN = float(os.getenv("RESPONSE_DELAY_HEAVY_MIN", "8"))
RESPONSE_DELAY_HEAVY_MAX = float(os.getenv("RESPONSE_DELAY_HEAVY_MAX", "20"))
# Legacy alias (unused — delays are computed dynamically)
RESPONSE_DELAY = float(os.getenv("RESPONSE_DELAY", "1.5"))


def require_config() -> None:
    missing = []
    if not DISCORD_TOKEN:
        missing.append("DISCORD_TOKEN")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
