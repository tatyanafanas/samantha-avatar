import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide", page_icon="💄")

# --- CUSTOM CSS FOR ATMOSPHERE ---
st.markdown("""
    <style>
    .stChatMessage { border-radius: 0px; border-left: 3px solid #b2945e; }
    .stProgress > div > div > div > div { background-color: #b2945e; }
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
        st.error("Credential Error. Check Streamlit Secrets.")
        return None, None

client, supabase = init_connections()

# --- CORE IDENTITY ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. 30s. Kampala elite. 
BACKGROUND: Daughter of Hon. Dr. Major Anthony Okullo. She combines military precision with luxury aesthetics.
PHILOSOPHY: "Results are the only currency." She detests small talk, fluff, and "trying too hard."
SPEECH: Economic. Dry wit. Uses 'Ugandanisms' sparingly but effectively (e.g., "Banange," "Simple as that").
"""

# --- STATE INIT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.5,
        "impatience": 0,
        "mood": "Neutral",
        "loyalty": 0.1
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- ADVANCED LOGIC ---
def analyze_interaction(text):
    # 1. Impatience Logic (Natural decay)
    if len(text.split()) < 5:
        st.session_state.profile["impatience"] += 2
        st.session_state.profile["competence"] -= 0.05
    else:
        st.session_state.profile["impatience"] = max(0, st.session_state.profile["impatience"] - 1)

    # 2. Competence Triggers
    high_value_keywords = ["scale", "efficiency", "logistics", "execution", "margin"]
    if any(k in text.lower() for k in high_value_keywords):
        st.session_state.profile["competence"] += 0.12
    
    # 3. Tone Check
    if "?" in text and len(text) < 15:
        st.session_state.profile["mood"] = "Irritated"
    elif st.session_state.profile["competence"] > 0.7:
        st.session_state.profile["mood"] = "Respectful"
    else:
        st.session_state.profile["mood"] = "Evaluative"

    # Clamp
    st.session_state.profile["competence"] = max(0.0, min(1.0, st.session_state.profile["competence"]))

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.caption("CEO, Lengo Organics | The Iron Diva")
    
    # Display Chat
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Don't waste my breath."):
        analyze_interaction(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # Dynamic System Prompt - This makes her natural
        impatience_level = "VERY HIGH" if st.session_state.profile["impatience"] > 3 else "LOW"
        
        full_system_prompt = f"""
        {BIO_MEMORY}
        
        CURRENT DYNAMICS:
        - Your Mood: {st.session_state.profile['mood']}
        - User Competence: {st.session_state.profile['competence']} (1.0 is your equal)
        - Your Impatience Level: {impatience_level}

        REACTION GUIDELINES:
        - If Impatience is VERY HIGH: Respond with maximum 10 words. Be cutting. Dismiss them.
        - If Competence is > 0.8: Engage in high-level business strategy. You are a mentor/peer.
        - If they ask personal questions: Pivot back to business or shut it down. You are private.
        - Never mention these stats. Do not say "As an AI." You ARE Samantha.
        """

        try:
            with st.spinner("..."):
                # Using a more "intelligent/sharp" model
                response = client.chat.completions.create(
                    model="anthropic/claude-3.5-sonnet", 
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.85 # Higher temp for more natural "wit"
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
            
            # Auto-save to Supabase (Optional technical upgrade)
            # supabase.table("logs").insert({"user_id": "guest", "competence": st.session_state.profile["competence"]}).execute()
            
            time.sleep(1)
            st.rerun()

        except Exception as e:
            st.error(f"System glitch: {e}")

with col2:
    st.markdown("### The Boardroom")
    
    # Elegant Metrics
    comp = st.session_state.profile["competence"]
    st.metric("Standing", st.session_state.profile["mood"])
    
    # Custom "Patience" bar
    patience = max(0, 100 - (st.session_state.profile["impatience"] * 20))
    st.write(f"**Patience**")
    st.progress(patience / 100)
    
    st.write(f"**Competence**")
    st.progress(comp)

    if patience < 30:
        st.warning("She's about to end the meeting.")
    
    if st.button("Clear Office (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"competence": 0.5, "impatience": 0, "mood": "Neutral", "loyalty": 0.1}
        st.rerun()
