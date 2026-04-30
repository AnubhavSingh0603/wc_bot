from __future__ import annotations

import os
import re
import string
import time
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from word_counter_dsc.config import DEFAULT_TOP_N
from word_counter_dsc.ui.pagination import Paginator
from word_counter_dsc.ui.theme import base_embed
from word_counter_dsc.utils import safe_allowed_mentions, user_mention

DEFAULT_NAME_FRAGMENTS = ("make it a quote", "makeitaquote", "miq")
_CONFIG_TTL_SECONDS = 60
_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


def normalize_name_fragment(value: str) -> str:
    """Normalize quote-bot name fragments for storage and matching."""
    return " ".join((value or "").strip().lower().split())


def _compact(value: str) -> str:
    table = str.maketrans("", "", string.punctuation + string.whitespace)
    return (value or "").lower().translate(table)


def _env_bot_ids() -> set[int]:
    out: set[int] = set()
    raw = os.getenv("MIQ_BOT_ID", "")
    for part in re.split(r"[,\s]+", raw):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def _env_name_fragments() -> set[str]:
    raw = os.getenv("MIQ_BOT_NAMES", "")
    if not raw.strip():
        return set()
    return {normalize_name_fragment(x) for x in raw.split(",") if normalize_name_fragment(x)}


@dataclass(frozen=True)
class QuoteTriggerConfig:
    bot_ids: set[int]
    name_fragments: set[str]

    @property
    def compact_fragments(self) -> set[str]:
        return {_compact(x) for x in self.name_fragments if _compact(x)}


async def load_effective_quote_config(dbx: Any, guild_id: int) -> QuoteTriggerConfig:
    """Merge built-in defaults + env + per-guild DB config."""
    bot_ids = set(_env_bot_ids())
    names = {normalize_name_fragment(x) for x in DEFAULT_NAME_FRAGMENTS}
    names.update(_env_name_fragments())

    if dbx is not None:
        try:
            rows = await dbx.fetchall("SELECT bot_user_id FROM quote_trigger_bots WHERE guild_id=?", (guild_id,))
            bot_ids.update(int(r["bot_user_id"]) for r in rows)
        except Exception:
            pass
        try:
            rows = await dbx.fetchall("SELECT name_fragment FROM quote_trigger_names WHERE guild_id=?", (guild_id,))
            names.update(normalize_name_fragment(str(r["name_fragment"])) for r in rows)
        except Exception:
            pass

    return QuoteTriggerConfig(bot_ids=bot_ids, name_fragments={n for n in names if n})


def _user_names(user: Any) -> list[str]:
    vals: list[str] = []
    for attr in ("name", "global_name", "display_name"):
        v = getattr(user, attr, None)
        if isinstance(v, str) and v:
            vals.append(v)
    return vals


def is_quote_bot_user(user: Any, config: QuoteTriggerConfig) -> bool:
    uid = getattr(user, "id", None)
    if uid is not None:
        try:
            if int(uid) in config.bot_ids:
                return True
        except (TypeError, ValueError):
            pass

    if not bool(getattr(user, "bot", False)):
        return False

    raw_names = [normalize_name_fragment(n) for n in _user_names(user)]
    compact_names = [_compact(n) for n in raw_names]
    for frag in config.name_fragments:
        if frag and any(frag in n for n in raw_names):
            return True
    for frag in config.compact_fragments:
        if frag and any(frag in n for n in compact_names):
            return True
    return False


# Backwards-compatible aliases for older tests/imports.
def is_miq_user(user: Any, expected_id: int | None, name_fragments: list[str], require_bot_flag: bool = True) -> bool:
    ids = {int(expected_id)} if expected_id is not None else set()
    cfg = QuoteTriggerConfig(ids, {normalize_name_fragment(x) for x in name_fragments})
    if not require_bot_flag and expected_id is None:
        # preserve old helper behavior for isolated tests
        original_bot = getattr(user, "bot", None)
        try:
            setattr(user, "bot", True)
            return is_quote_bot_user(user, cfg)
        finally:
            try:
                setattr(user, "bot", original_bot)
            except Exception:
                pass
    return is_quote_bot_user(user, cfg)


