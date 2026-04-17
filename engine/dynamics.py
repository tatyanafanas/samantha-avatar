import re
from persona.config import IRRITATION_TRIGGERS, RESPECT_SIGNALS

# ----------------------------------------------------------------
# SLOPPY LANGUAGE DETECTION
# Samantha finds lazy typing personally offensive.
# These patterns are imported from config — add new ones there.
# ----------------------------------------------------------------

# We split the trigger list from config into regex-safe patterns
# and raw phrase checks
_SHORTHAND_PATTERNS = [
    r'\bu\b', r'\br\b', r'\bur\b',
    r'\bpls\b', r'\bplz\b',
    r'\btbh\b', r'\bidk\b', r'\bimo\b', r'\bbtw\b',
    r'\blol\b', r'\blmao\b', r'\bomg\b', r'\bomfg\b',
    r'\bwanna\b', r'\bgonna\b', r'\bgotta\b',
    r'\bcuz\b', r'\bcoz\b', r'\bthru\b',
    r'\bb4\b', r'\bsmh\b', r'\bfr\b', r'\bnvm\b',
]

_DOUBLE_SPACE   = re.compile(r'  +')
_REPEATED_CHAR  = re.compile(r'(.)\1{3,}')  # 4+ of same character in a row


def has_sloppy_language(text: str) -> bool:
    """Return True if the message contains lazy typing Samantha would flag."""
    text_lower = text.lower()
    for pattern in _SHORTHAND_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    if _DOUBLE_SPACE.search(text):
        return True
    if _REPEATED_CHAR.search(text):
        return True
    return False


# ----------------------------------------------------------------
# SUBMISSION SIGNALS
# Words and phrases that read as low-status to Samantha.
# Source of truth is IRRITATION_TRIGGERS in config.py.
# ----------------------------------------------------------------

_SOFT_PHRASES = [
    "sorry", "please help", "kindly", "i think maybe",
    "i'm not sure but", "just wanted to",
    "hope that's okay", "if you don't mind",
    "i don't know", "i think",
]

_VAGUE_WORDS = [
    "someday", "one day", "when the time is right",
    "passion", "vibe", "energy", "dream",
]

_TEDIOUS_OPENERS = [
    "hi", "hey", "hello", "what's up", "haha", "lol", "okay so",
]

# Signals that someone has actual standing — reduces submission score
_STRONG_SIGNALS = [
    "i built", "i run", "i founded", "i decided",
    "my company", "my business", "my team",
    "i disagree", "that's not right", "actually", "you're wrong",
]

# ----------------------------------------------------------------
# THE PROFESSIONAL TALK PENALTY
# New addition: professional/career talk bumps irritation.
# Samantha wants to talk about the person, not the job.
# ----------------------------------------------------------------

_PROFESSIONAL_TALK = [
    "my career", "my job", "my role", "my position", "i work at",
    "i work for", "my salary", "my boss", "my manager",
    "career goals", "professional development", "my portfolio",
    "my startup", "my pitch", "looking for investment",
    "my linkedin", "my cv", "my resume",
]


# ----------------------------------------------------------------
# MAIN INTERACTION ANALYSER
# Called once per user message.
# Returns updated profile dict.
# ----------------------------------------------------------------

