from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.utils import safe_allowed_mentions

BOT_DESC = (
    "**WordCounterBot** tracks *all* words (case-insensitive, punctuation-tolerant, with simple variant normalization),**\n"
    "but it only shows detailed profile stats for the server's **keywords** list.\n\n"
    "**Definitions:**\n"
    "• **Stopwords**: completely ignored + purged (invisible to the bot)\n"
    "• **Tracked words**: everything else (powering `/top` and `/search`)\n"
    "• **Keywords**: a subset you add per server (powering `/rank` + profile keyword stats)\n\n"
    "**Commands:**\n"
    "• `/keyword list` — show keywords (public)\n"
    "• `/keyword add` / `/keyword remove` — edit keywords (admin, ephemeral)\n"
    "• `/keyword abbrev_add` — map abbreviations to expansions (helps detect intended keywords)\n"
    "• `/rank <keyword>` — leaderboard for a keyword\n"
    "• `/search <word>` — leaderboard for any tracked word\n"
    "• `/top [user]` — top tracked words (server or user)\n"
    "• `/me` — your profile\n"
    "• `/profile [user]` — someone else's profile\n"
    "• `/stopword add|remove|list|seed` — manage stopwords (ignored + purged)\n\n"
    "Tip: Mentions in leaderboards are **clickable but won't ping** anyone."
)

class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show bot help.")
    async def help(self, interaction: discord.Interaction):
        emb = base_embed("Help", BOT_DESC)
        await interaction.response.send_message(embed=emb, ephemeral=True, allowed_mentions=safe_allowed_mentions())

async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
