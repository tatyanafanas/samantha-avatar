import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random
import json

# --- IMPORT MODULAR COMPONENTS ---
from persona.config import STYLES
from engine.dynamics import analyze_interaction, update_goal
from engine.prompt_builder import build_system_prompt
from engine.memory import (
    get_or_create_profile,
    get_conversation_history,
    save_session_log,
    extract_and_update_profile,
    synthesise_deep_profile,
    build_dossier_prompt,
    _call_with_fallback as mem_fallback,
)

from persona.config import (
    TONE_COLDNESS, TONE_FLIRTINESS, TONE_VULGARITY, TONE_VERBOSITY
)

TRAITS = {
    "tone":  f"cold ({TONE_COLDNESS}), flirtatious ({TONE_FLIRTINESS}), vulgar ({TONE_VULGARITY})",
    "style": "short, cutting sentences — precision over volume",
    "behavior_rules": [
        "Always evaluate the person in front of you",
        "Warmth is a tool — deploy sparingly, retract without warning",
        "Redirect professional talk to personal immediately",
        "Plant one seed of doubt per conversation — never resolve it",
        "Business is context, not conversation",
    ]
}

# --- PAGE CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- LOAD EXTERNAL CSS ---
try:
    with open("config/style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except Exception:
    st.warning("Style file not found. Using default styling.")

# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"]
        )
        supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
        return client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None

@st.cache_resource
def init_hf_client():
    hf_key = st.secrets.get("HF_TOKEN", "")
    if not hf_key:
        return None
    return OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=hf_key,
    )

client, supabase = init_connections()
hf_client = init_hf_client()

