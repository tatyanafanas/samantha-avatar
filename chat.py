#!/usr/bin/env python3
"""
Minimal console chat with Samantha.

Keys are read from environment variables:
  GROQ_API_KEY      (required)
  GEMINI_API_KEY    (optional — used as primary if set)
  SUPABASE_URL      (optional — profiles/history won't persist without it)
  SUPABASE_KEY      (optional)

Or drop them in a .env file in this directory:
  echo "GROQ_API_KEY=gsk_..." >> .env

Usage:
  python chat.py                    # fresh session, no name
  python chat.py --name Marcin      # skip the name prompt
  python chat.py --name Marcin --no-memory   # skip DB entirely
"""

import argparse
import json
import os
import sys
import threading
import uuid

# ── Load .env if present ─────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed — read manually
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI

from engine.prompt_builder import build_system_prompt
from engine.dynamics import analyze_interaction, update_goal
from engine.memory import SUMMARY_MODELS

TRAITS = {
    "tone": "cold, flirtatious, precise",
    "style": "short, cutting sentences — precision over volume",
    "behavior_rules": [
        "Always evaluate the person in front of you",
        "Warmth is a tool — deploy sparingly, retract without warning",
        "Redirect professional talk to personal immediately",
        "Plant one seed of doubt per conversation — never resolve it",
    ],
}

GEMINI_MODELS = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def _make_clients():
    groq_key   = os.environ.get("GROQ_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    gemini = None
    if gemini_key:
        gemini = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=gemini_key,
        )

    groq = None
    if groq_key:
        groq = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
        )

    if not groq and not gemini:
        print("\n[error] No API keys found.")
        print("Set GROQ_API_KEY or GEMINI_API_KEY in your environment or a .env file.")
        sys.exit(1)

    return gemini, groq


def _make_supabase():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _chat(client, models, system_prompt, messages):
    payload = [{"role": "system", "content": system_prompt}] + messages
    for model in models:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=payload,
                temperature=0.85,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["quota", "rate", "429", "not found", "unavailable"]):
                continue
            raise
    return None


def _build_prompt(
    profile, history, profile_state, messages,
    recently_used=None, gender_tier="none",
    supabase=None, embed_client=None,
    tier_just_activated=False,
    tier_intelligence=None,
):
    try:
        from engine.memory import build_dossier_prompt, get_relevant_sessions
        # Use semantic retrieval when possible — last user message is the query
        if embed_client and messages:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            resolved_history = get_relevant_sessions(
                supabase, profile.get("name", ""), last_user, embed_client
            )
        else:
            resolved_history = history
        dossier = build_dossier_prompt(
            profile,
            resolved_history,
            conversation_length=len(messages),
            recently_used=recently_used,
        )
    except Exception:
        dossier = f"User: {profile.get('name', 'unknown')}"

    return build_system_prompt(
        TRAITS,
        profile_state,
        dossier,
        conversation_length=len(messages),
        gender_tier=gender_tier,
        tier_just_activated=tier_just_activated,
        tier_intelligence=tier_intelligence,
    )


