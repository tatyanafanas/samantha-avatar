import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- IMPORT MODULAR COMPONENTS ---
from persona.samantha import BIO_MEMORY, TRAITS
from engine.dynamics import analyze_interaction
from engine.prompt_builder import build_system_prompt

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

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2,
        "irritation": 0.1,
        "mood": "Coronated"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- MAIN LAYOUT ---
col1, col2 = st.columns([2, 1])

# =======================
# LEFT: CHAT INTERFACE
# =======================
with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # User input
    if prompt := st.chat_input("Speak. I’m allergic to stagnation."):

        if not client:
            st.error("Missing credentials.")
            st.stop()

        # --- UPDATE STATE ---
        st.session_state.profile = analyze_interaction(
            st.session_state.profile,
            prompt
        )

        # Store user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        # --- BUILD SYSTEM PROMPT (MODULAR) ---
        system_prompt = build_system_prompt(
            BIO_MEMORY,
            TRAITS,
            st.session_state.profile
        )

        # --- MODEL CALL ---
        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": system_prompt}
                    ] + st.session_state.messages,
                    temperature=0.8
                )

                reply = response.choices[0].message.content

            # Store assistant reply
            st.session_state.messages.append({
                "role": "assistant",
                "content": reply
            })

            with st.chat_message("assistant"):
                st.markdown(reply)

            time.sleep(0.1)
            st.rerun()

        except Exception as e:
            st.error(f"Connection lost: {e}")

# =======================
# RIGHT: PROFILE PANEL
# =======================
with col2:
    st.markdown("### The Dynasty Dossier")

    st.metric("Current Aura", st.session_state.profile["mood"])

    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])

    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])

    st.markdown("---")

    st.write("**Interaction Protocol:**")
    st.caption("- Address her as 'Miss Samantha' or 'Boss'.")
    st.caption("- Frame success as discipline + hospitality.")

    # --- RESET BUTTON ---
    if st.button("Reset Interaction"):
        st.session_state.messages = []
        st.session_state.profile = {
            "submission": 0.2,
            "irritation": 0.1,
            "mood": "Observing"
        }
        st.rerun()