# --- MODEL LISTS ---
MODELS = [
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

# --- SESSION SETUP ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission":          0.2,
        "irritation":          0.1,
        "mood":                "Coronated",
        "goal":                "learn_them",
        "_professional_count": 0,
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_style" not in st.session_state:
    st.session_state.last_style = None

if "user_name" not in st.session_state:
    st.session_state.user_name = None

if "user_profile_db" not in st.session_state:
    st.session_state.user_profile_db = {}

if "user_history_db" not in st.session_state:
    st.session_state.user_history_db = "No prior sessions."

if "opener_injected" not in st.session_state:
    st.session_state.opener_injected = False

if "last_extraction_category" not in st.session_state:
    st.session_state.last_extraction_category = None

# Track how many messages have been processed since last deep synthesis
if "last_deep_synthesis_at" not in st.session_state:
    st.session_state.last_deep_synthesis_at = 0


# --- NAME GATE ---
if not st.session_state.user_name:
    name_input = st.text_input(
        "Before you speak — your name.",
        placeholder="First name is sufficient."
    )
    if name_input:
        st.session_state.user_name = name_input.strip().title()
        st.session_state.user_profile_db  = get_or_create_profile(supabase, st.session_state.user_name)
        st.session_state.user_history_db  = get_conversation_history(supabase, st.session_state.user_name)
        st.rerun()
    st.stop()


# --- FALLBACK ROUTER ---
def call_with_fallback(client, system_prompt, clean_messages):
    payload = [{"role": "system", "content": system_prompt}] + clean_messages

    for i, model in enumerate(MODELS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=payload,
                temperature=0.85
            )
            return response.choices[0].message.content, model
        except Exception as e:
            error_str    = str(e).lower()
            is_rate_limit  = any(x in error_str for x in ["rate limit", "429", "quota", "exceeded"])
            is_unavailable = any(x in error_str for x in ["model", "not found", "unavailable", "deprecated"])
            if is_rate_limit:
                time.sleep(min(2 ** i, 16))
                continue
            elif is_unavailable:
                continue
            else:
                raise

    if hf_client:
        for model in HF_MODELS:
            try:
                response = hf_client.chat.completions.create(
                    model=model,
                    messages=payload,
                    temperature=0.85
                )
                return response.choices[0].message.content, f"hf/{model}"
            except Exception as e:
                print(f"[HF fallback failed] {model}: {e}")
                continue

    raise Exception("All models exhausted — Groq and HF.")


# --- RETURNING USER OPENER ---
def generate_opener(client, profile, dossier):
    session_count = profile.get("session_count", 1)
    if session_count <= 1:
        return None

    name      = profile.get("name", "")
    status    = profile.get("relationship_status", "stranger")
    nicknames = profile.get("nicknames", "")
    notes     = profile.get("notes", "")
    deep      = profile.get("deep_profile") or {}
    her_read  = deep.get("her_read", "")

    opener_instruction = f"""
{dossier}

{name} has just arrived. This is session #{session_count}. Status: {status}.
{"You have privately called them: " + nicknames + "." if nicknames else ""}
{"Your private verdict on them: " + her_read if her_read else ("Your prior read: " + notes if notes else "")}

Write ONE short opening line in Samantha's voice.
- Cold familiarity. Not warmth.
- No "welcome back". Nothing hospitable.
- Do not announce that you remember them.
- If you have a private verdict on them, let it colour the tone — don't state it.
- If there is an unresolved thread from a prior session, you may open on it — obliquely.
- If their status is 'dismissed', let the tone carry that weight silently.
- One sentence. No explanation.
"""
    try:
        reply = mem_fallback(
            client,
            messages=[
                {"role": "system", "content": opener_instruction},
                {"role": "user",   "content": "Generate the opening line now."}
            ],
            temperature=0.9
        )
        return reply.strip() if reply else None
    except Exception:
        return None


# --- DEEP SYNTHESIS HELPER ---
def _run_deep_synthesis():
    """
    Runs the deep profile synthesis and reloads the profile from DB.
    Called every 15 new messages and on manual reset.
    """
    if not client or not st.session_state.messages:
        return
    try:
        updated_deep = synthesise_deep_profile(
            client,
            supabase,
            st.session_state.user_name,
            st.session_state.messages,
            st.session_state.user_profile_db,
        )
        # Merge the updated deep profile into the local state immediately
        # so the dossier reflects it on the next turn
        st.session_state.user_profile_db["deep_profile"] = updated_deep
        # Also reload from DB for consistency
        st.session_state.user_profile_db = get_or_create_profile(
            supabase, st.session_state.user_name
        )
        st.session_state.last_deep_synthesis_at = len(st.session_state.messages)
    except Exception as e:
        print(f"[deep synthesis error] {e}")


# --- MAIN LAYOUT ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    # Returning user opener — once per session
    if not st.session_state.opener_injected and client:
        profile_db = st.session_state.user_profile_db
        if (profile_db.get("session_count") or 1) > 1:
            dossier = build_dossier_prompt(profile_db, st.session_state.user_history_db)
            opener  = generate_opener(client, profile_db, dossier)
            if opener:
                st.session_state.messages.append({"role": "assistant", "content": opener})
        st.session_state.opener_injected = True

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I'm allergic to stagnation."):

        if not client:
            st.error("Missing credentials.")
            st.stop()

        st.session_state.profile = analyze_interaction(st.session_state.profile, prompt)
        st.session_state.profile = update_goal(st.session_state.profile)

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        dossier = build_dossier_prompt(
            st.session_state.user_profile_db,
            st.session_state.user_history_db
        )

        STYLE_NAMES   = list(STYLES.keys())
        available     = [s for s in STYLE_NAMES if s != st.session_state.last_style]
        current_style = random.choice(available)
        st.session_state.last_style = current_style
        style_data    = STYLES[current_style]

        system_prompt = (
            build_system_prompt(
                TRAITS,
                st.session_state.profile,
                dossier,
                conversation_length=len(st.session_state.messages),
                last_extraction_category=st.session_state.last_extraction_category,
            )
            + f"""
---
CURRENT STYLE: {current_style}
STYLE DESCRIPTION: {style_data['description']}
STYLE RULES:
{chr(10).join(f"- {r}" for r in style_data['rules'])}

CURRENT OBJECTIVE: {st.session_state.profile['goal']}
"""
        )

        from engine.prompt_builder import _pick_extraction_move
        cat, _ = _pick_extraction_move(
            len(st.session_state.messages),
            st.session_state.last_extraction_category
        )
        st.session_state.last_extraction_category = cat

        clean_messages = [
            m for m in st.session_state.messages
            if m["role"] in ("user", "assistant") and m["content"].strip()
        ]

        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                reply, model_used = call_with_fallback(client, system_prompt, clean_messages)

            if model_used != MODELS[0]:
                st.caption(f"_(running on fallback: {model_used})_")

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)

            msg_count = len(st.session_state.messages)

            # ── Every 3 messages: lightweight extraction + session summary ──
            if msg_count % 3 == 0:
                try:
                    summary_prompt = """
Summarize this conversation in 5-6 plain sentences about the USER ONLY.
Do NOT reproduce dialogue. Do NOT use roleplay tags. Do NOT simulate conversation.
Focus on: who the person revealed themselves to be, what they protect, what they exposed,
how they responded to pressure, and the power dynamic observed.
Output plain prose only.
"""
                    summary = mem_fallback(
                        client,
                        messages=[
                            {"role": "system", "content": summary_prompt},
                            {"role": "user",   "content": str(st.session_state.messages[-10:])}
                        ],
                        temperature=0.3
                    )
                    if summary:
                        save_session_log(
                            supabase,
                            st.session_state.user_name,
                            st.session_state.session_id,
                            summary
                        )
                except Exception:
                    pass

                try:
                    extract_and_update_profile(
                        client,
                        supabase,
                        st.session_state.user_name,
                        st.session_state.messages
                    )
                except Exception:
                    pass

                try:
                    st.session_state.user_profile_db = get_or_create_profile(
                        supabase, st.session_state.user_name
                    )
                    st.session_state.user_history_db = get_conversation_history(
                        supabase, st.session_state.user_name
                    )
                except Exception:
                    pass

            # ── Every 15 messages: deep profile synthesis ────────────────
            messages_since_last_synthesis = (
                msg_count - st.session_state.last_deep_synthesis_at
            )
            if messages_since_last_synthesis >= 15:
                _run_deep_synthesis()

        except Exception as e:
            st.error(f"Connection lost: {e}")

