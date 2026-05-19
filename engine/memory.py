# engine/memory.py

import json
import logging
import math
from datetime import datetime, timezone
from engine.living_hooks import build_living_hooks
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# Local filesystem fallback for environments without Supabase
LOCAL_DATA_DIR = Path("data")

# Embedding model — Groq's free nomic embed (768-dim, already normalised)
EMBED_MODEL = "nomic-embed-text-v1.5"


def _ensure_local_dirs():
    (LOCAL_DATA_DIR / "profiles").mkdir(parents=True, exist_ok=True)
    (LOCAL_DATA_DIR / "transcripts").mkdir(parents=True, exist_ok=True)
    (LOCAL_DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (LOCAL_DATA_DIR / "embeddings").mkdir(parents=True, exist_ok=True)


# ================================================================
# EMBEDDING UTILITIES
# ================================================================

def embed_text(client, text: str) -> list | None:
    """Embed text via Groq's nomic model. Returns a float list or None."""
    if not client or not text:
        return None
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=text[:2000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("[embed_text] %s", e)
        return None


def _embeddings_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower())
    return LOCAL_DATA_DIR / "embeddings" / f"{safe}.json"


def _load_local_embeddings(name: str) -> dict:
    return _read_json_file(_embeddings_path(name)) or {}


def _save_local_embedding(name: str, session_id: str, embedding: list):
    _ensure_local_dirs()
    path = _embeddings_path(name)
    data = _load_local_embeddings(name)
    data[session_id] = embedding
    _write_json_file(path, data)


def _cosine_sim(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return dot / mag if mag else 0.0


def _profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower())
    return LOCAL_DATA_DIR / "profiles" / f"{safe}.json"


def _transcript_path(session_id: str) -> Path:
    return LOCAL_DATA_DIR / "transcripts" / f"{session_id}.json"


def _conversation_log_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower())
    return LOCAL_DATA_DIR / "logs" / f"{safe}.log"


def _read_json_file(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json_file(path: Path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


SUMMARY_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct",
    "llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama3-8b-8192",
    "mistral-saba-24b",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-32b",
    "qwen-qwq-32b",
    "llama3-70b-8192",
    "llama3-groq-70b-8192-tool-use-preview",
    "llama3-groq-8b-8192-tool-use-preview",
    "llama-guard-3-8b",
]


# ================================================================
# CORE LLM HELPER
# ================================================================

def _call_with_fallback(client, messages, temperature=0.3):
    """Try each model in SUMMARY_MODELS until one succeeds."""
    for model in SUMMARY_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e).lower()
            if any(x in error_str for x in [
                "rate limit", "429", "quota", "exceeded",
                "model", "not found", "unavailable"
            ]):
                continue
            raise
    return None


# ================================================================
# PROFILE CRUD
# ================================================================

def get_or_create_profile(supabase, name: str) -> dict:
    """Load existing profile or create a fresh one."""
    # Prefer Supabase when available, otherwise use local JSON store
    if supabase:
        try:
            res = supabase.table("user_profiles") \
                .select("*") \
                .eq("name", name) \
                .limit(1) \
                .execute()
            if res.data:
                profile = res.data[0]
                # Increment session count on each load
                new_count = (profile.get("session_count") or 0) + 1
                update_profile(supabase, name, {"session_count": new_count})
                profile["session_count"] = new_count
                return profile
        except Exception as e:
            logger.warning("[get_or_create_profile] Supabase error: %s", e)

    # Local fallback
    _ensure_local_dirs()
    path = _profile_path(name)
    existing = _read_json_file(path) or {}
    if existing:
        new_count = (existing.get("session_count") or 0) + 1
        existing["session_count"] = new_count
        _write_json_file(path, existing)
        return existing

    new_profile = {
        "name": name,
        "relationship_status": "stranger",
        "session_count": 1,
    }
    _write_json_file(path, new_profile)
    return new_profile


