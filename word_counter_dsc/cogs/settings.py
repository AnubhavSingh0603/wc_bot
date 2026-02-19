from discord.ext import commands
import discord

class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="setup", description="Server dashboard")
    async def setup_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙ Server Configuration",
            description="Interactive dashboard coming next phase.",
            color=0x3399ff
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Settings(bot))
