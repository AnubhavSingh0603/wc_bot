from __future__ import annotations

import argparse
import asyncio
import os
from collections import defaultdict
from typing import Iterable

from word_counter_dsc.database import DBX, init_db
from word_counter_dsc.stopwords_core import CORE_STOPWORDS


TABLE_WORD_COLUMNS = [
    ("word_counts", "word"),
    ("keywords", "word"),
    ("keyword_medals", "word"),
    ("keyword_removals", "word"),
]


def _clean_words(words: Iterable[str]) -> list[str]:
    return sorted({str(w).strip().lower() for w in words if str(w).strip()})


def _in_clause(words: list[str]) -> str:
    return ",".join(["?"] * len(words))


async def _count_exact_words(db: DBX, table: str, word_column: str, words: list[str], guild_id: int | None = None) -> int:
    if not words:
        return 0
    q = _in_clause(words)
    if guild_id is None:
        row = await db.fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE {word_column} IN ({q})", tuple(words))
    else:
        row = await db.fetchone(
            f"SELECT COUNT(*) AS n FROM {table} WHERE guild_id=? AND {word_column} IN ({q})",
            (guild_id, *words),
        )
    return int(row["n"] if row is not None else 0)


async def _delete_exact_words(db: DBX, table: str, word_column: str, words: list[str], guild_id: int | None = None) -> int:
    if not words:
        return 0
    q = _in_clause(words)
    if guild_id is None:
        res = await db.execute(f"DELETE FROM {table} WHERE {word_column} IN ({q})", tuple(words))
    else:
        res = await db.execute(
            f"DELETE FROM {table} WHERE guild_id=? AND {word_column} IN ({q})",
            (guild_id, *words),
        )
    return db._rowcount(res)


async def _count_abbreviations(db: DBX, words: list[str], guild_id: int | None = None) -> int:
    if not words:
        return 0
    q = _in_clause(words)
    if guild_id is None:
        row = await db.fetchone(
            f"""
            SELECT COUNT(*) AS n
            FROM abbreviations
            WHERE abbreviation IN ({q}) OR lower(trim(expansion)) IN ({q})
            """,
            (*words, *words),
        )
    else:
        row = await db.fetchone(
            f"""
            SELECT COUNT(*) AS n
            FROM abbreviations
            WHERE guild_id=? AND (abbreviation IN ({q}) OR lower(trim(expansion)) IN ({q}))
            """,
            (guild_id, *words, *words),
        )
    return int(row["n"] if row is not None else 0)


async def _delete_abbreviations(db: DBX, words: list[str], guild_id: int | None = None) -> int:
    if not words:
        return 0
    q = _in_clause(words)
    if guild_id is None:
        res = await db.execute(
            f"""
            DELETE FROM abbreviations
            WHERE abbreviation IN ({q}) OR lower(trim(expansion)) IN ({q})
            """,
            (*words, *words),
        )
    else:
        res = await db.execute(
            f"""
            DELETE FROM abbreviations
            WHERE guild_id=? AND (abbreviation IN ({q}) OR lower(trim(expansion)) IN ({q}))
            """,
            (guild_id, *words, *words),
        )
    return db._rowcount(res)


async def estimate_server_stopwords(db: DBX) -> dict[str, int]:
    rows = await db.fetchall("SELECT guild_id, word FROM stopwords", ())
    by_guild: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        by_guild[int(r["guild_id"])].append(str(r["word"]))

    totals = {table: 0 for table, _ in TABLE_WORD_COLUMNS}
    totals["abbreviations"] = 0
    for gid, words0 in by_guild.items():
        words = _clean_words(words0)
        for table, col in TABLE_WORD_COLUMNS:
            totals[table] += await _count_exact_words(db, table, col, words, gid)
        totals["abbreviations"] += await _count_abbreviations(db, words, gid)
    return totals


async def prune_server_stopwords(db: DBX) -> dict[str, int]:
    rows = await db.fetchall("SELECT guild_id, word FROM stopwords", ())
    by_guild: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        by_guild[int(r["guild_id"])].append(str(r["word"]))

    totals = {table: 0 for table, _ in TABLE_WORD_COLUMNS}
    totals["abbreviations"] = 0
    for gid, words0 in by_guild.items():
        purged = await db.purge_stopword_related_data(gid, _clean_words(words0))
        for table, n in purged.items():
            totals[table] = totals.get(table, 0) + int(n)
    return totals


async def estimate_core_stopwords(db: DBX) -> dict[str, int]:
    words = _clean_words(CORE_STOPWORDS)
    totals = {table: await _count_exact_words(db, table, col, words, None) for table, col in TABLE_WORD_COLUMNS}
    totals["stopwords"] = await _count_exact_words(db, "stopwords", "word", words, None)
    totals["abbreviations"] = await _count_abbreviations(db, words, None)
    return totals


async def prune_core_stopwords(db: DBX) -> dict[str, int]:
    words = _clean_words(CORE_STOPWORDS)
    totals = {table: await _delete_exact_words(db, table, col, words, None) for table, col in TABLE_WORD_COLUMNS}
    totals["stopwords"] = await _delete_exact_words(db, "stopwords", "word", words, None)
    totals["abbreviations"] = await _delete_abbreviations(db, words, None)
    return totals


def _print_counts(title: str, counts: dict[str, int]) -> None:
    total = sum(int(v) for v in counts.values())
    print(f"{title}: {total} row(s)")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Prune existing rows for configured/core stopwords without touching unrelated bot data.")
    parser.add_argument("--sqlite-path", default="word_counts.db", help="SQLite DB path when DATABASE_URL is not set.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL for Neon/Postgres.")
    parser.add_argument("--include-core", action="store_true", help="Also prune built-in core stopwords globally.")
    parser.add_argument("--apply", action="store_true", help="Actually delete rows. Without this, the command is a dry run.")
    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    db = await init_db(url=args.database_url, sqlite_path=args.sqlite_path)
    try:
        if args.apply:
            server_counts = await prune_server_stopwords(db)
            _print_counts("Deleted configured server stopword data", server_counts)
            if args.include_core:
                core_counts = await prune_core_stopwords(db)
                _print_counts("Deleted built-in core stopword data", core_counts)
        else:
            server_counts = await estimate_server_stopwords(db)
            _print_counts("Dry run: configured server stopword data that would be deleted", server_counts)
            if args.include_core:
                core_counts = await estimate_core_stopwords(db)
                _print_counts("Dry run: built-in core stopword data that would be deleted", core_counts)
            print("No rows deleted. Re-run with --apply to prune.")
    finally:
        await db.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