def update_profile(supabase, name: str, updates: dict):
    """Patch fields on an existing profile."""
    timestamped = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
    if supabase:
        try:
            supabase.table("user_profiles") \
                .update(timestamped) \
                .eq("name", name) \
                .execute()
            return
        except Exception as e:
            logger.warning("[update_profile] Supabase error: %s", e)

    # Local fallback
    _ensure_local_dirs()
    path = _profile_path(name)
    existing = _read_json_file(path) or {}
    existing.update(timestamped)
    _write_json_file(path, existing)


def _append_note(existing_notes: str | None, new_note: str, client=None) -> str:
    """
    Append a new observation to the running notes field.
    When the combined text exceeds 800 chars, uses an LLM synthesis pass
    (if client is provided) rather than crudely truncating at a character boundary.
    """
    if not new_note:
        return existing_notes or ""
    combined = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note
    if len(combined) > 800:
        if client:
            compressed = _call_with_fallback(
                client,
                messages=[
                    {"role": "system", "content": (
                        "Compress these analyst notes into 3-5 sharp sentences. "
                        "Keep only the most psychologically significant observations. "
                        "Plain text, no bullets, no markdown."
                    )},
                    {"role": "user", "content": combined},
                ],
                temperature=0.1,
            )
            if compressed:
                return compressed.strip()
        trimmed = combined[-800:]
        dot = trimmed.find(". ")
        combined = trimmed[dot + 2:] if dot != -1 else trimmed
    return combined


# ================================================================
# CONVERSATION LOGS
# ================================================================

def get_conversation_history(supabase, name: str, limit: int = 3) -> str:
    """Fetch the last N session summaries for this user."""
    if supabase:
        try:
            res = supabase.table("conversation_logs") \
                .select("summary, created_at") \
                .eq("user_name", name) \
                .order("created_at", desc=True) \
                .limit(limit) \
                .execute()
            if res.data:
                entries = [f"[{r['created_at'][:10]}] {r['summary']}" for r in res.data]
                return "\n---\n".join(entries)
        except Exception as e:
            logger.warning("[get_conversation_history] Supabase error: %s", e)

    # Local fallback: read last `limit` JSON lines from a log file
    _ensure_local_dirs()
    path = _conversation_log_path(name)
    if not path.exists():
        return "No prior sessions."
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        entries = []
        for line in lines[-limit:][::-1]:
            try:
                obj = json.loads(line)
                ts = obj.get("created_at", "?")[:10]
                entries.append(f"[{ts}] {obj.get('summary','')}")
            except Exception:
                entries.append(line[:160])
        return "\n---\n".join(entries) if entries else "No prior sessions."
    except Exception:
        return "No prior sessions."


