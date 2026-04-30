from __future__ import annotations

import asyncio
import time
from collections import Counter

import discord
from discord.ext import commands

from word_counter_dsc.stopwords_core import CORE_STOPWORDS
from word_counter_dsc.utils import count_configured_keywords, tokenize


class TrackerCog(commands.Cog):
    """Tracks all normalized non-stopword tokens and configured keyword variants.

    Normal words are buffered briefly and flushed in batches to reduce database
    load. Keyword messages are flushed before medal checks so leaderboard/medal
    behavior stays accurate.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stop_cache: dict[int, tuple[float, set[str]]] = {}
        self._abbr_cache: dict[int, tuple[float, dict[str, str]]] = {}
        self._keyword_cache: dict[int, tuple[float, set[str]]] = {}
        self._ttl_sec = 60.0

        self._word_buffer: Counter[tuple[int, int, int, str]] = Counter()
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._flush_interval_sec = 3.0

        self._medal_seen: dict[int, float] = {}

    async def cog_load(self) -> None:
        self._ensure_flush_task()

    def cog_unload(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        # Best effort: schedule one final flush on unload. Discord.py does not
        # allow awaiting directly in cog_unload.
        try:
            asyncio.create_task(self._flush_word_buffer())
        except RuntimeError:
            pass

    def _ensure_flush_task(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._flush_interval_sec)
                await self._flush_word_buffer()
        except asyncio.CancelledError:
            await self._flush_word_buffer()
            raise
        except Exception:
            if getattr(self.bot, "logger", None):
                self.bot.logger.exception("word-count batch flush loop failed")

    async def _buffer_word_counts(self, guild_id: int, channel_id: int, user_id: int, counts: Counter[str]) -> None:
        if not counts:
            return
        async with self._buffer_lock:
            for word, count in counts.items():
                if count > 0:
                    self._word_buffer[(int(guild_id), int(channel_id), int(user_id), str(word))] += int(count)

    async def _flush_word_buffer(self) -> int:
        if not self.bot.dbx:
            return 0
        async with self._buffer_lock:
            if not self._word_buffer:
                return 0
            snapshot = self._word_buffer
            self._word_buffer = Counter()

        now = int(time.time())
        rows = [(gid, cid, uid, word, int(count), now) for (gid, cid, uid, word), count in snapshot.items() if count > 0]
        if not rows:
            return 0
        try:
            if hasattr(self.bot.dbx, "bulk_upsert_word_counts"):
                return await self.bot.dbx.bulk_upsert_word_counts(rows)
            # Compatibility fallback for older DB wrappers.
            for row in rows:
                await self.bot.dbx.execute(
                    """
                    INSERT INTO word_counts (guild_id, channel_id, user_id, word, count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, channel_id, user_id, word)
                    DO UPDATE SET count = word_counts.count + excluded.count,
                                  updated_at = excluded.updated_at
                    """,
                    row,
                )
            return len(rows)
        except Exception:
            # Put data back so a later flush can retry instead of silently losing stats.
            async with self._buffer_lock:
                for key, count in snapshot.items():
                    self._word_buffer[key] += count
            raise

    def clear_stopword_cache(self, guild_id: int | None = None) -> None:
        if guild_id is None:
            self._stop_cache.clear()
        else:
            self._stop_cache.pop(int(guild_id), None)

    def clear_abbreviation_cache(self, guild_id: int | None = None) -> None:
        if guild_id is None:
            self._abbr_cache.clear()
        else:
            self._abbr_cache.pop(int(guild_id), None)

    def clear_keyword_cache(self, guild_id: int | None = None) -> None:
        if guild_id is None:
            self._keyword_cache.clear()
        else:
            self._keyword_cache.pop(int(guild_id), None)

    async def _get_stopwords(self, guild_id: int) -> set[str]:
        now = time.time()
        cached = self._stop_cache.get(guild_id)
        if cached and (now - cached[0]) < self._ttl_sec:
            return cached[1]

        assert self.bot.dbx is not None
        rows = await self.bot.dbx.fetchall(
            "SELECT word FROM stopwords WHERE guild_id=?",
            (guild_id,),
        )
        sw = set(CORE_STOPWORDS) | {str(r["word"]) for r in rows}
        self._stop_cache[guild_id] = (now, sw)
        return sw

    async def _get_abbreviations(self, guild_id: int) -> dict[str, str]:
        now = time.time()
        cached = self._abbr_cache.get(guild_id)
        if cached and (now - cached[0]) < self._ttl_sec:
            return cached[1]

        assert self.bot.dbx is not None
        rows = await self.bot.dbx.fetchall(
            "SELECT abbreviation, expansion FROM abbreviations WHERE guild_id=?",
            (guild_id,),
        )
        ab = {str(r["abbreviation"]): str(r["expansion"]) for r in rows}
        self._abbr_cache[guild_id] = (now, ab)
        return ab

    async def _get_keywords(self, guild_id: int) -> set[str]:
        now = time.time()
        cached = self._keyword_cache.get(guild_id)
        if cached and (now - cached[0]) < self._ttl_sec:
            return cached[1]

        assert self.bot.dbx is not None
        rows = await self.bot.dbx.fetchall(
            "SELECT word FROM keywords WHERE guild_id=?",
            (guild_id,),
        )
        kws = {str(r["word"]) for r in rows}
        self._keyword_cache[guild_id] = (now, kws)
        return kws

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        self._ensure_flush_task()
        if message.author.bot or not message.guild or not self.bot.dbx:
            return

        text = (message.content or "").strip()
        if not text:
            return

        gid = int(message.guild.id)
        cid = int(message.channel.id)
        uid = int(message.author.id)

        # Expand abbreviations into their expansions, e.g. wtf -> fuck.
        abbr_map = await self._get_abbreviations(gid)
        tokens0 = tokenize(text)
        if abbr_map:
            expansions = [abbr_map[t] for t in tokens0 if t in abbr_map]
            if expansions:
                text = text + " " + " ".join(expansions)

        tokens = tokenize(text)
        if not tokens:
            return

        stopwords = await self._get_stopwords(gid)
        counts: Counter[str] = Counter(t for t in tokens if t and t not in stopwords)
        if not counts:
            return

        keywords = await self._get_keywords(gid)
        keyword_counts = count_configured_keywords(tokens, keywords)

        # Canonical keyword rows receive only the extra amount not already stored
        # by normal token counting. Example: "ass" token already stores ass once;
        # "dumbass" stores dumbass plus an extra canonical ass count.
        for kw, c in keyword_counts.items():
            extra = int(c) - int(counts.get(kw, 0))
            if extra > 0:
                counts[str(kw)] += extra

        await self._buffer_word_counts(gid, cid, uid, counts)

        # Medals read current totals from the DB, so flush keyword messages before
        # checking thresholds. Non-keyword messages still benefit from batching.
        if keyword_counts:
            await self._flush_word_buffer()

        # Avoid duplicate medal triggers per message.
        seen = self._medal_seen
        ts_now = time.time()
        for mid, ts in list(seen.items()):
            if ts_now - ts > 900:
                del seen[mid]
        if message.id in seen:
            return
        seen[message.id] = ts_now

        medals_cog = self.bot.get_cog("MedalsCog")
        if medals_cog and hasattr(medals_cog, "maybe_congratulate"):
            for kw in keywords:
                if kw in keyword_counts:
                    try:
                        await medals_cog.maybe_congratulate(message, gid, uid, kw)
                    except Exception:
                        self.bot.logger.exception("Medal congrats failed")


async def setup(bot: commands.Bot):
    await bot.add_cog(TrackerCog(bot))
