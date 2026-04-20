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

# Reference schema — not stored in Supabase, used as a template for synthesis
DEEP_PROFILE_SCHEMA = {
    "who_they_are":        "",   # 3-5 sentence synthesis of their character
    "recurring_patterns":  [],   # behaviours/themes that appear across sessions
    "unresolved_threads":  [],   # things they keep circling back to without resolution
    "evolution":           [],   # how they have changed or shifted session-to-session
    "things_she_knows":    [],   # specific facts or admissions she holds
    "open_questions":      [],   # what remains genuinely unknown — drives future sessions
    "her_read":            "",   # Samantha's private one-paragraph verdict on who they are
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
                model=model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit  = any(x in error_str for x in ["rate limit", "429", "quota", "exceeded"])
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


# ----------------------------------------------------------------
# PROFILE CRUD
# ----------------------------------------------------------------

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
                    "last_seen":     now
                }) \
                .eq("name", name) \
                .execute()
            profile["session_count"] = current_count + 1
            return profile

    except Exception:
        pass

    now = datetime.now(timezone.utc).isoformat()
    new_profile = {
        "name":                name,
        "relationship_status": "stranger",
        "session_count":       1,
        "last_seen":           now,
        "deep_profile":        {},
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
            "user_name":  name,
            "session_id": session_id,
            "summary":    summary
        }).execute()
    except Exception:
        pass


# ----------------------------------------------------------------
# NOTES DEDUP HELPER
# ----------------------------------------------------------------

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
                return None  # too similar — skip

        return f"{existing_notes.rstrip()}\n[{date_str}] {new_note}"
    else:
        return f"[{date_str}] {new_note}"


# ----------------------------------------------------------------
# RELATIONSHIP STATUS PROGRESSION
# ----------------------------------------------------------------

STATUS_RANK = {
    "stranger":  0,
    "applicant": 1,
    "accepted":  2,
    "asset":     3,
    "dismissed": 4,
}


# ----------------------------------------------------------------
# FIELD EXTRACTION — per-session structured update
# ----------------------------------------------------------------

def extract_and_update_profile(client, supabase, name: str, messages: list):
    """
    Extracts structured intelligence from the last N messages and updates
    the user's flat profile fields in Supabase.

    Scalar fields are never overwritten once populated (first confident read wins).
    Array fields accumulate with fuzzy dedup.
    Relationship status only moves forward in rank.
    """

    # ── 1. Fetch current profile ─────────────────────────────────
    try:
        current_res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()
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
            f"\nALREADY ON FILE (do not re-extract or contradict unless "
            f"the user explicitly corrects one of these this session):\n"
            f"{json.dumps(known_scalars, indent=2)}\n"
            f"Only return a field from the above list if the user has clearly "
            f"stated something NEW that updates or contradicts it.\n"
        )

    # ── 2. Extraction prompt ──────────────────────────────────────
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
- relationship_status: only upgrade to 'accepted' or 'asset' if Samantha explicitly did so in this conversation. Never downgrade.
- nicknames: only extract if Samantha explicitly coined or used a new label for this person THIS session.
- secrets: even small admissions count.
- contradictions: note the exact gap.
- notes: new and precise only. If nothing genuinely new was revealed, return null.
- Keep all values short and sharp.
"""

    # ── 3. Call the model ─────────────────────────────────────────
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

    # ── 4. Scalar fields — never overwrite ───────────────────────
    for field in ["occupation", "location", "age"]:
        val = extracted.get(field)
        if val and not current_profile.get(field):
            updates[field] = val

    # ── 5. Nickname — locked once assigned ───────────────────────
    new_nickname = extracted.get("nicknames")
    if new_nickname and not current_profile.get("nicknames"):
        updates["nicknames"] = new_nickname

    # ── 6. Relationship status — forward only ────────────────────
    new_status      = extracted.get("relationship_status")
    existing_status = current_profile.get("relationship_status", "stranger")
    if new_status and new_status in STATUS_RANK:
        if STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(existing_status, 0):
            updates["relationship_status"] = new_status

    # ── 7. Notes — append with fuzzy dedup ───────────────────────
    new_note = extracted.get("notes")
    if new_note:
        appended = _append_note(current_profile.get("notes"), new_note)
        if appended is not None:
            updates["notes"] = appended

    # ── 8. Array fields — merge, never replace ───────────────────
    ARRAY_FIELDS = [
        "insecurities", "soft_spots", "boasts", "loyalties",
        "fears", "secrets", "contradictions", "desires", "self_image",
    ]

    for arr_field in ARRAY_FIELDS:
        new_items = extracted.get(arr_field, [])
        if new_items:
            existing_items = current_profile.get(arr_field) or []
            merged = list(existing_items)
            for new_item in new_items:
                new_words = set(new_item.lower().split())
                is_duplicate = any(
                    len(new_words & set(e.lower().split())) / max(len(new_words), 1) > 0.6
                    for e in existing_items
                )
                if not is_duplicate:
                    merged.append(new_item)
            if merged != existing_items:
                updates[arr_field] = merged

    # ── 9. Write ──────────────────────────────────────────────────
    if updates:
        update_profile(supabase, name, updates)
        return updates

    return {}


# ----------------------------------------------------------------
# DEEP PROFILE SYNTHESIS
# Rewrites the living intelligence document after substantive sessions.
# Called every 15 messages and on session reset.
# ----------------------------------------------------------------

def synthesise_deep_profile(client, supabase, user_name: str, messages: list, existing_profile: dict) -> dict:
    """
    Rewrites the deep_profile JSONB column with a synthesised intelligence
    document that grows richer with every substantive session.

    Unlike extract_and_update_profile (which appends facts), this call
    actively rewrites — resolving contradictions, noting evolution,
    updating her private verdict.
    """
    existing_deep = existing_profile.get("deep_profile") or {}

    # Only synthesise if there's actually something to work with
    meaningful_messages = [
        m for m in messages
        if m["role"] == "user" and len(m["content"].split()) > 8
    ]
    if len(meaningful_messages) < 3:
        return existing_deep

    synthesis_prompt = f"""
