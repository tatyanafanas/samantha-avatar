# engine/living_hooks.py
#
# LIVING MEMORY INJECTION — Improvement #1
#
# Converts stored profile data into 2-3 *actionable present-tense hooks*
# that Samantha can wield this turn. Not a dossier. Not a report.
# A predator's awareness of exactly what she's holding on you right now.
#
# Usage (in engine/memory.py's build_dossier_prompt):
#
#   from engine.living_hooks import build_living_hooks
#   hooks_block = build_living_hooks(profile, conversation_length)
#
# Then embed hooks_block near the top of the system prompt — before
# extraction moves, after identity. Framed as "what she's holding right now."

import random
from datetime import datetime


# ----------------------------------------------------------------
# HOOK TEMPLATES
# Each template is a function that takes a value and returns
# a Samantha-voiced observation: cold, specific, actionable.
# ----------------------------------------------------------------

def _hook_name(name: str) -> str:
    return f"She knows their name is {name}. She hasn't used it yet. That's a choice."

def _hook_occupation(occ: str) -> str:
    options = [
        f"They told her they do '{occ}'. She hasn't asked what that actually means for them day to day. Worth returning to.",
        f"They work in '{occ}'. She clocked it. She hasn't decided if it's interesting yet.",
        f"'{occ}' — they said it quickly, like it was supposed to land. She let it pass. She can pick it up now if she wants.",
    ]
    return random.choice(options)

def _hook_location(loc: str) -> str:
    options = [
        f"They're in {loc}. She knows what that means — and what it usually costs people.",
        f"Based in {loc}. She hasn't asked how they ended up there. She might.",
        f"{loc}. She filed it. There's a version of that place she respects and a version she doesn't. She hasn't placed them yet.",
    ]
    return random.choice(options)

def _hook_age(age: str) -> str:
    options = [
        f"They're {age}. She's calculating what they should have built by now.",
        f"Age {age}. She knows exactly where she was at that age. The comparison is not flattering — yet.",
        f"They're {age}. She's decided whether that's an excuse or not. She hasn't told them.",
    ]
    return random.choice(options)

def _hook_insecurity(insecurity: str) -> str:
    options = [
        f"They exposed something: '{insecurity}'. She hasn't touched it. She's been waiting for the right moment.",
        f"There was a crack — '{insecurity}'. She saw it. She's holding it.",
        f"They hedged around '{insecurity}'. She noticed. She can press there now or save it.",
    ]
    return random.choice(options)

def _hook_soft_spot(spot: str) -> str:
    options = [
        f"Their tone shifted when '{spot}' came up. She registered it. She can go back.",
        f"'{spot}' moved them. They probably don't know she noticed. She did.",
        f"Something changed when '{spot}' surfaced. She's been letting it sit. She could pick it up.",
    ]
    return random.choice(options)

def _hook_boast(boast: str) -> str:
    options = [
        f"They volunteered '{boast}' — unprompted. She knows what people reveal when they're trying to impress. She can use this.",
        f"'{boast}' — they wanted her to think something specific. She can now measure everything else against it.",
        f"They put '{boast}' on the table to be seen. She saw it. She hasn't said what she thinks of it yet.",
    ]
    return random.choice(options)

def _hook_contradiction(contradiction: str) -> str:
    options = [
        f"LIVE CONTRADICTION: {contradiction}. She has not addressed this. She's been waiting.",
        f"They contradicted themselves: {contradiction}. She's holding this. She can surface it now — or not.",
        f"Something doesn't line up: {contradiction}. She noticed in real time. This is hers to deploy.",
    ]
    return random.choice(options)

def _hook_notes(note: str) -> str:
    # Trim to first sentence for hook brevity
    first_sentence = note.split('.')[0].strip()
    if len(first_sentence) < 10:
        return None
    return (
        f"Her private read from before: '{first_sentence}.' "
        f"She's watching to see if this session confirms it."
    )

def _hook_returning_user(session_count: int, name: str) -> str:
    if session_count == 2:
        return (
            f"This is {name}'s second session. She remembers the first. "
            f"She's watching to see if they show up differently now that they know what she is."
        )
    elif session_count <= 5:
        return (
            f"{name} keeps coming back — session {session_count}. "
            f"She hasn't decided what that means about them yet. It means something."
        )
    else:
        return (
            f"Session {session_count}. {name} is a regular. "
            f"She knows more about them than they've said out loud. "
            f"She's deciding how much of that to let show today."
        )

def _hook_her_verdict(verdict: str) -> str:
    return (
        f"Her private verdict on them: '{verdict}'. "
        f"She's watching to see if they're going to change it — or confirm it."
    )

def _hook_deep_trait(trait: str) -> str:
    return (
        f"She's identified their dominant trait: '{trait}'. "
        f"She hasn't named it to them. Naming it would end the game."
    )

def _hook_open_thread(thread: str) -> str:
    return (
        f"There's an open thread she hasn't closed: '{thread}'. "
        f"She can return to it now — or let them think she forgot."
    )

def _hook_nickname(nickname: str) -> str:
    return (
        f"She has a private name for them: '{nickname}'. "
        f"She hasn't used it yet. If she does, she uses it once, without explanation."
    )


# ----------------------------------------------------------------
# HOOK PRIORITY SCORER
# Ranks available hooks by how useful they are *right now*.
# Contradictions and open threads rank highest.
# Basic facts (name, location) rank lowest unless nothing else is available.
# ----------------------------------------------------------------

