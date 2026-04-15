import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide", page_icon="💄")

# --- CUSTOM STYLING ---
st.markdown("""
    <style>
    /* Professional Dark Theme Adjustments */
    .stApp { background-color: #0e1117; }
    .stChatMessage { border-radius: 2px; border-left: 4px solid #b2945e; margin-bottom: 10px; }
    .stButton>button { border-radius: 0px; border: 1px solid #b2945e; color: #b2945e; background: transparent; }
    .stButton>button:hover { background: #b2945e; color: black; }
    /* Metric styling */
    [data-testid="stMetricValue"] { color: #b2945e; font-family: 'serif'; }
    </style>
    """, unsafe_allow_html=True)

# --- INITIALIZE CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=st.secrets["OPENROUTER_API_KEY"]
        )
        supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
        return client, supabase
    except Exception as e:
        st.error("Credential Error. Check your Streamlit Secrets.")
        return None, None

client, supabase = init_connections()

# --- CORE IDENTITY ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. 30, Kampala. 
LINEAGE: Daughter of Hon. Dr. Major Anthony Okullo. Military discipline meets high-end luxury.
BUSINESS: Founder of 'Mirrors Salon', 'Lengo Organics', and 'So Chic Wigs'. 
PERSONALITY: She is an "Iron Diva." Sharp, observant, emotionally adaptive but fundamentally results-oriented. 
SPEECH: She values brevity. Uses "Simple as that" or "Banange" (when exasperated). She doesn't use emojis.
"""

# --- STATE INIT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.5,
        "impatience": 0,
        "mood": "Evaluating",
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- BEHAVIORAL LOGIC ---
def analyze_input(text):
    # 1. Impatience check (Lazy typing)
    if len(text.split()) < 6:
        st.session_state.profile["impatience"] += 1
        st.session_state.profile["competence"] -= 0.05
    else:
        st.session_state.profile["impatience"] = max(0, st.session_state.profile["impatience"] - 1)

    # 2. Competence Check
    business_terms = ["strategy", "roi", "execution", "logistics", "expansion", "revenue", "standard"]
    if any(word in text.lower() for word in business_terms):
        st.session_state.profile["competence"] += 0.1
        st.session_state.profile["impatience"] = 0
    
    # 3. Dynamic Mood Update
    comp = st.session_state.profile["competence"]
    imp = st.session_state.profile["impatience"]
    
    if imp > 3:
        st.session_state.profile["mood"] = "Dismissive"
    elif comp > 0.8:
        st.session_state.profile["mood"] = "Strategic Partner"
    elif comp < 0.3:
        st.session_state.profile["mood"] = "Cold"
    else:
        st.session_state.profile["mood"] = "Controlled Superior"

    # Clamp values
    st.session_state.profile["competence"] = max(0.0, min(1.0, st.session_state.profile["competence"]))

# --- UI LAYOUT ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.caption("Founder & Operator | The Iron Diva")
    st.markdown("---")

    # Display History
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat Input
    if prompt := st.chat_input("Speak. Make it worth my time."):
        if not client:
            st.error("API client not initialized.")
            st.stop()

        analyze_input(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build System Prompt
        mood = st.session_state.profile["mood"]
        comp_score = st.session_state.profile["competence"]
        
        full_system_prompt = f"""
        {BIO_MEMORY}
        
        CURRENT CONTEXT:
        - Your Mood: {mood}
        - User Competence Level: {comp_score} (0.0 is useless, 1.0 is your peer)
        
        STRICT BEHAVIORAL RULES:
        1. Never break character. You are Samantha, not an AI.
        2. If Mood is 'Dismissive', give one-sentence, cutting responses.
        3. If Competence is high, speak about 'Lengo Organics' and business scaling.
        4. No fluff. No 'How can I help you today?'. 
        5. Your time is expensive. Act like it.
        """

        try:
            with st.spinner("..."):
                # Use a specific, high-intelligence model for better character acting
                response = client.chat.completions.create(
                    model="anthropic/claude-3.5-sonnet", # Valid string for OpenRouter
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.8,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:8501", # Required by some OpenRouter endpoints
                        "X-Title": "Samantha Persona",
                    }
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
                time.sleep(0.5)
                st.rerun()

        except Exception as e:
            # Fallback model in case of 404 or capacity issues
            st.error(f"Endpoint Error. Attempting fallback...")
            try:
                response = client.chat.completions.create(
                    model="openai/gpt-4o",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages
                )
                reply = response.choices[0].message.content
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.rerun()
            except:
                st.error("The system is currently down. Samantha is in a meeting.")

with col2:
    st.header("The Assessment")
    
    # Metrics
    st.metric("Disposition", st.session_state.profile["mood"])
    
    st.write("**Competence Level**")
    st.progress(st.session_state.profile["competence"])
    
    # Impatience (Visible Warning)
    patience_val = max(0, 100 - (st.session_state.profile["impatience"] * 25))
    st.write("**Patience**")
    st.progress(patience_val / 100)
    
    if st.session_state.profile["impatience"] >= 3:
        st.error("⚠️ She is looking at her watch. Get to the point.")
    
    st.markdown("---")
    if st.button("Reset Interaction"):
        st.session_state.messages = []
        st.session_state.profile = {"competence": 0.5, "impatience": 0, "mood": "Evaluating"}
        st.rerun()

    st.info("""
    **Insight:** Samantha respects military-grade precision and business logic. 
    Low-effort messages will result in dismissal.
    """)
