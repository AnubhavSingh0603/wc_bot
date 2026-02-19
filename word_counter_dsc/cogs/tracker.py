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

        counts = Counter(t for t in tokens if t and t not in stopwords)
        if not counts:
            return

<<<<<<< HEAD
        ab_rows = await self.bot.dbx.fetchall(
            "SELECT abbreviation, expansion FROM abbreviations WHERE guild_id=?",
            (gid,),
        )
        abbr_map = {str(r["abbreviation"]): str(r["expansion"]) for r in ab_rows}

        working_text = text

        # If message contains abbreviations, append their expansions to the text
        lower_working = working_text.lower()
        tokens = tokenize(lower_working)
        for t in tokens:
            exp = abbr_map.get(t)
            if exp:
                working_text += " " + exp

        # ---- count keyword occurrences ----
        now = int(time.time())

        for kw in keywords:
            aliases = KEYWORD_ALIASES.get(kw, [])
            c = count_keyword_occurrences(working_text, kw, aliases=aliases)

            if c <= 0:
                continue

=======
        now = int(time.time())

        # Upsert per (guild, channel, user, word)
        for w, c in counts.items():
>>>>>>> ebbd5a6af7ba727497c5c2b2d64308a2d8d1a60c
            await self.bot.dbx.execute(
                """
                INSERT INTO word_counts (guild_id, channel_id, user_id, word, count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id, user_id, word)
                DO UPDATE SET count = word_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, cid, uid, w, int(c), now),
            )

<<<<<<< HEAD
            # Trigger medal update + congratulatory reply (avoid race with MedalsCog listener)
            medals_cog = self.bot.get_cog("MedalsCog")
            if medals_cog and hasattr(medals_cog, "maybe_congratulate"):
                try:
                    # mark so medals cog can skip its own on_message handler if it still runs
                    await medals_cog.maybe_congratulate(message, gid, uid, kw)
                except Exception:
                    self.bot.logger.exception("Medal congrats failed")

=======
>>>>>>> ebbd5a6af7ba727497c5c2b2d64308a2d8d1a60c

async def setup(bot: commands.Bot):
    await bot.add_cog(TrackerCog(bot))
