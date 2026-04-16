def analyze_interaction(profile, text):
    text_lower = text.lower()
    words = text_lower.split()
    word_count = len(words)

    # --- SUBMISSION SIGNALS ---
    soft_words = ["sorry", "please", "help", "kindly", "i think", "maybe", "i don't know",
                  "just wanted", "hope that's okay", "if you don't mind"]
    soft_hits = sum(1 for phrase in soft_words if phrase in text_lower)
    profile["submission"] += soft_hits * 0.08

    # Apologising twice in the same message: extra penalty
    if text_lower.count("sorry") >= 2:
        profile["submission"] += 0.1

    # --- IRRITATION SIGNALS ---
    # Long, thoughtful messages reduce irritation
    if word_count > 80:
        profile["irritation"] -= 0.08
    elif word_count > 40:
        profile["irritation"] -= 0.04

    # Very short, low-effort messages increase irritation
    if word_count < 5:
        profile["irritation"] += 0.1

    # Repetitive openers she finds tedious
    tedious = ["hi", "hey", "hello", "what's up", "haha", "lol", "okay so"]
    if any(text_lower.startswith(t) for t in tedious):
        profile["irritation"] += 0.05

    # Genuine pushback or confidence: she notices, irritation drops
    strong_signals = ["actually", "i disagree", "that's not right", "you're wrong",
                      "i built", "i run", "i founded", "my business", "my company"]
    if any(s in text_lower for s in strong_signals):
        profile["irritation"] -= 0.07
        profile["submission"] = max(profile["submission"] - 0.05, 0)

    # Vague aspiration language: she finds it hollow
    vague = ["passion", "vibe", "energy", "dream", "someday", "one day", "when the time is right"]
    if any(v in text_lower for v in vague):
        profile["irritation"] += 0.06

    # --- CLAMP VALUES ---
    profile["submission"] = round(min(max(profile["submission"], 0.0), 1.0), 3)
    profile["irritation"] = round(min(max(profile["irritation"], 0.0), 1.0), 3)

    # --- MOOD LOGIC (more granular) ---
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
