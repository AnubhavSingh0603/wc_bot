from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.ui.theme import base_embed, Theme
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.utils import safe_allowed_mentions


def _member_help_embed() -> discord.Embed:
    emb = base_embed(
        "📘 WC Bot Help — Members",
        "Use these commands to explore server stats, profiles, medals, emojis, and quote leaderboards.",
        Theme.INFO,
    )
    emb.add_field(
        name="Quick commands",
        value=(
            "• `/profile [user]` — View your profile, or another member's profile.\n"
            "• `/medals [user]` — View owned medals and progress to the next tier.\n"
            "• `/top [user] [top_n]` — See top tracked words for the server or a member.\n"
            "• `/search <word> [top_n]` — See who used any tracked word or keyword the most.\n"
            "• `/emoji [user] [n]` — View top emoji stats.\n"
            "• `/quotes [user] [channel]` — Quote leaderboard, or quote stats for one member.\n"
            "• `/keyword list` — See the server's special tracked keywords.\n"
            "• `/keyword test <text>` — Preview which keywords a sample message would hit."
        ),
        inline=False,
    )
    emb.add_field(
        name="Tips",
        value=(
            "`/search` replaces the old `/rank` command — it works for both normal words and keywords.\n"
            "`/profile` replaces the old `/me` command — leave the user blank to view yourself.\n"
            "Leaderboard mentions are clickable but do not ping users."
        ),
        inline=False,
    )
    return emb


def _admin_help_embed() -> discord.Embed:
    emb = base_embed(
        "🛠️ WC Bot Help — Admins & Mods",
        "Setup commands are visible only to members with moderation permissions where Discord supports command permissions.",
        Theme.WARN,
    )
    emb.add_field(
        name="1) Manage keywords",
        value=(
            "• `/keyword add words:<word list>` — Add words to medal/profile keyword stats.\n"
            "• `/keyword remove words:<word list>` — Remove keywords without deleting old `/search` history.\n"
            "• `/keyword abbrev_add rules:<abbr=phrase>` — Count short forms as keyword phrases.\n"
            "• `/keyword abbrev_remove abbrs:<list>` — Remove abbreviation rules."
        ),
        inline=False,
    )
    emb.add_field(
        name="2) Manage ignored words",
        value=(
            "• `/stopword list` — Review ignored words.\n"
            "• `/stopword add words:<word list>` — Ignore useless words and purge their old rows.\n"
            "• `/stopword remove words:<word list>` — Start tracking those words again from now on."
        ),
        inline=False,
    )
    emb.add_field(
        name="3) Configure quote tracking",
        value=(
            "• `/quote_config list` — See configured quote trigger bots/names.\n"
            "• `/quote_config add_bot bot_user_id:<id>` — Add the quote bot's Discord user ID.\n"
            "• `/quote_config add_name name_fragment:<name>` — Add a fallback trigger name.\n"
            "• `/quotes_backfill channel:<channel> limit:<n>` — Scan old quote replies safely."
        ),
        inline=False,
    )
    emb.add_field(
        name="Recommended setup flow",
        value=(
            "1. Add your keywords.\n"
            "2. Test tricky phrases with `/keyword test`.\n"
            "3. Add obvious junk words to stopwords only when you are sure.\n"
            "4. Configure quote tracking, then backfill the quotes channel once."
        ),
        inline=False,
    )
    return emb


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show WC Bot commands and setup help.")
    async def help(self, interaction: discord.Interaction):
        embeds = [_member_help_embed(), _admin_help_embed()]
        view = Paginator(embeds, author_id=int(interaction.user.id))
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            ephemeral=True,
            allowed_mentions=safe_allowed_mentions(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
