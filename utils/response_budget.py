import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mi_bombo.response_budget")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class ResponseBudget:
    """Tracks API usage and degrades gracefully based on budget thresholds."""
    
    def __init__(self) -> None:
        # Configurable thresholds (percentage of budget used)
        self.threshold_normal = float(os.getenv("BUDGET_THRESHOLD_NORMAL", "50"))  # Below this: normal behavior
        self.threshold_reduced = float(os.getenv("BUDGET_THRESHOLD_REDUCED", "80"))  # Above this: reduce spontaneous joins
        self.threshold_critical = float(os.getenv("BUDGET_THRESHOLD_CRITICAL", "95"))  # Above this: stop spontaneous joins
        self.budget_cap = int(os.getenv("BUDGET_CAP", "100"))  # Total budget per hour
        
        # Time windows for tracking (in minutes)
        self.window_minutes = int(os.getenv("BUDGET_WINDOW_MINUTES", "60"))
        
        # State file for persistence
        self.state_file = Path(os.getenv("BUDGET_STATE_FILE", "budget_state.json"))
        
        # Tracking
        self._request_times: deque[datetime] = deque()
        self._window_start: datetime = datetime.now(timezone.utc)
        self._load_state()
        
        logger.info(f"ResponseBudget initialized: budget_cap={self.budget_cap}, window={self.window_minutes}m")
    
    def _load_state(self) -> None:
        """Load state from disk if available."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    window_start_str = data.get("window_start")
                    if window_start_str:
                        self._window_start = datetime.fromisoformat(window_start_str)
                        if self._window_start.tzinfo is None:
                            self._window_start = self._window_start.replace(tzinfo=timezone.utc)
                    
                    # Check if window has expired
                    now = datetime.now(timezone.utc)
                    if now - self._window_start > timedelta(minutes=self.window_minutes):
                        logger.info("Loaded state window expired, starting fresh")
                        self._reset_window()
                    else:
                        # Load request times within current window
                        saved_times = data.get("request_times", [])
                        for time_str in saved_times:
                            try:
                                req_time = datetime.fromisoformat(time_str)
                                if req_time.tzinfo is None:
                                    req_time = req_time.replace(tzinfo=timezone.utc)
                                if req_time >= self._window_start:
                                    self._request_times.append(req_time)
                            except Exception:
                                continue
                        logger.info(f"Loaded state from disk: {len(self._request_times)} requests in current window")
        except Exception as exc:
            logger.warning(f"Failed to load state from disk: {exc}, starting fresh")
            self._reset_window()
    
    def _save_state(self) -> None:
        """Save current state to disk."""
        try:
            data = {
                "window_start": self._window_start.isoformat(),
                "request_times": [t.isoformat() for t in self._request_times],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to save state to disk: {exc}")
    
    def _reset_window(self) -> None:
        """Reset the tracking window."""
        self._window_start = datetime.now(timezone.utc)
        self._request_times.clear()
        logger.info("Reset budget tracking window")
        self._save_state()
    
    def _prune_old_requests(self) -> None:
        """Remove requests outside the current window."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self.window_minutes)
        
        # Check if we need to reset the window
        if now - self._window_start > timedelta(minutes=self.window_minutes):
            self._reset_window()
            return
        
        # Prune old requests
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()
    
    def record_request(self) -> None:
        """Record a new API request."""
        self._prune_old_requests()
        self._request_times.append(datetime.now(timezone.utc))
        self._save_state()
    
    def get_usage_percentage(self) -> float:
        """Get current usage as percentage of budget."""
        self._prune_old_requests()
        if self.budget_cap <= 0:
            return 0.0
        return (len(self._request_times) / self.budget_cap) * 100
    
    def get_budget_state(self) -> str:
        """Get current budget state: 'normal', 'reduced', 'critical', or 'exhausted'."""
        usage = self.get_usage_percentage()
        
        if usage >= 100:
            return "exhausted"
        elif usage >= self.threshold_critical:
            return "critical"
        elif usage >= self.threshold_reduced:
            return "reduced"
        else:
            return "normal"
    
    def can_respond(self) -> bool:
        """Check if bot can respond based on budget."""
        state = self.get_budget_state()
        return state != "exhausted"
    
    def get_spontaneous_probability_multiplier(self) -> float:
        """Get multiplier for spontaneous join probability based on budget state."""
        state = self.get_budget_state()
        
        if state == "normal":
            return 1.0  # Full probability
        elif state == "reduced":
            return 0.5  # Half probability
        elif state == "critical":
            return 0.0  # No spontaneous joins
        else:  # exhausted
            return 0.0
    
    def get_response_delay_multiplier(self) -> float:
        """Get multiplier for response delay based on budget state."""
        state = self.get_budget_state()
        
        if state == "normal":
            return 1.0  # Normal delay
        elif state == "reduced":
            return 1.5  # 1.5x delay
        elif state == "critical":
            return 2.0  # 2x delay
        else:  # exhausted
            return 0.0  # Shouldn't respond anyway
    
    def get_status(self) -> dict:
        """Get current budget status information."""
        self._prune_old_requests()
        usage = self.get_usage_percentage()
        state = self.get_budget_state()
        
        now = datetime.now(timezone.utc)
        window_end = self._window_start + timedelta(minutes=self.window_minutes)
        remaining = max(timedelta(0), window_end - now)
        
        return {
            "state": state,
            "usage_percentage": round(usage, 2),
            "requests_used": len(self._request_times),
            "budget_cap": self.budget_cap,
            "remaining_minutes": int(remaining.total_seconds() / 60),
            "window_end": window_end.isoformat(),
            "spontaneous_multiplier": self.get_spontaneous_probability_multiplier(),
            "delay_multiplier": self.get_response_delay_multiplier(),
        }


# Global instance
_response_budget: Optional[ResponseBudget] = None


def get_response_budget() -> ResponseBudget:
    """Get or create the global ResponseBudget instance."""
    global _response_budget
    if _response_budget is None:
        _response_budget = ResponseBudget()
    return _response_budget


def record_request() -> None:
    """Convenience function to record a request."""
    get_response_budget().record_request()


def can_respond() -> bool:
    """Convenience function to check if bot can respond based on budget."""
    return get_response_budget().can_respond()


def get_spontaneous_probability_multiplier() -> float:
    """Convenience function to get spontaneous probability multiplier."""
    return get_response_budget().get_spontaneous_probability_multiplier()
