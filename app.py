import streamlit as st
import uuid
import random
import time

from openai import OpenAI

# --- YOUR EXISTING MODULES (critical, do NOT remove) ---
from persona.samantha import BIO_MEMORY, TRAITS, STYLES
from engine.dynamics import analyze_interaction
from engine.prompt_builder import build_system_prompt
from engine.memory import get_memory, save_memory, summarize_conversation

# =========================
# CONFIG
# =========================

OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")
HF_API_KEY = st.secrets.get("HF_API_KEY", "")

OPENROUTER_MODEL = "openrouter/mistral-7b-instruct:free"
HF_MODEL = "HuggingFaceH4/zephyr-7b-beta:featherless-ai"

# =========================
# CLIENTS
# =========================

openrouter = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

hf_client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_API_KEY,
)

# =========================
# SESSION STATE
# =========================

st.set_page_config(page_title="Samantha", layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2,
        "irritation": 0.1,
        "mood": "Observing",
        "goal": "test_intellect"
    }

if "last_style" not in st.session_state:
    st.session_state.last_style = None

# =========================
# GOAL LOGIC (restored)
# =========================

def update_goal(profile):
    if profile["submission"] > 0.7:
        profile["goal"] = "break_user"
    elif profile["irritation"] > 0.6:
        profile["goal"] = "extract_value"
    else:
        profile["goal"] = "test_intellect"
    return profile

# =========================
# HF FALLBACK
# =========================

def query_hf(messages):
    try:
        return hf_client.chat.completions.create(
            model=HF_MODEL,
            messages=messages,
            temperature=0.8,
        ).choices[0].message.content
    except Exception as e:
        return f"[HF FAILED] {str(e)}"

# =========================
# MAIN MODEL ROUTER
# =========================

def generate_reply(messages, system_prompt):

    payload = [{"role": "system", "content": system_prompt}] + messages

    # 1. OpenRouter primary
    try:
        return openrouter.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=payload,
            temperature=0.85,
        ).choices[0].message.content

    except Exception as e:
        print("OpenRouter failed → HF fallback:", e)
        return query_hf(payload)

# =========================
# UI
# =========================

col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Speak.")

    if prompt:

        # --- update dynamics ---
        st.session_state.profile = analyze_interaction(
            st.session_state.profile,
            prompt
        )
        st.session_state.profile = update_goal(st.session_state.profile)

        # --- store message ---
        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })

        # --- memory ---
        memory = get_memory(st.session_state.session_id)

        # --- style ---
        styles = list(STYLES.keys())
        available = [s for s in styles if s != st.session_state.last_style]
        current_style = random.choice(available)
        st.session_state.last_style = current_style
        style_data = STYLES[current_style]

        # --- system prompt (THIS is Samantha) ---
        system_prompt = build_system_prompt(
            BIO_MEMORY,
            TRAITS,
            st.session_state.profile,
            memory
        ) + f"""

STYLE: {current_style}
STYLE RULES:
{chr(10).join(style_data['rules'])}

OBJECTIVE: {st.session_state.profile['goal']}
"""

        # --- generate ---
        with st.spinner("Samantha is evaluating you..."):
            reply = generate_reply(
                st.session_state.messages,
                system_prompt
            )

        st.session_state.messages.append({
            "role": "assistant",
            "content": reply
        })

        # --- memory write ---
        if len(st.session_state.messages) % 3 == 0:
            summary = summarize_conversation(
                openrouter,
                st.session_state.messages
            )
            if summary:
                save_memory(
                    st.session_state.session_id,
                    summary
                )

        st.rerun()

with col2:
    st.markdown("### Dynasty Profile")

    st.metric("Mood", st.session_state.profile["mood"])
    st.metric("Goal", st.session_state.profile["goal"])
    st.progress(st.session_state.profile["irritation"])
