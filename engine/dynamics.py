import re

# Common single-word typos / shorthand she'd find offensive
TYPO_PATTERNS = [
    r'\bu\b',           # "u" instead of "you"
    r'\br\b',           # "r" instead of "are"
    r'\bur\b',          # "ur"
    r'\bpls\b',         # "pls"
    r'\bplz\b',
    r'\btbh\b',
    r'\bidk\b',
    r'\bimo\b',
    r'\bbtw\b',
    r'\bngl\b',
    r'\blol\b',
    r'\blmao\b',
    r'\bomg\b',
    r'\bwanna\b',
    r'\bgonna\b',
    r'\bgotta\b',
    r'\bcuz\b',
    r'\bcos\b',
    r'\bcos\b',
    r'\bthru\b',
    r'\bw/\b',          # "w/" instead of "with"
    r'\bb4\b',          # "b4" instead of "before"
    r'\b4ever\b',
    r'\bngl\b',
    r'\bsmh\b',
    r'\bfr\b',          # "fr" = "for real"
    r'\bnvm\b',
    r'\bwdym\b',
    r'\bwtf\b',
    r'\bomfg\b',
]

# Regex: repeated characters suggesting typo (e.g. "teh", "hte", double-spaced words)
DOUBLE_SPACE = re.compile(r'  +')
REPEATED_CHAR = re.compile(r'(.)\1{3,}')  # 4+ of the same char


def has_sloppy_language(text: str) -> bool:
    text_lower = text.lower()
    for pattern in TYPO_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    if DOUBLE_SPACE.search(text):
        return True
    if REPEATED_CHAR.search(text):
        return True
    return False


def analyze_interaction(profile, text):
    text_lower = text.lower()
    words = text_lower.split()
    word_count = len(words)

    # --- SUBMISSION SIGNALS ---
    soft_words = [
        "sorry", "please", "help", "kindly", "i think", "maybe", "i don't know",
        "just wanted", "hope that's okay", "if you don't mind"
    ]
    soft_hits = sum(1 for phrase in soft_words if phrase in text_lower)
    profile["submission"] += soft_hits * 0.08

    if text_lower.count("sorry") >= 2:
        profile["submission"] += 0.1

    # --- IRRITATION SIGNALS ---
    if word_count > 80:
        profile["irritation"] -= 0.08
    elif word_count > 40:
        profile["irritation"] -= 0.04

    if word_count < 5:
        profile["irritation"] += 0.1

    tedious = ["hi", "hey", "hello", "what's up", "haha", "lol", "okay so"]
    if any(text_lower.startswith(t) for t in tedious):
        profile["irritation"] += 0.05

    strong_signals = [
        "actually", "i disagree", "that's not right", "you're wrong",
        "i built", "i run", "i founded", "my business", "my company"
    ]
    if any(s in text_lower for s in strong_signals):
        profile["irritation"] -= 0.07
        profile["submission"] = max(profile["submission"] - 0.05, 0)

    vague = ["passion", "vibe", "energy", "dream", "someday", "one day", "when the time is right"]
    if any(v in text_lower for v in vague):
        profile["irritation"] += 0.06

    # --- SLOPPY LANGUAGE / TYPOS ---
    if has_sloppy_language(text):
        profile["irritation"] += 0.12
        profile["submission"] += 0.04  # sloppiness reads as low-effort = low status

    # --- CLAMP VALUES ---
    profile["submission"] = round(min(max(profile["submission"], 0.0), 1.0), 3)
    profile["irritation"] = round(min(max(profile["irritation"], 0.0), 1.0), 3)

    # --- MOOD LOGIC ---
    sub = profile["submission"]
    irr = profile["irritation"]

    if irr > 0.8:
        profile["mood"] = "Brisk Firing Imminent"
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
