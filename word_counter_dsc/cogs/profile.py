from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.utils import safe_allowed_mentions, user_mention, progress_bar
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.stopwords_core import CORE_STOPWORDS


# NOTE:
#   /me      -> your own profile
#   /profile -> someone else's profile (optional user)

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

        e1.add_field(name="Fun facts", value="\n".join(facts), inline=False)

        # ---- Page 2: All keyword counts ----
        e2 = base_embed(f"Keyword Stats — {user.display_name}", "Your tracked keyword counts in this server.")
        if not kw_totals:
            e2.description = "_No keyword counts yet._"
        else:
            lines = [f"• `{kw}` — **{cnt}**" for kw, cnt in kw_totals[:50]]
            e2.add_field(name="Counts", value="\n".join(lines), inline=False)
            if len(kw_totals) > 50:
                e2.set_footer(text=f"Showing first 50 of {len(kw_totals)} keywords.")

        return [e1, e2]

    @app_commands.command(name="me", description="Show your profile.")
    async def me(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        gid = int(interaction.guild_id or 0)
        embeds = await self._build_profile_embeds(gid, interaction.user)
        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.followup.send(embed=view.first_embed(), view=view, allowed_mentions=safe_allowed_mentions())

    @app_commands.command(name="profile", description="Show a user's profile (defaults to you).")
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
