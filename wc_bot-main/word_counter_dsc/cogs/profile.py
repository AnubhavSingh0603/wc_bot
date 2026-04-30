from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.utils import safe_allowed_mentions, user_mention, progress_bar
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.stopwords_core import CORE_STOPWORDS


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _build_profile_embeds(self, guild_id: int, user: discord.abc.User):
        assert self.bot.dbx is not None
        uid = int(user.id)

        # keyword totals for this user
        rows = await self.bot.dbx.fetchall(
            """
            SELECT wc.word AS keyword, SUM(wc.count) AS total
            FROM word_counts wc
            JOIN keywords k
              ON k.guild_id = wc.guild_id AND k.word = wc.word
            WHERE wc.guild_id=? AND wc.user_id=?
            GROUP BY wc.word
            ORDER BY total DESC
            """,
            (guild_id, uid),
        )
        kw_totals = [(r["keyword"], int(r["total"])) for r in rows if int(r["total"]) > 0 and str(r["keyword"]) not in CORE_STOPWORDS]
        distinct_kw = len(kw_totals)
        top_kw = kw_totals[0] if kw_totals else None
        rare_kw = kw_totals[-1] if kw_totals else None

        # medals (top 3)
        medals_cog = self.bot.get_cog("MedalsCog")
        top_medals = []
        if medals_cog and hasattr(medals_cog, "top_medals_for_user"):
            top_medals = await medals_cog.top_medals_for_user(guild_id, uid, limit=3)

        # Quote stats (best-effort; cog may not be loaded in older deployments)
        quote_summary = None
        quote_cog = self.bot.get_cog("QuoteStatsCog")
        if quote_cog and hasattr(quote_cog, "quote_summary_for_user"):
            try:
                quote_summary = await quote_cog.quote_summary_for_user(guild_id, uid)
            except Exception:
                self.bot.logger.exception("quote_summary_for_user failed")
                quote_summary = None

        # ---- Page 1: Game / medals ----
        e1 = base_embed(f"Profile — {user.display_name}", f"{user_mention(uid)}")
        # Be defensive across discord.py versions: some environments don't expose Embed.Empty.
        # Also handle edge cases where display_avatar/url might not exist.
        thumb_url = getattr(getattr(user, "display_avatar", None), "url", None)
        if thumb_url:
            e1.set_thumbnail(url=thumb_url)
        if top_medals:
            lines = []
            for m in top_medals:
                nxt = m["next"]
                if nxt:
                    bar = progress_bar(m["total"], nxt)
                    lines.append(f"{m['emoji']} **{m['title']}**\n`{bar}`  `{m['total']}/{nxt}`")
                else:
                    lines.append(f"{m['emoji']} **{m['title']}**\n`MAXED`  `{m['total']}`")
            e1.add_field(name="Top Titles (Top 3 Keywords)", value="\n\n".join(lines), inline=False)
        else:
            e1.add_field(name="Top Titles", value="_No titles yet. Use some tracked keywords!_", inline=False)

        # fun facts
        facts = []
        if top_kw:
            facts.append(f"**Most used keyword:** `{top_kw[0]}` (**{top_kw[1]}**)")
        if rare_kw and rare_kw != top_kw:
            facts.append(f"**Rarest keyword you used:** `{rare_kw[0]}` (**{rare_kw[1]}**)")
        facts.append(f"**Distinct tracked keywords used:** **{distinct_kw}**")
        # Inline a one-liner quote stat on page 1 for at-a-glance visibility
        if quote_summary is not None and (quote_summary["quoted"] or quote_summary["quoter"]):
            facts.append(
                f"**Quote stats:** quoted **{quote_summary['quoted']}**× · "
                f"quoted others **{quote_summary['quoter']}**×"
            )

        e1.add_field(name="Fun facts", value="\n".join(facts), inline=False)

        embeds: list[discord.Embed] = [e1]

        # ---- Page 2: Quote stats (only if cog is loaded AND user has activity) ----
        if quote_summary is not None and (
            quote_summary["quoted"] or quote_summary["quoter"]
        ):
            eq = base_embed(
                f"Quote Stats — {user.display_name}",
                "Make it a Quote triggers in this server.",
            )
            if thumb_url:
                eq.set_thumbnail(url=thumb_url)
            eq.add_field(
                name="Times quoted",
                value=f"**{quote_summary['quoted']}** by **{quote_summary['unique_quoters']}** unique user(s)",
                inline=True,
            )
            eq.add_field(
                name="Quoted others",
                value=f"**{quote_summary['quoter']}** time(s) targeting **{quote_summary['unique_targets']}** user(s)",
                inline=True,
            )
            if quote_summary["top_quoter_id"]:
                eq.add_field(
                    name="Most often quoted by",
                    value=f"{user_mention(quote_summary['top_quoter_id'])} — **{quote_summary['top_quoter_count']}**",
                    inline=False,
                )
            embeds.append(eq)

        # ---- Page 3: Top emoji used by this user ----
        ee = await self._build_top_emoji_embed(guild_id, user, thumb_url)
        if ee is not None:
            embeds.append(ee)

        # ---- Pages 4+: All keyword counts (15 per page) ----
        if not kw_totals:
            e2 = base_embed(f"Keyword Stats — {user.display_name}", "Your tracked keyword counts in this server.")
            e2.description = "_No keyword counts yet._"
            embeds.append(e2)
            return embeds

        page_size = 15
        lines_all = [f"• `{kw}` — **{cnt}**" for kw, cnt in kw_totals]
        total_pages = (len(lines_all) + page_size - 1) // page_size
        for i in range(0, len(lines_all), page_size):
            chunk = lines_all[i : i + page_size]
            page_no = (i // page_size) + 1
            e = base_embed(f"Keyword Stats — {user.display_name}", "Your tracked keyword counts in this server.")
            e.add_field(
                name=f"Counts ({len(lines_all)}) — Page {page_no}/{total_pages}",
                value="\n".join(chunk),
                inline=False,
            )
            embeds.append(e)

        return embeds

    async def _build_top_emoji_embed(
        self,
        guild_id: int,
        user: discord.abc.User,
        thumb_url: str | None,
    ) -> discord.Embed | None:
        """Compact 'top emoji used' page for this user. Returns None if both
        custom and unicode tables are empty for the user (avoids a noisy page).
        """
        assert self.bot.dbx is not None
        uid = int(user.id)

        custom_rows = await self.bot.dbx.fetchall(
            """
            SELECT emoji_name, SUM(count) AS total
            FROM emoji_counts
            WHERE guild_id=? AND user_id=?
            GROUP BY emoji_name
            ORDER BY total DESC
            LIMIT 5
            """,
            (guild_id, uid),
        )
        unicode_rows = await self.bot.dbx.fetchall(
            """
            SELECT emoji, SUM(count) AS total
            FROM unicode_emoji_counts
            WHERE guild_id=? AND user_id=?
            GROUP BY emoji
            ORDER BY total DESC
            LIMIT 5
            """,
            (guild_id, uid),
        )

        custom_lines = [
            f"• `:{str(r['emoji_name'])}:` — **{int(r['total'])}**"
            for r in custom_rows if int(r["total"]) > 0
        ]
        unicode_lines = [
            f"• {str(r['emoji'])} — **{int(r['total'])}**"
            for r in unicode_rows if int(r["total"]) > 0
        ]
        if not custom_lines and not unicode_lines:
            return None

        e = base_embed(
            f"Top Emoji — {user.display_name}",
            "Your most-used emojis in this server (messages + custom emoji reactions).",
        )
        if thumb_url:
            e.set_thumbnail(url=thumb_url)
        e.add_field(
            name="Top custom emoji",
            value="\n".join(custom_lines) if custom_lines else "_None._",
            inline=False,
        )
        e.add_field(
            name="Top unicode emoji",
            value="\n".join(unicode_lines) if unicode_lines else "_None._",
            inline=False,
        )
        return e

    @app_commands.command(name="profile", description="Show your profile, or another member's profile.")
    async def profile(self, interaction: discord.Interaction, user: discord.User | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        gid = int(interaction.guild_id or 0)
        user = user or interaction.user
        embeds = await self._build_profile_embeds(gid, user)
        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.followup.send(embed=view.first_embed(), view=view, allowed_mentions=safe_allowed_mentions())


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