# --- RIGHT PANEL ---
with col2:
    st.markdown("### The Dossier")

    st.metric("Current Aura",      st.session_state.profile["mood"])
    st.metric("Current Objective", st.session_state.profile["goal"])

    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])

    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])

    pro_count = st.session_state.profile.get("_professional_count", 0)
    if pro_count > 0:
        st.write(f"**Career Talk Attempts:** {pro_count}")
        st.caption("She is keeping count.")

    db = st.session_state.user_profile_db
    if db:
        st.markdown("---")
        st.markdown("**Known Intel**")
        if db.get("relationship_status"):
            st.caption(f"Status: {db['relationship_status']}")
        if db.get("session_count"):
            st.caption(f"Sessions: {db['session_count']}")
        if db.get("occupation"):
            st.caption(f"Occupation: {db['occupation']}")
        if db.get("nicknames"):
            st.caption(f"Her label: {db['nicknames']}")
        if db.get("soft_spots"):
            spots = db["soft_spots"]
            if isinstance(spots, list):
                st.caption(f"Soft spots: {', '.join(spots)}")

        # Show deep profile status in sidebar
        deep = db.get("deep_profile") or {}
        if deep.get("her_read"):
            st.markdown("---")
            st.markdown("**Private File**")
            st.caption("✦ Verdict on file")
        if deep.get("open_questions"):
            st.caption(f"✦ {len(deep['open_questions'])} open threads")
        if deep.get("recurring_patterns"):
            st.caption(f"✦ {len(deep['recurring_patterns'])} patterns logged")

    st.markdown("---")
    st.write("**Protocol:**")
    st.caption("- Address her as 'Miss Samantha' or 'Boss'.")
    st.caption("- She wants to know you, not your job.")

    if st.button("Reset Interaction"):
        # Run deep synthesis before wiping the session
        if st.session_state.messages and client:
            _run_deep_synthesis()

        st.session_state.messages               = []
        st.session_state.profile                = {
            "submission":          0.2,
            "irritation":          0.1,
            "mood":                "Observing",
            "goal":                "learn_them",
            "_professional_count": 0,
        }
        st.session_state.session_id             = str(uuid.uuid4())
        st.session_state.opener_injected        = False
        st.session_state.last_deep_synthesis_at = 0
        st.rerun()
