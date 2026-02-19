from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

ZWSP = "\u200b"

import unicodedata

# Token pattern: Latin letters/digits with optional apostrophes, plus Devanagari letters.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*|[\u0900-\u097F]+", re.UNICODE)

# Matches common English contractions that should collapse to the base word.
# Examples: they'd -> they, he'll -> he, it's -> it, can't -> can (handles n't as 't')
_CONTRACTION_RE = re.compile(r"^([a-z]+)(?:'(?:d|ll|ve|re|m|s|t))$", re.IGNORECASE)

# --- Lightweight Porter Stemmer (for English) ---
# Based on the original Porter stemming algorithm; implemented here to avoid extra deps.
# Only applied to simple ASCII a-z words.

_VOWELS = set("aeiou")

def _cons(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _cons(word, i - 1)
    return True

def _m(word: str) -> int:
    n = 0
    i = 0
    L = len(word)
    while True:
        if i >= L:
            return n
        if not _cons(word, i):
            break
        i += 1
    i += 1
    while True:
        while True:
            if i >= L:
                return n
            if _cons(word, i):
                break
            i += 1
        i += 1
        n += 1
        while True:
            if i >= L:
                return n
            if not _cons(word, i):
                break
            i += 1
        i += 1

def _vowel_in_stem(word: str) -> bool:
    return any(not _cons(word, i) for i in range(len(word)))

def _doublec(word: str) -> bool:
    if len(word) < 2:
        return False
    return word[-1] == word[-2] and _cons(word, len(word) - 1)

def _cvc(word: str) -> bool:
    if len(word) < 3:
        return False
    if not _cons(word, -1) or _cons(word, -2) or not _cons(word, -3):
        return False
    ch = word[-1]
    return ch not in "wxy"

def porter_stem(word: str) -> str:
    w = word
    if len(w) <= 2:
        return w

    # Step 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]

    # Step 1b
    flag = False
    if w.endswith("eed"):
        stem = w[:-3]
        if _m(stem) > 0:
            w = w[:-1]
    elif w.endswith("ed"):
        stem = w[:-2]
        if _vowel_in_stem(stem):
            w = stem
            flag = True
    elif w.endswith("ing"):
        stem = w[:-3]
        if _vowel_in_stem(stem):
            w = stem
            flag = True
    # user's typo variant
    elif w.endswith("ind"):
        stem = w[:-3]
        if _vowel_in_stem(stem):
            w = stem
            flag = True

    if flag:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _doublec(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _m(w) == 1 and _cvc(w):
            w += "e"

    # Step 1c
    if w.endswith("y"):
        stem = w[:-1]
        if _vowel_in_stem(stem):
            w = stem + "i"

    # Step 2 (subset)
    step2 = {
        "ational": "ate",
        "tional": "tion",
        "enci": "ence",
        "anci": "ance",
        "izer": "ize",
        "abli": "able",
        "alli": "al",
        "entli": "ent",
        "eli": "e",
        "ousli": "ous",
        "ization": "ize",
        "ation": "ate",
        "ator": "ate",
        "alism": "al",
        "iveness": "ive",
        "fulness": "ful",
        "ousness": "ous",
        "aliti": "al",
        "iviti": "ive",
        "biliti": "ble",
    }
    for suf, rep in step2.items():
        if w.endswith(suf):
            stem = w[: -len(suf)]
            if _m(stem) > 0:
                w = stem + rep
            break

    # Step 3 (subset)
    step3 = {
        "icate": "ic",
        "ative": "",
        "alize": "al",
        "iciti": "ic",
        "ical": "ic",
        "ful": "",
        "ness": "",
    }
    for suf, rep in step3.items():
        if w.endswith(suf):
            stem = w[: -len(suf)]
            if _m(stem) > 0:
                w = stem + rep
            break

    # Step 4 (very small subset; keep conservative)
    step4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize")
    for suf in step4:
        if w.endswith(suf):
            stem = w[: -len(suf)]
            if suf == "ion":
                if stem and stem[-1] not in "st":
                    continue
            if _m(stem) > 1:
                w = stem
            break

    # Step 5a
    if w.endswith("e"):
        stem = w[:-1]
        m = _m(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            w = stem

    # Step 5b
    if _m(w) > 1 and _doublec(w) and w.endswith("l"):
        w = w[:-1]

    return w

def normalize_text(s: str) -> str:
    return (s or "").strip()

def normalize_word(w: str) -> str:
    """Normalize a token for counting/searching.

    - Unicode normalize (NFKC) + convert curly apostrophes to ASCII '
    - Case-fold (LOVE/Love/LoVe -> love)
    - Strip surrounding punctuation/symbols
    - Collapse common contractions to the base word (they'd -> they)
    """
    if not w:
        return ""
    w = unicodedata.normalize("NFKC", w)
    w = w.replace("’", "'").replace("‘", "'")
    w = w.casefold()

    # strip leading/trailing non-word chars (keep apostrophes inside)
    w = re.sub(r"^[^\w\u0900-\u097F']+|[^\w\u0900-\u097F']+$", "", w)

    # collapse contractions (latin)
    m = _CONTRACTION_RE.match(w)
    if m:
        base = m.group(1)
        # special-case n't -> base already captured (can, don, isn) which is fine; these are stopwords anyway
        w = base

    return w


def stem_word(w: str) -> str:
    """Lightweight stemmer to merge common suffix variants.

    Examples:
      eat/eats/eating/eaten/ate -> eat (best-effort)
      play/played/playing/plays -> play

    This is intentionally simple (no external deps).
    """
    w = normalize_word(w)
    if not w:
        return ""
    # Special-case some very common irregulars (extend if needed)
    irregular = {
        "ate": "eat",
        "eaten": "eat",
        "eating": "eat",
    }
    if w in irregular:
        return irregular[w]

    # Remove common suffixes; keep it conservative for short words to avoid over-stemming.
    if len(w) <= 3:
        return w

    # plural/3rd person
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("es") and len(w) > 4:
        w = w[:-2]
    elif w.endswith("s") and len(w) > 3:
        w = w[:-1]

    # past tense / gerund
    if w.endswith("ing") and len(w) > 5:
        w = w[:-3]
        # handle double consonant: running -> run, stopping -> stop
        if len(w) >= 2 and w[-1] == w[-2]:
            w = w[:-1]
    elif w.endswith("ed") and len(w) > 4:
        w = w[:-2]
        if len(w) >= 2 and w[-1] == w[-2]:
            w = w[:-1]
    return w

def tokenize(s: str) -> List[str]:
    """Tokenize to normalized tokens (case-insensitive, punctuation-tolerant)."""
    s = normalize_text(s)
    if not s:
        return []
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'")
    raw = _TOKEN_RE.findall(s)
    out: List[str] = []
    for t in raw:
        nt = normalize_word(t)
        if nt:
            out.append(nt)
    return out
def split_csv_words(s: str) -> List[str]:
    """Split a user input string into normalized words (comma/space/newline separated)."""
    if not s:
        return []
    parts = re.split(r"[\s,]+", (s or "").strip())
    out: List[str] = []
    for p in parts:
        w = normalize_word(p)
        if w:
            out.append(w)
    return out

def keyword_display(keyword: str) -> str:
    """Pretty keyword for UI."""
    if not keyword:
        return ""
    # Title-case but keep common acronyms readable
    if keyword.isupper():
        return keyword
    return keyword[:1].upper() + keyword[1:].lower()

def build_keyword_regex(keyword: str, aliases: Sequence[str] | None = None) -> re.Pattern:
    """
    Build a regex to match:
      - keyword at token boundary (non-alnum before)
      - then optional letters (for simple suffixes: plural/verb forms)
      - stop on non-letter
    This catches:
      'fuck', 'fucks', 'fucking', 'abso-fucking-lutely'
    But tries to avoid matching inside other words like 'pass' for 'ass'
    by requiring a non-alnum boundary before the root.
    """
    kw = re.escape(keyword.lower())
    alts = [kw]
    if aliases:
        for a in aliases:
            a = a.strip().lower()
            if a:
                alts.append(re.escape(a))
    group = "(?:" + "|".join(sorted(set(alts), key=len, reverse=True)) + ")"
    # boundary before: not a letter/digit
    # after: allow letters for inflections, then require next char not a letter
    pat = rf"(?<![a-z0-9]){group}[a-z]*"
    return re.compile(pat, re.IGNORECASE)

def count_keyword_occurrences(message: str, keyword: str, aliases: Sequence[str] | None = None) -> int:
    """Count occurrences of keyword variants in a message.

    Uses tokenization + stemming so counts are case-insensitive, punctuation-tolerant,
    and merges common suffix forms (eat/eating/eaten -> eat).    """
    if not message or not keyword:
        return 0

    tokens = [stem_word(t) for t in tokenize(message)]
    if not tokens:
        return 0

    kw = stem_word(keyword)
    alias_norm = [stem_word(a) for a in (aliases or []) if stem_word(a)]
    allowed = set([kw, *alias_norm])
    return sum(1 for t in tokens if t in allowed)
def user_mention(user_id: int) -> str:
    """Return a mention string. Use AllowedMentions.none() when sending to avoid pings."""
    return f"<@{int(user_id)}>"

def safe_allowed_mentions():
    import discord
    return discord.AllowedMentions.none()

def progress_bar(curr: int, target: int, width: int = 12) -> str:
    if target <= 0:
        return "█" * width
    curr = max(0, min(curr, target))
    filled = int(round(width * (curr / target)))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)