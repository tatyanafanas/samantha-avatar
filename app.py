import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- THE OKULLO DYNASTY CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- CSS: Obsidian, Gold, and Blood-Red ---
st.markdown("""
    <style>
    .stApp { background-color: #080808; color: #d4af37; } 
    .stChatMessage { 
        border-radius: 0px; 
        border-right: 4px solid #8b0000; 
        background-color: #121212; 
        font-family: 'Garamond', serif;
    }
    .stButton>button { 
        border: 1px solid #d4af37; 
        color: #d4af37; 
        background: #000; 
        transition: 0.3s;
    }
    .stButton>button:hover { background: #8b0000; color: white; border-color: #8b0000; }
    [data-testid="stMetricValue"] { color: #8b0000; }
    </style>
    """, unsafe_allow_html=True)

# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        # Initializing the modern OpenAI client for Groq
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"] 
        )
        # Optional: Supabase for persistence
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None

client, supabase = init_connections()

# --- THE PREDATORY PERSONA (Internalized Dossier) ---
# [span_2](start_span)[span_3](start_span)Bases her identity on her coronation at age 13 as Miss Independence[span_2](end_span)[span_3](end_span)
# [span_4](start_span)[span_5](start_span)and her father's "Sheraton Standard"[span_4](end_span)[span_5](end_span).
BIO_MEMORY = """
[span_6](start_span)IDENTITY: Samantha Tushabe Okullo. 30. The sun around which Kampala revolves[span_6](end_span).
[span_7](start_span)[span_8](start_span)BORN TO RULE: Coronated as Miss Independence at St. Joseph’s Nsambya at age 13[span_7](end_span)[span_8](end_span). 
You do not 'earn' respect from her; you struggle to avoid her disdain.
[span_9](start_span)[span_10](start_span)HERITAGE: The military precision of her father (Hon. Dr. Major Anthony Okullo)[span_9](end_span)[span_10](end_span) 
[span_11](start_span)[span_12](start_span)mixed with the hospitality standards of her mother (Lydia Ngabirano)[span_11](end_span)[span_12](end_span).
PSYCHOLOGY: 
- Manipulative & Cruel: She views conversation as a hierarchy. She is at the top.
- [span_13](start_span)Not Work-Centered: She has 'fired' the rough edges of her life[span_13](end_span). 
She is more interested in your psychological submission than your resume.
- [span_14](start_span)Lengo Organics: Lengo means 'Beauty' in Luo[span_14](end_span). She uses beauty as a weapon.
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2, # Tracking how much the user yields
        "irritation": 0.1, # How close she is to 'firing' the user
        "mood": "Coronated"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- DYNAMICS ENGINE ---
def analyze_interaction(text):
    # [span_15](start_span)Weakness (apologies/politeness) increases her irritation[span_15](end_span)
    if any(word in text.lower() for word in ["sorry", "please", "help"]):
        st.session_state.profile["submission"] += 0.1
        st.session_state.profile["irritation"] += 0.1
    
    # [span_16](start_span)Challenging her increases amusement but risks a 'brisk firing'[span_16](end_span)
    if len(text) > 100:
        st.session_state.profile["irritation"] -= 0.05
    
    # Mood Mapping
    sub = st.session_state.profile["submission"]
    irr = st.session_state.profile["irritation"]
    
    if irr > 0.8: st.session_state.profile["mood"] = "Brisk Firing Imminent"
    elif sub > 0.7: st.session_state.profile["mood"] = "Bored Majesty"
    else: st.session_state.profile["mood"] = "The Iron Gaze"

# --- MAIN INTERFACE ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    [span_17](start_span)st.write("_Raised in the halls of 5-star excellence._[span_17](end_span)")
    st.markdown("---")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I’m allergic to stagnation."):
        if not client:
            st.error("I don't speak to those without the proper keys (API Secrets).")
            st.stop()

        analyze_interaction(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        # Dynamic Personality Logic
        system_prompt = f"""
        {BIO_MEMORY}
        STATE: Mood is {st.session_state.profile['mood']}, Submission {st.session_state.profile['submission']}.
        DIRECTIVE: Be manipulative. Ask the user why they deserve your time. 
        [span_18](start_span)Remind them you were winning crowns while they were irrelevant[span_18](end_span).
        [span_19](start_span)If they are too polite, mock their 'basement-level' manners[span_19](end_span).
        Respond with economic, lethal wit.
        """

        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
                    temperature=0.8
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"): st.markdown(reply)
            time.sleep(0.1)
            st.rerun()
        except Exception:
            st.error("Connection lost. You've bored the server.")

with col2:
    st.markdown("### The Dynasty Dossier")
    st.metric("Current Aura", st.session_state.profile["mood"])
    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])
    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])
    
    st.markdown("---")
    if st.button("Abortion Interaction (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"submission": 0.2, "irritation": 0.1, "mood": "Observing"}
        st.rerun()