def save_session_log(
    supabase,
    user_name: str,
    session_id: str,
    summary: str,
    embed_client=None,
    gender_tier: str = "none",
):
    """
    Save a session summary to conversation_logs.
    Guards against the FK violation by ensuring the user_profiles row
    exists before attempting the insert.
    When embed_client is provided, also stores the embedding locally for
    semantic retrieval (avoids requiring a schema change in Supabase).
    """
    if not user_name or not summary:
        return

    embedding = embed_text(embed_client, summary) if embed_client else None

    entry = {
        "user_name": user_name,
        "session_id": session_id,
        "summary": summary,
        "gender_tier": gender_tier,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if supabase:
        try:
            check = supabase.table("user_profiles") \
                .select("name") \
                .eq("name", user_name) \
                .limit(1) \
                .execute()

            if not check.data:
                supabase.table("user_profiles").upsert(
                    {"name": user_name, "session_count": 1},
                    on_conflict="name"
                ).execute()

            supabase.table("conversation_logs").insert({
                "user_name":   user_name,
                "session_id":  session_id,
                "summary":     summary,
                "gender_tier": gender_tier,
            }).execute()

        except Exception as e:
            print(f"[save_session_log] Supabase error: {e}")

    # Local fallback: append JSON line
    _ensure_local_dirs()
    path = _conversation_log_path(user_name)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[save_session_log] Local fallback error: {e}")

    if embedding:
        _save_local_embedding(user_name, session_id, embedding)

def save_full_transcript(supabase, name: str, session_id: str, messages: list):
    """
    Persist the full message list for a session to the transcripts table.
    Creates or updates the row for this session_id.
    Safe to call multiple times — upserts on session_id.
    """
    if not messages:
        return
    payload = {
        "session_id": session_id,
        "user_name": name,
        "messages": messages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if supabase:
        try:
            supabase.table("transcripts").upsert({
                "session_id": session_id,
                "user_name": name,
                "messages": json.dumps(messages),
                "updated_at": payload["updated_at"],
            }, on_conflict="session_id").execute()
            return
        except Exception as e:
            print(f"[save_full_transcript error - supabase] {e}")

    # Local fallback: write full transcript to file
    try:
        _ensure_local_dirs()
        path = _transcript_path(session_id)
        _write_json_file(path, payload)
    except Exception as e:
        print(f"[save_full_transcript error - local] {e}")


# ================================================================
# EXTRACTION
# ================================================================

def extract_and_update_profile(client, supabase, name: str, messages: list):
    """
    Runs a structured extraction pass over recent messages.
    Pulls out profile-worthy signals and writes them to user_profiles.
    """
    extraction_prompt = """
You are a silent analyst reading a conversation between a user and Samantha.
Your job is to extract structured facts about the USER ONLY.

Return ONLY valid JSON. No explanation. No markdown. No preamble.

Schema:
{
  "occupation": "string or null",
  "location": "string or null",
  "age": "string or null",
  "relationship_status": "one of: stranger / applicant / accepted / dismissed — or null if unchanged",
  "insecurities": ["list of strings — hedges, apologies, self-doubts observed"],
  "soft_spots": ["topics that visibly shifted their tone"],
  "boasts": ["things they volunteered to impress Samantha"],
  "notes": "1-2 sentence observation about who this person is"
}

Rules:
- Only include fields where you have clear evidence from the conversation.
- Use null for fields you cannot determine.
- For relationship_status: only set "accepted" if Samantha explicitly accepted them.
- For insecurities: look for apologies, hedging, over-explanation, self-deprecation.
- Keep values short and sharp — Samantha's dossier, not a therapy report.
"""
    try:
        raw = _call_with_fallback(
            client,
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user",   "content": str(messages[-20:])}
            ],
            temperature=0.1
        )

        if not raw:
            return {}

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        extracted = json.loads(raw)
        updates   = {}

        scalar_fields = ["occupation", "location", "age", "relationship_status"]
        for field in scalar_fields:
            val = extracted.get(field)
            if val:
                updates[field] = val

        new_note = extracted.get("notes")
        if new_note:
            existing_notes = None
            try:
                if supabase:
                    cur = supabase.table("user_profiles") \
                        .select("notes").eq("name", name).limit(1).execute()
                    existing_notes = cur.data[0].get("notes") if cur.data else None
                else:
                    existing_notes = (_read_json_file(_profile_path(name)) or {}).get("notes")
            except Exception:
                pass
            appended = _append_note(existing_notes, new_note)
            if appended:
                updates["notes"] = appended

        # Array fields — append, deduplicate
        try:
            if supabase:
                cur = supabase.table("user_profiles") \
                    .select("insecurities, soft_spots, boasts") \
                    .eq("name", name).limit(1).execute()
                existing = cur.data[0] if cur.data else {}
            else:
                existing = _read_json_file(_profile_path(name)) or {}
        except Exception:
            existing = {}

        for arr_field in ["insecurities", "soft_spots", "boasts"]:
            new_items = extracted.get(arr_field, [])
            if new_items:
                existing_items = existing.get(arr_field) or []
                merged = list(existing_items)
                for item in new_items:
                    new_words    = set(item.lower().split())
                    is_duplicate = any(
                        len(new_words & set(e.lower().split())) / max(len(new_words), 1) > 0.6
                        for e in existing_items
                    )
                    if not is_duplicate:
                        merged.append(item)
                if merged != existing_items:
                    updates[arr_field] = merged

        if updates:
            update_profile(supabase, name, updates)
            return updates

    except json.JSONDecodeError:
        pass
    except Exception:
        pass

    return {}


# ================================================================
# DEEP PROFILE SYNTHESIS
# ================================================================

def synthesise_deep_profile(
    client,
    supabase,
    name: str,
    messages: list,
    current_profile: dict,
) -> dict:
    """
    Runs a deep synthesis pass every N messages.
    Produces a rich psychological read that lives in profile["deep_profile"].
    Returns the updated deep_profile dict.
    """
    existing_deep = current_profile.get("deep_profile") or {}

    synthesis_prompt = f"""
You are Samantha Tushabe Okullo's private analyst.
You have been watching {name} across this conversation.

Your job: produce a deep psychological profile of this person.
Base it ONLY on what has been said. Do not invent.

Return ONLY valid JSON. No preamble, no markdown, no explanation.

Schema:
{{
  "her_read":           "Samantha's private verdict on this person — 1-2 sentences, cold and precise",
  "dominant_trait":     "the single most defining thing she has observed",
  "pressure_points":    ["things that visibly affected them"],
  "open_questions":     ["things she noticed but has not yet resolved — worth returning to"],
  "recurring_patterns": ["behaviours or framings they repeated"],
  "self_image_vs_reality": "the gap between who they think they are and what the conversation revealed",
  "utility_assessment": "what are they actually worth to her — and in what currency",
  "nicknames":          "a nickname Samantha would privately use for this person — one or two words, sharp"
}}

Prior read (update, don't erase):
{json.dumps(existing_deep, indent=2)}

Conversation (last 20 messages):
{str(messages[-20:])}
"""

    try:
        raw = _call_with_fallback(
            client,
            messages=[
                {"role": "system", "content": synthesis_prompt},
                {"role": "user",   "content": "Produce the deep profile now."}
            ],
            temperature=0.2
        )

        if not raw:
            return existing_deep

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        deep = json.loads(raw)

        # Merge arrays — don't overwrite, accumulate
        for arr_field in ["pressure_points", "open_questions", "recurring_patterns"]:
            old_items = existing_deep.get(arr_field, [])
            new_items = deep.get(arr_field, [])
            if old_items or new_items:
                merged = list({item for item in (old_items + new_items)})
                deep[arr_field] = merged

        # Persist nickname to top-level profile if we got one
        if deep.get("nicknames"):
            update_profile(supabase, name, {"nicknames": deep["nicknames"]})

        # Persist the whole deep profile as JSON in the profiles table
        update_profile(supabase, name, {"deep_profile": json.dumps(deep)})

        return deep

    except json.JSONDecodeError:
        return existing_deep
    except Exception as e:
        print(f"[synthesise_deep_profile error] {e}")
        return existing_deep


# ================================================================
# ARRAY COMPRESSION
# ================================================================

def compress_array(client, field_name: str, items: list) -> list:
    """Synthesize a bloated observation array into 3-5 sharp, distinct insights."""
    if not client or len(items) <= 8:
        return items

    prompt = f"""You are a ruthlessly concise intelligence analyst.
You have {len(items)} raw observations about one person, category: {field_name}.
Many are repetitive or minor.

Synthesize them into exactly 3-5 key insights.
Each insight: one sentence, sharp and specific, capturing the most actionable intelligence.
Do not soften. Do not repeat.

Return ONLY a JSON array of strings. No preamble, no markdown fences.

Observations:
{json.dumps(items, ensure_ascii=False)}"""

    for model_attempt in ["gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            response = client.chat.completions.create(
                model=model_attempt,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Synthesize now."}
                ],
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw.strip())
            if isinstance(result, list) and result:
                return result
        except Exception:
            continue

    return items[-6:]


