import json
import time
from datetime import datetime, timezone


# ================================================================
# MODEL LISTS
# ================================================================

SUMMARY_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama-3.2-3b-preview",
    "llama-3.2-1b-preview",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-32b",
]

HF_MODELS = [
    "NousResearch/Hermes-2-Pro-Llama-3-8B:novita",
    "openchat/openchat-3.5-0106",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mistral-7B-Instruct-v0.1",
    "HuggingFaceH4/zephyr-7b-beta",
    "HuggingFaceH4/zephyr-7b-alpha",
    "microsoft/Phi-3-mini-4k-instruct",
    "microsoft/Phi-3-mini-128k-instruct",
    "Qwen/Qwen2-7B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "google/gemma-7b-it",
    "google/gemma-2-9b-it",
    "meta-llama/Llama-3.2-3B-Instruct",
    "meta-llama/Llama-3.2-1B-Instruct",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
]

# Reference schema — Python only, documents the deep_profile JSONB column shape.
DEEP_PROFILE_SCHEMA = {
    "who_they_are":       "",
    "recurring_patterns": [],
    "unresolved_threads": [],
    "evolution":          [],
    "things_she_knows":   [],
    "open_questions":     [],
    "her_read":           "",
}

_hf_client = None


def _get_hf_client():
    global _hf_client
    if _hf_client is not None:
        return _hf_client
    try:
        import streamlit as st
        from openai import OpenAI
        hf_key = st.secrets.get("HF_TOKEN", "")
        if hf_key:
            _hf_client = OpenAI(
                base_url="https://router.huggingface.co/v1",
                api_key=hf_key,
            )
    except Exception:
        pass
    return _hf_client


def _call_with_fallback(client, messages, temperature=0.3):
    for i, model in enumerate(SUMMARY_MODELS):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["rate limit", "429", "quota", "exceeded"]):
                time.sleep(min(2 ** (i % 6), 30))
                continue
            elif any(x in err for x in ["not found", "unavailable", "deprecated", "invalid model"]):
                continue
            else:
                print(f"[memory model error] {model}: {e}")
                continue

    hf = _get_hf_client()
    if hf:
        for model in HF_MODELS:
            try:
                response = hf.chat.completions.create(
                    model=model, messages=messages, temperature=temperature
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"[HF memory fallback failed] {model}: {e}")
                continue

    return None


# ================================================================
# PROFILE CRUD
# ================================================================

def get_or_create_profile(supabase, name: str) -> dict:
    try:
        res = supabase.table("user_profiles") \
            .select("*").eq("name", name).limit(1).execute()
        now = datetime.now(timezone.utc).isoformat()

        if res.data:
            profile       = res.data[0]
            current_count = profile.get("session_count") or 0
            supabase.table("user_profiles") \
                .update({"session_count": current_count + 1, "last_seen": now}) \
                .eq("name", name).execute()
            profile["session_count"] = current_count + 1
            return profile

    except Exception:
        pass

    now         = datetime.now(timezone.utc).isoformat()
    new_profile = {
        "name": name, "relationship_status": "stranger",
        "session_count": 1, "last_seen": now, "deep_profile": {},
    }
    try:
        supabase.table("user_profiles").insert(new_profile).execute()
    except Exception:
        pass
    return new_profile


def update_profile(supabase, name: str, updates: dict):
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("user_profiles") \
            .update({**updates, "updated_at": now}) \
            .eq("name", name).execute()
    except Exception:
        pass


def get_conversation_history(supabase, name: str, limit: int = 5) -> str:
    """
    Returns the last N session summaries as a readable block.
    Limit raised to 5 so Samantha has more prior context available.
    """
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
    except Exception:
        pass
    return "No prior sessions."


def save_session_log(supabase, name: str, session_id: str, summary: str):
    """Save a prose summary of the session to conversation_logs."""
    try:
        supabase.table("conversation_logs").insert({
            "user_name":  name,
            "session_id": session_id,
            "summary":    summary
        }).execute()
    except Exception:
        pass