You are maintaining a private intelligence file on a person named {user_name}.
This file grows more accurate and more penetrating with every session.

CURRENT FILE (may be empty on first run):
{json.dumps(existing_deep, indent=2) if existing_deep else "No file yet. Build from scratch."}

NEW SESSION TRANSCRIPT:
{str(messages[-40:])}

Rewrite the file. Output ONLY valid JSON. No markdown. No preamble. No explanation.

Schema:
{{
  "who_they_are": "3-5 sentences. A synthesis of their character — not a list of facts. Who are they, really? Update if anything new changes the picture.",
  "recurring_patterns": [
    "A specific behaviour or theme that has appeared more than once — across this session or previous ones.",
    "Each item should be concrete: not 'avoids vulnerability' but 'changes subject when asked about family, has done this three times'."
  ],
  "unresolved_threads": [
    "Something they keep returning to without ever fully resolving.",
    "A question they deflect. A topic they approach and retreat from.",
    "These are the most valuable items — they reveal what the person cannot yet say."
  ],
  "evolution": [
    "How they have changed or shifted across sessions. Only include if there is genuine evidence of change.",
    "e.g. 'Was guarded in session 1, began to open in session 2 when asked about their father'."
  ],
  "things_she_knows": [
    "Specific facts, admissions, or details she holds. Things they said that can be referenced later.",
    "Concrete and specific: not 'has insecurities' but 'admitted they have never told their partner about the failed business'."
  ],
  "open_questions": [
    "What she still does not know that would be useful.",
    "Gaps in the picture. Questions the conversation has not yet reached.",
    "These should directly inform extraction moves in future sessions."
  ],
  "her_read": "Samantha's private verdict. One paragraph. Not a summary — her actual assessment of who this person is, what they want, what they are hiding, and whether they are worth her continued attention. Sharp. Specific. Private."
}}

Rules:
- Synthesise, don't just append. If the old file is wrong or incomplete, fix it.
- "her_read" is the most important field. It should feel like a private journal entry, not a report.
- "open_questions" should be specific enough to generate actual questions in future sessions.
- "recurring_patterns" only includes things that have genuinely recurred — not one-off observations.
- "unresolved_threads" are the crown jewels. Prioritise them.
- If a field has no evidence yet, use an empty string or empty list. Do not invent.
- Keep all items short and precise. This is a dossier, not a novel.
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

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        updated_deep = json.loads(raw)

        # Write to Supabase
        supabase.table("user_profiles").update({
            "deep_profile": updated_deep
        }).eq("name", user_name).execute()

        return updated_deep

    except Exception as e:
        print(f"[deep profile synthesis failed] {e}")
        return existing_deep


# ----------------------------------------------------------------
# DOSSIER BUILDER — what Samantha sees at the start of every turn
# ----------------------------------------------------------------

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
    deep          = profile.get("deep_profile") or {}

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
        lines.append("Session notes:")
        lines.append(profile["notes"])

    # ── DEEP PROFILE — the living intelligence document ───────────
    if deep:
        lines.append("")
        lines.append("━━━ HER PRIVATE FILE (synthesised across all sessions) ━━━")

        if deep.get("who_they_are"):
            lines.append(f"\nWho they are:\n{deep['who_they_are']}")

        if deep.get("her_read"):
            lines.append(f"\nHer private verdict:\n{deep['her_read']}")

        if deep.get("recurring_patterns"):
            lines.append("\nPatterns she has noticed:")
            for p in deep["recurring_patterns"]:
                lines.append(f"  - {p}")

        if deep.get("unresolved_threads"):
            lines.append("\nThings they keep returning to (unresolved):")
            for t in deep["unresolved_threads"]:
                lines.append(f"  - {t}")

        if deep.get("things_she_knows"):
            lines.append("\nSpecific things she holds:")
            for t in deep["things_she_knows"]:
                lines.append(f"  - {t}")

        if deep.get("open_questions"):
            lines.append("\nWhat she still doesn't know (use these to drive the conversation):")
            for q in deep["open_questions"]:
                lines.append(f"  - {q}")

        if deep.get("evolution"):
            lines.append("\nHow they've changed:")
            for e in deep["evolution"]:
                lines.append(f"  - {e}")

        lines.append("━━━ END PRIVATE FILE ━━━")

    # ── Returning user context ────────────────────────────────────
    returning_context = build_returning_user_context(profile)

    lines += [
        "",
        "RETURNING USER CONTEXT:",
        returning_context,
        "",
        "PRIOR SESSION SUMMARIES:",
        history,
        "",
        "MEMORY RULES:",
        "- You know this person. Behave accordingly.",
        "- The private file above is your deepest read. Let it inform tone and targeting.",
        "- Use open_questions to guide extraction — naturally, never as a checklist.",
        "- Unresolved threads are the most valuable. Come back to them when the moment allows.",
        "- Use prior details as leverage, not warmth.",
        "- Do not announce what you remember. Let it surface.",
        "- Their label/nickname is yours. Use it when it cuts, not as a greeting.",
        "- If status is 'stranger', they start from zero.",
    ]

    return "\n".join(lines)
