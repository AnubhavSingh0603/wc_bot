from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.cogs.quote_stats import normalize_name_fragment
from word_counter_dsc.utils import safe_allowed_mentions


def _is_quote_admin(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    perms = user.guild_permissions
    return bool(perms.administrator or perms.manage_guild)


class QuoteConfigCog(commands.GroupCog, name="quote_config"):
    """Admin commands for generalized quote-bot trigger configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _clear_quote_cache(self, guild_id: int) -> None:
        cog = self.bot.get_cog("QuoteStatsCog")
        if cog and hasattr(cog, "clear_config_cache"):
            cog.clear_config_cache(guild_id)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not self.bot.dbx:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return False
        if not _is_quote_admin(interaction):
            await interaction.response.send_message("You need Administrator or Manage Server to use quote config.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="list", description="List configured quote trigger bots and name fragments.")
    @app_commands.default_permissions(administrator=True)
    async def list_config(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        gid = int(interaction.guild.id)
        bots = await self.bot.dbx.fetchall("SELECT bot_user_id FROM quote_trigger_bots WHERE guild_id=? ORDER BY bot_user_id", (gid,))
        names = await self.bot.dbx.fetchall("SELECT name_fragment FROM quote_trigger_names WHERE guild_id=? ORDER BY name_fragment", (gid,))
        bot_lines = [f"• `{int(r['bot_user_id'])}`" for r in bots] or ["_No configured bot IDs._"]
        name_lines = [f"• `{str(r['name_fragment'])}`" for r in names] or ["_No configured name fragments._"]
        await interaction.response.send_message(
            "**Quote trigger bot IDs**\n" + "\n".join(bot_lines) + "\n\n**Quote trigger names**\n" + "\n".join(name_lines),
            ephemeral=True,
            allowed_mentions=safe_allowed_mentions(),
        )

    @app_commands.command(name="add_bot", description="Add a quote trigger bot user ID for this server.")
    @app_commands.default_permissions(administrator=True)
    async def add_bot(self, interaction: discord.Interaction, bot_user_id: str):
        if not await self._guard(interaction):
            return
        try:
            bid = int(str(bot_user_id).strip())
        except ValueError:
            await interaction.response.send_message("Please provide a numeric Discord bot user ID.", ephemeral=True)
            return
        gid = int(interaction.guild.id)
        await self.bot.dbx.execute(
            """
            INSERT INTO quote_trigger_bots (guild_id, bot_user_id, added_by_user_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, bot_user_id) DO NOTHING
            """,
            (gid, bid, int(interaction.user.id), int(time.time())),
        )
        self._clear_quote_cache(gid)
        await interaction.response.send_message(f"Added quote trigger bot ID `{bid}`.", ephemeral=True)

    @app_commands.command(name="remove_bot", description="Remove a quote trigger bot user ID for this server.")
    @app_commands.default_permissions(administrator=True)
    async def remove_bot(self, interaction: discord.Interaction, bot_user_id: str):
        if not await self._guard(interaction):
            return
        try:
            bid = int(str(bot_user_id).strip())
        except ValueError:
            await interaction.response.send_message("Please provide a numeric Discord bot user ID.", ephemeral=True)
            return
        gid = int(interaction.guild.id)
        await self.bot.dbx.execute("DELETE FROM quote_trigger_bots WHERE guild_id=? AND bot_user_id=?", (gid, bid))
        self._clear_quote_cache(gid)
        await interaction.response.send_message(f"Removed quote trigger bot ID `{bid}` if it existed.", ephemeral=True)

    @app_commands.command(name="add_name", description="Add a quote trigger name fragment for this server.")
    @app_commands.default_permissions(administrator=True)
    async def add_name(self, interaction: discord.Interaction, name_fragment: str):
        if not await self._guard(interaction):
            return
        frag = normalize_name_fragment(name_fragment)
        if not frag:
            await interaction.response.send_message("Name fragment cannot be empty.", ephemeral=True)
            return
        gid = int(interaction.guild.id)
        await self.bot.dbx.execute(
            """
            INSERT INTO quote_trigger_names (guild_id, name_fragment, added_by_user_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, name_fragment) DO NOTHING
            """,
            (gid, frag, int(interaction.user.id), int(time.time())),
        )
        self._clear_quote_cache(gid)
        await interaction.response.send_message(f"Added quote trigger name fragment `{frag}`.", ephemeral=True)

    @app_commands.command(name="remove_name", description="Remove a quote trigger name fragment for this server.")
    @app_commands.default_permissions(administrator=True)
    async def remove_name(self, interaction: discord.Interaction, name_fragment: str):
        if not await self._guard(interaction):
            return
        frag = normalize_name_fragment(name_fragment)
        if not frag:
            await interaction.response.send_message("Name fragment cannot be empty.", ephemeral=True)
            return
        gid = int(interaction.guild.id)
        await self.bot.dbx.execute("DELETE FROM quote_trigger_names WHERE guild_id=? AND name_fragment=?", (gid, frag))
        self._clear_quote_cache(gid)
        await interaction.response.send_message(f"Removed quote trigger name fragment `{frag}` if it existed.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuoteConfigCog(bot))
