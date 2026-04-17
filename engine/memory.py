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