# ================================================================
# FULL TRANSCRIPT ARCHIVE
# Stores the complete message-by-message transcript in a dedicated
# table so nothing is ever lost — even if summaries are imperfect.
# Requires a `chat_transcripts` table in Supabase (schema below).
#
# CREATE TABLE chat_transcripts (
#   id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
#   user_name    text NOT NULL,
#   session_id   text NOT NULL,
#   transcript   jsonb NOT NULL,
#   message_count integer,
#   created_at   timestamptz DEFAULT now(),
#   updated_at   timestamptz DEFAULT now()
# );
# CREATE INDEX ON chat_transcripts (user_name);
# CREATE INDEX ON chat_transcripts (session_id);
# ================================================================

def save_full_transcript(supabase, name: str, session_id: str, messages: list):
    """
    Upserts the full conversation transcript for this session.
    Uses session_id as the unique key — so repeated calls within
    the same session overwrite rather than duplicate.

    The transcript is stored as JSONB — every message with role,
    content, and a rough timestamp index.
    """
    if not messages:
        return

    try:
        now = datetime.now(timezone.utc).isoformat()

        # Annotate each message with its position for easier querying
        annotated = [
            {"index": i, "role": m["role"], "content": m["content"]}
            for i, m in enumerate(messages)
        ]

        # Check if a record already exists for this session
        existing = supabase.table("chat_transcripts") \
            .select("id") \
            .eq("session_id", session_id) \
            .limit(1) \
            .execute()

        if existing.data:
            # Update existing record
            supabase.table("chat_transcripts").update({
                "transcript":    annotated,
                "message_count": len(messages),
                "updated_at":    now,
            }).eq("session_id", session_id).execute()
        else:
            # Insert new record
            supabase.table("chat_transcripts").insert({
                "user_name":     name,
                "session_id":    session_id,
                "transcript":    annotated,
                "message_count": len(messages),
                "created_at":    now,
                "updated_at":    now,
            }).execute()

    except Exception as e:
        print(f"[transcript save error] {e}")


def get_full_transcript(supabase, name: str, session_id: str = None) -> list:
    """
    Retrieve a stored transcript.
    If session_id provided: returns that specific session.
    Otherwise: returns the most recent session for this user.
    """
    try:
        query = supabase.table("chat_transcripts") \
            .select("transcript, session_id, created_at, message_count") \
            .eq("user_name", name)

        if session_id:
            query = query.eq("session_id", session_id)
        else:
            query = query.order("created_at", desc=True).limit(1)

        res = query.execute()
        if res.data:
            return res.data[0].get("transcript", [])
    except Exception as e:
        print(f"[transcript fetch error] {e}")
    return []


def get_transcript_index(supabase, name: str, limit: int = 20) -> list:
    """
    Returns a lightweight index of all stored sessions for a user:
    session_id, date, message count. Useful for browsing history.
    """
    try:
        res = supabase.table("chat_transcripts") \
            .select("session_id, created_at, message_count") \
            .eq("user_name", name) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return res.data or []
    except Exception as e:
        print(f"[transcript index error] {e}")
    return []


# ================================================================
# NOTES DEDUP HELPER
# ================================================================

def _append_note(existing_notes: str | None, new_note: str | None) -> str | None:
    if not new_note:
        return None
    new_note = new_note.strip()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if existing_notes:
        new_words = set(new_note.lower().split())
        for line in existing_notes.split('\n'):
            line_clean = line.strip()
            if not line_clean:
                continue
            line_words = set(line_clean.lower().split())
            if line_words and len(new_words & line_words) / max(len(new_words), 1) > 0.6:
                return None
        return f"{existing_notes.rstrip()}\n[{date_str}] {new_note}"
    else:
        return f"[{date_str}] {new_note}"


# ================================================================
# RELATIONSHIP STATUS
# ================================================================

STATUS_RANK = {
    "stranger": 0, "applicant": 1, "accepted": 2, "asset": 3, "dismissed": 4,
}


# ================================================================
# FIELD EXTRACTION
# ================================================================

