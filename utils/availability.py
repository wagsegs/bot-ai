import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mi_bombo.availability")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class BotAvailability:
    """Manages bot online/offline cycles with configurable durations and persistence."""
    
    def __init__(self) -> None:
        # Configurable durations (in minutes) - can be overridden by env vars
        self.online_min = int(os.getenv("BOT_ONLINE_MIN", "25"))
        self.online_max = int(os.getenv("BOT_ONLINE_MAX", "40"))
        self.offline_min = int(os.getenv("BOT_OFFLINE_MIN", "15"))
        self.offline_max = int(os.getenv("BOT_OFFLINE_MAX", "60"))
        
        # State file for persistence
        self.state_file = Path(os.getenv("BOT_STATE_FILE", "bot_state.json"))
        
        # Current state
        self._is_online: bool = True
        self._window_end: datetime = datetime.now(timezone.utc)
        self._load_state()
        
        logger.info(f"BotAvailability initialized: online={self._is_online}, window_end={self._window_end}")
    
    def _load_state(self) -> None:
        """Load state from disk if available."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self._is_online = data.get("is_online", True)
                    window_end_str = data.get("window_end")
                    if window_end_str:
                        self._window_end = datetime.fromisoformat(window_end_str)
                        if self._window_end.tzinfo is None:
                            self._window_end = self._window_end.replace(tzinfo=timezone.utc)
                    logger.info(f"Loaded state from disk: online={self._is_online}, window_end={self._window_end}")
        except Exception as exc:
            logger.warning(f"Failed to load state from disk: {exc}, starting fresh")
            self._start_new_window()
    
    def _save_state(self) -> None:
        """Save current state to disk."""
        try:
            data = {
                "is_online": self._is_online,
                "window_end": self._window_end.isoformat(),
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to save state to disk: {exc}")
    
    def _start_new_window(self) -> None:
        """Start a new online or offline window with random duration."""
        now = datetime.now(timezone.utc)
        if self._is_online:
            duration_minutes = random.randint(self.online_min, self.online_max)
        else:
            duration_minutes = random.randint(self.offline_min, self.offline_max)
        
        self._window_end = now + timedelta(minutes=duration_minutes)
        logger.info(f"Started new {'online' if self._is_online else 'offline'} window ending at {self._window_end} (duration: {duration_minutes}m)")
        self._save_state()
    
    def _check_and_transition(self) -> None:
        """Check if current window has ended and transition if needed."""
        now = datetime.now(timezone.utc)
        if now >= self._window_end:
            # Window ended, flip state
            self._is_online = not self._is_online
            self._start_new_window()
    
    def is_bot_available(self) -> bool:
        """Check if bot is currently available (online)."""
        self._check_and_transition()
        return self._is_online
    
    def get_status(self) -> dict:
        """Get current status information."""
        self._check_and_transition()
        now = datetime.now(timezone.utc)
        remaining = max(timedelta(0), self._window_end - now)
        return {
            "is_online": self._is_online,
            "window_end": self._window_end.isoformat(),
            "remaining_minutes": int(remaining.total_seconds() / 60),
            "state": "online" if self._is_online else "offline",
        }
    
    def force_online(self, duration_minutes: Optional[int] = None) -> None:
        """Force bot to be online for specified duration (or random online duration)."""
        self._is_online = True
        now = datetime.now(timezone.utc)
        if duration_minutes:
            self._window_end = now + timedelta(minutes=duration_minutes)
        else:
            duration_minutes = random.randint(self.online_min, self.online_max)
            self._window_end = now + timedelta(minutes=duration_minutes)
        logger.info(f"Forced online until {self._window_end}")
        self._save_state()
    
    def force_offline(self, duration_minutes: Optional[int] = None) -> None:
        """Force bot to be offline for specified duration (or random offline duration)."""
        self._is_online = False
        now = datetime.now(timezone.utc)
        if duration_minutes:
            self._window_end = now + timedelta(minutes=duration_minutes)
        else:
            duration_minutes = random.randint(self.offline_min, self.offline_max)
            self._window_end = now + timedelta(minutes=duration_minutes)
        logger.info(f"Forced offline until {self._window_end}")
        self._save_state()


# Global instance
_bot_availability: Optional[BotAvailability] = None


def get_bot_availability() -> BotAvailability:
    """Get or create the global BotAvailability instance."""
    global _bot_availability
    if _bot_availability is None:
        _bot_availability = BotAvailability()
    return _bot_availability


def is_bot_available() -> bool:
    """Convenience function to check if bot is available."""
    return get_bot_availability().is_bot_available()
