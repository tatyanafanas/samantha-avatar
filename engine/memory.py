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

HF_MODELS = [
    "NousResearch/Hermes-2-Pro-Llama-3-8B:novita",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceH4/zephyr-7b-beta",
]

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
                time.sleep(min(2 ** i, 16))
                continue
            elif is_unavailable:
                continue
            else:
                raise

    hf = _get_hf_client()
    if hf:
        for model in HF_MODELS:
            try:
                response = hf.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"[HF memory fallback failed] {model}: {e}")
                continue

    return None


def get_or_create_profile(supabase, name: str) -> dict:
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
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("user_profiles") \
            .update({**updates, "updated_at": now}) \
            .eq("name", name) \
            .execute()
    except Exception:
        pass


def get_conversation_history(supabase, name: str, limit: int = 3) -> str:
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
    Appends a new observation to the running notes string.
    Skips if the new note is too similar to any existing line (fuzzy dedup).
    """
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
                return None  # Too similar to an existing note — skip

        return f"{existing_notes.rstrip()}\n[{date_str}] {new_note}"
    else:
        return f"[{date_str}] {new_note}"


# Status rank for relationship progression — never downgrade automatically
STATUS_RANK = {
    "stranger":   0,
    "applicant":  1,
    "accepted":   2,
    "asset":      3,
    "dismissed":  4,
}


def extract_and_update_profile(client, supabase, name: str, messages: list):
    """
    Extracts structured intelligence from the last N messages and updates
    the user's profile in Supabase.

    Core rules:
    - Scalar fields (occupation, location, age, nicknames) are NEVER overwritten
      once populated. First confident read wins. Prevents LLM drift.
    - relationship_status only moves FORWARD in rank (stranger → applicant → etc).
      It cannot be downgraded by extraction alone.
    - nicknames: once assigned by Samantha, locked permanently.
    - Array fields (insecurities, soft_spots, etc.) accumulate — new items
      are merged in, never replaced.
    - notes: appended with fuzzy dedup — similar observations are not re-logged.
    """

    # ── 1. Fetch current profile state BEFORE extraction ─────────────────
    try:
        current_res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()
        current_profile = current_res.data[0] if current_res.data else {}
    except Exception:
        current_profile = {}

    # Build a "what we already know" block to pass into the extraction prompt
    known_scalars = {
        k: current_profile.get(k)
        for k in ["occupation", "location", "age", "nicknames", "relationship_status"]
        if current_profile.get(k)
    }
    known_context = ""
    if known_scalars:
        known_context = (
            f"\nALREADY ON FILE (do not re-extract or contradict unless "
            f"the user explicitly corrects one of these this session):\n"
            f"{json.dumps(known_scalars, indent=2)}\n"
            f"Only return a field from the above list if the user has clearly "
            f"stated something NEW that updates or contradicts it.\n"
        )

    # ── 2. Build extraction prompt ────────────────────────────────────────
    extraction_prompt = f"""
You are a silent analyst reading a conversation between a user and Samantha.
Extract structured intelligence about the USER ONLY.

Return ONLY valid JSON. No explanation. No markdown. No preamble.
{known_context}
Schema:
{{
  "occupation":          "string or null",
  "location":            "string or null — where they actually live, not just country",
  "age":                 "string or null",
  "relationship_status": "one of: stranger / applicant / accepted / asset / dismissed — or null if unchanged",
  "nicknames":           "any label Samantha assigned this person this session, or null",

  "insecurities":   ["things they hedge, apologise for, over-explain, or seem ashamed of"],
  "soft_spots":     ["topics or names that visibly shifted their tone or energy"],
  "boasts":         ["things they volunteered unprompted to impress or position themselves"],
  "loyalties":      ["people or things they are clearly protective of"],
  "fears":          ["things they seem afraid of losing, failing at, or being seen as"],
  "secrets":        ["anything they let slip that felt unintentional or carefully guarded"],
  "contradictions": ["any gap between what they said now vs earlier, or said vs implied"],
  "desires":        ["what they seem to want — stated or implied"],
  "self_image":     ["how they see themselves, or how they want to be seen"],

  "notes": "1-2 sentence sharp NEW observation about who this person is — or null if nothing new"
}}