def extract_and_update_profile(client, supabase, name: str, messages: list):
    try:
        current_res = supabase.table("user_profiles") \
            .select("*").eq("name", name).limit(1).execute()
        current_profile = current_res.data[0] if current_res.data else {}
    except Exception:
        current_profile = {}

    known_scalars = {
        k: current_profile.get(k)
        for k in ["occupation", "location", "age", "nicknames", "relationship_status"]
        if current_profile.get(k)
    }
    known_context = ""
    if known_scalars:
        known_context = (
            f"\nALREADY ON FILE:\n{json.dumps(known_scalars, indent=2)}\n"
            f"Only return a field from above if the user has clearly stated something NEW.\n"
        )

    extraction_prompt = f"""
Extract structured intelligence about the USER ONLY from this conversation.
Return ONLY valid JSON. No markdown. No preamble.
{known_context}
Schema:
{{
  "occupation": null, "location": null, "age": null,
  "relationship_status": null,
  "nicknames": null,
  "insecurities": [], "soft_spots": [], "boasts": [],
  "loyalties": [], "fears": [], "secrets": [],
  "contradictions": [], "desires": [], "self_image": [],
  "notes": null
}}
Rules: only include fields with clear evidence. relationship_status never downgrades.
nicknames only if Samantha coined one this session. notes: new observations only.
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
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        extracted = json.loads(raw.strip())
    except Exception:
        return {}

    updates = {}

    for field in ["occupation", "location", "age"]:
        val = extracted.get(field)
        if val and not current_profile.get(field):
            updates[field] = val

    new_nickname = extracted.get("nicknames")
    if new_nickname and not current_profile.get("nicknames"):
        updates["nicknames"] = new_nickname

    new_status      = extracted.get("relationship_status")
    existing_status = current_profile.get("relationship_status", "stranger")
    if new_status and new_status in STATUS_RANK:
        if STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(existing_status, 0):
            updates["relationship_status"] = new_status

    new_note = extracted.get("notes")
    if new_note:
        appended = _append_note(current_profile.get("notes"), new_note)
        if appended:
            updates["notes"] = appended

    ARRAY_FIELDS = [
        "insecurities", "soft_spots", "boasts", "loyalties",
        "fears", "secrets", "contradictions", "desires", "self_image",
    ]
    for arr_field in ARRAY_FIELDS:
        new_items = extracted.get(arr_field, [])
        if new_items:
            existing = current_profile.get(arr_field) or []
            merged   = list(existing)
            for item in new_items:
                new_words    = set(item.lower().split())
                is_duplicate = any(
                    len(new_words & set(e.lower().split())) / max(len(new_words), 1) > 0.6
                    for e in existing
                )
                if not is_duplicate:
                    merged.append(item)
            if merged != existing:
                updates[arr_field] = merged

    if updates:
        update_profile(supabase, name, updates)
        return updates
    return {}


# ================================================================
# DEEP PROFILE SYNTHESIS
# ================================================================

def synthesise_deep_profile(
    client, supabase,
    user_name: str, messages: list, existing_profile: dict
) -> dict:
    existing_deep = existing_profile.get("deep_profile") or {}

    meaningful = [
        m for m in messages
        if m["role"] == "user" and len(m["content"].split()) > 8
    ]
    if len(meaningful) < 3:
        return existing_deep

    synthesis_prompt = f"""
You are maintaining a private intelligence file on {user_name}.

CURRENT FILE:
{json.dumps(existing_deep, indent=2) if existing_deep else "No file yet."}

NEW SESSION:
{str(messages[-40:])}

Rewrite the file. Output ONLY valid JSON. No markdown.

Schema:
{{
  "who_they_are": "3-5 sentence character synthesis — not a list of facts",
  "recurring_patterns": ["specific behaviours that have appeared more than once"],
  "unresolved_threads": ["things they keep returning to without resolution — most valuable"],
  "evolution": ["how they have changed across sessions — only if evidenced"],
  "things_she_knows": ["specific facts/admissions she holds — concrete, not vague"],
  "open_questions": ["what she still doesn't know — specific enough to generate real questions"],
  "her_read": "her private verdict — one paragraph, sharp, specific, like a journal entry not a report"
}}

