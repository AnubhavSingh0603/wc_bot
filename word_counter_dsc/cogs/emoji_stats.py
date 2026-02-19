from __future__ import annotations

import re
import time
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.utils import safe_allowed_mentions


# Discord custom emoji formats in message content:
#   <:name:id>
#   <a:name:id>
_CUSTOM_EMOJI_RE = re.compile(r"<a?:([A-Za-z0-9_]{2,32}):\d+>")

# Some users may type :name: expecting it to become an emoji.
_COLON_EMOJI_RE = re.compile(r"(?<!\w):([A-Za-z0-9_]{2,32}):(?!\w)")


class EmojiStatsCog(commands.Cog):
    """Tracks server custom emoji usage and provides /emoji stats."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.dbx:
            return

        text = (message.content or "").strip()
        if not text:
            return

        guild = message.guild
        guild_emoji_names = {e.name for e in (guild.emojis or [])}
        if not guild_emoji_names:
            return

        # Collect emoji name occurrences from both formats.
        names: list[str] = []
        names.extend(_CUSTOM_EMOJI_RE.findall(text))
        names.extend(_COLON_EMOJI_RE.findall(text))
        if not names:
            return

        counts = Counter(n for n in names if n in guild_emoji_names)
        if not counts:
            return

        now = int(time.time())
        gid = int(guild.id)
        uid = int(message.author.id)

        for name, c in counts.items():
            await self.bot.dbx.execute(
                """
                INSERT INTO emoji_counts (guild_id, user_id, emoji_name, count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, emoji_name)
                DO UPDATE SET count = emoji_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, uid, str(name), int(c), now),
            )

    @app_commands.command(name="emoji", description="Show top and bottom used server emojis.")
    @app_commands.describe(n="How many emojis to show in top/bottom lists (default 10).")
    async def emoji(self, interaction: discord.Interaction, n: int = 10):
        if not interaction.guild or not self.bot.dbx:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=False,
                allowed_mentions=safe_allowed_mentions(),
            )
            return

        n = max(1, min(int(n or 10), 25))
        guild = interaction.guild
        gid = int(guild.id)

        emojis = list(guild.emojis or [])
        if not emojis:
            await interaction.response.send_message(
                "This server has no custom emojis.",
                ephemeral=False,
                allowed_mentions=safe_allowed_mentions(),
            )
            return

        # Server totals from DB
        rows = await self.bot.dbx.fetchall(
            """
            SELECT emoji_name, COALESCE(SUM(count), 0) AS total
            FROM emoji_counts
            WHERE guild_id=?
            GROUP BY emoji_name
            """,
            (gid,),
        )
        totals = {str(r["emoji_name"]): int(r["total"]) for r in rows}

        # Include *all* server emojis, even if never used.
        items = []
        for e in emojis:
            items.append((e, totals.get(e.name, 0)))

        top = sorted(items, key=lambda t: (-t[1], t[0].name))[:n]
        bottom = sorted(items, key=lambda t: (t[1], t[0].name))[:n]

        def fmt(pair: tuple[discord.Emoji, int]) -> str:
            e, c = pair
            return f"{str(e)} `:{e.name}:` — **{c}**"

        emb = base_embed(
            "Emoji usage",
            f"Top **{n}** and bottom **{n}** used **server emojis** (includes unused / 0-count emojis).",
        )
        emb.add_field(name=f"Top {n}", value="\n".join(fmt(p) for p in top) or "—", inline=False)
        emb.add_field(name=f"Bottom {n}", value="\n".join(fmt(p) for p in bottom) or "—", inline=False)

        # Visible response (not ephemeral) as requested.
        await interaction.response.send_message(embed=emb, ephemeral=False, allowed_mentions=safe_allowed_mentions())


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiStatsCog(bot))
