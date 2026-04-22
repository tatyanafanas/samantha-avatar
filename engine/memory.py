# engine/memory.py

import json
from datetime import datetime, timezone


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
    except Exception:
        pass

    new_profile = {
        "name": name,
        "relationship_status": "stranger",
        "session_count": 1,
    }
    try:
        supabase.table("user_profiles").insert(new_profile).execute()
    except Exception:
        pass
    return new_profile


def update_profile(supabase, name: str, updates: dict):
    """Patch fields on an existing profile."""
    try:
        supabase.table("user_profiles") \
            .update({**updates, "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("name", name) \
            .execute()
    except Exception:
        pass


def _append_note(existing_notes: str | None, new_note: str) -> str:
    """
    Append a new observation to the running notes field.
    Keeps the last ~800 characters to avoid unbounded growth.
    """
    if not new_note:
        return existing_notes or ""
    combined = f"{existing_notes}\n{new_note}".strip() if existing_notes else new_note
    # Trim to last 800 chars at a sentence boundary where possible
    if len(combined) > 800:
        trimmed = combined[-800:]
        # Try to start at a sentence boundary
        dot = trimmed.find(". ")
        combined = trimmed[dot + 2:] if dot != -1 else trimmed
    return combined


# ================================================================
# CONVERSATION LOGS
# ================================================================

def get_conversation_history(supabase, name: str, limit: int = 3) -> str:
    """Fetch the last N session summaries for this user."""
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
    """Append a session summary to conversation_logs."""
    try:
        supabase.table("conversation_logs").insert({
            "user_name":  name,
            "session_id": session_id,
            "summary":    summary,
        }).execute()
    except Exception:
        pass


def save_full_transcript(supabase, name: str, session_id: str, messages: list):
    """
    Persist the full message list for a session to the transcripts table.
    Creates or updates the row for this session_id.
    Safe to call multiple times — upserts on session_id.
    """
    if not messages:
        return
    try:
        supabase.table("transcripts").upsert({
            "session_id":   session_id,
            "user_name":    name,
            "messages":     json.dumps(messages),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }, on_conflict="session_id").execute()
    except Exception as e:
        print(f"[save_full_transcript error] {e}")


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
            try:
                cur = supabase.table("user_profiles") \
                    .select("notes").eq("name", name).limit(1).execute()
                existing_notes = cur.data[0].get("notes") if cur.data else None
            except Exception:
                existing_notes = None
            appended = _append_note(existing_notes, new_note)
            if appended:
                updates["notes"] = appended

        # Array fields — append, deduplicate
        try:
            cur = supabase.table("user_profiles") \
                .select("insecurities, soft_spots, boasts") \
                .eq("name", name).limit(1).execute()
            existing = cur.data[0] if cur.data else {}
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
# DOSSIER PROMPT BUILDER
# ================================================================

def build_dossier_prompt(profile: dict, history: str) -> str:
    """Render the full dossier block for prompt injection."""
    status = profile.get("relationship_status", "stranger")

    # deep_profile may be stored as a JSON string in Supabase
    deep = profile.get("deep_profile") or {}
    if isinstance(deep, str):
        try:
            deep = json.loads(deep)
        except Exception:
            deep = {}

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

    # Deep profile fields
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

    lines += [
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
    return "\n".join(lines)
