import asyncio
import os
import importlib

try:
    import aiosqlite  # type: ignore
except Exception:  # pragma: no cover
    aiosqlite = None

def run_database_tests():
    if aiosqlite is None:
        return

    async def _run():
        os.environ["DB_DIALECT"] = "sqlite"
        os.environ["DB_PATH"] = ":memory:"

        import word_counter_dsc.config as config
        importlib.reload(config)

        import word_counter_dsc.database as database
        importlib.reload(database)
        init_db = database.init_db

        class FakeBot:
            db_lock = None
            dbx = None

        bot = FakeBot()

        # ✅ Isolated DB per test run (in-memory)
        await init_db(bot)

        # ✅ Verify schema exists
        row = await bot.dbx.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='word_counts'"
        )
        if not row:
            raise Exception("DB schema missing: word_counts table not created")

        # ✅ Insert + upsert test
        await bot.dbx.execute("""
            INSERT INTO word_counts (guild_id, channel_id, user_id, word, count)
            VALUES (1, 1, 1, 'hello', 1)
            ON CONFLICT(guild_id, channel_id, user_id, word)
            DO UPDATE SET count = word_counts.count + excluded.count
        """)

        await bot.dbx.execute("""
            INSERT INTO word_counts (guild_id, channel_id, user_id, word, count)
            VALUES (1, 1, 1, 'hello', 2)
            ON CONFLICT(guild_id, channel_id, user_id, word)
            DO UPDATE SET count = word_counts.count + excluded.count
        """)

        await bot.dbx.commit()

        row = await bot.dbx.fetchone("""
            SELECT count FROM word_counts
            WHERE guild_id=1 AND channel_id=1 AND user_id=1 AND word='hello'
        """)
        c = row[0]

        if c != 3:
            raise Exception(f"Upsert failed. Expected 3, got {c}")

        await bot.dbx.close()

    asyncio.run(_run())
