import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from utils.supabase_memory import PersistentDatabaseClient


class SupabaseMemoryTimestampTests(unittest.TestCase):
    def test_coerce_timestamp_converts_string_to_datetime(self) -> None:
        client = PersistentDatabaseClient()

        value = client._coerce_timestamp("2024-01-02T03:04:05+00:00")

        self.assertIsInstance(value, datetime)
        self.assertEqual(value, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_flush_identity_normalizes_timestamps_before_db_insert(self) -> None:
        client = PersistentDatabaseClient()
        conn = AsyncMock()
        identity = {
            "discord_user_id": "1",
            "guild_id": "2",
            "username": "alice",
            "display_name": "Alice",
            "nickname": "ali",
            "highest_role": "member",
            "important_roles": "[]",
            "join_date": "2024-01-02T03:04:05+00:00",
            "last_seen": "2024-01-02T03:05:05+00:00",
            "message_count": 1,
            "created_at": "2024-01-02T03:06:05+00:00",
            "updated_at": "2024-01-02T03:07:05+00:00",
        }

        asyncio.run(client._flush_identity(conn, identity))

        args = conn.execute.await_args.args
        self.assertIsInstance(args[8], datetime)
        self.assertIsInstance(args[9], datetime)
        self.assertEqual(args[10], 1)
        self.assertIsInstance(args[11], datetime)
        self.assertIsInstance(args[12], datetime)


if __name__ == "__main__":
    unittest.main()
