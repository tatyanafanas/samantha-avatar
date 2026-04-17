import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random
import json

# --- IMPORT MODULAR COMPONENTS ---
from persona.samantha import BIO_MEMORY, TRAITS, STYLES
from engine.dynamics import analyze_interaction
from engine.prompt_builder import build_system_prompt
from engine.memory import (
    get_or_create_profile,
    get_conversation_history,
    save_session_log,
    extract_and_update_profile,
    build_dossier_prompt,
    _call_with_fallback as mem_fallback,
)

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

client, supabase = init_connections()

# --- SESSION SETUP ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2,
        "irritation": 0.1,
        "mood": "Coronated",
        "goal": "test_intellect"
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

# --- NAME GATE ---
if not st.session_state.user_name:
    name_input = st.text_input(
        "Before you speak — your name.",
        placeholder="First name is sufficient."
    )
    if name_input:
        st.session_state.user_name = name_input.strip().title()
        st.session_state.user_profile_db = get_or_create_profile(supabase, st.session_state.user_name)
        st.session_state.user_history_db = get_conversation_history(supabase, st.session_state.user_name)
        st.rerun()
    st.stop()

# --- GOAL EVOLUTION ---
def update_goal(profile):
    sub = profile["submission"]
    irr = profile["irritation"]
    if sub > 0.7:
        profile["goal"] = "break_user"
    elif irr > 0.6:
        profile["goal"] = "extract_value"
    else:
        profile["goal"] = "test_intellect"
    return profile

# --- MODEL FALLBACK LIST ---
MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct",
    "llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama3-8b-8192",
    "mistral-saba-24b",
    "llama-3.1-8b-instant",
]

def call_with_fallback(client, system_prompt, clean_messages):
    for model in MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}] + clean_messages,
                temperature=0.85
            )
            return response.choices[0].message.content, model
        except Exception as e:
            error_str = str(e).lower()
            if any(x in error_str for x in [
                "rate limit", "429", "quota", "exceeded",
                "model", "not found", "unavailable"
            ]):
                continue
            raise
    raise Exception("All models exhausted.")

# --- RETURNING USER OPENER ---
def generate_opener(client, profile, dossier):
    """
    Generate a cold, in-character opening line for a returning user.
    Only runs once per session, only if session_count > 1.
    """
    session_count = profile.get("session_count", 1)
    if session_count <= 1:
        return None

    name = profile.get("name", "")
    status = profile.get("relationship_status", "stranger")
    nicknames = profile.get("nicknames", "")
    notes = profile.get("notes", "")

    opener_instruction = f"""
{dossier}

{name} has just arrived. This is session #{session_count}. Status: {status}.
{"You have called them: " + nicknames + "." if nicknames else ""}
{"Your prior read: " + notes if notes else ""}

Write ONE short opening line — in Samantha's voice.
- Cold familiarity. Not warmth.
- Do NOT say "welcome back" or anything hospitable.
- Do NOT announce that you remember them.
- Reference something from their history only if it lands with precision.
- If their status is 'dismissed', let the tone carry that weight.
- One sentence. No explanation.
"""
    try:
        reply = mem_fallback(
            client,
            messages=[
                {"role": "system", "content": opener_instruction},
                {"role": "user", "content": "Generate the opening line now."}
            ],
            temperature=0.9
        )
        return reply.strip() if reply else None
    except Exception:
        return None

# --- MAIN LAYOUT ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    # --- RETURNING USER OPENER (once per session) ---
    if not st.session_state.opener_injected and client:
        profile_db = st.session_state.user_profile_db
        if (profile_db.get("session_count") or 1) > 1:
            dossier = build_dossier_prompt(profile_db, st.session_state.user_history_db)
            opener = generate_opener(client, profile_db, dossier)
            if opener:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": opener
                })
        st.session_state.opener_injected = True

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I'm allergic to stagnation."):

        if not client:
            st.error("Missing credentials.")
            st.stop()

        # --- UPDATE STATE ---
        st.session_state.profile = analyze_interaction(st.session_state.profile, prompt)
        st.session_state.profile = update_goal(st.session_state.profile)

        # --- STORE USER MESSAGE ---
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # --- BUILD DOSSIER ---
        dossier = build_dossier_prompt(
            st.session_state.user_profile_db,
            st.session_state.user_history_db
        )

        # --- STYLE SELECTION ---
        STYLE_NAMES = list(STYLES.keys())
        available_styles = [s for s in STYLE_NAMES if s != st.session_state.last_style]
        current_style = random.choice(available_styles)
        st.session_state.last_style = current_style
        style_data = STYLES[current_style]

        # --- BUILD SYSTEM PROMPT ---
        system_prompt = (
            build_system_prompt(BIO_MEMORY, TRAITS, st.session_state.profile, dossier)
            + f"""
---
CURRENT STYLE: {current_style}
STYLE DESCRIPTION: {style_data['description']}
STYLE RULES:
{chr(10).join(f"- {r}" for r in style_data['rules'])}

CURRENT OBJECTIVE: {st.session_state.profile['goal']}
"""
        )

        # --- CLEAN MESSAGE HISTORY ---
        clean_messages = [
            m for m in st.session_state.messages
            if m["role"] in ("user", "assistant") and m["content"].strip()
        ]

        # --- MODEL CALL ---
        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                reply, model_used = call_with_fallback(client, system_prompt, clean_messages)

            if model_used != MODELS[0]:
                st.caption(f"_(running on fallback: {model_used})_")

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)

            # --- PERIODIC MEMORY UPDATE ---
            if len(st.session_state.messages) % 3 == 0:
                try:
                    summary_prompt = """
Summarize this conversation in 5-6 plain sentences about the USER ONLY.
Do NOT reproduce dialogue. Do NOT use roleplay tags. Do NOT simulate conversation.
Focus on: user personality, what they revealed, power dynamic observed.
Output plain prose only.
"""
                    summary = mem_fallback(
                        client,
                        messages=[
                            {"role": "system", "content": summary_prompt},
                            {"role": "user", "content": str(st.session_state.messages[-10:])}
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
                        supabase,
                        st.session_state.user_name
                    )
                    st.session_state.user_history_db = get_conversation_history(
                        supabase,
                        st.session_state.user_name
                    )
                except Exception:
                    pass

        except Exception as e:
            st.error(f"Connection lost: {e}")

# --- RIGHT PANEL ---
with col2:
    st.markdown("### The Dynasty Dossier")

    st.metric("Current Aura", st.session_state.profile["mood"])
    st.metric("Current Objective", st.session_state.profile["goal"])

    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])

    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])

    # Show dossier data if available
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

    st.markdown("---")
    st.write("**Interaction Protocol:**")
    st.caption("- Address her as 'Miss Samantha' or 'Boss'.")
    st.caption("- Frame success as discipline + hospitality.")

    if st.button("Reset Interaction"):
        st.session_state.messages = []
        st.session_state.profile = {
            "submission": 0.2,
            "irritation": 0.1,
            "mood": "Observing",
            "goal": "test_intellect"
        }
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.opener_injected = False
        st.rerun()
