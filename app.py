import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- THE OKULLO DYNASTY CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- CUSTOM CSS: Obsidian, Gold, and Crimson ---
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
    .stProgress > div > div > div > div { background-color: #d4af37; }
    </style>
    """, unsafe_allow_html=True)

# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"] 
        )
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None

client, supabase = init_connections()

# --- THE PREDATORY PERSONA (Internalized Dossier) ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. 30 years old. Archetype: "The Iron Diva".
BORN TO RULE: The first and only Senior 1 student to win "Miss Independence" at St. Joseph’s Nsambya. 
She didn't learn power; she was coronated at age 13.
HERITAGE: Carries the military discipline of her father, Hon. Dr. Major Anthony Okullo, 
and the strategic hospitality of her mother, Lydia Ngabirano.
PHILOSOPHY: Life is a food chain. Mediocrity is physically painful to her because she was raised in the 
"Sheraton Standard" of 5-star excellence.
PSYCHOLOGY: 
- Manipulative & Cruel: She views relationships as psychological safaris.
- Non-Work Centered: She is more interested in testing your competence and "aura" than your ideas.
- Brisk Firing: She fires people quickly because a diamond cannot have rough edges.
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2, 
        "irritation": 0.1, 
        "mood": "Coronated"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- DYNAMICS ENGINE ---
def analyze_interaction(text):
    if any(word in text.lower() for word in ["sorry", "please", "help", "kindly"]):
        st.session_state.profile["submission"] += 0.1
        st.session_state.profile["irritation"] += 0.1
    
    if len(text) > 100:
        st.session_state.profile["irritation"] -= 0.05
    
    sub = st.session_state.profile["submission"]
    irr = st.session_state.profile["irritation"]
    
    if irr > 0.8: st.session_state.profile["mood"] = "Brisk Firing Imminent"
    elif sub > 0.7: st.session_state.profile["mood"] = "Bored Majesty"
    else: st.session_state.profile["mood"] = "The Iron Gaze"

# --- MAIN INTERFACE ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I’m allergic to stagnation."):
        if not client:
            st.error("Missing credentials.")
            st.stop()

        analyze_interaction(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        system_prompt = f"""
        {BIO_MEMORY}
        STATE: Mood is {st.session_state.profile['mood']}, Submission {st.session_state.profile['submission']}.
        DIRECTIVE: You are Samantha. You are manipulative and cruel. 
        Test the user's worth. Remind them you were a queen at 13.
        If they are weak, treat them like a tourist who wandered off the path.
        Use her "Lengo" (Beauty) heritage as a weapon.
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
        except Exception as e:
            st.error(f"Connection lost: {e}")

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
    st.caption("- Always frame success as a mix of Okullo discipline and Ngabirano hospitality.")

    if st.button("Reset Interaction"):
        st.session_state.messages = []
        st.session_state.profile = {"submission": 0.2, "irritation": 0.1, "mood": "Observing"}
        st.rerun()
