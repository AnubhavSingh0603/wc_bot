from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.utils import split_csv_words
from word_counter_dsc.utils import safe_allowed_mentions
from word_counter_dsc.utils import count_configured_keywords, tokenize
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.stopwords_core import CORE_STOPWORDS


def _is_keyword_admin(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    perms = user.guild_permissions
    return bool(perms.administrator or perms.manage_guild or perms.manage_messages)


async def _require_keyword_admin(interaction: discord.Interaction) -> bool:
    if _is_keyword_admin(interaction):
        return True
    await interaction.response.send_message(
        "🔒 You need Administrator, Manage Server, or Manage Messages permission to change keyword settings.",
        ephemeral=True,
        allowed_mentions=safe_allowed_mentions(),
    )
    return False


class KeywordCog(commands.GroupCog, group_name="keyword", group_description="Manage tracked keywords"):
    """Slash-command group: /keyword ..."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    def _clear_tracker_cache(self, guild_id: int, *, keywords: bool = False, abbreviations: bool = False) -> None:
        tracker = self.bot.get_cog("TrackerCog")
        if not tracker:
            return
        if keywords and hasattr(tracker, "clear_keyword_cache"):
            tracker.clear_keyword_cache(guild_id)
        if abbreviations and hasattr(tracker, "clear_abbreviation_cache"):
            tracker.clear_abbreviation_cache(guild_id)

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
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(name="add", description="Add one or more keywords (comma/space separated).")
    @app_commands.describe(words="Example: hello, world, foo")
    async def add_keywords(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        if not await _require_keyword_admin(interaction):
            return
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

        self._clear_tracker_cache(gid, keywords=True)

        await interaction.response.send_message(
            f"✅ Added **{len(allowed)}** keyword(s): " + (", ".join(f"`{w}`" for w in allowed) if allowed else "_(none)_") + ("\n⚠️ Skipped stopword(s): " + ", ".join(f"`{w}`" for w in skipped) if skipped else ""),
            ephemeral=True,
        )

    # ---------------------------
    # /keyword remove (EPHEMERAL)
    # ---------------------------
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(name="remove", description="Remove one or more keywords (comma/space separated).")
    @app_commands.describe(words="Example: hello, world")
    async def remove_keywords(self, interaction: discord.Interaction, words: str):
        assert self.bot.dbx is not None
        if not await _require_keyword_admin(interaction):
            return
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
            # Keep word_counts history so removed keywords can be searched or
            # promoted again later without losing old stats.
            await self.bot.dbx.execute(
                "DELETE FROM keyword_medals WHERE guild_id=? AND word=?",
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

        self._clear_tracker_cache(gid, keywords=True)

        await interaction.response.send_message(
            f"✅ Removed **{len(kws)}** keyword(s): " + ", ".join(f"`{w}`" for w in kws) + "\nStored word history was kept, so `/search` can still find old counts.",
            ephemeral=True,
        )


    # ---------------------------
    # /keyword test  (EPHEMERAL)
    # ---------------------------
    @app_commands.command(name="test", description="Preview which configured keywords a sample text would count.")
    @app_commands.describe(
        text="Sample message text to test locally before changing keywords.",
        keywords="Optional comma/space-separated keywords to test instead of the server list.",
    )
    async def test_keywords(self, interaction: discord.Interaction, text: str, keywords: str | None = None):
        assert self.bot.dbx is not None
        gid = int(interaction.guild_id or 0)

        if keywords:
            kw_set = sorted(set(split_csv_words(keywords)))
        else:
            rows = await self.bot.dbx.fetchall(
                "SELECT word FROM keywords WHERE guild_id=? ORDER BY word ASC",
                (gid,),
            )
            kw_set = [str(r["word"]) for r in rows]

        if not kw_set:
            await interaction.response.send_message(
                "No keywords available to test. Add keywords first or pass the optional `keywords` field.",
                ephemeral=True,
            )
            return

        tokens = tokenize(text)
        matches = count_configured_keywords(tokens, kw_set)

        lines: list[str] = []
        for tok in tokens[:30]:
            hit_words = [kw for kw in kw_set if count_configured_keywords([tok], [kw]).get(kw, 0)]
            if hit_words:
                lines.append(f"• `{tok}` → " + ", ".join(f"`{kw}`" for kw in hit_words))
            else:
                lines.append(f"• `{tok}` → _no keyword hit_")

        if len(tokens) > 30:
            lines.append(f"…and {len(tokens) - 30} more token(s).")

        summary = ", ".join(f"`{kw}`×{count}" for kw, count in sorted(matches.items())) or "_No keyword hits._"
        emb = base_embed("Keyword Match Test", "Preview only — this does not write stats.")
        emb.add_field(name="Summary", value=summary, inline=False)
        emb.add_field(name="Token results", value="\n".join(lines)[:1000] if lines else "_No tokens found._", inline=False)
        await interaction.response.send_message(embed=emb, ephemeral=True, allowed_mentions=safe_allowed_mentions())

    # ---------------------------
    # Abbreviations
    # ---------------------------
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(name="abbrev_add", description="Add abbreviations: abbr=phrase. (Ephemeral)")
    @app_commands.describe(rules="Example: wtf=fuck | lol=fuck this | (use commas/newlines for multiple)")
    async def add_abbrev(self, interaction: discord.Interaction, rules: str):
        assert self.bot.dbx is not None
        if not await _require_keyword_admin(interaction):
            return
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

        self._clear_tracker_cache(gid, abbreviations=True)

        await interaction.response.send_message(
            f"✅ Saved **{len(pairs)}** abbreviation rule(s).",
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

    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(name="abbrev_remove", description="Remove abbreviations by name (comma/space). (Ephemeral)")
    @app_commands.describe(abbrs="Example: wtf, lol")
    async def remove_abbrev(self, interaction: discord.Interaction, abbrs: str):
        assert self.bot.dbx is not None
        if not await _require_keyword_admin(interaction):
            return
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

        self._clear_tracker_cache(gid, abbreviations=True)

        await interaction.response.send_message(f"✅ Removed abbreviation(s): {', '.join(f'`{x}`' for x in items)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(KeywordCog(bot))
