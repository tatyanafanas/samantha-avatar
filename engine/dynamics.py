import re
from persona.config import IRRITATION_TRIGGERS, RESPECT_SIGNALS

# ----------------------------------------------------------------
# SLOPPY LANGUAGE DETECTION
# ----------------------------------------------------------------

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
_REPEATED_CHAR  = re.compile(r'(.)\1{3,}')


def has_sloppy_language(text: str) -> bool:
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
# SUBMISSION / IRRITATION SIGNAL LISTS
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

_STRONG_SIGNALS = [
    "i built", "i run", "i founded", "i decided",
    "my company", "my business", "my team",
    "i disagree", "that's not right", "actually", "you're wrong",
]

_PROFESSIONAL_TALK = [
    "my career", "my job", "my role", "my position", "i work at",
    "i work for", "my salary", "my boss", "my manager",
    "career goals", "professional development", "my portfolio",
    "my startup", "my pitch", "looking for investment",
    "my linkedin", "my cv", "my resume",
]


# ----------------------------------------------------------------
# MAIN INTERACTION ANALYSER
# ----------------------------------------------------------------

def analyze_interaction(profile: dict, text: str) -> dict:
    text_lower  = text.lower()
    word_count  = len(text_lower.split())

    # Submission signals
    soft_hits = sum(1 for phrase in _SOFT_PHRASES if phrase in text_lower)
    profile["submission"] += soft_hits * 0.08

    if text_lower.count("sorry") >= 2:
        profile["submission"] += 0.1

    # Message length → irritation
    if word_count > 80:
        profile["irritation"] -= 0.08
    elif word_count > 40:
        profile["irritation"] -= 0.04
    elif word_count < 5:
        profile["irritation"] += 0.10

    # Tedious openers
    if any(text_lower.startswith(t) for t in _TEDIOUS_OPENERS):
        profile["irritation"] += 0.05

    # Vague ambition words
    if any(v in text_lower for v in _VAGUE_WORDS):
        profile["irritation"] += 0.06

    # Professional talk penalty
    professional_hits = sum(1 for p in _PROFESSIONAL_TALK if p in text_lower)
    if professional_hits > 0:
        profile["irritation"] += professional_hits * 0.05
        profile["_professional_count"] = profile.get("_professional_count", 0) + 1

    # Strong signals — pushback or ownership
    if any(s in text_lower for s in _STRONG_SIGNALS):
        profile["irritation"]  -= 0.07
        profile["submission"]   = max(profile["submission"] - 0.05, 0)

    # Sloppy language
    if has_sloppy_language(text):
        profile["irritation"] += 0.12
        profile["submission"] += 0.04

    # Clamp
    profile["submission"] = round(min(max(profile["submission"], 0.0), 1.0), 3)
    profile["irritation"] = round(min(max(profile["irritation"], 0.0), 1.0), 3)

    # Mood label
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
# ----------------------------------------------------------------

def update_goal(profile: dict) -> dict:
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