# ================================================================
# SEMANTIC SESSION RETRIEVAL
# ================================================================

def get_relevant_sessions(
    supabase,
    name: str,
    query_text: str,
    embed_client,
    limit: int = 3,
) -> str:
    """
    Return session summaries ranked by semantic similarity to query_text.
    Falls back gracefully to recency-based order when embeddings are unavailable.

    Embeddings are stored locally (data/embeddings/{name}.json) to avoid
    requiring a schema change in Supabase.  Summaries are sourced from
    Supabase when available, otherwise from the local log file.
    """
    query_emb = embed_text(embed_client, query_text) if (embed_client and query_text) else None
    if not query_emb:
        return get_conversation_history(supabase, name, limit)

    sessions = []  # list of {summary, created_at, embedding}

    if supabase:
        try:
            res = supabase.table("conversation_logs") \
                .select("session_id, summary, created_at") \
                .eq("user_name", name) \
                .order("created_at", desc=True) \
                .limit(50) \
                .execute()
            local_embs = _load_local_embeddings(name)
            for r in (res.data or []):
                sessions.append({
                    "summary":    r.get("summary", ""),
                    "created_at": r.get("created_at", ""),
                    "embedding":  local_embs.get(r.get("session_id", "")),
                })
        except Exception as e:
            logger.warning("[get_relevant_sessions] Supabase error: %s", e)

    if not sessions:
        _ensure_local_dirs()
        path = _conversation_log_path(name)
        local_embs = _load_local_embeddings(name)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            sid = obj.get("session_id", "")
                            sessions.append({
                                "summary":    obj.get("summary", ""),
                                "created_at": obj.get("created_at", ""),
                                "embedding":  local_embs.get(sid),
                            })
                        except Exception:
                            pass
            except Exception:
                pass

    if not sessions:
        return "No prior sessions."

    scored = []
    for i, s in enumerate(sessions):
        if s.get("embedding"):
            sim = _cosine_sim(query_emb, s["embedding"])
        else:
            sim = -i * 0.01  # recency proxy: more recent = less negative
        scored.append((sim, s))

    scored.sort(key=lambda x: x[0], reverse=True)

    entries = []
    for _, s in scored[:limit]:
        ts = s["created_at"][:10] if s.get("created_at") else "?"
        entries.append(f"[{ts}] {s['summary']}")

    return "\n---\n".join(entries) if entries else "No prior sessions."


