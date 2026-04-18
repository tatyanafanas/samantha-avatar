import json
import time
from datetime import datetime, timezone



SUMMARY_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]


def _call_with_fallback(client, messages, temperature=0.3):
    """Try each model in SUMMARY_MODELS until one succeeds."""
    for i, model in enumerate(SUMMARY_MODELS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = any(x in error_str for x in ["rate limit", "429", "quota", "exceeded"])
            is_unavailable = any(x in error_str for x in ["model", "not found", "unavailable", "deprecated"])
            
            if is_rate_limit:
                wait = min(2 ** i, 16)
                time.sleep(wait)
                continue
            elif is_unavailable:
                continue
            else:
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


def _append_note(existing_notes: str | None, new_note: str | None) -> str | None:
    """
    Append a new observation to the existing notes string.
    Notes are stored as a single text column in Supabase — plain text,
    never an array — so we concatenate with a dated separator.

    Returns None if there is nothing new to write.
    """
    if not new_note:
        return None

    new_note = new_note.strip()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if existing_notes:
        # Avoid appending exact duplicates
        if new_note in existing_notes:
            return None
        return f"{existing_notes.rstrip()}\n[{date_str}] {new_note}"
    else:
        return f"[{date_str}] {new_note}"


def extract_and_update_profile(client, supabase, name: str, messages: list):
    """
    Runs a structured extraction pass over recent messages.
    Pulls out profile-worthy signals and writes them to user_profiles.

    NOTES FIELD: always appended, never overwritten.
    All other scalar fields: overwrite only if a non-null value is extracted.
    All array fields (insecurities, soft_spots, boasts): merged, deduplicated.
    """
    extraction_prompt = """
You are a silent analyst reading a conversation between a user and Samantha.
Extract structured intelligence about the USER ONLY.

Return ONLY valid JSON. No explanation. No markdown. No preamble.

Schema:
{
  "occupation":          "string or null",
  "location":            "string or null — where they actually live, not just country",
  "age":                 "string or null",
  "relationship_status": "one of: stranger / applicant / accepted / asset / dismissed — or null if unchanged",
  "nicknames":           "any label Samantha assigned this person, or null",

  "insecurities":  ["things they hedge, apologise for, over-explain, or seem ashamed of"],
  "soft_spots":    ["topics or names that visibly shifted their tone or energy"],
  "boasts":        ["things they volunteered unprompted to impress or position themselves"],
  "loyalties":     ["people or things they are clearly protective of"],
  "fears":         ["things they seem afraid of losing, failing at, or being seen as"],
  "secrets":       ["anything they let slip that felt unintentional or carefully guarded"],
  "contradictions":["any gap between what they said now vs earlier, or said vs implied"],
  "desires":       ["what they seem to want — stated or implied"],
  "self_image":    ["how they see themselves, or how they want to be seen"],

  "notes": "1-2 sentence sharp NEW observation about who this person is — or null if nothing new"
}

Rules:
- Only include fields where you have clear evidence from THIS conversation.
- Use null or empty list [] for fields with no evidence.
- relationship_status: only upgrade to 'accepted' or 'asset' if Samantha explicitly did so.
- secrets: even small admissions count — things said casually that reveal more than intended.
- contradictions: note the exact gap, e.g. 'said they have no regrets but described one in detail'.
- notes: new and precise only. If nothing genuinely new was revealed, return null.
- Keep all values short and sharp — this is a dossier, not a therapy report.
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

        # ── Scalar fields — overwrite if we have a non-null value ─
        scalar_fields = ["occupation", "location", "age", "relationship_status", "nicknames"]
        for field in scalar_fields:
            val = extracted.get(field)
            if val:
                updates[field] = val

        # ── notes — APPEND, never overwrite ───────────────────────
        new_note = extracted.get("notes")
        if new_note:
            try:
                current_res = supabase.table("user_profiles") \
                    .select("notes") \
                    .eq("name", name) \
                    .limit(1) \
                    .execute()

                existing_notes = None
                if current_res.data:
                    existing_notes = current_res.data[0].get("notes")

                appended = _append_note(existing_notes, new_note)
                if appended is not None:
                    updates["notes"] = appended

            except Exception:
                updates["notes"] = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {new_note}"

        # ── Array fields — merge and deduplicate ──────────────────
        # Extended set: all dossier intelligence categories
        ARRAY_FIELDS = [
            "insecurities",
            "soft_spots",
            "boasts",
            "loyalties",
            "fears",
            "secrets",
            "contradictions",
            "desires",
            "self_image",
        ]

        try:
            arr_res = supabase.table("user_profiles") \
                .select(", ".join(ARRAY_FIELDS)) \
                .eq("name", name) \
                .limit(1) \
                .execute()

            if arr_res.data:
                existing = arr_res.data[0]
                for arr_field in ARRAY_FIELDS:
                    new_items = extracted.get(arr_field, [])
                    if new_items:
                        existing_items = existing.get(arr_field) or []
                        merged = list(dict.fromkeys(existing_items + new_items))
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
    should open with a returning user.
    """
    status        = profile.get("relationship_status", "stranger")
    name          = profile.get("name", "them")
    session_count = profile.get("session_count", 1)
    nicknames     = profile.get("nicknames")
    notes         = profile.get("notes", "")

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
        lines.append(f"Your accumulated read on them:\n{notes}")

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
    status        = profile.get("relationship_status", "stranger")
    session_count = profile.get("session_count", 1)

    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status}",
        f"Sessions: {session_count}",
    ]

    # ── Scalar fields ─────────────────────────────────────────────
    for field, label in [
        ("occupation", "Occupation"),
        ("location",   "Location"),
        ("age",        "Age"),
        ("nicknames",  "Her label for them"),
    ]:
        if profile.get(field):
            lines.append(f"{label}: {profile[field]}")

    # ── Intelligence array fields — all rendered if populated ─────
    INTEL_FIELDS = [
        ("insecurities",   "Insecurities"),
        ("soft_spots",     "Soft spots"),
        ("boasts",         "Boasts"),
        ("loyalties",      "Loyalties"),
        ("fears",          "Fears"),
        ("secrets",        "Secrets"),
        ("contradictions", "Contradictions"),
        ("desires",        "Desires"),
        ("self_image",     "Self-image"),
    ]

    for field, label in INTEL_FIELDS:
        items = profile.get(field) or []
        if items:
            lines.append(f"{label}: {', '.join(items)}")

    # ── Notes — dated observation log ─────────────────────────────
    if profile.get("notes"):
        lines.append("Observations:")
        lines.append(profile["notes"])

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
        "- Status is real. 'accepted'/'asset' means they earned it — standard never drops.",
        "- 'dismissed' — let them feel it without announcing it.",
        "- Use prior details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface naturally.",
        "- Their label/nickname is yours. Use it when it cuts, not as a greeting.",
        "- If status is 'stranger', they start from zero.",
    ]
    return "\n".join(lines)