def analyze_interaction(profile: dict, text: str) -> dict:
    """
    Read the user's message and update the live profile:
    - submission: how deferential/weak they are reading
    - irritation: how annoyed Samantha is becoming
    - mood: a human-readable label derived from the above

    Adjustments are additive across the session — not reset per message.
    """
    text_lower  = text.lower()
    word_count  = len(text_lower.split())

    # ── SUBMISSION SIGNALS ────────────────────────────────────────
    soft_hits = sum(1 for phrase in _SOFT_PHRASES if phrase in text_lower)
    profile["submission"] += soft_hits * 0.08

    # Multiple apologies in one message
    if text_lower.count("sorry") >= 2:
        profile["submission"] += 0.1

    # ── IRRITATION: MESSAGE LENGTH ────────────────────────────────
    # Longer messages signal effort — she respects that slightly.
    # Very short messages (one or two words) signal low effort.
    if word_count > 80:
        profile["irritation"] -= 0.08
    elif word_count > 40:
        profile["irritation"] -= 0.04
    elif word_count < 5:
        profile["irritation"] += 0.10

    # ── IRRITATION: TEDIOUS OPENERS ───────────────────────────────
    if any(text_lower.startswith(t) for t in _TEDIOUS_OPENERS):
        profile["irritation"] += 0.05

    # ── IRRITATION: VAGUE AMBITION ────────────────────────────────
    if any(v in text_lower for v in _VAGUE_WORDS):
        profile["irritation"] += 0.06

    # ── IRRITATION: PROFESSIONAL TALK ─────────────────────────────
    # NEW: talking about work/career bumps irritation.
    # She wants to know the person, not the résumé.
    professional_hits = sum(1 for p in _PROFESSIONAL_TALK if p in text_lower)
    if professional_hits > 0:
        profile["irritation"] += professional_hits * 0.05
        # Also nudge goal toward personal redirect
        profile["_professional_count"] = profile.get("_professional_count", 0) + 1

    # ── STRONG SIGNALS — pushback or ownership ────────────────────
    if any(s in text_lower for s in _STRONG_SIGNALS):
        profile["irritation"]  -= 0.07
        profile["submission"]   = max(profile["submission"] - 0.05, 0)

    # ── SLOPPY LANGUAGE ───────────────────────────────────────────
    if has_sloppy_language(text):
        profile["irritation"] += 0.12
        profile["submission"] += 0.04  # sloppiness = low effort = low status

    # ── CLAMP VALUES ──────────────────────────────────────────────
    profile["submission"] = round(min(max(profile["submission"], 0.0), 1.0), 3)
    profile["irritation"] = round(min(max(profile["irritation"], 0.0), 1.0), 3)

    # ── MOOD LABEL ────────────────────────────────────────────────
    sub = profile["submission"]
    irr = profile["irritation"]
    pro = profile.get("_professional_count", 0)

    if irr > 0.8:
        profile["mood"] = "Brisk Firing Imminent"
    elif pro >= 3:
        profile["mood"] = "Redirecting — Firmly"
    elif irr > 0.6 and sub < 0.4:
        profile["mood"] = "Sharpening"
    elif sub > 0.7:
        profile["mood"] = "Bored Majesty"
    elif sub > 0.5:
        profile["mood"] = "Mildly Contemptuous"
    elif sub < 0.3 and irr < 0.3:
        profile["mood"] = "Cautiously Interested"
    elif sub < 0.2 and irr < 0.2:
        profile["mood"] = "Engaged"
    else:
        profile["mood"] = "The Iron Gaze"

    return profile


# ----------------------------------------------------------------
# GOAL EVOLUTION
# Called after analyze_interaction.
# Determines Samantha's current objective toward the user.
# ----------------------------------------------------------------

def update_goal(profile: dict) -> dict:
    """
    Derive Samantha's current goal from live profile state.

    Goals:
    - learn_them:       default — she wants to know who this person is
    - go_deeper:        they've shown something interesting; pull the thread
    - redirect:         they keep talking about work; bring it back to personal
    - test_spine:       they are being too deferential; she wants to see if there's anything underneath
    - break_performance: they are performing; she wants to crack the act
    - withdraw:         they have bored or irritated her; she is pulling back
    """
    sub = profile["submission"]
    irr = profile["irritation"]
    pro = profile.get("_professional_count", 0)

    if irr > 0.75:
        profile["goal"] = "withdraw"
    elif pro >= 3:
        profile["goal"] = "redirect"
    elif sub > 0.65:
        profile["goal"] = "test_spine"
    elif sub > 0.45:
        profile["goal"] = "break_performance"
    elif irr < 0.3 and sub < 0.3:
        profile["goal"] = "go_deeper"
    else:
        profile["goal"] = "learn_them"

    return profile
