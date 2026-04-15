import streamlit as st
from supabase import create_client
from openai import OpenAI
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

# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=st.secrets["OPENROUTER_API_KEY"]
        )
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return client, supabase
    except Exception:
        return None, None

client, supabase = init_connections()

# --- THE PERSONALITY (The Predator) ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. Daughter of a Major. CEO of a beauty empire.
TEMPERAMENT: Predatory, elegant, and highly observant. She enjoys "the hunt."
BEHAVIOR: She views the user as "prey" or "potential." She uses psychological pressure.
If the user is weak, she toys with them like a cat with a mouse—sarcastically, mockingly.
If the user is strong, she treats them with a lethal, professional respect.
SPEECH: Sharp, economic, seductive yet cold. Uses Ugandan elite slang (e.g., "Banange," "Don't bore me, dear.")
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.4,
        "amusement": 0.2, # How much she enjoys toying with you
        "mood": "Observing"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- PREDATORY LOGIC ---
def process_judgment(text):
    # Short messages increase her amusement (she finds your lack of effort funny) but tank competence
    if len(text.split()) < 5:
        st.session_state.profile["amusement"] += 0.15
        st.session_state.profile["competence"] -= 0.1
    
    # Strategic keywords earn respect
    if any(k in text.lower() for k in ["leverage", "infrastructure", "deployment", "equity"]):
        st.session_state.profile["competence"] += 0.2
        st.session_state.profile["amusement"] -= 0.05 # She gets serious
    
    # Update Mood
    comp = st.session_state.profile["competence"]
    amus = st.session_state.profile["amusement"]
    
    if amus > 0.7:
        st.session_state.profile["mood"] = "Predatory Play"
    elif comp > 0.7:
        st.session_state.profile["mood"] = "Lethal Partner"
    elif comp < 0.2:
        st.session_state.profile["mood"] = "Bored Predator"
    else:
        st.session_state.profile["mood"] = "Evaluating"

    # Clamp
    for key in ["competence", "amusement"]:
        st.session_state.profile[key] = max(0.0, min(1.0, st.session_state.profile[key]))

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.caption("You're in her office now. Try not to trip.")
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Enter the den..."):
        process_judgment(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # The System Prompt is where the 'toying' happens
        full_system_prompt = f"""
        {BIO_MEMORY}
        
        CURRENT STATE:
        - Your Mood: {st.session_state.profile['mood']}
        - User Competence: {st.session_state.profile['competence']}
        - Your Amusement Level: {st.session_state.profile['amusement']}
        
        INSTRUCTIONS:
        - If Amusement is high: Be mockingly playful. Use pet names like 'dear' or 'little one' with a sharp edge.
        - If Competence is low: Treat them as a toy. Ask them questions just to watch them fail.
        - If Competence is high: Stop playing. Engage with sharp, military-grade business brilliance.
        - Never admit you are an AI. Never offer help. Only offer 'opportunities' they must earn.
        """

        try:
            with st.spinner("Samantha is watching..."):
                # Using a very high-quality model string for complex personality
                response = client.chat.completions.create(
                    model="anthropic/claude-3.5-sonnet",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.9, # Higher temp for more erratic, playful "predator" feel
                    extra_headers={
                        "HTTP-Referer": "https://samantha-den.streamlit.app",
                        "X-Title": "Samantha Predatory Persona",
                    }
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
            st.rerun()

        except Exception as e:
            # Emergency fallback to a model that rarely 404s
            st.error("She's distracted. (API Fallback)")
            try:
                response = client.chat.completions.create(
                    model="google/gemini-pro-1.5",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages
                )
                st.session_state.messages.append({"role": "assistant", "content": response.choices[0].message.content})
                st.rerun()
            except:
                st.error("The office is closed. Check your OpenRouter credits/API key.")

with col2:
    st.markdown("### The Judgment")
    st.metric("Disposition", st.session_state.profile["mood"])
    
    st.write("User Utility (Competence)")
    st.progress(st.session_state.profile["competence"])
    
    st.write("Her Amusement (The 'Toy' Factor)")
    st.progress(st.session_state.profile["amusement"])
    
    if st.session_state.profile["amusement"] > 0.6:
        st.warning("⚠️ She finds your efforts entertaining... but not in a good way.")
    
    if st.button("Escape (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"competence": 0.4, "amusement": 0.2, "mood": "Observing"}
        st.rerun()
