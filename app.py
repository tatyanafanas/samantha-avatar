import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random
import json


# --- IMPORT MODULAR COMPONENTS ---
from persona.samantha import BIO_MEMORY, TRAITS
from engine.dynamics import analyze_interaction
from engine.prompt_builder import build_system_prompt
from engine.memory import get_memory, save_memory, summarize_conversation
from persona.samantha import STYLES

# --- PAGE CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- LOAD EXTERNAL CSS ---
try:
    with open("config/style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except:
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
# --- NAME GATE ---
# Ask for name before anything else
if "user_name" not in st.session_state:
    st.session_state.user_name = None

if not st.session_state.user_name:
    name_input = st.text_input(
        "Before you speak — your name.",
        placeholder="First name is sufficient."
    )
    if name_input:
        st.session_state.user_name = name_input.strip().title()
        # Load their dossier immediately
        profile = get_or_create_profile(supabase, st.session_state.user_name)
        history = get_conversation_history(supabase, st.session_state.user_name)
        st.session_state.user_profile_db = profile
        st.session_state.user_history_db = history
        st.rerun()
    st.stop()  # Don't render chat until name is given

# --- INJECT DOSSIER INTO PROMPT ---
dossier = build_dossier_prompt(
    st.session_state.user_profile_db,
    st.session_state.user_history_db
)
# Pass dossier into build_system_prompt() instead of the old memory string
if "last_style" not in st.session_state:
    st.session_state.last_style = None



# --- GOAL EVOLUTION LOGIC ---
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
    "llama-3.3-70b-versatile",          # primary — best quality
    "llama-4-scout-17b-16e-instruct",   # fallback 1 — fast, capable
    "llama-4-maverick-17b-128e-instruct", # fallback 2 — creative, strong on persona
    "qwen-qwq-32b",                     # fallback 3 — strong reasoning
    "llama-3.1-8b-instant",             # fallback 4 — lightweight last resort
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
            if any(x in error_str for x in ["rate limit", "429", "quota", "exceeded", "model"]):
                continue  # try next model
            else:
                raise   # non-rate-limit error, surface it
    raise Exception("All models exhausted.")

# --- MAIN LAYOUT ---
col1, col2 = st.columns([2, 1])

# =======================
# LEFT: CHAT INTERFACE
# =======================
with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

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

        # --- FETCH MEMORY ---
        memory = get_memory(supabase, st.session_state.session_id)

        # --- STYLE SELECTION ---
        STYLE_NAMES = list(STYLES.keys())
        available_styles = [s for s in STYLE_NAMES if s != st.session_state.last_style]
        current_style = random.choice(available_styles)
        st.session_state.last_style = current_style
        style_data = STYLES[current_style]

        # --- BUILD SYSTEM PROMPT ---
        system_prompt = (
            build_system_prompt(BIO_MEMORY, TRAITS, st.session_state.profile, memory)
            + f"""
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

            # --- STORE ASSISTANT REPLY ---
            st.session_state.messages.append({"role": "assistant", "content": reply})

            with st.chat_message("assistant"):
                st.markdown(reply)

            # --- PERIODIC MEMORY UPDATE ---
            if len(st.session_state.messages) % 3 == 0:
    # 1. Narrative summary for conversation_logs
                summary = summarize_conversation(client, st.session_state.messages)
                if summary:
                    save_session_log(
                        supabase,
                        st.session_state.user_name,
                        st.session_state.session_id,
                        summary
                    )
            
                # 2. Structured extraction → user_profiles
                if st.session_state.get("user_name"):
                    extract_and_update_profile(
                        client,
                        supabase,
                        st.session_state.user_name,
                        st.session_state.messages
                    )
            
                    # 3. Reload the dossier so the running session also benefits
                    st.session_state.user_profile_db = get_or_create_profile(
                        supabase,
                        st.session_state.user_name
                    )
                    st.session_state.user_history_db = get_conversation_history(
                        supabase,
                        st.session_state.user_name
                    )
            
                        

        except Exception as e:
            st.error(f"Connection lost: {e}")

# =======================
# RIGHT: PROFILE PANEL
# =======================
with col2:
    st.markdown("### The Dynasty Dossier")

    st.metric("Current Aura", st.session_state.profile["mood"])
    st.metric("Current Objective", st.session_state.profile["goal"])

    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])

    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])

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
        st.rerun()
