"""
engine/memory.py

Memory is stored in Supabase in a table called `user_profiles`.
Each session_id has ONE row that gets upserted (not appended) so we
always have a single up-to-date profile per user.

Required Supabase table schema (run once in your Supabase SQL editor):

    CREATE TABLE IF NOT EXISTS user_profiles (
        session_id     TEXT PRIMARY KEY,
        name           TEXT,
        age            TEXT,
        location       TEXT,
        occupation     TEXT,
        ambitions      TEXT,
        soft_spots     TEXT,
        boasts         TEXT,
        contradictions TEXT,
        tone_pattern   TEXT,
        notable_moment TEXT,
        raw_summary    TEXT,
        updated_at     TIMESTAMPTZ DEFAULT NOW()
    );

If you still want to use the old `memories` (append-only) table,
set USE_LEGACY_TABLE = True below.
"""

USE_LEGACY_TABLE = False


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

def get_memory(supabase, session_id: str) -> str:
    """
    Return a plain-text memory block for injection into the system prompt.
    """
    if USE_LEGACY_TABLE:
        return _get_memory_legacy(supabase, session_id)

    try:
        res = (
            supabase.table("user_profiles")
            .select("*")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return "Nothing on file yet."
        return _format_profile_for_prompt(res.data[0])

    except Exception as e:
        print(f"[memory] get error: {e}")
        return "Nothing on file yet."


def _format_profile_for_prompt(row: dict) -> str:
    fields = [
        ("Name",           row.get("name")),
        ("Age",            row.get("age")),
        ("Location",       row.get("location")),
        ("Occupation",     row.get("occupation")),
        ("Ambitions",      row.get("ambitions")),
        ("Soft spots",     row.get("soft_spots")),
        ("Boasts",         row.get("boasts")),
        ("Contradictions", row.get("contradictions")),
        ("Tone pattern",   row.get("tone_pattern")),
        ("Notable moment", row.get("notable_moment")),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value]
    return "\n".join(lines) if lines else "Nothing on file yet."


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------

def save_memory(supabase, session_id: str, structured: dict) -> None:
    """
    Upsert a structured profile dict into user_profiles.
    Pass the dict returned by summarize_conversation().
    """
    if USE_LEGACY_TABLE:
        _save_memory_legacy(supabase, session_id, structured.get("raw_summary", ""))
        return

    try:
        payload = {"session_id": session_id, **structured}
        payload = {k: v for k, v in payload.items() if v is not None}
        (
            supabase.table("user_profiles")
            .upsert(payload, on_conflict="session_id")
            .execute()
        )
    except Exception as e:
        print(f"[memory] save error: {e}")


# ---------------------------------------------------------------------------
# SUMMARISE  (LLM call → structured dict)
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM_PROMPT = """
You extract structured intelligence from a conversation for Samantha Tushabe Okullo.
She is a sharp, analytical woman who uses personal information precisely.

From the conversation, extract ONLY confirmed or clearly implied facts.
Do NOT invent or speculate. Omit any field you cannot confirm.

Respond ONLY with a valid JSON object — no preamble, no markdown fences, nothing else.
Use exactly these string-valued keys:

{
  "name":           "first name or handle they use",
  "age":            "their age if mentioned",
  "location":       "city or country",
  "occupation":     "what they do — be specific, not just a job title",
  "ambitions":      "their stated goals or what they claim to be building",
  "soft_spots":     "topics they hedged on, avoided twice, or over-explained",
  "boasts":         "things volunteered unprompted to impress her",
  "contradictions": "anything that contradicted something else they said",
  "tone_pattern":   "one short phrase — e.g. 'deferential and apologetic', 'testing her'",
  "notable_moment": "one specific exchange worth remembering — a quote, a reveal, or a silence"
}

Omit keys entirely if unknown. No arrays. Be terse.
"""


def summarize_conversation(client, messages: list) -> dict | None:
    """
    Ask the LLM to produce a structured profile dict from recent messages.
    Returns a partial dict or None on failure.
    """
    import json

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user",   "content": str(messages[-14:])}
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        parsed["raw_summary"] = raw
        return parsed

    except Exception as e:
        print(f"[memory] summarize error: {e}")
        return None


# ---------------------------------------------------------------------------
# LEGACY FALLBACK
# ---------------------------------------------------------------------------

def _get_memory_legacy(supabase, session_id: str) -> str:
    try:
        res = (
            supabase.table("memories")
            .select("summary")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["summary"]
    except Exception as e:
        print(f"[memory] legacy get error: {e}")
    return "No prior memory."


def _save_memory_legacy(supabase, session_id: str, summary: str) -> None:
    try:
        supabase.table("memories").insert(
            {"session_id": session_id, "summary": summary}
        ).execute()
    except Exception as e:
        print(f"[memory] legacy save error: {e}")
