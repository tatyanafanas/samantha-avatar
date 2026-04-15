import streamlit as st
from supabase import create_client
from openai import OpenAI # Groq is OpenAI-compatible
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide", page_icon="🍷")

# --- STYLING: Dark, High-End, Dangerous ---
st.markdown("""
    <style>
    .stApp { background-color: #050505; color: #e0e0e0; }
    .stChatMessage { border-radius: 0px; border-left: 3px solid #6b0f0f; background-color: #111; }
    .stButton>button { border-radius: 0px; border: 1px solid #6b0f0f; color: #6b0f0f; background: transparent; width: 100%; }
    .stButton>button:hover { background: #6b0f0f; color: white; }
    [data-testid="stMetricValue"] { color: #6b0f0f; }
    .stProgress > div > div > div > div { background-color: #6b0f0f; }
    </style>
    """, unsafe_allow_html=True)

# --- CONNECTIONS (SWITCHED TO GROQ FOR FREE TIER) ---
@st.cache_resource
def init_connections():
    try:
        # Groq provides a free tier for Llama 3 models
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"] 
        )
        # Supabase setup
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return client, supabase
    except Exception:
        return None, None

client, supabase = init_connections()

# --- THE PERSONALITY ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. Kampala Elite. 
BEHAVIOR: Predatory, elegant, observant. She treats the user as 'prey' to be tested.
If the user is lazy/boring, she is mockingly playful and condescending.
If the user is strategic/competent, she becomes a lethal, sharp professional ally.
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {"competence": 0.4, "amusement": 0.2, "mood": "Observing"}

if "messages" not in st.session_state:
    st.session_state.messages = []

def process_judgment(text):
    # Logic for competence and amusement
    if len(text.split()) < 5:
        st.session_state.profile["amusement"] += 0.1
        st.session_state.profile["competence"] -= 0.05
    if any(k in text.lower() for k in ["strategy", "roi", "execution", "deployment"]):
        st.session_state.profile["competence"] += 0.15
        st.session_state.profile["amusement"] -= 0.1
    
    # Mood Mapping
    comp = st.session_state.profile["competence"]
    amus = st.session_state.profile["amusement"]
    if amus > 0.6: st.session_state.profile["mood"] = "Predatory Play"
    elif comp > 0.7: st.session_state.profile["mood"] = "Lethal Partner"
    else: st.session_state.profile["mood"] = "Evaluating"

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Enter the den..."):
        if not client:
            st.error("Missing GROQ_API_KEY in secrets.")
            st.stop()

        process_judgment(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        full_system_prompt = f"""
        {BIO_MEMORY}
        Mood: {st.session_state.profile['mood']} | Competence: {st.session_state.profile['competence']}
        Rules: Never break character. Be sharp. If amusement is high, be mockingly seductive/predatory. 
        If competence is low, treat them like a toy.
        """

        try:
            with st.spinner("..."):
                # Use Llama 3 70B - it's free on Groq and very smart/sharp
                response = client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.8
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
            st.rerun()
        except Exception as e:
            st.error(f"Groq API Error: {e}")

with col2:
    st.header("The Judgment")
    st.metric("Disposition", st.session_state.profile["mood"])
    st.write("User Utility")
    st.progress(st.session_state.profile["competence"])
    st.write("Her Amusement")
    st.progress(st.session_state.profile["amusement"])
    
    if st.button("Escape (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"competence": 0.4, "amusement": 0.2, "mood": "Evaluating"}
        st.rerun()
