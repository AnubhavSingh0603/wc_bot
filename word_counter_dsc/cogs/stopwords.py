from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.utils import split_csv_words, safe_allowed_mentions
from word_counter_dsc.stopwords_core import CORE_STOPWORDS

from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.ui.pagination import Paginator

# Core stopwords are built-in and never counted.
# Server stopwords are extra per-server exclusions.
EXTRA_STOPWORDS: set[str] = set()


class StopwordsCog(commands.GroupCog, group_name="stopword", group_description="Manage stopwords (words ignored for fun stats)"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="list", description="Show stopwords for this server.")
    async def list_sw(self, interaction: discord.Interaction):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        rows = await self.bot.dbx.fetchall(
            "SELECT word FROM stopwords WHERE guild_id=? ORDER BY word ASC",
            (gid,),
        )
        server_words = [str(r["word"]) for r in rows]
        core_words = sorted(CORE_STOPWORDS)

        page_size = 15
        embeds: list[discord.Embed] = []

        # Server stopwords pages (first)
        if server_words:
            for i in range(0, len(server_words), page_size):
                chunk = server_words[i : i + page_size]
                page_no = (i // page_size) + 1
                total_pages = (len(server_words) + page_size - 1) // page_size
                emb = base_embed(
                    "Stopwords — Server",
                    "Server stopwords are extra exclusions for this server (ignored and purged).",
                )
                emb.add_field(
                    name=f"Server stopwords ({len(server_words)}) — Page {page_no}/{total_pages}",
                    value="\n".join([f"• {w}" for w in chunk]) or "—",
                    inline=False,
                )
                embeds.append(emb)
        else:
            emb = base_embed(
                "Stopwords — Server",
                "Server stopwords are extra exclusions for this server (ignored and purged).",
            )
            emb.description = "_No server stopwords yet. Add some with /stopword add._"
            embeds.append(emb)

        # Core stopwords pages (after)
        for i in range(0, len(core_words), page_size):
            chunk = core_words[i : i + page_size]
            page_no = (i // page_size) + 1
            total_pages = (len(core_words) + page_size - 1) // page_size
            emb = base_embed(
                "Stopwords — Core",
                "Core stopwords are built-in and never counted.",
            )
            emb.add_field(
                name=f"Core stopwords ({len(core_words)}) — Page {page_no}/{total_pages}",
                value="\n".join([f"• {w}" for w in chunk]) or "—",
                inline=False,
            )
            embeds.append(emb)

        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            allowed_mentions=safe_allowed_mentions(),
        )

    @app_commands.command(name="add", description="Add one or more stopwords (comma/space separated).")
    @app_commands.describe(words="Example: the, and, lol")
    async def add_sw(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        items = sorted(set(split_csv_words(words)))
        if not items:
            await interaction.response.send_message("No stopwords provided.", ephemeral=True)
            return

        now = int(time.time())
        for w in items:
            await self.bot.dbx.execute(
                """
                INSERT INTO stopwords (guild_id, word, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, word) DO NOTHING
                """,
                (gid, w, now),
            )

        # Purge any existing counts for these stopwords to save DB space (server extras + core are never counted going forward)
        if getattr(self.bot.dbx, "dialect", "") == "postgres":
            await self.bot.dbx.execute(
                "DELETE FROM word_counts WHERE guild_id=? AND word = ANY(?)",
                (gid, items),
            )
        else:
            q = "DELETE FROM word_counts WHERE guild_id=? AND word IN (" + ",".join(["?"] * len(items)) + ")"
            await self.bot.dbx.execute(q, (gid, *items))

        await interaction.response.send_message(f"Added {len(items)} stopword(s).", ephemeral=True)

    @app_commands.command(name="remove", description="Remove one or more stopwords (comma/space separated).")
    async def remove_sw(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        items = sorted(set(split_csv_words(words)))
        if not items:
            await interaction.response.send_message("No stopwords provided.", ephemeral=True)
            return
        for w in items:
            await self.bot.dbx.execute(
                "DELETE FROM stopwords WHERE guild_id=? AND word=?",
                (gid, w),
            )
        await interaction.response.send_message(f"Removed {len(items)} stopword(s).", ephemeral=True)

    @app_commands.command(name="seed", description="Seed a good default stopword list (Ephemeral).")
    async def seed_defaults(self, interaction: discord.Interaction):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        now = int(time.time())
        for w in sorted(EXTRA_STOPWORDS):
            await self.bot.dbx.execute(
                """
                INSERT INTO stopwords (guild_id, word, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, word) DO NOTHING
                """,
                (gid, w, now),
            )
        await interaction.response.send_message("Core stopwords are built-in. (No server defaults to seed.)", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StopwordsCog(bot))
