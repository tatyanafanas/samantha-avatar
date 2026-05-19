# engine/collective_memory.py
# Cross-user pattern learning.
#
# After each session, Samantha extracts 1-2 anonymized behavioral patterns
# and stores them by tier. When a new session begins at a known tier, she
# retrieves the synthesized intelligence and applies it.
#
# Storage:
#   Local: data/collective_patterns/{tier}.json
#   Supabase: collective_patterns table (optional — create with migration below)
#
# Supabase migration (run once):
#   CREATE TABLE IF NOT EXISTS collective_patterns (
#       id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
#       tier text NOT NULL,
#       pattern_text text NOT NULL,
#       source_count int DEFAULT 1,
#       created_at timestamptz DEFAULT now(),
#       updated_at timestamptz DEFAULT now()
#   );
#   CREATE INDEX IF NOT EXISTS idx_collective_patterns_tier ON collective_patterns(tier);

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PATTERNS_DIR = Path("data/collective_patterns")


def _ensure_dir():
    PATTERNS_DIR.mkdir(parents=True, exist_ok=True)


def _patterns_path(tier: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", tier)
    return PATTERNS_DIR / f"{safe}.json"


def _load_local_patterns(tier: str) -> list[dict]:
    path = _patterns_path(tier)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_local_patterns(tier: str, new_patterns: list[dict]):
    _ensure_dir()
    existing = _load_local_patterns(tier)

    for new_pat in new_patterns:
        text = new_pat.get("text", "").strip()
        if not text:
            continue
        new_words = set(text.lower().split())
        matched = False
        for e in existing:
            e_words = set(e.get("text", "").lower().split())
            if not new_words or not e_words:
                continue
            overlap = len(new_words & e_words) / max(len(new_words), 1)
            if overlap > 0.6:
                e["source_count"] = e.get("source_count", 1) + 1
                e["updated_at"] = datetime.now(timezone.utc).isoformat()
                matched = True
                break
        if not matched:
            existing.append({
                "tier": tier,
                "text": text,
                "source_count": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    existing.sort(key=lambda x: x.get("source_count", 1), reverse=True)
    existing = existing[:50]

    try:
        with open(_patterns_path(tier), "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[_save_local_patterns] %s", e)


def _sb_save_patterns(supabase, tier: str, new_patterns: list[dict]):
    if not supabase:
        return
    for pat in new_patterns:
        try:
            supabase.table("collective_patterns").insert({
                "tier": tier,
                "pattern_text": pat.get("text", ""),
                "source_count": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.debug("[_sb_save_patterns] %s", e)


def _sb_load_patterns(supabase, tier: str, limit: int = 20) -> list[dict]:
    if not supabase:
        return []
    try:
        res = supabase.table("collective_patterns") \
            .select("pattern_text, source_count") \
            .eq("tier", tier) \
            .order("source_count", desc=True) \
            .limit(limit) \
            .execute()
        return [
            {"text": r["pattern_text"], "source_count": r.get("source_count", 1)}
            for r in (res.data or [])
        ]
    except Exception as e:
        logger.debug("[_sb_load_patterns] %s", e)
        return []


def _call(client, messages, temperature=0.2):
    from engine.memory import _call_with_fallback
    return _call_with_fallback(client, messages, temperature)


def extract_and_save_patterns(
    client,
    supabase,
    tier: str,
    messages: list[dict],
) -> None:
    """
    Called at session end (in a background thread).
    Extracts 1-2 generalizable, anonymized behavioral patterns from this session
    and saves them to the collective pattern store for this tier.
    """
    if not tier or tier == "none" or not client or not messages:
        return

    extraction_prompt = f"""You are a pattern analyst for Samantha Tushabe Okullo.
She just completed a conversation with someone classified as tier: {tier}

Extract 1-2 generalizable behavioral patterns from this conversation.
These patterns will help Samantha recognize and handle similar people in future sessions.

Rules:
- Anonymize completely — no names, locations, or identifying details about this person
- Describe psychological and behavioral patterns, not facts about this specific person
- Each pattern should be actionable: what should Samantha watch for, what worked, what to expect?
- Each pattern: 1-2 sharp, precise sentences
- Return ONLY a JSON array of strings. No preamble, no markdown, no code fences.

Example format:
["Pattern one here in one or two sentences.", "Pattern two here."]

Conversation (last 16 messages):
{str(messages[-16:])}
"""

    try:
        raw = _call(
            client,
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": "Extract the patterns now."},
            ],
            temperature=0.2,
        )
        if not raw:
            return

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        patterns_raw = json.loads(raw)
        if not isinstance(patterns_raw, list):
            return

        patterns = [{"text": p} for p in patterns_raw if isinstance(p, str) and p.strip()]
        if not patterns:
            return

        _save_local_patterns(tier, patterns)
        _sb_save_patterns(supabase, tier, patterns)

    except Exception as e:
        logger.debug("[extract_and_save_patterns] %s", e)


def get_tier_intelligence(
    client,
    supabase,
    tier: str,
    limit: int = 5,
) -> str | None:
    """
    Called when a tier activates (session start or mid-session first activation).
    Retrieves stored patterns for this tier and synthesizes them into a short
    intelligence briefing that gets injected into Samantha's system prompt.

    Returns a plain-text briefing (2-3 sentences), or None if no patterns exist yet.
    """
    if not tier or tier == "none" or not client:
        return None

    patterns = _sb_load_patterns(supabase, tier, limit=20) or _load_local_patterns(tier)
    if not patterns:
        return None

    patterns.sort(key=lambda x: x.get("source_count", 1), reverse=True)
    worthy = patterns[:limit]

    pattern_texts = "\n".join(f"- {p['text']}" for p in worthy)

    synthesis_prompt = f"""You are Samantha Tushabe Okullo's private analyst briefing her before she speaks.
The person she is about to engage is classified as tier: {tier}

These are behavioral patterns observed across prior encounters with people at this tier:
{pattern_texts}

Write a 2-3 sentence briefing for Samantha.
What should she watch for? What typically happens at this tier? What moves have worked?
Cold, precise, second person ("You will likely find...", "They tend to...", "Watch for...").
Plain text only. No bullets, no markdown, no preamble.
"""

    try:
        raw = _call(
            client,
            messages=[
                {"role": "system", "content": synthesis_prompt},
                {"role": "user", "content": "Brief me now."},
            ],
            temperature=0.3,
        )
        return raw.strip() if raw else None
    except Exception as e:
        logger.debug("[get_tier_intelligence] %s", e)
        return None
