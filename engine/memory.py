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
]


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


def get_or_create_profile(supabase, name: str) -> dict:
    """
    Load existing profile or create a fresh one.
    Increments session_count and updates last_seen on every call.
    """
    try:
        res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()

        now = datetime.now(timezone.utc).isoformat()

        if res.data:
            profile = res.data[0]
            current_count = profile.get("session_count") or 0
            supabase.table("user_profiles") \
                .update({
                    "session_count": current_count + 1,
                    "last_seen": now
                }) \
                .eq("name", name) \
                .execute()
            profile["session_count"] = current_count + 1
            return profile

    except Exception:
        pass

    # New user
    now = datetime.now(timezone.utc).isoformat()
    new_profile = {
        "name": name,
        "relationship_status": "stranger",
        "session_count": 1,
        "last_seen": now
    }
    try:
        supabase.table("user_profiles").insert(new_profile).execute()
    except Exception:
        pass

    return new_profile


def update_profile(supabase, name: str, updates: dict):
    """Patch fields on an existing profile."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("user_profiles") \
            .update({**updates, "updated_at": now}) \
            .eq("name", name) \
            .execute()
    except Exception:
        pass


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
            "user_name": name,
            "session_id": session_id,
            "summary": summary
        }).execute()
    except Exception:
        pass


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
  "nicknames": "any nickname Samantha assigned to this person during conversation, or null",
  "insecurities": ["list of strings — hedges, apologies, self-doubts observed"],
  "soft_spots": ["topics that visibly shifted their tone"],
  "boasts": ["things they volunteered to impress Samantha"],
  "notes": "1-2 sentence sharp observation about who this person is"
}

Rules:
- Only include fields where you have clear evidence from the conversation.
- Use null for fields you cannot determine.
- For relationship_status: only set "accepted" if Samantha explicitly accepted them.
- For nicknames: only set if Samantha actually coined or used a specific label for this person.
- For insecurities: look for apologies, hedging, over-explanation, self-deprecation.
- Keep values short and sharp.
"""

    try:
        raw = _call_with_fallback(
            client,
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": str(messages[-20:])}
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
        updates = {}

        scalar_fields = ["occupation", "location", "age", "relationship_status", "notes", "nicknames"]
        for field in scalar_fields:
            val = extracted.get(field)
            if val:
                updates[field] = val

        # For array fields, APPEND not overwrite
        try:
            current = supabase.table("user_profiles") \
                .select("insecurities, soft_spots, boasts") \
                .eq("name", name) \
                .limit(1) \
                .execute()

            if current.data:
                existing = current.data[0]
                for arr_field in ["insecurities", "soft_spots", "boasts"]:
                    new_items = extracted.get(arr_field, [])
                    if new_items:
                        existing_items = existing.get(arr_field) or []
                        merged = list(set(existing_items + new_items))
                        updates[arr_field] = merged
        except Exception:
            pass

        if updates:
            update_profile(supabase, name, updates)
            return updates

    except json.JSONDecodeError:
        pass
    except Exception:
        pass

    return {}


def build_returning_user_context(profile: dict) -> str:
    """
    Returns an in-character instruction block for how Samantha
    should open with a returning user. Cold familiarity — not warmth.
    """
    status = profile.get("relationship_status", "stranger")
    name = profile.get("name", "them")
    session_count = profile.get("session_count", 1)
    nicknames = profile.get("nicknames")
    notes = profile.get("notes", "")

    if status == "stranger" or session_count <= 1:
        return "This person is new. You have no prior read on them. Start from zero."

    lines = [
        f"You have spoken to {name} before. This is session #{session_count}.",
        f"Status: {status}.",
    ]

    if nicknames:
        lines.append(
            f"You have privately labelled them: '{nicknames}'. "
            f"Use it if it lands — never explain it, never announce it."
        )

    if notes:
        lines.append(f"Your prior read on them: {notes}")

    lines += [
        "You remember them. Do not pretend otherwise.",
        "Do not announce that you remember them either.",
        "Cold familiarity. Not warmth. They have not re-earned warmth just by returning.",
        "If their status is 'dismissed', make them feel it without stating it.",
        "If their status is 'accepted', they still start each session proving themselves.",
    ]

    return "\n".join(lines)


def build_dossier_prompt(profile: dict, history: str) -> str:
    """Render the full dossier block for prompt injection."""
    status = profile.get("relationship_status", "stranger")
    session_count = profile.get("session_count", 1)

    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status}",
        f"Sessions: {session_count}",
    ]

    if profile.get("occupation"):
        lines.append(f"Occupation: {profile['occupation']}")
    if profile.get("location"):
        lines.append(f"Location: {profile['location']}")
    if profile.get("age"):
        lines.append(f"Age: {profile['age']}")
    if profile.get("nicknames"):
        lines.append(f"Your label for them: {profile['nicknames']}")

    # Safe join for array fields that may be None from Supabase
    insecurities = profile.get("insecurities") or []
    soft_spots = profile.get("soft_spots") or []
    boasts = profile.get("boasts") or []

    if insecurities:
        lines.append(f"Insecurities: {', '.join(insecurities)}")
    if soft_spots:
        lines.append(f"Soft spots: {', '.join(soft_spots)}")
    if boasts:
        lines.append(f"Boasts: {', '.join(boasts)}")
    if profile.get("notes"):
        lines.append(f"Notes: {profile['notes']}")

    # Returning user context block
    returning_context = build_returning_user_context(profile)

    lines += [
        "",
        "RETURNING USER CONTEXT:",
        returning_context,
        "",
        "PRIOR SESSIONS:",
        history,
        "",
        "MEMORY RULES:",
        "- You know this person. Behave accordingly.",
        "- Status is real. If they are 'accepted', they earned it — but the standard never drops.",
        "- If they are 'dismissed', let them feel it without announcing it.",
        "- Use prior session details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface naturally.",
        "- Their label/nickname is yours. Use it when it cuts, not as greeting.",
        "- If status is 'stranger', they start from zero.",
    ]
    return "\n".join(lines)
