from __future__ import annotations

import time
from collections import Counter

import discord
from discord.ext import commands

from word_counter_dsc.stopwords_core import CORE_STOPWORDS
from word_counter_dsc.utils import tokenize


class TrackerCog(commands.Cog):
    """Tracks *all* words (tracked words) case-insensitively.

    Stopwords (core + server) are never counted.
    Keywords are a subset of tracked words and are used for profiles/leaderboards.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stop_cache: dict[int, tuple[float, set[str]]] = {}
        self._abbr_cache: dict[int, tuple[float, dict[str, str]]] = {}
        self._ttl_sec = 60.0

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.dbx:
            return

        text = (message.content or "").strip()
        if not text:
            return

        gid = int(message.guild.id)
        cid = int(message.channel.id)
        uid = int(message.author.id)

        # Expand abbreviations into their expansions (helps catch intended keywords)
        abbr_map = await self._get_abbreviations(gid)
        tokens0 = tokenize(text)
        if abbr_map:
            expansions = []
            for t in tokens0:
                exp = abbr_map.get(t)
                if exp:
                    expansions.append(exp)
            if expansions:
                text = text + " " + " ".join(expansions)

        tokens = tokenize(text)
        if not tokens:
            return

        stopwords = await self._get_stopwords(gid)

        # Count tracked words (already tokenized + normalized), excluding stopwords
        counts = Counter(t for t in tokens if t and t not in stopwords)
        if not counts:
            return

        now = int(time.time())

        # ---- persist tracked-word counts ----
        # This table stores *all* tracked words; profile page 2 later filters to keywords.
        for w, c in counts.items():
            await self.bot.dbx.execute(
                """
                INSERT INTO word_counts (guild_id, channel_id, user_id, word, count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id, user_id, word)
                DO UPDATE SET count = word_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, cid, uid, str(w), int(c), now),
            )

        # Pull server keywords from DB (used for keyword stats + medals)
        kw_rows = await self.bot.dbx.fetchall(
            "SELECT word FROM keywords WHERE guild_id=?",
            (gid,),
        )
        keywords = {str(r["word"]) for r in kw_rows}

        # Avoid duplicate medal triggers per message (discord.Message is slot-based; no setattr)
        if not hasattr(self, "_medal_seen"):
            self._medal_seen = {}  # msg_id -> ts
        seen = self._medal_seen
        ts_now = time.time()
        # prune old entries (keep ~15 minutes)
        for mid, ts in list(seen.items()):
            if ts_now - ts > 900:
                del seen[mid]
        if message.id in seen:
            return
        seen[message.id] = ts_now

        # Trigger medal update + congratulatory reply for any keywords that appeared
        medals_cog = self.bot.get_cog("MedalsCog")
        if medals_cog and hasattr(medals_cog, "maybe_congratulate"):
            for kw in keywords:
                if kw in counts:
                    try:
                        await medals_cog.maybe_congratulate(message, gid, uid, kw)
                    except Exception:
                        self.bot.logger.exception("Medal congrats failed")


async def setup(bot: commands.Bot):
    await bot.add_cog(TrackerCog(bot))