Rules: synthesise don't append. Fix outdated entries. her_read is most important.
Empty string or [] if no evidence. Do not invent.
"""

    try:
        raw = _call_with_fallback(
            client,
            messages=[
                {"role": "system", "content": synthesis_prompt},
                {"role": "user",   "content": "Rewrite the file now."}
            ],
            temperature=0.25
        )
        if not raw:
            return existing_deep
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        updated_deep = json.loads(raw.strip())
        supabase.table("user_profiles").update({
            "deep_profile": updated_deep
        }).eq("name", user_name).execute()
        return updated_deep
    except Exception as e:
        print(f"[deep profile synthesis failed] {e}")
        return existing_deep


# ================================================================
# DOSSIER BUILDER
# ================================================================

def build_returning_user_context(profile: dict) -> str:
    status        = profile.get("relationship_status", "stranger")
    name          = profile.get("name", "them")
    session_count = profile.get("session_count", 1)
    nicknames     = profile.get("nicknames")
    notes         = profile.get("notes", "")

    if status == "stranger" or session_count <= 1:
        return "This person is new. Start from zero."

    lines = [
        f"You have spoken to {name} before. Session #{session_count}. Status: {status}.",
    ]
    if nicknames:
        lines.append(f"You have privately labelled them: '{nicknames}'. Use it when it cuts.")
    if notes:
        lines.append(f"Accumulated read:\n{notes}")
    lines += [
        "Cold familiarity. Not warmth.",
        "Do not announce that you remember them.",
        "If status is 'dismissed', make them feel it without stating it.",
        "If status is 'accepted', they still start each session proving themselves.",
    ]
    return "\n".join(lines)


def build_dossier_prompt(profile: dict, history: str) -> str:
    status        = profile.get("relationship_status", "stranger")
    session_count = profile.get("session_count", 1)
    deep          = profile.get("deep_profile") or {}

    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status} | Sessions: {session_count}",
    ]

    for field, label in [
        ("occupation", "Occupation"), ("location", "Location"),
        ("age", "Age"), ("nicknames", "Her label"),
    ]:
        if profile.get(field):
            lines.append(f"{label}: {profile[field]}")

    INTEL_FIELDS = [
        ("insecurities", "Insecurities"), ("soft_spots", "Soft spots"),
        ("boasts", "Boasts"), ("loyalties", "Loyalties"), ("fears", "Fears"),
        ("secrets", "Secrets"), ("contradictions", "Contradictions"),
        ("desires", "Desires"), ("self_image", "Self-image"),
    ]
    for field, label in INTEL_FIELDS:
        items = profile.get(field) or []
        if items:
            lines.append(f"{label}: {', '.join(items)}")

    if profile.get("notes"):
        lines.append(f"Session notes:\n{profile['notes']}")

    if deep:
        lines.append("\n━━━ HER PRIVATE FILE ━━━")
        if deep.get("who_they_are"):
            lines.append(f"Who they are:\n{deep['who_they_are']}")
        if deep.get("her_read"):
            lines.append(f"\nHer verdict:\n{deep['her_read']}")
        if deep.get("recurring_patterns"):
            lines.append("\nPatterns:")
            lines.extend(f"  - {p}" for p in deep["recurring_patterns"])
        if deep.get("unresolved_threads"):
            lines.append("\nUnresolved threads (most valuable):")
            lines.extend(f"  - {t}" for t in deep["unresolved_threads"])
        if deep.get("things_she_knows"):
            lines.append("\nThings she holds:")
            lines.extend(f"  - {t}" for t in deep["things_she_knows"])
        if deep.get("open_questions"):
            lines.append("\nOpen questions (drive conversation toward these):")
            lines.extend(f"  - {q}" for q in deep["open_questions"])
        if deep.get("evolution"):
            lines.append("\nEvolution:")
            lines.extend(f"  - {e}" for e in deep["evolution"])
        lines.append("━━━ END PRIVATE FILE ━━━")

    lines += [
        "",
        "RETURNING USER CONTEXT:",
        build_returning_user_context(profile),
        "",
        "PRIOR SESSION SUMMARIES:",
        history,
        "",
        "MEMORY RULES:",
        "- The private file is your deepest read. Let it inform tone and targeting.",
        "- Use open_questions to guide extraction — naturally, never as a checklist.",
        "- Unresolved threads are the most valuable. Return to them when the moment allows.",
        "- Use prior details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface.",
    ]
    return "\n".join(lines)
