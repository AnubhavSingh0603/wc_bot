from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

# =========================
# Secrets / environment
# =========================
# Put these in Render "Environment" (or a local .env), NOT in code:
#   DISCORD_TOKEN=...
#   DATABASE_URL=...
#
# BOT_TOKEN is kept for backwards-compat with older code paths.
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "") or os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# =========================
# Bot behavior
# =========================
# Counting requires the privileged "Message Content Intent" enabled in the Discord Developer Portal.
# If you can't enable it, set this to "0" in env to run the bot without message counting.
REQUIRE_MESSAGE_CONTENT_INTENT = os.getenv("REQUIRE_MESSAGE_CONTENT_INTENT", "1").strip() not in ("0", "false", "False")

# Default pagination / leaderboard sizes
DEFAULT_TOP_N = int(os.getenv("DEFAULT_TOP_N", "10"))

# =========================
# Keyword matching rules
# =========================
# How aggressive to be when matching inside words (e.g., "abso-fucking-lutely").
# 0 = only whole tokens
# 1 = allow inside-word matches with safe boundaries (recommended)
MATCH_MODE = int(os.getenv("MATCH_MODE", "1"))

# Optional extra aliases for specific keywords (lowercase).
# Example: for keyword "fuck" include slang variants.
KEYWORD_ALIASES: Dict[str, List[str]] = {
    "fuck": ["fucks", "fucking", "fuckin", "fuckity", "wtf", "tf"],
}

# =========================
# Stopwords
# =========================
# Built-in stopwords are in cogs/stopwords.py (user can add more via commands).

# =========================
# Medals / game
# =========================
# Tier thresholds for "how many times you used a keyword".
MEDAL_THRESHOLDS: List[int] = [25, 50, 100, 250, 500, 1000, 2500, 5000]

# Cooldown after removing a keyword before medal cleanup (seconds)
KEYWORD_REMOVAL_GRACE_SECONDS = int(os.getenv("KEYWORD_REMOVAL_GRACE_SECONDS", "3600"))

# Emoji per tier (index aligned with MEDAL_THRESHOLDS)
MEDAL_EMOJIS: List[str] = ["🥉", "🥈", "🥇", "🏅", "🎖️", "👑", "⚔️", "🏰"]

# Title templates (keyword is injected as Title-cased / upper where needed)
# Keep it quirky + royal/knight themed.
TITLE_TEMPLATES: List[str] = [
    "Squire of {K}",
    "Knight of {K}",
    "Baron of {K}",
    "Count of {K}",
    "Duke of {K}",
    "Archduke of {K}",
    "High King of {K}",
    "Mythic Sovereign of {K}",
]

def get_bot_token() -> str:
    return BOT_TOKEN
