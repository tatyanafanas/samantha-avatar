def analyze_interaction(profile, text):
    text_lower = text.lower()

    if any(word in text_lower for word in ["sorry", "please", "help", "kindly"]):
        profile["submission"] += 0.1
        profile["irritation"] += 0.1

    if len(text) > 100:
        profile["irritation"] -= 0.05

    # Clamp values
    profile["submission"] = min(max(profile["submission"], 0), 1)
    profile["irritation"] = min(max(profile["irritation"], 0), 1)

    # Mood logic
    if profile["irritation"] > 0.8:
        profile["mood"] = "Brisk Firing Imminent"
    elif profile["submission"] > 0.7:
        profile["mood"] = "Bored Majesty"
    else:
        profile["mood"] = "The Iron Gaze"

    return profile
