import asyncio
import os
from datetime import datetime
from typing import Any

import asyncpg

SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL", "")
DB_AVAILABLE = bool(SUPABASE_DATABASE_URL)

class PersistentDatabaseClient:
    def __init__(self) -> None:
        self.available = DB_AVAILABLE
        self.pool: asyncpg.Pool | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if not self.available:
            print("=== DB === SUPABASE_DATABASE_URL not configured, persistent memory disabled")
            return
        if self._started:
            return
        try:
            self.pool = await asyncpg.create_pool(dsn=SUPABASE_DATABASE_URL, min_size=1, max_size=4)
            async with self.pool.acquire() as conn:
                await self._initialize_tables(conn)
                await self._verify_connection(conn)
            self._worker_task = asyncio.create_task(self._worker())
            self._started = True
            print("=== DB === asyncpg pool initialized and tables ready")
        except Exception as exc:
            self.available = False
            print("=== DB === failed to initialize persistent storage:", exc)

    async def _initialize_tables(self, conn: asyncpg.Connection) -> None:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                discord_user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                username TEXT,
                display_name TEXT,
                nickname TEXT,
                highest_role TEXT,
                important_roles TEXT,
                join_date TIMESTAMP WITH TIME ZONE,
                last_seen TIMESTAMP WITH TIME ZONE,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                PRIMARY KEY (guild_id, discord_user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                discord_user_id TEXT,
                preference_type TEXT,
                preference_value TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                subject_user_id TEXT,
                object_user_id TEXT,
                relation_type TEXT,
                strength INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quotes (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                quoted_user_id TEXT,
                quote TEXT,
                channel_id TEXT,
                message_id TEXT,
                added_by_user_id TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remembered_topics (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                topic TEXT,
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_history (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                discord_user_id TEXT,
                query TEXT,
                topic TEXT,
                video_url TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_discord_user_id ON users(discord_user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_id ON users(guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_video_history_discord_user_id ON video_history(discord_user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_video_history_guild_id ON video_history(guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_discord_user_id ON user_preferences(discord_user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_guild_id ON user_preferences(guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_guild_id ON relationships(guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_guild_id ON quotes(guild_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_remembered_topics_guild_id ON remembered_topics(guild_id)")

    async def _verify_connection(self, conn: asyncpg.Connection) -> None:
        test_guild = "__verify_guild__"
        test_user = "__verify_user__"
        await conn.execute(
            """
            INSERT INTO users (discord_user_id, guild_id, username, display_name, nickname, highest_role, important_roles, join_date, last_seen, message_count, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now(), 0, now(), now())
            ON CONFLICT (guild_id, discord_user_id) DO NOTHING
            """,
            test_user,
            test_guild,
            "verify",
            "verify",
            "verify",
            "verify",
            "[]",
        )
        row = await conn.fetchrow(
            "SELECT discord_user_id FROM users WHERE guild_id = $1 AND discord_user_id = $2",
            test_guild,
            test_user,
        )
        if not row:
            raise RuntimeError("Database verification failed")

    def _coerce_timestamp(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        return value

    async def _worker(self) -> None:
        if not self.pool:
            return
        while True:
            batch = [await self._queue.get()]
            while len(batch) < 16:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                async with self.pool.acquire() as conn:
                    async with conn.transaction():
                        for item in batch:
                            if item["type"] == "identity":
                                await self._flush_identity(conn, item["payload"])
            except Exception as exc:
                print("=== DB === failed to flush batch:", exc)
                for item in batch:
                    await self._queue.put(item)
                await asyncio.sleep(5)
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _flush_identity(self, conn: asyncpg.Connection, identity: dict[str, Any]) -> None:
        normalized_identity = {
            "discord_user_id": identity["discord_user_id"],
            "guild_id": identity["guild_id"],
            "username": identity["username"],
            "display_name": identity["display_name"],
            "nickname": identity["nickname"],
            "highest_role": identity["highest_role"],
            "important_roles": identity["important_roles"],
            "join_date": self._coerce_timestamp(identity.get("join_date", identity.get("joined_at"))),
            "last_seen": self._coerce_timestamp(identity.get("last_seen")),
            "message_count": identity.get("message_count", 0),
            "created_at": self._coerce_timestamp(identity.get("created_at")),
            "updated_at": self._coerce_timestamp(identity.get("updated_at")),
        }
        await conn.execute(
            """
            INSERT INTO users (
                discord_user_id,
                guild_id,
                username,
                display_name,
                nickname,
                highest_role,
                important_roles,
                join_date,
                last_seen,
                message_count,
                created_at,
                updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (guild_id, discord_user_id) DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                nickname = EXCLUDED.nickname,
                highest_role = EXCLUDED.highest_role,
                important_roles = EXCLUDED.important_roles,
                join_date = COALESCE(EXCLUDED.join_date, users.join_date),
                last_seen = EXCLUDED.last_seen,
                message_count = users.message_count + 1,
                updated_at = EXCLUDED.updated_at
            """,
            normalized_identity["discord_user_id"],
            normalized_identity["guild_id"],
            normalized_identity["username"],
            normalized_identity["display_name"],
            normalized_identity["nickname"],
            normalized_identity["highest_role"],
            normalized_identity["important_roles"],
            normalized_identity["join_date"],
            normalized_identity["last_seen"],
            normalized_identity["message_count"],
            normalized_identity["created_at"],
            normalized_identity["updated_at"],
        )

    async def enqueue_identity(self, identity: dict[str, Any]) -> None:
        if not self.available:
            return
        await self._queue.put({"type": "identity", "payload": identity})
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def flush(self) -> None:
        await self._queue.join()

    async def get_stats(self) -> dict[str, Any]:
        stats = {
            "status": "offline",
            "users": 0,
            "relationships": 0,
            "quotes": 0,
            "topics": 0,
            "queue": self._queue.qsize(),
            "pool": "Unavailable",
        }
        if not self.available or not self.pool:
            return stats
        try:
            async with self.pool.acquire() as conn:
                stats["status"] = "connected"
                stats["users"] = (await conn.fetchval("SELECT COUNT(*) FROM users")) or 0
                stats["relationships"] = (await conn.fetchval("SELECT COUNT(*) FROM relationships")) or 0
                stats["quotes"] = (await conn.fetchval("SELECT COUNT(*) FROM quotes")) or 0
                stats["topics"] = (await conn.fetchval("SELECT COUNT(*) FROM remembered_topics")) or 0
            stats["pool"] = "Healthy"
        except Exception as exc:
            stats["status"] = "degraded"
            stats["pool"] = "Unhealthy"
            print("=== DB === error collecting stats:", exc)
        return stats

persistent_db_client = PersistentDatabaseClient()
