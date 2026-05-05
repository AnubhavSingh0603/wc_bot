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


def compact_latin_word(value: str) -> str:
    """Normalize a word for embedded keyword matching."""
    value = normalize_word(value)
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def keyword_root_forms(keyword: str) -> set[str]:
    """Return conservative root forms used for configured keyword matching."""
    kw = compact_latin_word(keyword)
    if not kw:
        return set()
    forms = {kw, stem_word(kw), porter_stem(kw)}
    if kw.endswith("y") and len(kw) > 3:
        forms.add(kw[:-1] + "ie")
    return {f for f in forms if f}


_SUFFIX_VARIANT_TAILS = {
    # plurals / possessive-like word endings
    "s", "es",
    # verbs
    "d", "ed", "er", "ers", "ing",
    # adjectives/adverbs/common derivations
    "y", "ies", "ish", "ly", "ness", "ful", "less",
    # noun/adjective derivations requested by user and common variants
    "ity", "ities", "ility", "ilities", "able", "ible", "ability", "ibilities",
    # common longer derivations; kept as suffix-only, not fuzzy spell correction
    "ment", "ments", "tion", "tions", "ation", "ations", "ization", "izations",
    "ism", "isms", "ery", "eries",
}

# Prefix-compound tails that are common enough to be intentional for short roots,
# but not broad enough to make words like hello -> hell or caterpillar -> cat.
_COMMON_COMPOUND_TAILS = {
    "hole", "head", "face", "fuck", "fucker", "fucking", "fuckery", "shit", "shitter", "shitting",
    "wipe", "hat", "bag", "lord", "king", "queen", "boy", "girl", "man", "woman", "brain",
    "clown", "lord", "lordy", "lordship",
}


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _suffix_variant_match(tok: str, root: str) -> bool:
    """Strictly match exact/common suffix variants of a configured keyword.

    This intentionally does not do spelling correction. For example, ``pies``
    must never count as ``piss`` even though it is visually close.
    """
    if tok == root:
        return True
    if len(root) < 3 or len(tok) <= len(root):
        return False

    candidates = {root}

    # Direct suffixes: hellish, hellity, pisses, pissed, pissing, fucker.
    for suf in _SUFFIX_VARIANT_TAILS:
        candidates.add(root + suf)

    # Drop final silent e before some endings: love -> loving/lovable.
    if root.endswith("e") and len(root) > 3:
        base = root[:-1]
        for suf in ("ing", "ed", "er", "ers", "able", "ability", "ity", "ly"):
            candidates.add(base + suf)

    # y -> ies/iness/iful style: silly -> sillies/silliness.
    if root.endswith("y") and len(root) > 3:
        base = root[:-1]
        candidates.update({base + "ies", base + "iness", base + "iful", base + "ily"})

    # Double-final-consonant before ed/ing/er: piss -> pissed/pissing/pisser.
    if root[-1] not in "aeiouy" and len(root) >= 3:
        doubled = root + root[-1]
        for suf in ("ed", "ing", "er", "ers", "y", "ies"):
            candidates.add(doubled + suf)

    return tok in candidates


