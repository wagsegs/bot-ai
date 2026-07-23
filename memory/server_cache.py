"""Server cache: members, roles, channels on startup."""

from typing import Optional

import discord


class ServerCache:
    def __init__(self) -> None:
        self._guilds: dict[int, dict] = {}

    async def warm(self, guild: discord.Guild) -> None:
        members = {}
        for member in guild.members:
            roles = [r.name for r in member.roles if r.name != "@everyone"]
            members[member.id] = {
                "display_name": member.display_name,
                "nickname": member.nick or "",
                "roles": roles,
                "top_role": member.top_role.name if member.top_role else "",
            }
        channels = {ch.id: ch.name for ch in guild.channels if hasattr(ch, "name")}
        role_names = [r.name for r in guild.roles if r.name != "@everyone"]
        self._guilds[guild.id] = {
            "name": guild.name,
            "members": members,
            "channels": channels,
            "roles": role_names,
        }

    def size(self) -> int:
        total = 0
        for g in self._guilds.values():
            total += len(g.get("members", {}))
            total += len(g.get("channels", {}))
            total += len(g.get("roles", []))
        return total

    def get_member(self, guild_id: int, user_id: int) -> Optional[dict]:
        guild = self._guilds.get(guild_id, {})
        return guild.get("members", {}).get(user_id)

    def build_context_block(
        self,
        guild_id: int,
        current_user: Optional[discord.Member],
        mentioned_users: list[discord.Member] | None = None,
    ) -> str:
        lines = ["=== Server Context ===", ""]
        if current_user is None:
            lines.extend(["Current User", "Display Name: Unknown", ""])
        else:
            cached = self.get_member(guild_id, current_user.id)
            display = cached["display_name"] if cached else current_user.display_name
            roles = cached["roles"] if cached else [r.name for r in current_user.roles if r.name != "@everyone"]
            lines.extend([
                "Current User",
                f"Display Name: {display}",
                f"Highest Role: {cached['top_role'] if cached else getattr(current_user.top_role, 'name', 'None')}",
                "Roles:",
            ])
            lines.extend(f"- {r}" for r in roles[:8]) if roles else lines.append("- None")
            admin = current_user.guild_permissions.administrator
            lines.append(f"Administrator: {'Yes' if admin else 'No'}")
            lines.append("")

        if mentioned_users:
            lines.append("Mentioned Users")
            for member in mentioned_users[:4]:
                cached = self.get_member(guild_id, member.id)
                display = cached["display_name"] if cached else member.display_name
                lines.append(f"Display Name: {display}")
                lines.append(f"Highest Role: {cached['top_role'] if cached else getattr(member.top_role, 'name', 'None')}")
                lines.append("")
        return "\n".join(lines).strip()

    def clear(self) -> None:
        self._guilds = {}
