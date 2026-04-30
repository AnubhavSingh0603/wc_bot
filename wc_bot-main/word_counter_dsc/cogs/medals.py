from __future__ import annotations

import time

import discord
from discord.ext import commands

from word_counter_dsc.config import (
    MEDAL_THRESHOLDS,
    MEDAL_EMOJIS,
    TITLE_TEMPLATES,
    KEYWORD_REMOVAL_GRACE_SECONDS,
)
from word_counter_dsc.utils import keyword_display, progress_bar


def tier_for_count(n: int) -> int:
    """Return tier index based on MEDAL_THRESHOLDS. -1 means no tier yet."""
    for i, thr in enumerate(MEDAL_THRESHOLDS):
        if n < thr:
            return i - 1
    return len(MEDAL_THRESHOLDS) - 1


def next_threshold(n: int) -> int | None:
    for thr in MEDAL_THRESHOLDS:
        if n < thr:
            return thr
    return None


def title_for(keyword: str, tier: int) -> str:
    """Return the display title in the requested form: "The [Title] of the [Keyword]".

    - Keyword is capitalised unless stored in ALL CAPS.
    - "Page" tier is renamed to "Novice".
    """
    k = keyword_display(keyword)
    if tier < 0:
        base = "Novice"
    else:
        idx = min(tier, len(TITLE_TEMPLATES) - 1)
        # TITLE_TEMPLATES are of the form "Squire of {K}"; we only want the rank/title.
        base = TITLE_TEMPLATES[idx].split(" of ", 1)[0].strip() or TITLE_TEMPLATES[idx].format(K=k)
    return f"The {base} of the {k}"


def emoji_for(tier: int) -> str:
    if tier < 0:
        return "📜"
    idx = min(tier, len(MEDAL_EMOJIS) - 1)
    return MEDAL_EMOJIS[idx]


class MedalsCog(commands.Cog):
    """Awards knight/royal themed titles based on keyword usage."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Cleanup medal rows for keywords removed long ago
        if not self.bot.dbx:
            return
        now = int(time.time())
        cutoff = now - int(KEYWORD_REMOVAL_GRACE_SECONDS)

        try:
            removals = await self.bot.dbx.fetchall(
                "SELECT guild_id, word, removed_at FROM keyword_removals WHERE removed_at <= ?",
                (cutoff,),
            )
            for r in removals:
                gid = int(r["guild_id"])
                w = str(r["word"])
                removed_at = int(r["removed_at"])

                # delete medals for that keyword
                await self.bot.dbx.execute(
                    "DELETE FROM keyword_medals WHERE guild_id=? AND word=?",
                    (gid, w),
                )
                # delete just the expired removal entries
                await self.bot.dbx.execute(
                    "DELETE FROM keyword_removals WHERE guild_id=? AND word=? AND removed_at=?",
                    (gid, w, removed_at),
                )
        except Exception:
            self.bot.logger.exception("Medals cleanup failed")

    async def update_user_keyword(self, guild_id: int, user_id: int, word: str):
        """Recompute total count and upsert medal tier if changed.

        Returns:
            crossed_thr: The highest threshold crossed on this update (or None)
            new_total:   New total count
            new_tier:    New tier
        """
        assert self.bot.dbx is not None

        row = await self.bot.dbx.fetchone(
            "SELECT COALESCE(SUM(count), 0) AS total FROM word_counts WHERE guild_id=? AND user_id=? AND word=?",
            (guild_id, user_id, word),
        )
        total = int(row["total"] if row else 0)
        tier = tier_for_count(total)

        existing = await self.bot.dbx.fetchone(
            "SELECT tier, total_count FROM keyword_medals WHERE guild_id=? AND user_id=? AND word=?",
            (guild_id, user_id, word),
        )
        old_tier = int(existing["tier"]) if existing else -1
        if existing is None:
            old_total = 0
        else:
            try:
                old_total = int(existing["total_count"] or 0)
            except Exception:
                old_total = 0

        # Did we cross a threshold? (handles multi-occurrence messages)
        crossed_thr = None
        for thr in MEDAL_THRESHOLDS:
            if old_total < thr <= total:
                crossed_thr = thr

        # Also update stored total_count periodically even if tier doesn't change
        if tier == old_tier:
            await self.bot.dbx.execute(
                """
                INSERT INTO keyword_medals (guild_id, user_id, word, tier, total_count, awarded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, word)
                DO UPDATE SET total_count=excluded.total_count
                """,
                (guild_id, user_id, word, tier, total, int(time.time())),
            )
            return crossed_thr, total, tier

        await self.bot.dbx.execute(
            """
            INSERT INTO keyword_medals (guild_id, user_id, word, tier, total_count, awarded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, word)
            DO UPDATE SET tier=excluded.tier,
                          total_count=excluded.total_count,
                          awarded_at=excluded.awarded_at
            """,
            (guild_id, user_id, word, tier, total, int(time.time())),
        )

        return crossed_thr, total, tier


    async def maybe_congratulate(self, message: discord.Message, guild_id: int, user_id: int, word: str):
        """Update medal state for (user, word) and send congrats reply if a threshold is crossed.

        Notes for threads:
        - If the bot lacks "Send Messages in Threads" permission, replying inside the thread will fail.
          In that case, we fall back to posting in the parent channel with a link to the thread/message.
        """
        crossed_thr, total, tier = await self.update_user_keyword(guild_id, user_id, word)
        if crossed_thr is None:
            return

        medal_emoji = emoji_for(tier)
        title = title_for(word, tier)
        kdisp = keyword_display(word)

        content = (
            f"✨🏅 **MEDAL UNLOCKED!** 🏅✨\n"
            f"{message.author.mention} you used **{kdisp}** **{crossed_thr}** times.\n"
            f"You're now **{title}** {medal_emoji}✨"
        )

        try:
            # Reply in-place (works in normal channels and threads, assuming permissions allow).
            await message.reply(
                content,
                mention_author=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True, replied_user=True, roles=False, everyone=False
                ),
            )
        except discord.Forbidden:
            # Common in threads if the bot doesn't have "Send Messages in Threads".
            # Fallback: post in the parent channel (or current channel) with a jump link.
            jump = getattr(message, "jump_url", None)
            fallback = content
            if jump:
                fallback += f"\n↪️ {jump}"

            chan = message.channel
            parent = getattr(chan, "parent", None)
            target = parent or chan
            try:
                await target.send(
                    fallback,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False
                    ),
                )
            except Exception:
                self.bot.logger.exception("Failed to send medal congrats fallback message")
        except Exception:
            self.bot.logger.exception("Failed to send medal congrats message")

    async def top_medals_for_user(self, guild_id: int, user_id: int, limit: int = 3):
        assert self.bot.dbx is not None
        rows = await self.bot.dbx.fetchall(
            """
            SELECT word, tier, total_count
            FROM keyword_medals
            WHERE guild_id=? AND user_id=?
            ORDER BY total_count DESC
            LIMIT ?
            """,
            (guild_id, user_id, limit),
        )

        out = []
        for r in rows:
            w = str(r["word"])
            tier = int(r["tier"])
            total = int(r["total_count"])
            nxt = next_threshold(total)
            out.append(
                dict(
                    keyword=w,
                    tier=tier,
                    total=total,
                    next=nxt,
                    title=title_for(w, tier),
                    emoji=emoji_for(tier),
                )
            )
        return out


async def setup(bot: commands.Bot):
    await bot.add_cog(MedalsCog(bot))
