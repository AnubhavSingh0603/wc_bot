from discord.ext import commands
import discord

class Analytics(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="userstats", description="User analytics")
    async def userstats(self, interaction: discord.Interaction, user: discord.Member):
        async with self.bot.db_lock:
            cursor = await self.bot.db.execute("""
            SELECT word, SUM(count) as total
            FROM word_counts
            WHERE guild_id=? AND user_id=?
            GROUP BY word
            ORDER BY total DESC
            LIMIT 5
            """, (interaction.guild.id, user.id))
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.response.send_message("No data.", ephemeral=True)

        embed = discord.Embed(title=f"📈 Stats for {user.display_name}", color=0xffcc00)
        for word, total in rows:
            embed.add_field(name=word, value=str(total), inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Analytics(bot))
