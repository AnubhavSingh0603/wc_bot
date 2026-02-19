import asyncio

try:
    import discord  # type: ignore
    from discord.ext import commands  # type: ignore
except Exception:  # pragma: no cover
    discord = None
    commands = None

def run_bot_tests():
    if discord is None or commands is None:
        # Environment running tests without discord.py installed
        return

    async def _run():
        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)

        # Ensure extensions load
        await bot.load_extension("word_counter_dsc.cogs.tracker")
        await bot.load_extension("word_counter_dsc.cogs.search")
        await bot.load_extension("word_counter_dsc.cogs.keyword")
        await bot.load_extension("word_counter_dsc.cogs.stopwords")
        await bot.load_extension("word_counter_dsc.cogs.help_cmd")
        await bot.load_extension("word_counter_dsc.cogs.medals")
        await bot.load_extension("word_counter_dsc.cogs.profile")

        # Unload to ensure no crashes on cleanup
        await bot.close()

    asyncio.run(_run())
