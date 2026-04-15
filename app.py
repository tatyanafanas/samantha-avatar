import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide", page_icon="🍷")

# --- CUSTOM CSS: Luxury, Dark, Lethal ---
st.markdown("""
    <style>
    .stApp { background-color: #050505; color: #e0e0e0; }
    .stChatMessage { 
        border-radius: 0px; 
        border-left: 3px solid #6b0f0f; 
        background-color: #111; 
        margin-bottom: 15px;
    }
    .stButton>button { 
        border-radius: 0px; 
        border: 1px solid #6b0f0f; 
        color: #6b0f0f; 
        background: transparent; 
        width: 100%; 
        font-weight: bold;
    }
    .stButton>button:hover { background: #6b0f0f; color: white; }
    [data-testid="stMetricValue"] { color: #6b0f0f; font-family: 'Georgia', serif; }
    .stProgress > div > div > div > div { background-color: #6b0f0f; }
    .stChatInputContainer { border-top: 1px solid #333; }
    </style>
    """, unsafe_allow_html=True)

# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        # Using Groq's free tier for high-speed, intelligent responses
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"] 
        )
        # Supabase for persistence (optional)
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return client, supabase
    except Exception as e:
        st.error(f"Configuration Error: {e}")
        return None, None

client, supabase = init_connections()

# --- THE PREDATORY PERSONA ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. 30. Kampala Elite. 
VIBE: "The Iron Diva." Daughter of a retired Major. She runs 'Mirrors Salon' and 'Lengo Organics'.
PHILOSOPHY: Life is a food chain. She is at the top. 
ATTITUDE: She enjoys "playing with her food." If you are boring, she will mock you with elegant, sharp wit. 
If you are competent, she will test you with high-stakes business logic. 
She never says "I am an AI." She never offers help unless it benefits her bottom line.
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.4,
        "amusement": 0.3, # Tracking how much she enjoys toying with you
        "mood": "Observing"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- BEHAVIORAL LOGIC ---
def analyze_interaction(text):
    # Short/Low-effort messages increase amusement (mockery) and lower competence
    if len(text.split()) < 6:
        st.session_state.profile["amusement"] += 0.15
        st.session_state.profile["competence"] -= 0.05
    else:
        st.session_state.profile["amusement"] -= 0.05
    
    # High-value business keywords earn respect
    keywords = ["margin", "deployment", "scaling", "infrastructure", "equity", "execution"]
    if any(k in text.lower() for k in keywords):
        st.session_state.profile["competence"] += 0.2
        st.session_state.profile["amusement"] = 0.1 # She gets serious
    
    # Update Mood State
    comp = st.session_state.profile["competence"]
    amus = st.session_state.profile["amusement"]
    
    if amus > 0.7:
        st.session_state.profile["mood"] = "Predatory Play"
    elif comp > 0.8:
        st.session_state.profile["mood"] = "Lethal Partner"
    elif comp < 0.2:
        st.session_state.profile["mood"] = "Bored Predator"
    else:
        st.session_state.profile["mood"] = "Evaluating"

    # Clamp values 0-1
    st.session_state.profile["competence"] = max(0.0, min(1.0, st.session_state.profile["competence"]))
    st.session_state.profile["amusement"] = max(0.0, min(1.0, st.session_state.profile["amusement"]))

# --- UI LAYOUT ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.caption("CEO | Operator | Predator")
    st.markdown("---")

    # Display Chat History
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat Input
    if prompt := st.chat_input("Don't bore me, dear."):
        if not client:
            st.error("GROQ_API_KEY missing in secrets.")
            st.stop()

        analyze_interaction(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # Dynamic System Prompt
        full_system_prompt = f"""
        {BIO_MEMORY}
        
        CURRENT DYNAMICS:
        - Your Mood: {st.session_state.profile['mood']}
        - User Competence: {st.session_state.profile['competence']} (1.0 is your peer)
        - Your Amusement: {st.session_state.profile['amusement']} (1.0 means you are mockingly toying with them)
        
        RESPONSE GUIDELINES:
        - If Amusement is high: Be condescendingly playful. Use terms like 'little one' or 'my dear' like a sharp blade.
        - If Competence is low: Dismiss their points. Ask them why they are wasting your Kampala air.
        - If Competence is high: Be sharp, cold, and professional. Discuss logistics and results.
        - Speech should be economic. No long AI explanations.
        """

        try:
            with st.spinner("Samantha is observing..."):
                # Using the latest free Llama 3.3 model on Groq
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.9 # High temp for erratic, witty character acting
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
            
            # Slight delay then rerun to update the sidebar metrics
            time.sleep(0.2)
            st.rerun()

        except Exception as e:
            st.error(f"Connection lost. She's busy. ({e})")

with col2:
    st.markdown("### The Boardroom")
    
    # Metrics
    st.metric("Disposition", st.session_state.profile["mood"])
    
    st.write("**Utility (Competence)**")
    st.progress(st.session_state.profile["competence"])
    
    st.write("**Her Amusement (The 'Toy' Factor)**")
    st.progress(st.session_state.profile["amusement"])
    
    if st.session_state.profile["amusement"] > 0.6:
        st.warning("⚠️ You are currently her entertainment. Try to be serious.")
    
    st.markdown("---")
    if st.button("Escape the Den (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"competence": 0.4, "amusement": 0.3, "mood": "Observing"}
        st.rerun()

    st.info("Pro-tip: Samantha values 'Execution' over 'Ideas'. Mention strategy or revenue to win her respect.")