def _embedded_keyword_match(tok: str, root: str, all_roots: set[str] | None = None) -> bool:
    """Conservative embedded matching for configured keywords.

    Goal:
      ✅ hell/hells/hellish/hellity, piss/pissed/pissing, ass/asses
      ✅ dumbass, hoeass, assfuck, assfuckery, asshole
      ❌ hello->hell, pies->piss, cassie/classic/assassin->ass

    The rule is intentionally deterministic and does not use typo/fuzzy matching.
    """
    if not tok or not root or len(root) < 3:
        return False

    all_roots = all_roots or set()

    # 1) Exact and approved suffix variants only.
    if _suffix_variant_match(tok, root):
        return True

    # 2) Stem equality is allowed only when it does not shrink to a tiny unsafe
    # stem. This keeps pissed/pissing -> piss but avoids broad typo-like matches.
    tok_forms = {stem_word(tok), porter_stem(tok)}
    root_forms = {stem_word(root), porter_stem(root)}
    safe_forms = {f for f in (tok_forms & root_forms) if len(f) >= max(3, min(len(root), 4))}
    if safe_forms:
        return True

    # 3) Prefix compounds: root + meaningful tail.
    if tok.startswith(root) and len(tok) > len(root):
        tail = tok[len(root):]

        # Configured-overlap compounds: assfuck counts as ass and fuck when both
        # are configured. Also handles suffixes after the second root: assfuckery.
        for other in all_roots:
            if other != root and len(other) >= 3 and tail.startswith(other):
                remainder = tail[len(other):]
                if not remainder or _suffix_variant_match(other + remainder, other):
                    return True

        # Common known compound tails for short roots, e.g. asshole, shithead.
        if tail in _COMMON_COMPOUND_TAILS:
            return True
        for common in _COMMON_COMPOUND_TAILS:
            if tail.startswith(common) and _suffix_variant_match(tail, common):
                return True

        # Conservative generic compounds. Reject vowel-starting tails for short
        # consonant-ending roots, which blocks hello/assassin/assist/assume/caterpillar.
        if len(root) <= 4 and root[-1] not in "aeiouy" and tail[0] in "aeiouy":
            return False
        # Require a substantial tail and at least one vowel so random short tails
        # do not become matches. This catches many readable compounds like catnip
        # while rejecting hello -> hell.
        return len(tail) >= 3 and any(ch in "aeiouy" for ch in tail)

    # 4) Suffix compounds: meaningful prefix + root, e.g. dumbass/badass/hoeass.
    if tok.endswith(root) and len(tok) > len(root):
        head = tok[:-len(root)]
        # avoid pass/class/grass for ass; require a meaningful compound head
        return len(head) >= 3 and any(ch in "aeiouy" for ch in head)

    # 5) Middle compounds only for safer 4+ letter roots, e.g. absofuckinglutely.
    if len(root) >= 4:
        idx = tok.find(root)
        if idx > 0:
            before = tok[:idx]
            after = tok[idx + len(root):]
            if len(before) >= 3 and (not after or len(after) >= 2):
                return True

    # 6) Doubled-letter variants for very short slang roots: tit -> titties.
    if len(root) <= 4:
        doubled = root + root[-1]
        if doubled in tok and not tok.startswith(root[:-1] if len(root) > 1 else root):
            return True

    return False

def token_matches_keyword(token: str, keyword: str, all_keywords: Iterable[str] | None = None) -> bool:
    """Return True when a token should count toward a configured keyword.

    This is used for every configured keyword, not a hard-coded special case.
    ``all_keywords`` lets the matcher recognize intentional overlapping
    compounds such as ``assfuckery`` when both ``ass`` and ``fuck`` are configured.
    """
    tok = compact_latin_word(token)
    if not tok:
        return False

    all_roots: set[str] = set()
    if all_keywords is not None:
        for item in all_keywords:
            all_roots.update(keyword_root_forms(item))

    for root in keyword_root_forms(keyword):
        if _embedded_keyword_match(tok, root, all_roots):
            return True
    return False


def count_configured_keywords(tokens: Iterable[str], keywords: Iterable[str]) -> Dict[str, int]:
    """Count configured keywords canonically from tokenized message text.

    Each configured keyword is evaluated independently. This matters for words
    that intentionally contain multiple configured roots, for example:
      - ``hoeass`` should count for both ``hoe`` and ``ass`` when both exist
      - ``assfuckery`` should count for both ``ass`` and ``fuck`` when both exist
    """
    keyword_list = sorted({normalize_word(k) for k in keywords if normalize_word(k)}, key=len, reverse=True)
    counts: Dict[str, int] = {kw: 0 for kw in keyword_list}
    for tok in tokens:
        for kw in keyword_list:
            if token_matches_keyword(tok, kw, keyword_list):
                counts[kw] += 1
    return {kw: c for kw, c in counts.items() if c}

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
