from discord.ext import commands
import discord

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="leaderboard", description="Top words")
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.bot.db_lock:
            cursor = await self.bot.db.execute("""
            SELECT word, SUM(count) as total
            FROM word_counts
            WHERE guild_id=?
            GROUP BY word
            ORDER BY total DESC
            LIMIT 10
            """, (interaction.guild.id,))
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.response.send_message("No data.", ephemeral=True)

        embed = discord.Embed(title="📊 Top Words", color=0x00ffcc)
        for i, (word, total) in enumerate(rows):
            embed.add_field(name=f"{i+1}. {word}", value=str(total), inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Stats(bot))
