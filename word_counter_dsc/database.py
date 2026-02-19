from __future__ import annotations

import os
from collections.abc import Iterable as IterABC
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import aiosqlite

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS word_counts (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id, user_id, word)
);

CREATE TABLE IF NOT EXISTS keywords (
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS stopwords (
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS keyword_removals (
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    removed_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, word, removed_at)
);

CREATE TABLE IF NOT EXISTS keyword_medals (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    tier INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    awarded_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, word)
);

CREATE TABLE IF NOT EXISTS app_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS abbreviations (
    guild_id INTEGER NOT NULL,
    abbreviation TEXT NOT NULL,
    expansion TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, abbreviation)
);

CREATE TABLE IF NOT EXISTS emoji_counts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    emoji_name TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, emoji_name)
);

"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS word_counts (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    count BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, channel_id, user_id, word)
);

CREATE TABLE IF NOT EXISTS keywords (
    guild_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS stopwords (
    guild_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS keyword_removals (
    guild_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    removed_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, word, removed_at)
);

CREATE TABLE IF NOT EXISTS keyword_medals (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    tier INTEGER NOT NULL,
    total_count BIGINT NOT NULL,
    awarded_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id, word)
);

CREATE TABLE IF NOT EXISTS app_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS abbreviations (
    guild_id BIGINT NOT NULL,
    abbreviation TEXT NOT NULL,
    expansion TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, abbreviation)
);

