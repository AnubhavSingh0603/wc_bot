import asyncio

try:
    import aiosqlite  # type: ignore
except Exception:  # pragma: no cover
    aiosqlite = None

def run_concurrency_tests():
    if aiosqlite is None:
        return

    async def _run():
        db = await aiosqlite.connect(":memory:")
        await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
        await db.commit()

        async def insert_one(i: int):
            await db.execute("INSERT INTO t (value) VALUES (?)", (str(i),))

        # Run many inserts concurrently, then commit once (more realistic)
        await asyncio.gather(*(insert_one(i) for i in range(200)))
        await db.commit()

        cur = await db.execute("SELECT COUNT(*) FROM t")
        count = (await cur.fetchone())[0]
        if count != 200:
            raise Exception(f"Concurrency insert mismatch. Expected 200 got {count}")

        await db.close()

    asyncio.run(_run())
