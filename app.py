import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random

from persona.samantha import BIO_MEMORY, TRAITS, STYLES
from engine.dynamics import analyze_interaction
from engine.prompt_builder import build_system_prompt
from engine.memory import get_memory, save_memory, summarize_conversation

# --- PAGE CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- LOAD EXTERNAL CSS ---
try:
    with open("config/style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except:
    st.warning("Style file not found.")

# ---------------------------------------------------------------------------
# MODEL ROSTER
# Primary: Llama 3.3 70B on Groq (fast, free tier)
# Fallback: Nous Hermes 4 70B on Nous Portal (better roleplay depth)
# Both use the OpenAI-compatible API format.
# ---------------------------------------------------------------------------

PRIMARY_MODEL   = "llama-3.3-70b-versatile"
FALLBACK_MODEL  = "Hermes-4-70B"   # Nous Portal model slug

# Groq error codes that should trigger a fallback (rate limit, quota)
FALLBACK_CODES  = {429, 503, 529}

# ---------------------------------------------------------------------------
# CONNECTIONS
# ---------------------------------------------------------------------------

@st.cache_resource
def init_connections():
    try:
        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"],
        )
        nous_client = OpenAI(
            base_url="https://inference.nousresearch.com/v1",
            api_key=st.secrets["NOUS_API_KEY"],
        )
        supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"],
        )
        return groq_client, nous_client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None, None


groq_client, nous_client, supabase = init_connections()


# ---------------------------------------------------------------------------
# MODEL CALL WITH AUTO-FALLBACK
# ---------------------------------------------------------------------------

def call_model(messages: list, system_prompt: str) -> tuple[str, str]:
    """
    Try Groq first. On rate-limit / quota errors fall back to Nous Hermes.
    Returns (reply_text, model_used).
    """
    # --- PRIMARY: Groq ---
    if groq_client:
        try:
            resp = groq_client.chat.completions.create(
                model=PRIMARY_MODEL,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                temperature=0.85,
            )
            return resp.choices[0].message.content, "groq"

        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            is_quota = status in FALLBACK_CODES or "rate" in str(e).lower() or "quota" in str(e).lower()

            if not is_quota:
                # Hard error — surface it, don't silently fall back
                raise e

            st.warning("Groq quota reached — switching to Nous Hermes.", icon="⚠️")

    # --- FALLBACK: Nous Hermes ---
    if not nous_client:
        st.error("Both primary and fallback clients unavailable. Add NOUS_API_KEY to secrets.")
        st.stop()

    resp = nous_client.chat.completions.create(
        model=FALLBACK_MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        temperature=0.85,
    )
    return resp.choices[0].message.content, "nous"


# ---------------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------------

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2,
        "irritation": 0.1,
        "mood": "Coronated",
        "goal": "test_intellect",
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

if "active_model" not in st.session_state:
    st.session_state.active_model = "groq"


# ---------------------------------------------------------------------------
# GOAL EVOLUTION
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------

col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I'm allergic to stagnation."):

        if not groq_client and not nous_client:
            st.error("Missing credentials.")
            st.stop()

        # Update state
        st.session_state.profile = analyze_interaction(st.session_state.profile, prompt)
        st.session_state.profile = update_goal(st.session_state.profile)

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Fetch memory
        memory = get_memory(supabase, st.session_state.session_id)

        # Style rotation (no repeats)
        STYLE_NAMES = list(STYLES.keys())
        if "last_style" not in st.session_state:
            st.session_state.last_style = None
        available_styles = [s for s in STYLE_NAMES if s != st.session_state.last_style]
        current_style = random.choice(available_styles)
        st.session_state.last_style = current_style
        style_data = STYLES[current_style]

        # Build prompt
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

        # Call model (with fallback)
        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                reply, model_used = call_model(st.session_state.messages, system_prompt)
                st.session_state.active_model = model_used

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)

            # Periodic memory update — every 4 messages
            if len(st.session_state.messages) % 4 == 0:
                structured = summarize_conversation(
                    groq_client or nous_client,
                    st.session_state.messages,
                )
                if structured:
                    save_memory(supabase, st.session_state.session_id, structured)

            time.sleep(0.1)
            st.rerun()

        except Exception as e:
            st.error(f"Connection lost: {e}")


# ---------------------------------------------------------------------------
# RIGHT PANEL
# ---------------------------------------------------------------------------

with col2:
    st.markdown("### The Dynasty Dossier")

    model_label = "Groq / Llama 3.3" if st.session_state.active_model == "groq" else "Nous Hermes 4"
    st.metric("Engine", model_label)
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
            "goal": "test_intellect",
        }
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.active_model = "groq"
        st.rerun()