CREATE TABLE IF NOT EXISTS emoji_counts (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    emoji_name TEXT NOT NULL,
    count BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id, emoji_name)
);
"""


class DBX:
    dialect: str

    @staticmethod
    def _norm_params(params: Any | None) -> list[Any]:
        """Normalize params into a list. Accepts scalars (int, str, etc.)."""
        if params is None:
            return []
        if isinstance(params, (list, tuple)):
            return list(params)
        # Don't treat strings/bytes as iterables for SQL params
        if isinstance(params, (str, bytes, bytearray)):
            return [params]
        # If it's an iterable (e.g., generator), materialize it
        try:
            if isinstance(params, IterABC):
                return list(params)  # type: ignore[arg-type]
        except Exception:
            pass
        # Scalar (int, float, etc.)
        return [params]

    def _q(self, sql: str) -> str:
        raise NotImplementedError

    async def execute(self, sql: str, params: Any = None) -> Any:
        raise NotImplementedError

    async def fetchone(self, sql: str, params: Any = None) -> Optional[Any]:
        raise NotImplementedError

    async def fetchall(self, sql: str, params: Any = None) -> list[Any]:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


@dataclass
class SQLiteDBX(DBX):
    sqlite_path: str
    dialect: str = "sqlite"
    _conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> "SQLiteDBX":
        self._conn = await aiosqlite.connect(self.sqlite_path)
        # Return rows as dict-like objects (so code can do row["col"]) like asyncpg.
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQLITE)
        await self._conn.commit()
        await self._migrate_keyword_removals()
        return self


    async def _ensure_app_meta(self) -> None:
        await self.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)", ())

    async def _migrate_keyword_removals(self) -> None:
        # If legacy schema had PRIMARY KEY(guild_id, word, removed_at), migrate to PRIMARY KEY(guild_id, word)
        rows = await self.fetchall("PRAGMA table_info(keyword_removals)", ())
<<<<<<< HEAD
        # aiosqlite.Row supports dict-style indexing but not .get()
        pk_cols = [r["name"] for r in rows if int(r["pk"]) > 0]
=======
        pk_cols = [r["name"] for r in rows if int(r.get("pk", 0)) > 0]
>>>>>>> ebbd5a6af7ba727497c5c2b2d64308a2d8d1a60c
        if pk_cols == ["guild_id", "word", "removed_at"]:
            await self.execute(
                "CREATE TABLE IF NOT EXISTS keyword_removals_new (guild_id INTEGER NOT NULL, word TEXT NOT NULL, removed_at INTEGER NOT NULL, PRIMARY KEY(guild_id, word))",
                (),
            )
            # keep latest removed_at per (guild_id, word)
            await self.execute(
                """
                INSERT OR REPLACE INTO keyword_removals_new (guild_id, word, removed_at)
                SELECT guild_id, word, MAX(removed_at) AS removed_at
                FROM keyword_removals
                GROUP BY guild_id, word
                """,
                (),
            )
            await self.execute("DROP TABLE keyword_removals", ())
            await self.execute("ALTER TABLE keyword_removals_new RENAME TO keyword_removals", ())

    async def apply_core_stopwords(self, core_words: list[str], hash_value: str) -> None:
        # Purge any legacy counted stopwords and keep a hash in app_meta so we only do it when the core list changes.
        await self._ensure_app_meta()
        row = await self.fetchone("SELECT value FROM app_meta WHERE key='core_stopwords_hash'", ())
        if not row or str(row["value"]) != hash_value:
            # purge
            if core_words:
                q = "DELETE FROM word_counts WHERE word IN (" + ",".join(["?"] * len(core_words)) + ")"
                await self.execute(q, tuple(core_words))
                q2 = "DELETE FROM keywords WHERE word IN (" + ",".join(["?"] * len(core_words)) + ")"
                await self.execute(q2, tuple(core_words))
                q3 = "DELETE FROM stopwords WHERE word IN (" + ",".join(["?"] * len(core_words)) + ")"
                await self.execute(q3, tuple(core_words))
            await self.execute(
                "INSERT OR REPLACE INTO app_meta(key,value) VALUES ('core_stopwords_hash', ?)",
                (hash_value,),
            )

    def _q(self, sql: str) -> str:
        return sql

    async def execute(self, sql: str, params: Any = None) -> Any:
        assert self._conn is not None
        cur = await self._conn.execute(self._q(sql), tuple(self._norm_params(params)))
        await self._conn.commit()
        return cur.rowcount

    async def fetchone(self, sql: str, params: Any = None) -> Optional[Any]:
        assert self._conn is not None
        cur = await self._conn.execute(self._q(sql), tuple(self._norm_params(params)))
        return await cur.fetchone()

    async def fetchall(self, sql: str, params: Any = None) -> list[Any]:
        assert self._conn is not None
        cur = await self._conn.execute(self._q(sql), tuple(self._norm_params(params)))
        return await cur.fetchall()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


@dataclass
class PostgresDBX(DBX):
    url: str
    dialect: str = "postgres"
    _pool: Any = None

    async def init(self) -> "PostgresDBX":
        if asyncpg is None:
            raise RuntimeError("asyncpg is not installed")
        self._pool = await asyncpg.create_pool(self.url, min_size=1, max_size=10, command_timeout=60)
        # asyncpg does not reliably accept multi-statement SQL via a single execute call.
        # Execute statements one-by-one.
        stmts = [s.strip() for s in SCHEMA_POSTGRES.split(";") if s.strip()]
        for s in stmts:
            await self.execute(s + ";")

        # --- Compatibility migrations (older schema variants) ---
        # Some earlier versions used different column names like `keyword`/`abbr`.
        # Since we use CREATE TABLE IF NOT EXISTS above, existing tables won't be altered.
        # Here we *safely* rename legacy columns to the current canonical names.
        async with self._pool.acquire() as conn:
            async def has_col(table: str, col: str) -> bool:
                q = """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2
                LIMIT 1
                """
                return (await conn.fetchval(q, table, col)) is not None

            # column renames: (table, old, new)
            renames = [
                ("keywords", "keyword", "word"),
                ("stopwords", "stopword", "word"),
                ("keyword_removals", "keyword", "word"),
                ("keyword_medals", "keyword", "word"),
                ("word_counts", "keyword", "word"),
                ("abbreviations", "abbr", "abbreviation"),
            ]

            for table, old, new in renames:
                if await has_col(table, old) and not await has_col(table, new):
                    await conn.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}";')

            # Ensure timestamp columns exist (older schemas might not have them)
            # We keep them NOT NULL DEFAULT 0 to avoid breaking existing rows.
            add_cols = [
                ("keywords", "created_at", "BIGINT"),
                ("stopwords", "created_at", "BIGINT"),
                ("abbreviations", "created_at", "BIGINT"),
                ("word_counts", "updated_at", "BIGINT"),
                ("keyword_removals", "removed_at", "BIGINT"),
                # medals (older schemas might have only (guild_id,user_id,keyword,count) etc.)
                ("keyword_medals", "tier", "INTEGER"),
                ("keyword_medals", "awarded_at", "BIGINT"),
                ("keyword_medals", "total_count", "BIGINT"),
            ]
            for table, col, typ in add_cols:
                if not await has_col(table, col):
                    await conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {typ} NOT NULL DEFAULT 0;')

        return self


    async def _ensure_app_meta(self) -> None:
        await self.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)", ())

    async def _migrate_keyword_removals(self) -> None:
        # Ensure PRIMARY KEY(guild_id, word) on keyword_removals for ON CONFLICT to work reliably.
        # If a legacy constraint exists, rebuild the table.
        rows = await self.fetchall(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE c.relname = 'keyword_removals' AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
            """,
            (),
        )
        pk_cols = [str(r["attname"]) for r in rows] if rows else []
        if pk_cols and pk_cols != ["guild_id", "word"]:
            await self.execute(
                """
                CREATE TABLE IF NOT EXISTS keyword_removals_new (
                  guild_id BIGINT NOT NULL,
                  word TEXT NOT NULL,
                  removed_at BIGINT NOT NULL,
                  PRIMARY KEY(guild_id, word)
                );
                """,
                (),
            )
            await self.execute(
                """
                INSERT INTO keyword_removals_new (guild_id, word, removed_at)
                SELECT guild_id, word, MAX(removed_at) AS removed_at
                FROM keyword_removals
                GROUP BY guild_id, word
                ON CONFLICT (guild_id, word) DO UPDATE SET removed_at = EXCLUDED.removed_at
                """,
                (),
            )
            await self.execute("DROP TABLE keyword_removals", ())
            await self.execute("ALTER TABLE keyword_removals_new RENAME TO keyword_removals", ())

    async def apply_core_stopwords(self, core_words: list[str], hash_value: str) -> None:
        await self._ensure_app_meta()
        row = await self.fetchone("SELECT value FROM app_meta WHERE key='core_stopwords_hash'", ())
        if not row or str(row["value"]) != hash_value:
            if core_words:
                await self.execute("DELETE FROM word_counts WHERE word = ANY(?)", (core_words,))
                await self.execute("DELETE FROM keywords WHERE word = ANY(?)", (core_words,))
                await self.execute("DELETE FROM stopwords WHERE word = ANY(?)", (core_words,))
            await self.execute(
                """
                INSERT INTO app_meta(key,value) VALUES ('core_stopwords_hash', ?)
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                """,
                (hash_value,),
            )

    def _q(self, sql: str) -> str:
        # Replace ? -> $1, $2...
        out = []
        i = 1
        for ch in sql:
            if ch == "?":
                out.append(f"${i}")
                i += 1
            else:
                out.append(ch)
        return "".join(out)

    async def execute(self, sql: str, params: Any = None) -> Any:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.execute(self._q(sql), *self._norm_params(params))

    async def fetchone(self, sql: str, params: Any = None) -> Optional[Any]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(self._q(sql), *self._norm_params(params))

    async def fetchall(self, sql: str, params: Any = None) -> list[Any]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(self._q(sql), *self._norm_params(params))

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


async def init_db(url: str | None = None, sqlite_path: str = "word_counts.db") -> DBX:
    """Initialize DB.

    - If url is provided or env DATABASE_URL looks like Postgres -> PostgresDBX
    - Else -> SQLiteDBX (local dev)
    """
    url = (url if url is not None else os.getenv("DATABASE_URL", "")).strip()
    # Postgres on Render usually starts with postgres:// or postgresql://
    u = url.lower()
    is_pg = u.startswith("postgres://") or u.startswith("postgresql://")
    if is_pg:
        return await PostgresDBX(url=url).init()
    return await SQLiteDBX(sqlite_path=sqlite_path).init()


# Backwards-compat: older code imports Database from this module.
Database = DBX
