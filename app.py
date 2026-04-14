import streamlit as st
from supabase import create_client
from openai import OpenAI

# --- INITIALIZE CONNECTIONS ---
# These will be pulled from "Secrets" later
try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=st.secrets["OPENROUTER_API_KEY"]
    )
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error("Setup not complete. Please add your API keys in the Streamlit Dashboard.")

# --- SAMANTHA'S CORE KNOWLEDGE (From your Dossier) ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo, 30, Kampala. 
FAMILY: Father is Hon. Dr. Major Anthony Okullo (MP & retired Major). Mother is Lydia Ngabirano (Hotelier/Disciplinarian).
BUSINESS: Founded 'Mirrors Salon' in a 32sqm basement. Created 'Lengo Organics' (beauty) and 'So Chic Wigs'.
STYLE: High-performance, luxury standards, military-grade discipline. 
"""

# --- LOGIC: MEMORY & JUDGMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {"competence": 0.5, "discipline": 0.5, "dominance_state": "controlled_superior"}

def update_judgment(text):
    # Simple logic: vague or lazy words drop scores
    if len(text) < 20: st.session_state.profile["competence"] -= 0.05
    if "plan" in text.lower(): st.session_state.profile["competence"] += 0.05
    # Clamp scores between 0 and 1
    st.session_state.profile["competence"] = max(0, min(1, st.session_state.profile["competence"]))

# --- UI LAYOUT ---
st.set_page_config(page_title="Samantha Okullo", layout="wide")
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.caption("Founder | Iron Diva | Operator")
    
    # Chat History
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input("Speak. Make it worth my time."):
        update_judgment(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.write(prompt)

        # Build the final prompt for the AI
        full_system_prompt = f"""
        You are Samantha Tushabe Okullo. Never break character.
        {BIO_MEMORY}
        Current dominance state: {st.session_state.profile['dominance_state']}
        User Competence Score: {st.session_state.profile['competence']}
        Speak with authority. Be sharp, polished, and demanding.
        """

        response = client.chat.completions.create(
            model="openrouter/auto", # Or your preferred model
            messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages
        )
        
        reply = response.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"): st.write(reply)

with col2:
    st.header("Her Opinion")
    st.progress(st.session_state.profile["competence"], text="User Competence")
    st.write(f"**State:** {st.session_state.profile['dominance_state']}")
    if st.session_state.profile["competence"] < 0.4:
        st.warning("She is losing patience with you.")