# ================================================================
# KEY FACTS — EVERGREEN CROSS-SESSION SYNTHESIS
# ================================================================

def update_key_facts(client, supabase, name: str) -> str | None:
    """
    Synthesize all recorded session summaries into 5-8 stable, permanent facts
    about the interlocutor.  Stored in profile["key_facts"] and refreshed on
    every session end once at least 2 sessions exist.

    Returns the new key_facts string, or None on failure.
    """
    all_summaries = []

    if supabase:
        try:
            res = supabase.table("conversation_logs") \
                .select("summary, created_at") \
                .eq("user_name", name) \
                .order("created_at", desc=True) \
                .limit(50) \
                .execute()
            all_summaries = [r["summary"] for r in (res.data or []) if r.get("summary")]
        except Exception:
            pass

    if not all_summaries:
        _ensure_local_dirs()
        path = _conversation_log_path(name)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                s = json.loads(line).get("summary", "")
                                if s:
                                    all_summaries.append(s)
                            except Exception:
                                pass
            except Exception:
                pass

    if len(all_summaries) < 2:
        return None

    existing_key_facts = (get_or_create_profile(supabase, name) or {}).get("key_facts", "")

    synthesis_prompt = f"""You are a ruthlessly concise intelligence analyst.
You have been watching {name} across multiple sessions.
Synthesize 5-8 stable, permanent facts about this person.

Include only what is persistently true: occupation, location, core relationships,
dominant behavioural patterns, recurring psychological traits, how they respond to pressure.
Skip single-session moods or transient topics.

Write each fact as one sharp sentence. Plain text, one per line. No bullets.

Existing facts (update but do not duplicate):
{existing_key_facts or 'None yet.'}

Session summaries (most recent first):
{chr(10).join(all_summaries[:20])}
"""

    raw = _call_with_fallback(
        client,
        messages=[
            {"role": "system", "content": synthesis_prompt},
            {"role": "user",   "content": "Extract the permanent facts now."},
        ],
        temperature=0.2,
    )

    if raw:
        key_facts = raw.strip()
        update_profile(supabase, name, {"key_facts": key_facts})
        return key_facts

    return None


