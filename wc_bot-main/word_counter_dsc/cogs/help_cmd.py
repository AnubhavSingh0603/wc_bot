from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.utils import safe_allowed_mentions

BOT_DESC = (
    "**WordCounterBot** keeps track of what your server talks about — automatically.\n"
    "It counts words case-insensitively, handles punctuation well, and applies simple normalization.\n\n"
    "**How stats work:**\n"
    "• **Stopwords**: ignored and purged (the bot won’t count or show them)\n"
    "• **Tracked words**: everything else (powers `/top` and `/search`)\n"
    "• **Keywords**: a server-chosen subset (powers `/rank` + keyword stats in profiles)\n\n"
    "**Core commands:**\n"
    "• `/me` — your profile (keywords, medals, quote stats, top emoji)\n"
    "• `/profile [user]` — someone else’s profile\n"
    "• `/top [user]` — top tracked words (server or user)\n"
    "• `/search <word>` — leaderboard for any tracked word\n"
    "• `/rank <keyword>` — leaderboard for a keyword\n"
    "• `/emoji [user]` — top emoji stats (server-wide, or filtered to a user)\n"
    "• `/quotes [user] [channel]` — quote leaderboard or one user’s quote stats\n"
    "• `/quote_profile <user>` — quote stats for one member\n\n"
    "**Keyword tools:**\n"
    "• `/keyword list` — show keywords (public)\n"
    "• `/keyword add` / `/keyword remove` — edit keywords (admin, ephemeral)\n"
    "• `/keyword abbrev_add` — map abbreviations → expansions\n"
    "• `/keyword abbrev_list` / `/keyword abbrev_remove` — manage abbreviation mappings\n\n"
    "**Stopwords tools:**\n"
    "• `/stopword list` — view stopwords\n"
    "• `/stopword add` / `/stopword remove` — manage stopwords\n"
    "• `/stopword seed` — seed common stopwords\n\n"
    "**Admin tools:**\n"
    "• `/quote_config list/add_bot/remove_bot/add_name/remove_name` — configure quote bot detection per server\n"
    "• `/quotes_backfill <channel> [limit]` — scan channel history for quote events; safe to re-run\n\n"
    "Tip: Mentions in leaderboards are **clickable but won’t ping** anyone."
)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show bot help.")
    async def help(self, interaction: discord.Interaction):
        emb = base_embed("Help", BOT_DESC)
        await interaction.response.send_message(
            embed=emb,
            ephemeral=True,
            allowed_mentions=safe_allowed_mentions(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