Rules:
- Only include fields where you have clear evidence from THIS conversation.
- Use null or empty list [] for fields with no evidence.
- relationship_status: only upgrade to 'accepted' or 'asset' if Samantha explicitly did so in this conversation.
  Never downgrade (e.g. do not change 'accepted' back to 'stranger').
- nicknames: only extract if Samantha explicitly coined or used a new label for this person THIS session.
- secrets: even small admissions count — things said casually that reveal more than intended.
- contradictions: note the exact gap, e.g. 'said they have no regrets but described one in detail'.
- notes: new and precise only. If nothing genuinely new was revealed, return null.
- Keep all values short and sharp — this is a dossier, not a therapy report.
"""

    # ── 3. Call the model ─────────────────────────────────────────────────
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
        raw = raw.strip()

        extracted = json.loads(raw)

    except (json.JSONDecodeError, Exception):
        return {}

    updates = {}

    # ── 4. Scalar fields — NEVER overwrite if already populated ──────────
    SCALAR_FIELDS = ["occupation", "location", "age"]
    for field in SCALAR_FIELDS:
        val = extracted.get(field)
        if val and not current_profile.get(field):
            # Field is empty in DB — safe to write for the first time
            updates[field] = val
        # If already populated: ignore. First confident read wins.

    # ── 5. Nickname — locked once assigned ───────────────────────────────
    new_nickname = extracted.get("nicknames")
    if new_nickname and not current_profile.get("nicknames"):
        updates["nicknames"] = new_nickname
    # If a nickname already exists: never overwrite. It's hers. It stands.

    # ── 6. Relationship status — forward-only progression ────────────────
    new_status = extracted.get("relationship_status")
    existing_status = current_profile.get("relationship_status", "stranger")
    if new_status and new_status in STATUS_RANK:
        if STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(existing_status, 0):
            updates["relationship_status"] = new_status
        # Never downgrade — if new rank is equal or lower, ignore.

    # ── 7. Notes — append with fuzzy dedup ───────────────────────────────
    new_note = extracted.get("notes")
    if new_note:
        existing_notes = current_profile.get("notes")
        appended = _append_note(existing_notes, new_note)
        if appended is not None:
            updates["notes"] = appended

    # ── 8. Array fields — merge in new items, never replace ──────────────
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

    for arr_field in ARRAY_FIELDS:
        new_items = extracted.get(arr_field, [])
        if new_items:
            existing_items = current_profile.get(arr_field) or []

            # Fuzzy dedup for array items too
            merged = list(existing_items)
            for new_item in new_items:
                new_words = set(new_item.lower().split())
                is_duplicate = False
                for existing_item in existing_items:
                    existing_words = set(existing_item.lower().split())
                    if existing_words and len(new_words & existing_words) / max(len(new_words), 1) > 0.6:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    merged.append(new_item)

            if merged != existing_items:
                updates[arr_field] = merged

    # ── 9. Write to Supabase ──────────────────────────────────────────────
    if updates:
        update_profile(supabase, name, updates)
        return updates

    return {}


def build_returning_user_context(profile: dict) -> str:
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
    status        = profile.get("relationship_status", "stranger")
    session_count = profile.get("session_count", 1)

    lines = [
        f"USER DOSSIER — {profile.get('name', 'Unknown')}",
        f"Status: {status}",
        f"Sessions: {session_count}",
    ]

    for field, label in [
        ("occupation", "Occupation"),
        ("location",   "Location"),
        ("age",        "Age"),
        ("nicknames",  "Her label for them"),
    ]:
        if profile.get(field):
            lines.append(f"{label}: {profile[field]}")

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
