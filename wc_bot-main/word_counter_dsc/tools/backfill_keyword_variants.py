from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections import defaultdict
from typing import Any

from word_counter_dsc.database import init_db
from word_counter_dsc.utils import count_configured_keywords


async def _fetch_existing_rows(db, guild_id: int | None = None) -> list[Any]:
    if guild_id is None:
        return await db.fetchall(
            "SELECT guild_id, channel_id, user_id, word, count FROM word_counts ORDER BY guild_id, channel_id, user_id, word",
            (),
        )
    return await db.fetchall(
        "SELECT guild_id, channel_id, user_id, word, count FROM word_counts WHERE guild_id=? ORDER BY channel_id, user_id, word",
        (guild_id,),
    )


async def _fetch_keywords(db, guild_id: int | None = None) -> dict[int, set[str]]:
    if guild_id is None:
        rows = await db.fetchall("SELECT guild_id, word FROM keywords", ())
    else:
        rows = await db.fetchall("SELECT guild_id, word FROM keywords WHERE guild_id=?", (guild_id,))
    out: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        out[int(row["guild_id"])].add(str(row["word"]))
    return out


async def run_backfill(*, database_url: str | None, sqlite_path: str, guild_id: int | None, apply: bool) -> None:
    db = await init_db(url=database_url, sqlite_path=sqlite_path)
    try:
        keywords_by_guild = await _fetch_keywords(db, guild_id)
        rows = await _fetch_existing_rows(db, guild_id)
        increments: dict[tuple[int, int, int, str], int] = defaultdict(int)

        for row in rows:
            gid = int(row["guild_id"])
            word = str(row["word"])
            count = int(row["count"])
            if count <= 0:
                continue
            keywords = keywords_by_guild.get(gid, set())
            if not keywords:
                continue
            hits = count_configured_keywords([word], keywords)
            for kw, multiplier in hits.items():
                if kw == word:
                    continue
                increments[(gid, int(row["channel_id"]), int(row["user_id"]), kw)] += count * multiplier

        print(f"Candidate canonical keyword increments: {len(increments)}")
        print(f"Total count to add into canonical keyword rows: {sum(increments.values())}")

        if not apply:
            print("DRY RUN ONLY. Re-run with --apply to write changes.")
            return

        now = int(time.time())
        for (gid, cid, uid, kw), count in sorted(increments.items()):
            await db.execute(
                """
                INSERT INTO word_counts (guild_id, channel_id, user_id, word, count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id, user_id, word)
                DO UPDATE SET count = word_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, cid, uid, kw, count, now),
            )
        print("Backfill applied successfully.")
    finally:
        await db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill canonical keyword counts from existing variant word_counts rows.")
    parser.add_argument("--sqlite-path", default="word_counts.db", help="SQLite DB path when DATABASE_URL is not used.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres/Neon URL. Defaults to DATABASE_URL env var.")
    parser.add_argument("--guild-id", type=int, default=None, help="Optional single guild/server ID to backfill.")
    parser.add_argument("--apply", action="store_true", help="Actually write updates. Without this, performs a dry run.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag for readability.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_backfill(database_url=args.database_url, sqlite_path=args.sqlite_path, guild_id=args.guild_id, apply=bool(args.apply)))


if __name__ == "__main__":
    main()