def find_quote_bot_in_message(message: Any, config: QuoteTriggerConfig) -> Any | None:
    for user in (getattr(message, "mentions", None) or []):
        if is_quote_bot_user(user, config):
            return user

    content = getattr(message, "content", "") or ""
    for mid in _USER_MENTION_RE.findall(content):
        try:
            if int(mid) in config.bot_ids:
                guild = getattr(message, "guild", None)
                if guild and hasattr(guild, "get_member"):
                    return guild.get_member(int(mid)) or True
                return True
        except ValueError:
            continue

    # Name/text fallback, useful for user-app style invocations or test/local data.
    norm_content = normalize_name_fragment(content)
    compact_content = _compact(content)
    for frag in config.name_fragments:
        if frag and frag in norm_content:
            return True
    for frag in config.compact_fragments:
        if frag and frag in compact_content:
            return True
    return None


def find_miq_in_message(message: Any, expected_id: int | None, name_fragments: list[str], require_bot_flag: bool = True) -> Any | None:
    cfg = QuoteTriggerConfig(
        {int(expected_id)} if expected_id is not None else set(),
        {normalize_name_fragment(x) for x in name_fragments},
    )
    return find_quote_bot_in_message(message, cfg)


class QuoteStatsCog(commands.Cog):
    """Track generalized quote-bot reply invocations and expose leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._config_cache: dict[int, tuple[float, QuoteTriggerConfig]] = {}

    def clear_config_cache(self, guild_id: int | None = None) -> None:
        if guild_id is None:
            self._config_cache.clear()
        else:
            self._config_cache.pop(int(guild_id), None)

    async def get_effective_config(self, guild_id: int) -> QuoteTriggerConfig:
        now = time.monotonic()
        cached = self._config_cache.get(int(guild_id))
        if cached and now - cached[0] < _CONFIG_TTL_SECONDS:
            return cached[1]
        cfg = await load_effective_quote_config(getattr(self.bot, "dbx", None), int(guild_id))
        self._config_cache[int(guild_id)] = (now, cfg)
        return cfg

    async def _resolve_reference(self, message: Any) -> Any | None:
        ref = getattr(message, "reference", None)
        if ref is None:
            return None
        resolved = getattr(ref, "resolved", None)
        if resolved is not None and getattr(resolved, "author", None) is not None:
            return resolved
        message_id = getattr(ref, "message_id", None)
        channel = getattr(message, "channel", None)
        if message_id is not None and channel is not None and hasattr(channel, "fetch_message"):
            try:
                return await channel.fetch_message(message_id)
            except Exception:
                return None
        return None

    async def maybe_record_quote_from_message(self, message: Any) -> bool:
        if getattr(getattr(message, "author", None), "bot", False):
            return False
        guild = getattr(message, "guild", None)
        if guild is None or getattr(self.bot, "dbx", None) is None:
            return False
        if getattr(message, "reference", None) is None:
            return False

        guild_id = int(guild.id)
        cfg = await self.get_effective_config(guild_id)
        trigger_bot = find_quote_bot_in_message(message, cfg)
        if trigger_bot is None:
            return False

        source = await self._resolve_reference(message)
        if source is None or getattr(source, "author", None) is None:
            return False
        quoted_author = source.author
        if getattr(quoted_author, "bot", False):
            return False

        inserted = await self._record_quote_event(
            guild_id=guild_id,
            channel_id=int(message.channel.id),
            quoted_user_id=int(quoted_author.id),
            invoker_user_id=int(message.author.id),
            source_message_id=int(source.id),
            trigger_message_id=int(message.id),
            trigger_bot_user_id=(int(getattr(trigger_bot, "id")) if getattr(trigger_bot, "id", None) is not None else None),
            trigger_text=(getattr(message, "content", None) or None),
        )
        return inserted

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self.maybe_record_quote_from_message(message)
        except Exception:
            if getattr(self.bot, "logger", None):
                self.bot.logger.exception("quote detection failed")

    async def _record_quote_event(
        self,
        *,
        guild_id: int,
        channel_id: int,
        quoted_user_id: int,
        invoker_user_id: int,
        source_message_id: int,
        trigger_message_id: int,
        trigger_bot_user_id: int | None,
        trigger_text: str | None,
    ) -> bool:
        before = await self.bot.dbx.fetchone(
            "SELECT 1 AS found FROM quote_events WHERE guild_id=? AND trigger_message_id=?",
            (guild_id, trigger_message_id),
        )
        if before:
            return False
        await self.bot.dbx.execute(
            """
            INSERT INTO quote_events
              (guild_id, channel_id, quoted_user_id, invoker_user_id, source_message_id,
               trigger_message_id, trigger_bot_user_id, trigger_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, trigger_message_id) DO NOTHING
            """,
            (guild_id, channel_id, quoted_user_id, invoker_user_id, source_message_id,
             trigger_message_id, trigger_bot_user_id, trigger_text, int(time.time())),
        )
        return True

    @app_commands.command(name="quotes", description="Quote leaderboard, or quote stats for one user.")
    @app_commands.describe(user="Optional member to inspect.", top_n="How many leaderboard rows to show.", channel="Optional channel filter.")
    async def quotes_cmd(self, interaction: discord.Interaction, user: discord.Member | None = None, top_n: int | None = None, channel: discord.TextChannel | None = None):
        if not interaction.guild or not self.bot.dbx:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True, allowed_mentions=safe_allowed_mentions())
            return
        gid = int(interaction.guild.id)
        if user is not None:
            await self._send_user_view(interaction, gid, user, channel)
            return
        await self._send_leaderboard(interaction, gid, top_n or DEFAULT_TOP_N, channel)

    @app_commands.command(name="quote_profile", description="Quote stats for a specific member.")
    async def quote_profile_cmd(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.guild or not self.bot.dbx:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True, allowed_mentions=safe_allowed_mentions())
            return
        await self._send_user_view(interaction, int(interaction.guild.id), user, None)

    async def _send_leaderboard(self, interaction: discord.Interaction, gid: int, top_n: int, channel: discord.TextChannel | None):
        top_n = max(1, min(int(top_n or DEFAULT_TOP_N), 25))
        params: list[Any] = [gid]
        ch_filter = ""
        if channel is not None:
            ch_filter = "AND channel_id=?"
            params.append(int(channel.id))
        params.append(top_n)
        rows = await self.bot.dbx.fetchall(
            f"""
            SELECT quoted_user_id, COUNT(*) AS quote_count, COUNT(DISTINCT invoker_user_id) AS unique_invokers
            FROM quote_events
            WHERE guild_id=? {ch_filter}
            GROUP BY quoted_user_id
            ORDER BY quote_count DESC, unique_invokers DESC, quoted_user_id ASC
            LIMIT ?
            """,
            tuple(params),
        )
        if not rows:
            await interaction.response.send_message("No quote events recorded yet.", ephemeral=False, allowed_mentions=safe_allowed_mentions())
            return
        lines = [f"**{i}.** {user_mention(int(r['quoted_user_id']))} — **{int(r['quote_count'])}** quotes by **{int(r['unique_invokers'])}** user(s)" for i, r in enumerate(rows, 1)]
        emb = base_embed("Quote Leaderboard", "Who has been quoted the most" + (f" in {channel.mention}" if channel else " in this server") + ".")
        emb.add_field(name=f"Top {len(lines)}", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())

    async def _send_user_view(self, interaction: discord.Interaction, gid: int, user: discord.abc.User, channel: discord.TextChannel | None):
        summary = await self.quote_summary_for_user(gid, int(user.id), channel_id=(int(channel.id) if channel else None))
        emb = base_embed(f"Quote Stats — {user.display_name}", "Make it a Quote style trigger events.")
        thumb_url = getattr(getattr(user, "display_avatar", None), "url", None)
        if thumb_url:
            emb.set_thumbnail(url=thumb_url)
        emb.add_field(name="Times quoted", value=f"**{summary['quoted']}** by **{summary['unique_invokers']}** unique user(s)", inline=True)
        emb.add_field(name="Quoted others", value=f"**{summary['invoked']}** time(s) targeting **{summary['unique_targets']}** user(s)", inline=True)
        rank = summary.get("rank")
        emb.add_field(name="Quote rank", value=(f"#{rank}" if rank else "Not ranked yet"), inline=True)
        if summary.get("top_invoker_id"):
            emb.add_field(name="Most often quoted by", value=f"{user_mention(summary['top_invoker_id'])} — **{summary['top_invoker_count']}**", inline=False)
        await interaction.response.send_message(embed=emb, allowed_mentions=safe_allowed_mentions())

    @app_commands.command(name="quotes_backfill", description="Admin: scan recent channel history for quote-bot reply triggers.")
    @app_commands.default_permissions(administrator=True)
    async def quotes_backfill(self, interaction: discord.Interaction, channel: discord.TextChannel, limit: int | None = 1000):
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if not member or not (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
            await interaction.response.send_message("You need Administrator or Manage Server to run this.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        scanned = recorded = 0
        async for msg in channel.history(limit=max(1, min(int(limit or 1000), 10000)), oldest_first=False):
            scanned += 1
            if await self.maybe_record_quote_from_message(msg):
                recorded += 1
        await interaction.followup.send(f"Backfill complete. Scanned **{scanned}**, recorded **{recorded}** new quote event(s).", ephemeral=True)

    async def quote_summary_for_user(self, guild_id: int, user_id: int, channel_id: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"quoted": 0, "unique_invokers": 0, "invoked": 0, "unique_targets": 0, "rank": None, "top_invoker_id": None, "top_invoker_count": 0}
        if not self.bot.dbx:
            return out
        params: list[Any] = [guild_id, user_id]
        ch_filter = ""
        if channel_id is not None:
            ch_filter = "AND channel_id=?"
            params.append(channel_id)
        r1 = await self.bot.dbx.fetchone(f"SELECT COUNT(*) AS c, COUNT(DISTINCT invoker_user_id) AS u FROM quote_events WHERE guild_id=? AND quoted_user_id=? {ch_filter}", tuple(params))
        if r1:
            out["quoted"] = int(r1["c"] or 0)
            out["unique_invokers"] = int(r1["u"] or 0)
        r2 = await self.bot.dbx.fetchone(f"SELECT COUNT(*) AS c, COUNT(DISTINCT quoted_user_id) AS u FROM quote_events WHERE guild_id=? AND invoker_user_id=? {ch_filter}", tuple(params))
        if r2:
            out["invoked"] = int(r2["c"] or 0)
            out["unique_targets"] = int(r2["u"] or 0)
        r3 = await self.bot.dbx.fetchone(f"SELECT invoker_user_id, COUNT(*) AS c FROM quote_events WHERE guild_id=? AND quoted_user_id=? {ch_filter} GROUP BY invoker_user_id ORDER BY c DESC LIMIT 1", tuple(params))
        if r3:
            out["top_invoker_id"] = int(r3["invoker_user_id"])
            out["top_invoker_count"] = int(r3["c"])
        rank_rows = await self.bot.dbx.fetchall(
            f"""
            SELECT quoted_user_id, COUNT(*) AS c
            FROM quote_events
            WHERE guild_id=? {('AND channel_id=?' if channel_id is not None else '')}
            GROUP BY quoted_user_id
            ORDER BY c DESC, quoted_user_id ASC
            """,
            (guild_id, channel_id) if channel_id is not None else (guild_id,),
        )
        for idx, row in enumerate(rank_rows, 1):
            if int(row["quoted_user_id"]) == int(user_id):
                out["rank"] = idx
                break
        # Backwards-compatible keys used by older ProfileCog code.
        out["unique_quoters"] = out["unique_invokers"]
        out["quoter"] = out["invoked"]
        out["top_quoter_id"] = out["top_invoker_id"]
        out["top_quoter_count"] = out["top_invoker_count"]
        return out


async def setup(bot: commands.Bot):
    await bot.add_cog(QuoteStatsCog(bot))
