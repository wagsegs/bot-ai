from datetime import datetime, timedelta, UTC


class DashboardData:
    """Collect telemetry for the ~dashboard command."""

    def __init__(
        self,
        *,
        start_time: datetime,
        provider_status: str,
        ai_enabled: bool,
        queue_stats: dict,
        budget_status: dict,
        availability_status: dict,
        conversation_count: int,
        cache_size: int,
        memory_usage_mb: float,
        bot_latency_ms: float,
        last_error: str | None,
        cache_breakdown: dict[str, int] | None = None,
    ) -> None:
        self.start_time = start_time
        self.provider_status = provider_status
        self.ai_enabled = ai_enabled
        self.queue_stats = queue_stats
        self.budget_status = budget_status
        self.availability_status = availability_status
        self.conversation_count = conversation_count
        self.cache_size = cache_size
        self.memory_usage_mb = memory_usage_mb
        self.bot_latency_ms = bot_latency_ms
        self.last_error = last_error
        self.cache_breakdown = cache_breakdown or {}

    @staticmethod
    def format_uptime(uptime: timedelta) -> str:
        total_seconds = int(uptime.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def build_embed(self) -> dict:
        """Return grouped field data for discord.Embed construction."""
        uptime = datetime.now(UTC) - self.start_time
        provider_label = {
            "ready": "Ready",
            "rate_limited": "Rate Limited",
            "auth_error": "Auth Error",
            "network_error": "Network Error",
            "provider_error": "Provider Error",
        }.get(self.provider_status, self.provider_status.replace("_", " ").title())

        return {
            "system": {
                "ai_enabled": "Enabled" if self.ai_enabled else "Disabled",
                "provider": "Groq (llama-3.3-70b-versatile)",
                "provider_status": provider_label,
                "uptime": self.format_uptime(uptime),
            },
            "performance": {
                "api_latency_ms": round(self.bot_latency_ms),
                "avg_response_ms": self.queue_stats.get("average_response_ms", 0),
                "queue_size": str(self.queue_stats.get("queue_size", 0)),
                "current_rate": f"{self.queue_stats.get('current_rate', 0)}/10s",
                "requests_per_min": self._requests_per_min(),
            },
            "availability": {
                "state": self.availability_status.get('state', 'unknown').upper(),
                "remaining_minutes": str(self.availability_status.get('remaining_minutes', 0)),
                "budget_state": self.budget_status.get('state', 'unknown').upper(),
                "budget_usage": f"{self.budget_status.get('usage_percentage', 0)}%",
            },
            "memory": {
                "conversations": str(self.conversation_count),
                "cache_size": str(self.cache_size),
                "memory_mb": f"{round(self.memory_usage_mb, 1)} MB",
            },
            "statistics": {
                "success": str(self.queue_stats.get("successful_requests", 0)),
                "failures": str(self.queue_stats.get("failed_requests", 0)),
                "dropped": str(self.queue_stats.get("overflow_drops", 0)),
                "last_error": self.last_error or "None",
            },
            "server_cache": {
                "members": str(self.cache_breakdown.get("members", 0)),
                "channels": str(self.cache_breakdown.get("channels", 0)),
                "roles": str(self.cache_breakdown.get("roles", 0)),
            },
            "last_updated": datetime.now(UTC).strftime("%H:%M:%S UTC"),
        }

    def _requests_per_min(self) -> str:
        success = self.queue_stats.get("successful_requests", 0)
        uptime_min = max(1, (datetime.now(UTC) - self.start_time).total_seconds() / 60)
        return f"{round(success / uptime_min, 1)}"
