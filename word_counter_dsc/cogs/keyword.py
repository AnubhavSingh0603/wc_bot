from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.utils import split_csv_words
from word_counter_dsc.utils import safe_allowed_mentions
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.stopwords_core import CORE_STOPWORDS


class KeywordCog(commands.GroupCog, group_name="keyword", group_description="Manage tracked keywords"):
    """Slash-command group: /keyword ..."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    # ---------------------------
    # /keyword list  (PUBLIC)
    # ---------------------------
    @app_commands.command(name="list", description="Show tracked keywords for this server.")
    async def list_keywords(self, interaction: discord.Interaction):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        rows = await self.bot.dbx.fetchall(
            "SELECT word FROM keywords WHERE guild_id=? ORDER BY word ASC",
            (gid,),
        )
        kws = [str(r["word"]) for r in rows]

        if not kws:
            emb = base_embed("Tracked Keywords", "Server-wide tracked keywords.")
            emb.description = "_No keywords yet. Use /keyword add (admin)._"
            await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())
            return

        # 15 entries per page
        page_size = 15
        embeds: list[discord.Embed] = []
        for i in range(0, len(kws), page_size):
            chunk = kws[i : i + page_size]
            page_no = (i // page_size) + 1
            total_pages = (len(kws) + page_size - 1) // page_size
            emb = base_embed("Tracked Keywords", "Server-wide tracked keywords.")
            emb.add_field(
                name=f"Keywords ({len(kws)}) — Page {page_no}/{total_pages}",
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

    # ---------------------------
    # /keyword add  (EPHEMERAL)
    # ---------------------------
    @app_commands.command(name="add", description="Add one or more keywords (comma/space separated).")
    @app_commands.describe(words="Example: hello, world, foo")
    async def add_keywords(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        kws = sorted(set(split_csv_words(words)))
        if not kws:
            await interaction.response.send_message("No keywords provided.", ephemeral=True)
            return

        # Disallow stopwords as keywords (stopwords are invisible to the bot)
        sw_rows = await self.bot.dbx.fetchall("SELECT word FROM stopwords WHERE guild_id=?",(gid,))
        sw = set(CORE_STOPWORDS) | {str(r["word"]) for r in sw_rows}

        allowed = [kw for kw in kws if kw not in sw]
        skipped = [kw for kw in kws if kw in sw]

        now = int(time.time())
        for kw in allowed:
            await self.bot.dbx.execute(
                """
                INSERT INTO keywords (guild_id, word, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, word) DO NOTHING
                """,
                (gid, kw, now),
            )

        await interaction.response.send_message(
            f"Added {len(allowed)} keyword(s): " + (", ".join(allowed) if allowed else "(none)" ) + ("\nSkipped (stopwords): " + ", ".join(skipped) if skipped else ""),
            ephemeral=True,
        )

    # ---------------------------
    # /keyword remove (EPHEMERAL)
    # ---------------------------
    @app_commands.command(name="remove", description="Remove one or more keywords (comma/space separated).")
    @app_commands.describe(words="Example: hello, world")
    async def remove_keywords(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        kws = sorted(set(split_csv_words(words)))
        if not kws:
            await interaction.response.send_message("No keywords provided.", ephemeral=True)
            return

        now = int(time.time())
        for kw in kws:
            await self.bot.dbx.execute(
                "DELETE FROM keywords WHERE guild_id=? AND word=?",
                (gid, kw),
            )
            await self.bot.dbx.execute(
                "DELETE FROM word_counts WHERE guild_id=? AND word=?",
                (gid, kw),
            )
            await self.bot.dbx.execute(
                "DELETE FROM keyword_medals WHERE guild_id=? AND keyword=?",
                (gid, kw),
            )
            # record removal time for cleanup (medals cog)
            await self.bot.dbx.execute(
                """
                INSERT INTO keyword_removals (guild_id, word, removed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, word) DO UPDATE SET removed_at = excluded.removed_at
                """,
                (gid, kw, now),
            )

        await interaction.response.send_message(
            f"Removed {len(kws)} keyword(s): " + ", ".join(kws),
            ephemeral=True,
        )

    # ---------------------------
    # Abbreviations
    # ---------------------------
    @app_commands.command(name="abbrev_add", description="Add abbreviations: abbr=phrase. (Ephemeral)")
    @app_commands.describe(rules="Example: wtf=fuck | lol=fuck this | (use commas/newlines for multiple)")
    async def add_abbrev(self, interaction: discord.Interaction, rules: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)

        # get keyword set to validate expansions
        kw_rows = await self.bot.dbx.fetchall("SELECT word FROM keywords WHERE guild_id=?", (gid,))
        kw_set = {str(r["word"]) for r in kw_rows}

        pairs: list[tuple[str, str]] = []
        for line in rules.splitlines():
            for part in line.split(","):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                abbr, exp = part.split("=", 1)
                abbr = abbr.strip().lower()
                exp = exp.strip().lower()
                if not abbr or not exp:
                    continue
                # If we have keywords configured, require expansion to mention at least one.
                if kw_set and not any(k in exp for k in kw_set):
                    continue
                pairs.append((abbr, exp))

        if not pairs:
            await interaction.response.send_message(
                "No valid abbreviation rules found. Use format like `wtf=fuck` and ensure the expansion contains an existing keyword.",
                ephemeral=True,
            )
            return

        now = int(time.time())
        for abbr, exp in pairs:
            await self.bot.dbx.execute(
                """
                INSERT INTO abbreviations (guild_id, abbreviation, expansion, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, abbreviation)
                DO UPDATE SET expansion=excluded.expansion, created_at=excluded.created_at
                """,
                (gid, abbr, exp, now),
            )

        await interaction.response.send_message(
            f"Saved {len(pairs)} abbreviation rule(s).",
            ephemeral=True,
        )

    @app_commands.command(name="abbrev_list", description="List abbreviation rules (public).")
    async def list_abbrev(self, interaction: discord.Interaction):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        rows = await self.bot.dbx.fetchall(
            "SELECT abbreviation, expansion FROM abbreviations WHERE guild_id=? ORDER BY abbreviation ASC",
            (gid,),
        )
        if not rows:
            emb = base_embed("Keyword Abbreviations", "These map short forms to phrases containing tracked keywords.")
            emb.description = "_No abbreviation rules yet._"
            await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())
            return

        lines = [f"• **{r['abbreviation']}** = {r['expansion']}" for r in rows]
        page_size = 15
        embeds: list[discord.Embed] = []
        for i in range(0, len(lines), page_size):
            chunk = lines[i : i + page_size]
            page_no = (i // page_size) + 1
            total_pages = (len(lines) + page_size - 1) // page_size
            emb = base_embed("Keyword Abbreviations", "These map short forms to phrases containing tracked keywords.")
            emb.add_field(
                name=f"Rules ({len(lines)}) — Page {page_no}/{total_pages}",
                value="\n".join(chunk) or "—",
                inline=False,
            )
            embeds.append(emb)

        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            allowed_mentions=safe_allowed_mentions(),
        )

    @app_commands.command(name="abbrev_remove", description="Remove abbreviations by name (comma/space). (Ephemeral)")
    @app_commands.describe(abbrs="Example: wtf, lol")
    async def remove_abbrev(self, interaction: discord.Interaction, abbrs: str):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)
        items = sorted(set(split_csv_words(abbrs)))
        if not items:
            await interaction.response.send_message("No abbreviations provided.", ephemeral=True)
            return

        for a in items:
            await self.bot.dbx.execute(
                "DELETE FROM abbreviations WHERE guild_id=? AND abbreviation=?",
                (gid, a),
            )

        await interaction.response.send_message(f"Removed: {', '.join(items)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(KeywordCog(bot))