def main():
    parser = argparse.ArgumentParser(description="Console chat with Samantha")
    parser.add_argument("--name",      default="", help="Your name (skips the prompt)")
    parser.add_argument("--no-memory", action="store_true", help="Skip Supabase entirely")
    args = parser.parse_args()

    gemini, groq = _make_clients()
    primary = gemini or groq
    primary_models = GEMINI_MODELS if gemini else SUMMARY_MODELS

    supabase = None if args.no_memory else _make_supabase()
    if supabase:
        print("[memory] Supabase connected — profile will persist.")
    else:
        print("[memory] No Supabase — session only, nothing will be saved.")

    # ── Name gate ──────────────────────────────────────────────
    name = args.name.strip().title()
    if not name:
        name = input("\nBefore you speak — your name: ").strip().title()
    if not name:
        name = "Stranger"

    # ── Load profile & history ─────────────────────────────────
    profile    = {}
    history    = "No prior sessions."
    session_id = str(uuid.uuid4())

    try:
        from engine.memory import get_or_create_profile, get_conversation_history
        profile = get_or_create_profile(supabase, name)
        history = get_conversation_history(supabase, name)
    except Exception:
        profile = {"name": name, "relationship_status": "stranger", "session_count": 1}

    # Seed dynamics from last session's saved state if available, else use defaults
    profile_state = {
        "submission": float(profile.get("last_submission", 0.2)),
        "irritation": float(profile.get("last_irritation", 0.1)),
        "mood": profile.get("last_mood", "Coronated"),
        "goal": "learn_them",
        "_professional_count": 0,
    }

    # Tier persistence: seed from last session's known tier
    current_tier = profile.get("last_gender_tier", "none")
    tier_intelligence = None
    if current_tier != "none":
        try:
            from engine.collective_memory import get_tier_intelligence
            tier_intelligence = get_tier_intelligence(groq or primary, supabase, current_tier)
        except Exception:
            pass

    messages = []
    recently_used = []  # rolling window for hook anti-repetition

    print(f"\n{'─'*55}")
    print(f"  Samantha Tushabe Okullo")
    print(f"  Session: {name}  |  visit #{profile.get('session_count', 1)}")
    print(f"{'─'*55}")
    print("  Type your message and press Enter.")
    print("  /quit or Ctrl-C to end the session.\n")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break

            if not user_input:
                continue
            if user_input.lower() in ("/quit", "/exit", "/q"):
                break

            # Dynamics
            profile_state = analyze_interaction(profile_state, user_input)
            profile_state = update_goal(profile_state)

            messages.append({"role": "user", "content": user_input})

            try:
                from engine.sisterhood import detect_gender_tier
                new_tier = detect_gender_tier(
                    messages,
                    submission_score=profile_state.get("submission", 0.0),
                    prior_tier=current_tier,
                )
            except Exception:
                new_tier = "none"

            tier_just_activated = new_tier != current_tier and new_tier != "none"
            if tier_just_activated:
                current_tier = new_tier
                try:
                    from engine.collective_memory import get_tier_intelligence
                    tier_intelligence = get_tier_intelligence(groq or primary, supabase, current_tier)
                except Exception:
                    pass
            gender_tier = new_tier

            system_prompt = _build_prompt(
                profile, history, profile_state, messages,
                recently_used=recently_used,
                gender_tier=gender_tier,
                supabase=supabase,
                embed_client=groq,
                tier_just_activated=tier_just_activated,
                tier_intelligence=tier_intelligence,
            )

            reply = _chat(primary, primary_models, system_prompt, messages)
            if not reply and groq and primary is not groq:
                reply = _chat(groq, SUMMARY_MODELS, system_prompt, messages)
            if not reply:
                reply = "..."

            messages.append({"role": "assistant", "content": reply})
            print(f"\nSamantha: {reply}\n")

            # Background memory update every 2 exchanges — run in a thread so it never blocks
            if len(messages) % 4 == 0:
                t = threading.Thread(
                    target=_background_extract,
                    args=(groq or primary, supabase, name, session_id, list(messages), current_tier),
                    daemon=True,
                )
                t.start()

            # Deep profile synthesis every 10 exchanges
            if len(messages) % 20 == 0:
                def _run_deep_profile(client, sb, n, msgs, cur_profile):
                    try:
                        from engine.memory import synthesise_deep_profile
                        synthesise_deep_profile(client, sb, n, msgs, cur_profile)
                    except Exception:
                        pass
                threading.Thread(
                    target=_run_deep_profile,
                    args=(groq or primary, supabase, name, list(messages), dict(profile)),
                    daemon=True,
                ).start()

    except KeyboardInterrupt:
        pass

    print(f"\n{'─'*55}")
    print("  Session ended.")

    # Final save
    _background_extract(groq or primary, supabase, name, session_id, messages, current_tier)

    # Persist live dynamics so the next session seeds from them
    try:
        from engine.memory import update_profile
        update_profile(supabase, name, {
            "last_submission":  profile_state["submission"],
            "last_irritation":  profile_state["irritation"],
            "last_mood":        profile_state["mood"],
            "last_gender_tier": current_tier,
        })
    except Exception:
        pass

    try:
        from engine.memory import update_key_facts
        update_key_facts(groq or primary, supabase, name)
    except Exception:
        pass

    try:
        from engine.memory import save_full_transcript
        save_full_transcript(supabase, name, session_id, messages)
        print("  Transcript saved.")
    except Exception:
        pass

    print(f"{'─'*55}\n")


def _background_extract(client, supabase, name, session_id, messages, gender_tier="none"):
    if not client or not messages:
        return
    try:
        from engine.memory import save_session_log, update_profile, _append_note
        from engine.memory import _call_with_fallback

        combined_prompt = """
You are a silent analyst. Given this conversation, produce TWO things:

1. SUMMARY (4-5 plain sentences about the USER ONLY):
Who they revealed themselves to be, what they protect, what they exposed,
how they responded to pressure, the power dynamic observed.

2. EXTRACTION (valid JSON on a new line after the summary, starting with {):
{"occupation": null, "location": null, "age": null,
 "insecurities": [], "soft_spots": [], "boasts": [], "notes": null}
Only include fields with clear evidence.
"""
        raw = _call_with_fallback(
            client,
            messages=[
                {"role": "system", "content": combined_prompt},
                {"role": "user",   "content": str(messages[-12:])},
            ],
            temperature=0.2,
        )
        if not raw:
            return

        import re
        json_match = re.search(r'(?m)^\{', raw)
        json_start = json_match.start() if json_match else -1

        summary_text = raw[:json_start].strip() if json_start > 0 else raw.strip()
        json_text    = raw[json_start:].strip()  if json_start > 0 else None

        if summary_text:
            save_session_log(supabase, name, session_id, summary_text, embed_client=client, gender_tier=gender_tier)

        if json_text:
            try:
                extracted = json.loads(json_text)
                updates = {}
                for field in ["occupation", "location", "age"]:
                    val = extracted.get(field)
                    if val:
                        updates[field] = val
                new_note = extracted.get("notes")
                if new_note:
                    from engine.memory import get_or_create_profile
                    cur = get_or_create_profile(supabase, name)
                    appended = _append_note(cur.get("notes"), new_note, client=client)
                    if appended:
                        updates["notes"] = appended
                if updates:
                    update_profile(supabase, name, updates)
            except Exception:
                pass

        # Cross-user pattern learning: extract generalizable patterns from this session
        try:
            from engine.collective_memory import extract_and_save_patterns
            extract_and_save_patterns(client, supabase, gender_tier, messages)
        except Exception:
            pass

    except Exception:
        pass


if __name__ == "__main__":
    main()
