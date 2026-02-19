from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from word_counter_dsc.config import REQUIRE_MESSAGE_CONTENT_INTENT, get_bot_token
from word_counter_dsc.database import init_db
from word_counter_dsc.stopwords_core import CORE_STOPWORDS

EXTENSIONS = [
    "word_counter_dsc.cogs.tracker",
    "word_counter_dsc.cogs.emoji_stats",
    "word_counter_dsc.cogs.search",
    "word_counter_dsc.cogs.keyword",
    "word_counter_dsc.cogs.stopwords",
    "word_counter_dsc.cogs.help_cmd",
    "word_counter_dsc.cogs.medals",
    "word_counter_dsc.cogs.profile",
]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("word_counter_dsc")


class WCBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = bool(REQUIRE_MESSAGE_CONTENT_INTENT)

        super().__init__(command_prefix="!", intents=intents)

        self.logger = logger
        self.dbx = None  # set in setup_hook

    async def setup_hook(self):
        # init_db expects an optional DATABASE_URL string (or env DATABASE_URL),
        # not a logger instance.
        self.dbx = await init_db()
        logger.info("DB initialized: %s", type(self.dbx).__name__)

        # Apply core stopwords maintenance (purges legacy data if core list changed)
        try:
            import hashlib

            core_list = sorted(CORE_STOPWORDS)
            h = hashlib.sha256("\n".join(core_list).encode("utf-8")).hexdigest()
            await self.dbx.apply_core_stopwords(core_list, h)
        except Exception:
            logger.exception("Core stopwords maintenance failed")

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info("Loaded extension: %s", ext)
            except Exception:
                logger.exception("Failed loading extension %s", ext)

        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands.", len(synced))
        except Exception:
            logger.exception("Slash command sync failed")

        if REQUIRE_MESSAGE_CONTENT_INTENT:
            logger.info("If counting is not working, enable MESSAGE CONTENT INTENT in the Discord Developer Portal.")
        else:
            logger.info("Message counting is disabled (REQUIRE_MESSAGE_CONTENT_INTENT=0).")


async def main():
    token = get_bot_token().strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN (or BOT_TOKEN) env var not set.")

    bot = WCBot()
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