# ================================================================
# DOSSIER PROMPT BUILDER
# ================================================================

def build_dossier_prompt(
    profile: dict,
    history: str,
    conversation_length: int = 0,
    recently_used: list = None,
) -> str:
    """
    Render the full dossier block for prompt injection.
    Now includes living hooks — actionable present-tense observations
    Samantha can deploy this turn — prominently, above the static facts.
    """
    from engine.living_hooks import build_living_hooks   # lazy import (safe)
    import json

    status = profile.get("relationship_status", "stranger")

    deep = profile.get("deep_profile") or {}
    if isinstance(deep, str):
        try:
            deep = json.loads(deep)
        except Exception:
            deep = {}

    # ── Living hooks (top of block — highest priority) ───────────
    hooks_block = build_living_hooks(profile, conversation_length, recently_used=recently_used)
 
    # ── Static dossier facts ─────────────────────────────────────
    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status}",
        f"Sessions: {profile.get('session_count', 1)}",
    ]
 
    if profile.get("occupation"):
        lines.append(f"Occupation: {profile['occupation']}")
    if profile.get("location"):
        lines.append(f"Location: {profile['location']}")
    if profile.get("age"):
        lines.append(f"Age: {profile['age']}")
    if profile.get("nicknames"):
        lines.append(f"Her label for them: {profile['nicknames']}")
    if profile.get("insecurities"):
        ins = profile["insecurities"]
        lines.append(f"Insecurities: {', '.join(ins) if isinstance(ins, list) else ins}")
    if profile.get("soft_spots"):
        ss = profile["soft_spots"]
        lines.append(f"Soft spots: {', '.join(ss) if isinstance(ss, list) else ss}")
    if profile.get("boasts"):
        b = profile["boasts"]
        lines.append(f"Boasts: {', '.join(b) if isinstance(b, list) else b}")
    if profile.get("notes"):
        lines.append(f"Notes: {profile['notes']}")

    if profile.get("key_facts"):
        lines.append("")
        lines.append("PERMANENT FILE (stable across all sessions):")
        for fact in profile["key_facts"].strip().splitlines():
            fact = fact.strip()
            if fact:
                lines.append(f"  {fact}")

    if deep:
        lines.append("")
        lines.append("PRIVATE FILE:")
        if deep.get("her_read"):
            lines.append(f"Verdict: {deep['her_read']}")
        if deep.get("dominant_trait"):
            lines.append(f"Dominant trait: {deep['dominant_trait']}")
        if deep.get("self_image_vs_reality"):
            lines.append(f"Self-image gap: {deep['self_image_vs_reality']}")
        if deep.get("utility_assessment"):
            lines.append(f"Utility: {deep['utility_assessment']}")
        if deep.get("open_questions"):
            lines.append(f"Open threads: {'; '.join(deep['open_questions'][:3])}")
        if deep.get("recurring_patterns"):
            lines.append(f"Patterns: {'; '.join(deep['recurring_patterns'][:3])}")
 
    static_block = "\n".join(lines)
 
    lines_footer = [
        "",
        "PRIOR SESSIONS:",
        history,
        "",
        "MEMORY RULES:",
        "- You know this person. Behave accordingly.",
        "- Their status is real. If they are 'accepted', they earned it — hold them to the standard.",
        "- Use prior session details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface naturally.",
        "- If status is 'stranger', they start from zero.",
    ]
    footer_block = "\n".join(lines_footer)
 
    # ── Assemble: hooks first, then static facts, then history ──
    parts = []
    if hooks_block:
        parts.append(hooks_block)
        parts.append("")   # blank line separator
    parts.append(static_block)
    parts.append(footer_block)
 
    return "\n".join(parts)
