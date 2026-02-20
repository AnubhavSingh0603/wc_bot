from __future__ import annotations

import re
import time
from collections import Counter
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.utils import safe_allowed_mentions


# Discord custom emoji formats in message content:
#   <:name:id>
#   <a:name:id>
_CUSTOM_EMOJI_RE = re.compile(r"<a?:([A-Za-z0-9_]{2,32}):\d+>")

# Some users may type :name: expecting it to become an emoji.
_COLON_EMOJI_RE = re.compile(r"(?<!\w):([A-Za-z0-9_]{2,32}):(?!\w)")


def _extract_unicode_emojis(text: str) -> list[str]:
    """Best-effort unicode emoji extractor.

    We intentionally avoid extra deps. This catches the most common emoji blocks
    (including flags) and is safe (won't crash on odd unicode).
    """
    if not text:
        return []

    out: list[str] = []

    def is_emoji_cp(cp: int) -> bool:
        # Common emoji ranges
        return (
            0x1F300 <= cp <= 0x1FAFF
            or 0x2600 <= cp <= 0x26FF
            or 0x2700 <= cp <= 0x27BF
            or 0x1F000 <= cp <= 0x1F02F
            or 0x1F1E6 <= cp <= 0x1F1FF  # regional indicators (flags)
            or 0xFE00 <= cp <= 0xFE0F  # variation selectors
            or 0x200D == cp  # ZWJ
            or 0x20E3 == cp  # keycap
        )

    # Build simple sequences for:
    # - flags (regional indicator pairs)
    # - ZWJ sequences (e.g., family emojis)
    # - keycaps
    i = 0
    s = text
    n = len(s)
    while i < n:
        cp = ord(s[i])

        # Flag: two regional indicators
        if 0x1F1E6 <= cp <= 0x1F1FF and i + 1 < n:
            cp2 = ord(s[i + 1])
            if 0x1F1E6 <= cp2 <= 0x1F1FF:
                out.append(s[i : i + 2])
                i += 2
                continue

        # Keycap: [0-9#*] + optional VS16 + keycap
        if s[i] in "0123456789#*":
            j = i + 1
            if j < n and ord(s[j]) == 0xFE0F:
                j += 1
            if j < n and ord(s[j]) == 0x20E3:
                out.append(s[i : j + 1])
                i = j + 1
                continue

        # Single codepoint emoji (and allow ZWJ chains)
        if is_emoji_cp(cp):
            j = i + 1
            # consume VS16/ZWJ chains conservatively
            while j < n and is_emoji_cp(ord(s[j])):
                j += 1
            emoji = s[i:j]
            # Filter out pure modifiers/selectors
            if any(0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF for ch in emoji):
                out.append(emoji)
            i = j
            continue

        i += 1

    # Final cleanup: drop empty / whitespace / non-emoji
    cleaned: list[str] = []
    for e in out:
        if not e or e.isspace():
            continue
        # defensive: some sequences might include only selectors
        if any("EMOJI" in unicodedata.name(ch, "") for ch in e):
            cleaned.append(e)
        else:
            # keep common pictographs anyway
            if any(0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF for ch in e):
                cleaned.append(e)
    return cleaned


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

        # Collect custom emoji name occurrences from both formats.
        names: list[str] = []
        names.extend(_CUSTOM_EMOJI_RE.findall(text))
        names.extend(_COLON_EMOJI_RE.findall(text))
        counts_custom = Counter(n for n in names if n in guild_emoji_names)

        # Collect unicode emoji occurrences.
        unicode_list = _extract_unicode_emojis(text)
        counts_unicode = Counter(unicode_list)

        if not counts_custom and not counts_unicode:
            return

        now = int(time.time())
        gid = int(guild.id)
        uid = int(message.author.id)

        for name, c in counts_custom.items():
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

        for emoji, c in counts_unicode.items():
            await self.bot.dbx.execute(
                """
                INSERT INTO unicode_emoji_counts (guild_id, user_id, emoji, count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, emoji)
                DO UPDATE SET count = unicode_emoji_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, uid, str(emoji), int(c), now),
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or not self.bot.dbx:
            return
        if payload.user_id == getattr(self.bot.user, "id", None):
            return

        now = int(time.time())
        gid = int(payload.guild_id)
        uid = int(payload.user_id)

        # Custom emoji reaction
        if payload.emoji and payload.emoji.id is not None:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            guild_emoji_names = {e.name for e in (guild.emojis or [])}
            name = payload.emoji.name
            if not name or name not in guild_emoji_names:
                return

            await self.bot.dbx.execute(
                """
                INSERT INTO emoji_counts (guild_id, user_id, emoji_name, count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, emoji_name)
                DO UPDATE SET count = emoji_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, uid, str(name), 1, now),
            )
            return

        # Unicode emoji reaction
        if payload.emoji:
            e = str(payload.emoji)
            if not e:
                return
            await self.bot.dbx.execute(
                """
                INSERT INTO unicode_emoji_counts (guild_id, user_id, emoji, count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, emoji)
                DO UPDATE SET count = unicode_emoji_counts.count + excluded.count,
                              updated_at = excluded.updated_at
                """,
                (gid, uid, e, 1, now),
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

        # Keep pages compact. We show 3 pages (server top / server bottom / unicode top).
        n = max(1, min(int(n or 10), 15))
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

        # Server totals from DB (custom emojis)
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

        # Unicode emoji totals from DB
        urows = await self.bot.dbx.fetchall(
            """
            SELECT emoji, COALESCE(SUM(count), 0) AS total
            FROM unicode_emoji_counts
            WHERE guild_id=?
            GROUP BY emoji
            ORDER BY total DESC
            """,
            (gid,),
        )
        unicode_totals = [(str(r["emoji"]), int(r["total"])) for r in urows if int(r["total"]) > 0]

        # Include *all* server emojis, even if never used.
        items = []
        for e in emojis:
            items.append((e, totals.get(e.name, 0)))

        top = sorted(items, key=lambda t: (-t[1], t[0].name))[:n]
        bottom = sorted(items, key=lambda t: (t[1], t[0].name))[:n]

        def fmt(pair: tuple[discord.Emoji, int]) -> str:
            e, c = pair
            return f"{str(e)} `:{e.name}:` — **{c}**"

        # Page 1: Server top
        e1 = base_embed(
            "Emoji usage — Server (Top)",
            f"Top **{n}** used **server emojis** (includes unused / 0-count emojis in the DB totals).",
        )
        e1.add_field(name=f"Top {n}", value="\n".join(fmt(p) for p in top) or "—", inline=False)

        # Page 2: Server bottom
        e2 = base_embed(
            "Emoji usage — Server (Bottom)",
            f"Bottom **{n}** used **server emojis** (includes unused / 0-count emojis).",
        )
        e2.add_field(name=f"Bottom {n}", value="\n".join(fmt(p) for p in bottom) or "—", inline=False)

        # Page 3: Unicode top
        e3 = base_embed(
            "Emoji usage — Unicode (Top)",
            f"Top **{n}** unicode emoji used in this server (from messages + reactions).",
        )
        if not unicode_totals:
            e3.description = "_No unicode emoji counted yet._"
        else:
            lines = [f"**{i}.** {emo} — **{cnt}**" for i, (emo, cnt) in enumerate(unicode_totals[:n], start=1)]
            e3.add_field(name=f"Top {min(n, len(unicode_totals))}", value="\n".join(lines), inline=False)

        embeds = [e1, e2, e3]
        view = Paginator(embeds, author_id=int(interaction.user.id))

        # Visible response (not ephemeral) as requested.
        await interaction.response.send_message(
            embed=view.first_embed(),
            view=view,
            ephemeral=False,
            allowed_mentions=safe_allowed_mentions(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiStatsCog(bot))
