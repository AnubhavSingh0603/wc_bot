from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.config import DEFAULT_TOP_N
from word_counter_dsc.stopwords_core import CORE_STOPWORDS
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.utils import normalize_word, user_mention, safe_allowed_mentions


def _chunk(lines: list[str], n: int = 15) -> list[list[str]]:
    return [lines[i : i + n] for i in range(0, len(lines), n)]


class SearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _guild_stopwords(self, guild_id: int) -> set[str]:
        assert self.bot.dbx is not None
        rows = await self.bot.dbx.fetchall(
            "SELECT word FROM stopwords WHERE guild_id=?",
            (guild_id,),
        )
        return set(CORE_STOPWORDS) | {str(r["word"]) for r in rows}

    @app_commands.command(name="rank", description="Top users for a keyword in this server.")
    @app_commands.describe(keyword="Keyword (must be in /keyword list)", top_n="How many users to show (max 25)")
    async def rank(self, interaction: discord.Interaction, keyword: str, top_n: int | None = None):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        kw = normalize_word(keyword)
        n = int(top_n or DEFAULT_TOP_N)
        n = max(1, min(n, 25))
        if not kw:
            await interaction.response.send_message("Please provide a keyword.", ephemeral=True)
            return

        # Validate keyword exists for this server
        exists = await self.bot.dbx.fetchone(
            "SELECT 1 AS ok FROM keywords WHERE guild_id=? AND word=?",
            (gid, kw),
        )
        if not exists:
            await interaction.response.send_message(
                f"`{kw}` is not in /keyword list for this server.",
                ephemeral=True,
            )
            return

        rows = await self.bot.dbx.fetchall(
            """
            SELECT user_id, SUM(count) AS total
            FROM word_counts
            WHERE guild_id=? AND word=?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (gid, kw, n),
        )

        title = f"Top {len(rows)} for '{kw}'"
        if not rows:
            emb = base_embed(title, "Keyword leaderboard (server-wide).")
            emb.description = "_No counts yet._"
            await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())
            return

        lines = []
        for i, r in enumerate(rows, start=1):
            uid = int(r["user_id"])
            total = int(r["total"])
            lines.append(f"**{i}.** {user_mention(uid)} — **{total}**")

        embeds: list[discord.Embed] = []
        chunks = _chunk(lines, 15)
        for pi, chunk in enumerate(chunks, start=1):
            emb = base_embed(title, "Keyword leaderboard (server-wide).")
            emb.add_field(
                name=f"Leaderboard — Page {pi}/{len(chunks)}",
                value="\n".join(chunk),
                inline=False,
            )
            embeds.append(emb)

        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            allowed_mentions=safe_allowed_mentions(),
        )

    @app_commands.command(name="search", description="See who used a tracked word the most in this server.")
    @app_commands.describe(word="Any tracked word", top_n="How many users to show (max 25)")
    async def search_word(self, interaction: discord.Interaction, word: str, top_n: int | None = None):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        w = normalize_word(word)
        n = max(1, min(int(top_n or DEFAULT_TOP_N), 25))

        if not w:
            await interaction.response.send_message("Please provide a word to search.", ephemeral=True)
            return

        sw = await self._guild_stopwords(gid)
        if w in sw:
            await interaction.response.send_message(f"`{w}` is a stopword and is not tracked.", ephemeral=True)
            return

        rows = await self.bot.dbx.fetchall(
            """
            SELECT user_id, SUM(count) AS total
            FROM word_counts
            WHERE guild_id=? AND word=?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (gid, w, n),
        )
        total_row = await self.bot.dbx.fetchone(
            "SELECT SUM(count) AS total FROM word_counts WHERE guild_id=? AND word=?",
            (gid, w),
        )
        total = int(total_row["total"] or 0) if total_row else 0

        title = f"Search: '{w}'"
        subtitle = f"Total in this server: **{total}**"
        if not rows:
            emb = base_embed(title, subtitle)
            emb.description = "_No counts yet._"
            await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())
            return

        lines = []
        for i, r in enumerate(rows, start=1):
            uid = int(r["user_id"])
            c = int(r["total"])
            lines.append(f"**{i}.** {user_mention(uid)} — **{c}**")

        embeds: list[discord.Embed] = []
        chunks = _chunk(lines, 15)
        for pi, chunk in enumerate(chunks, start=1):
            emb = base_embed(title, subtitle)
            emb.add_field(name=f"Top users — Page {pi}/{len(chunks)}", value="\n".join(chunk), inline=False)
            embeds.append(emb)

        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            allowed_mentions=safe_allowed_mentions(),
        )

    @app_commands.command(name="top", description="Top tracked words (stopwords ignored).")
    @app_commands.describe(user="Optional: show top words for a specific user", top_n="How many words to show (max 25)")
    async def top_words(self, interaction: discord.Interaction, user: discord.Member | None = None, top_n: int | None = None):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        uid = int(user.id) if user else None
        n = max(1, min(int(top_n or DEFAULT_TOP_N), 25))

        sw = await self._guild_stopwords(gid)

        if uid is None:
            rows = await self.bot.dbx.fetchall(
                """
                SELECT word, SUM(count) AS total
                FROM word_counts
                WHERE guild_id=?
                GROUP BY word
                ORDER BY total DESC
                LIMIT ?
                """,
                (gid, n * 3),  # fetch extra then filter stopwords
            )
            title = f"Top tracked words (server) — showing {n}"
        else:
            rows = await self.bot.dbx.fetchall(
                """
                SELECT word, SUM(count) AS total
                FROM word_counts
                WHERE guild_id=? AND user_id=?
                GROUP BY word
                ORDER BY total DESC
                LIMIT ?
                """,
                (gid, uid, n * 3),
            )
            title = f"Top tracked words for {user.display_name} — showing {n}"

        # Filter stopwords + trim
        clean = []
        for r in rows:
            w = str(r["word"])
            if w in sw:
                continue
            clean.append((w, int(r["total"])))
            if len(clean) >= n:
                break

        subtitle = "All word tracking is case-insensitive and normalizes simple variants (e.g., eat/eating)."
        if not clean:
            emb = base_embed(title, subtitle)
            emb.description = "_No counts yet._"
            await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())
            return

        lines = [f"**{i}.** `{w}` — **{c}**" for i, (w, c) in enumerate(clean, start=1)]
        embeds: list[discord.Embed] = []
        chunks = _chunk(lines, 15)
        for pi, chunk in enumerate(chunks, start=1):
            emb = base_embed(title, subtitle)
            emb.add_field(name=f"Top — Page {pi}/{len(chunks)}", value="\n".join(chunk), inline=False)
            embeds.append(emb)

        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            allowed_mentions=safe_allowed_mentions(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SearchCog(bot))