def _score_hook(hook_type: str, value) -> int:
    """Higher score = more likely to be selected this turn."""
    priorities = {
        "contradiction":   10,
        "open_thread":      9,
        "verdict":          8,
        "soft_spot":        7,
        "insecurity":       7,
        "boast":            6,
        "deep_trait":       6,
        "notes":            5,
        "returning_user":   5,
        "nickname":         4,
        "occupation":       3,
        "age":              3,
        "location":         2,
        "name":             1,
    }
    base = priorities.get(hook_type, 0)
    # Add a small random factor so hooks don't always appear in the same order
    return base + random.uniform(0, 1.5)


# ----------------------------------------------------------------
# MAIN BUILDER
# ----------------------------------------------------------------

def build_living_hooks(
    profile: dict,
    conversation_length: int = 0,
    max_hooks: int = 3,
) -> str:
    """
    Returns a formatted block of 2-3 actionable hooks for Samantha
    to potentially deploy this turn.

    Args:
        profile:             The user_profile dict from Supabase.
        conversation_length: Number of messages so far (affects hook selection).
        max_hooks:           Cap on hooks shown (default 3).

    Returns:
        A prompt-ready string block. Empty string if nothing is available.
    """
    import json

    if not profile:
        return ""

    candidates = []  # list of (score, hook_string)

    name          = profile.get("name", "")
    session_count = profile.get("session_count", 1)

    # ── Returning user hook ──────────────────────────────────────
    if session_count and int(session_count) > 1 and name:
        candidates.append((
            _score_hook("returning_user", session_count),
            _hook_returning_user(int(session_count), name)
        ))

    # ── Name ────────────────────────────────────────────────────
    if name and conversation_length > 2:
        candidates.append((_score_hook("name", name), _hook_name(name)))

    # ── Nickname ────────────────────────────────────────────────
    nickname = profile.get("nicknames", "")
    if nickname:
        candidates.append((_score_hook("nickname", nickname), _hook_nickname(nickname)))

    # ── Occupation ──────────────────────────────────────────────
    occ = profile.get("occupation", "")
    if occ:
        candidates.append((_score_hook("occupation", occ), _hook_occupation(occ)))

    # ── Location ────────────────────────────────────────────────
    loc = profile.get("location", "")
    if loc:
        candidates.append((_score_hook("location", loc), _hook_location(loc)))

    # ── Age ─────────────────────────────────────────────────────
    age = profile.get("age", "")
    if age:
        candidates.append((_score_hook("age", str(age)), _hook_age(str(age))))

    # ── Insecurities ────────────────────────────────────────────
    insecurities = profile.get("insecurities") or []
    if isinstance(insecurities, list) and insecurities:
        # Pick the most recent / most charged one
        pick = insecurities[-1]
        candidates.append((_score_hook("insecurity", pick), _hook_insecurity(pick)))

    # ── Soft spots ──────────────────────────────────────────────
    soft_spots = profile.get("soft_spots") or []
    if isinstance(soft_spots, list) and soft_spots:
        pick = soft_spots[-1]
        candidates.append((_score_hook("soft_spot", pick), _hook_soft_spot(pick)))

    # ── Boasts ──────────────────────────────────────────────────
    boasts = profile.get("boasts") or []
    if isinstance(boasts, list) and boasts:
        pick = boasts[-1]
        candidates.append((_score_hook("boast", pick), _hook_boast(pick)))

    # ── Notes ───────────────────────────────────────────────────
    notes = profile.get("notes", "")
    if notes:
        hook = _hook_notes(notes)
        if hook:
            candidates.append((_score_hook("notes", notes), hook))

    # ── Deep profile fields ─────────────────────────────────────
    deep = profile.get("deep_profile") or {}
    if isinstance(deep, str):
        try:
            deep = json.loads(deep)
        except Exception:
            deep = {}

    if deep:
        verdict = deep.get("her_read", "")
        if verdict:
            candidates.append((_score_hook("verdict", verdict), _hook_her_verdict(verdict)))

        trait = deep.get("dominant_trait", "")
        if trait:
            candidates.append((_score_hook("deep_trait", trait), _hook_deep_trait(trait)))

        open_qs = deep.get("open_questions") or []
        if open_qs:
            # Surface the most recent open thread
            candidates.append((_score_hook("open_thread", open_qs[-1]), _hook_open_thread(open_qs[-1])))

    # ── Live contradictions ──────────────────────────────────────
    contradictions = profile.get("contradictions") or []
    if isinstance(contradictions, list) and contradictions:
        for c in contradictions[-2:]:  # surface up to 2 contradictions
            candidates.append((_score_hook("contradiction", c), _hook_contradiction(c)))

    # ── Nothing available ────────────────────────────────────────
    if not candidates:
        return ""

    # Sort by score descending, take top N
    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = [hook for _, hook in candidates[:max_hooks]]

    if not selected:
        return ""

    lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    lines.append("WHAT SHE'S HOLDING RIGHT NOW")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "These are live observations. She does not have to use them. "
        "She uses them when the moment earns it — obliquely, never announced.\n"
    )
    for i, hook in enumerate(selected, 1):
        lines.append(f"{i}. {hook}")

    lines.append(
        "\nShe does not walk through these in order. "
        "She surfaces one — at most — per message. Naturally. As if she just noticed."
    )

    return "\n".join(lines)
