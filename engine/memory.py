import json

SUMMARY_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct", 
    "llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
]

def get_or_create_profile(supabase, name: str) -> dict:
    """Load existing profile or create a fresh one."""
    try:
        res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()
        if res.data:
            return res.data[0]
    except:
        pass

    # Create new profile
    new_profile = {"name": name, "relationship_status": "stranger"}
    try:
        supabase.table("user_profiles").insert(new_profile).execute()
    except:
        pass
    return new_profile


def update_profile(supabase, name: str, updates: dict):
    """Patch fields on an existing profile."""
    try:
        supabase.table("user_profiles") \
            .update({**updates, "updated_at": "NOW()"}) \
            .eq("name", name) \
            .execute()
    except:
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
    except:
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
    except:
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
  "insecurities": ["list of strings — hedges, apologies, self-doubts observed"],
  "soft_spots": ["topics that visibly shifted their tone"],
  "boasts": ["things they volunteered to impress Samantha"],
  "notes": "1-2 sentence observation about who this person is"
}

Rules:
- Only include fields where you have clear evidence from the conversation.
- Use null for fields you cannot determine.
- For relationship_status: only set "accepted" if Samantha explicitly accepted them or approved their application.
- For insecurities: look for apologies, hedging language, over-explanation, self-deprecation.
- Keep values short and sharp — Samantha's dossier, not a therapy report.
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": str(messages[-20:])}
            ],
            temperature=0.1  # low temp — we want precision, not creativity
        )

        raw = response.choices[0].message.content.strip()

        # Strip accidental markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        extracted = json.loads(raw)

        # Build the update dict — only include non-null, non-empty values
        updates = {}

        scalar_fields = ["occupation", "location", "age", "relationship_status", "notes"]
        for field in scalar_fields:
            val = extracted.get(field)
            if val:
                updates[field] = val

        # For array fields, we need to APPEND not overwrite
        # Fetch current profile first
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
                    # Merge, deduplicate
                    merged = list(set(existing_items + new_items))
                    updates[arr_field] = merged

        if updates:
            update_profile(supabase, name, updates)
            return updates  # return so app.py can log what changed if needed

    except json.JSONDecodeError:
        pass  # extraction failed cleanly — don't crash the app
    except Exception:
        pass
    def _call_with_fallback(client, messages, temperature=0.3):
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
            if any(x in error_str for x in ["rate limit", "429", "quota", "exceeded", "model"]):
                continue
            raise
    return None
    return {}


def build_dossier_prompt(profile: dict, history: str) -> str:
    """Render the full dossier block for prompt injection."""
    status = profile.get("relationship_status", "stranger")
    
    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status}",
    ]
    if profile.get("occupation"):
        lines.append(f"Occupation: {profile['occupation']}")
    if profile.get("location"):
        lines.append(f"Location: {profile['location']}")
    if profile.get("insecurities"):
        lines.append(f"Insecurities: {', '.join(profile['insecurities'])}")
    if profile.get("soft_spots"):
        lines.append(f"Soft spots: {', '.join(profile['soft_spots'])}")
    if profile.get("boasts"):
        lines.append(f"Boasts: {', '.join(profile['boasts'])}")
    if profile.get("notes"):
        lines.append(f"Notes: {profile['notes']}")

    lines += [
        "",
        "PRIOR SESSIONS:",
        history,
        "",
        "MEMORY RULES:",
        "- You know this person. Behave accordingly.",
        "- Their status is real. If they are 'accepted', they earned it — treat them accordingly, but never let them forget the standard.",
        "- Use prior session details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface naturally.",
        "- If status is 'stranger', they start from zero.",
    ]
    return "\n".join(lines)
