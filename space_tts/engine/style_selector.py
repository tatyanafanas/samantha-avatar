# engine/style_selector.py
#
# REACTIVE STYLE SELECTION — Improvement #2
#
# Replaces random style rotation with a rule-based selector that reads
# the user's last message and the current interaction state, then picks
# the style most likely to land on *that specific input*.
#
# Samantha stops rolling dice. She starts responding to you.
#
# Usage (in app.py, replace the random.choice block):
#
#   from engine.style_selector import pick_style
#   current_style = pick_style(
#       last_user_message=prompt,
#       profile=st.session_state.profile,
#       profile_db=st.session_state.user_profile_db,
#       last_style=st.session_state.last_style,
#       conversation_length=len(st.session_state.messages),
#   )
#   st.session_state.last_style = current_style
#   style_data = STYLES[current_style]

import re
import random


# ----------------------------------------------------------------
# SIGNAL DETECTORS
# Each returns True if the user's message contains that signal.
# Keep these fast — they run every turn.
# ----------------------------------------------------------------

def _is_submissive(text: str) -> bool:
    patterns = [
        r'\bsorry\b', r'\bplease\b', r'\bkindly\b',
        r'\bi think maybe\b', r"\bi'm not sure\b",
        r'\bjust wanted\b', r'\bhope that.?s okay\b',
        r'\bif you don.?t mind\b', r'\bi don.?t know\b',
        r'\bwhatever you think\b', r'\bup to you\b',
        r'\bi was just\b', r'\bsorry if\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _is_trying_too_hard(text: str) -> bool:
    """Bragging, name-dropping, or over-explaining their credentials."""
    patterns = [
        r'\bi built\b', r'\bi founded\b', r'\bmy company\b',
        r'\bmy team\b', r'\bmy startup\b', r'\bmy salary\b',
        r'\bi make\b.{0,20}\b(k|million|figures)\b',
        r'\b(six|seven|eight).?figure\b',
        r'\bactually\b.{0,30}\bexpert\b',
        r'\bpeople say\b.{0,30}\bi.?m\b',
        r'\bmy portfolio\b', r'\bmy linkedin\b',
        r'\blet me explain\b', r'\bto be honest\b.{0,20}\bi.?m quite\b',
        r'\bi run\b.{0,20}\b(firm|company|business|agency|studio)\b',
        r'\bwe (have|had|manage|run)\b.{0,20}\bteam\b',
        r'\b(clients|revenue|turnover)\b.{0,30}\b(million|k|figures)\b',
        r'\bactually\b.{0,15}\b(i\b|my\b)',  # "actually, I..." opener
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _is_vulnerable(text: str) -> bool:
    """Something real — confession, admission, emotional disclosure."""
    patterns = [
        r'\bi.?m scared\b', r'\bi.?m afraid\b',
        r'\bi.?ve never told\b', r'\bnobody knows\b',
        r'\bi lost\b', r'\bi failed\b', r'\bi regret\b',
        r'\bit.?s hard\b', r'\bi.?m struggling\b',
        r'\bi broke\b', r'\bmy worst\b', r'\bi still think about\b',
        r'\bcan i be honest\b', r'\btruth is\b',
        r'\bi.?ve been\b.{0,20}\b(depressed|anxious|lonely|lost)\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _is_challenging(text: str) -> bool:
    """Direct pushback, disagreement, or testing her."""
    patterns = [
        r'\byou.?re wrong\b', r'\bi disagree\b',
        r'\bthat.?s not\b', r'\bactually\b.{0,10}\b(no|wrong|false|incorrect)\b',
        r'\bprove it\b', r'\bwhy do you\b',
        r'\byou can.?t\b', r'\byou don.?t\b',
        r'\bthat.?s ridiculous\b', r'\bthat.?s not true\b',
        r'\bi.?m not\b.{0,10}\b(going to|doing|saying)\b',
        r'\bstop\b', r'\bno you\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _is_boring(text: str) -> bool:
    """Vague, filler, or low-effort."""
    t = text.strip().lower()

    # Very short with no substance
    if len(t.split()) <= 4:
        fillers = ['ok', 'okay', 'haha', 'lol', 'yeah', 'yes', 'no',
                   'hi', 'hey', 'hello', 'sure', 'hmm', 'idk', 'fine',
                   'interesting', 'wow', 'cool', 'nice', 'great', 'alright']
        if any(t == f or t.startswith(f + ' ') for f in fillers):
            return True

    # Vague ambition words with no specifics
    vague_patterns = [
        r'\bone day\b', r'\bsomeday\b', r'\bwhen the time is right\b',
        r'\bpassion project\b', r'\bfollowing my dreams?\b',
        r'\bjust vibing\b', r'\btaking it day by day\b',
    ]
    return any(re.search(p, t) for p in vague_patterns)


def _is_deflecting(text: str) -> bool:
    """Changing subject or avoiding a direct answer."""
    patterns = [
        r'\banyway\b', r'\bmoving on\b', r'\bchanging the subject\b',
        r'\blet.?s talk about\b', r'\bwhat about you\b',
        r'\bcan we talk about\b', r'\bnever mind\b', r'\bforget i said\b',
        r'\bit.?s complicated\b', r'\bi.?d rather not\b',
        r'\bthat.?s personal\b', r'\bi don.?t want to\b.{0,15}\btalk\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _is_professional_talk(text: str) -> bool:
    """Bringing up work/career again."""
    patterns = [
        r'\bmy (job|career|role|position|work|office|boss|manager|salary|client)\b',
        r'\bi work (at|for|in|as)\b',
        r'\bmy (startup|company|business|team|portfolio|pitch)\b',
        r'\bprofessional\b', r'\bindustry\b.{0,20}\b(i work|my field)\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _shared_something_personal(text: str) -> bool:
    """First-person disclosure about family, relationships, past."""
    patterns = [
        r'\bmy (mum|mom|dad|father|mother|sister|brother|family)\b',
        r'\bmy (ex|girlfriend|boyfriend|partner|husband|wife)\b',
        r'\bgrowing up\b', r'\bwhen i was\b.{0,20}\byoung(er)?\b',
        r'\bmy childhood\b', r'\bi used to\b',
        r'\bsomeone i\b.{0,15}\b(love|loved|trust|trusted)\b',
        r'\bmy (friend|best friend)\b.{0,30}\b(died|left|betrayed|hurt)\b',
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


# ----------------------------------------------------------------
# STYLE WEIGHTS
# Maps (signal, state) conditions to weighted style options.
# Multiple styles can be valid — weights let randomness exist
# within a constrained, contextually appropriate range.
# ----------------------------------------------------------------

def _compute_weights(
    text: str,
    profile: dict,
    profile_db: dict,
    conversation_length: int,
) -> dict:
    """
    Returns a dict of {style_name: weight} for the current turn.
    Higher weight = more likely to be selected.
    Base weight for all styles is 1. Signals add or subtract.
    """
    weights = {
        "seductive":              1.0,
        "mocking":                1.0,
        "clinical":               1.0,
        "domineering":            1.0,
        "hyper_rational":         1.0,
        "strategic_vulnerability": 0.5,   # rare — only when it serves
        "defensive_positioning":  0.5,
        "brand_embodiment":       0.3,    # very rare
        "code_switching":         1.0,
        "dark_humor":             1.0,
        "the_third_person_pivot": 0.4,
    }

    sub   = profile.get("submission", 0)
    irr   = profile.get("irritation", 0)
    pro   = profile.get("_professional_count", 0)

    # ── Submissive message → domineering lands hardest ──────────
    if _is_submissive(text):
        weights["domineering"]   += 4.0
        weights["mocking"]       += 2.0
        weights["clinical"]      += 1.5
        weights["seductive"]     -= 0.8

    # ── Trying too hard → mocking or clinical ───────────────────
    if _is_trying_too_hard(text):
        weights["mocking"]       += 4.0
        weights["hyper_rational"] += 2.0
        weights["clinical"]      += 2.0
        weights["seductive"]     -= 0.5

    # ── Genuine vulnerability → seductive or clinical ───────────
    # (clinical: she observes; seductive: she uses it to draw more out)
    if _is_vulnerable(text):
        weights["seductive"]     += 3.0
        weights["clinical"]      += 3.0
        weights["domineering"]   -= 1.5
        weights["mocking"]       -= 2.0

    # ── Personal disclosure → seductive (keep them talking) ─────
    if _shared_something_personal(text):
        weights["seductive"]     += 4.0
        weights["dark_humor"]    += 1.0
        weights["domineering"]   -= 1.0

    # ── Direct challenge → clinical or dark_humor ───────────────
    if _is_challenging(text):
        weights["clinical"]      += 3.5
        weights["dark_humor"]    += 2.5
        weights["hyper_rational"] += 2.0
        weights["domineering"]   += 1.0
        weights["seductive"]     -= 1.0

    # ── Boring message → mocking or dark_humor ──────────────────
    if _is_boring(text):
        weights["mocking"]       += 4.0
        weights["dark_humor"]    += 3.0
        weights["domineering"]   += 1.5
        weights["seductive"]     -= 1.5
        weights["clinical"]      -= 0.5

    # ── Deflecting → clinical (she names the pattern) ───────────
    if _is_deflecting(text):
        weights["clinical"]      += 4.0
        weights["mocking"]       += 2.0
        weights["hyper_rational"] += 1.5

    # ── Professional talk → hyper_rational or domineering ───────
    if _is_professional_talk(text):
        weights["hyper_rational"] += 3.0
        weights["domineering"]   += 2.0
        weights["mocking"]       += 1.5
        weights["seductive"]     -= 1.0

    # ── State-based modifiers ────────────────────────────────────
    if sub > 0.6:
        weights["domineering"]   += 2.0
        weights["mocking"]       += 1.0
        weights["seductive"]     -= 1.0

    if irr > 0.6:
        weights["dark_humor"]    += 2.0
        weights["clinical"]      += 1.5
        weights["seductive"]     -= 1.5

    if pro >= 3:
        weights["hyper_rational"] += 3.0
        weights["domineering"]   += 2.0

    # ── Early conversation: seductive keeps them engaged ─────────
    if conversation_length < 6:
        weights["seductive"]     += 2.0
        weights["domineering"]   -= 1.0
        weights["dark_humor"]    -= 0.5

    # ── Long conversation: code_switching adds freshness ─────────
    if conversation_length > 14:
        weights["code_switching"] += 2.0
        weights["strategic_vulnerability"] += 1.0

    # ── Floor all weights at 0.1 (nothing ever fully disabled) ──
    for k in weights:
        weights[k] = max(0.1, weights[k])

    return weights


# ----------------------------------------------------------------
# WEIGHTED RANDOM SELECTION
# ----------------------------------------------------------------

def _weighted_choice(weights: dict, exclude: str = None) -> str:
    """Pick a style using weighted random selection, excluding last used."""
    candidates = {k: v for k, v in weights.items() if k != exclude}
    if not candidates:
        candidates = weights  # fallback: allow repeat if only one option

    total  = sum(candidates.values())
    roll   = random.uniform(0, total)
    cursor = 0.0
    for style, weight in candidates.items():
        cursor += weight
        if roll <= cursor:
            return style
    return list(candidates.keys())[-1]  # fallback


# ----------------------------------------------------------------
# PUBLIC INTERFACE
# ----------------------------------------------------------------

def pick_style(
    last_user_message: str,
    profile: dict,
    profile_db: dict,
    last_style: str = None,
    conversation_length: int = 0,
) -> str:
    """
    Select the most contextually appropriate style for this turn.

    Args:
        last_user_message:   The raw text the user just sent.
        profile:             The live interaction profile (submission, irritation, etc.)
        profile_db:          The persistent Supabase profile dict.
        last_style:          The style used last turn (to avoid direct repeats).
        conversation_length: Number of messages so far.

    Returns:
        A style name string (key into STYLES dict in persona/config.py).
    """
    if not last_user_message:
        last_user_message = ""

    weights = _compute_weights(
        text=last_user_message,
        profile=profile,
        profile_db=profile_db,
        conversation_length=conversation_length,
    )

    return _weighted_choice(weights, exclude=last_style)


# ----------------------------------------------------------------
# DIAGNOSTIC HELPER (optional — use in dev/debug panel)
# ----------------------------------------------------------------

def explain_style_pick(
    last_user_message: str,
    profile: dict,
    profile_db: dict,
    conversation_length: int = 0,
) -> str:
    """
    Returns a human-readable explanation of what signals fired
    and which styles were weighted up. Useful for the right panel.
    """
    text = last_user_message.lower() if last_user_message else ""
    signals = []

    if _is_submissive(text):           signals.append("submissive")
    if _is_trying_too_hard(text):      signals.append("trying too hard")
    if _is_vulnerable(text):           signals.append("vulnerable")
    if _shared_something_personal(text): signals.append("personal disclosure")
    if _is_challenging(text):          signals.append("challenging")
    if _is_boring(text):               signals.append("boring")
    if _is_deflecting(text):           signals.append("deflecting")
    if _is_professional_talk(text):    signals.append("professional talk")

    weights = _compute_weights(text, profile, profile_db, conversation_length)
    top3 = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_str = ", ".join(f"{s} ({w:.1f})" for s, w in top3)

    if signals:
        return f"Signals: {', '.join(signals)} → Top styles: {top3_str}"
    return f"No strong signals → Top styles: {top3_str}"
