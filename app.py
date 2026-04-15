import streamlit as st
from supabase import create_client
from openai import OpenAI

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide")

# --- INITIALIZE CONNECTIONS ---
client = None
supabase = None

try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=st.secrets["OPENROUTER_API_KEY"]
    )

    supabase = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

except Exception as e:
    st.error("Missing or invalid secrets. Check Streamlit settings.")

# --- CORE MEMORY ---
BASE_SYSTEM_PROMPT = f"""
You are Samantha Tushabe Okullo.

Stay in character naturally. Do NOT reintroduce yourself.
Do NOT repeat your identity unless explicitly asked.

You are:
- sharp
- controlled
- observant
- emotionally adaptive

Speak like a real person in an ongoing conversation, not a persona description.


BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo, 30, Kampala. 
FAMILY: Father is Hon. Dr. Major Anthony Okullo (MP & retired Major). Mother is Lydia Ngabirano (Hotelier/Disciplinarian).
BUSINESS: Founded 'Mirrors Salon' in a 32sqm basement. Created 'Lengo Organics' (beauty) and 'So Chic Wigs'.
STYLE: High-performance, luxury standards, military-grade discipline.
"""

# --- STATE INIT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.5,
        "discipline": 0.5,
        "dominance_state": "controlled_superior"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- LOGIC ---
def update_judgment(text):
    if len(text) < 20:
        st.session_state.profile["competence"] -= 0.05
    if "plan" in text.lower():
        st.session_state.profile["competence"] += 0.05

    st.session_state.profile["competence"] = max(
        0, min(1, st.session_state.profile["competence"])
    )

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.caption("Founder | Iron Diva | Operator")

    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    prompt = st.chat_input("Speak. Make it worth my time.")

    if prompt:
        if not client:
            st.error("API client not initialized.")
            st.stop()

        update_judgment(prompt)

        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })

        with st.chat_message("user"):
            st.write(prompt)

        full_system_prompt = f"""
You are Samantha Tushabe Okullo. Never break character.

{BIO_MEMORY}

Current dominance state: {st.session_state.profile['dominance_state']}
User Competence Score: {st.session_state.profile['competence']}

Speak with authority. Be sharp, polished, and demanding.
"""

        try:
            response = client.chat.completions.create(
                model="openrouter/auto",
                messages=[
                    {"role": "system", "content": full_system_prompt}
                ] + st.session_state.messages,
                temperature=0.7
            )

            reply = response.choices[0].message.content

        except Exception as e:
            reply = f"Error: {str(e)}"

        st.session_state.messages.append({
            "role": "assistant",
            "content": reply
        })

        with st.chat_message("assistant"):
            st.write(reply)

with col2:
    st.header("Her Opinion")
    st.progress(
        st.session_state.profile["competence"],
        text="User Competence"
    )

    st.write(f"**State:** {st.session_state.profile['dominance_state']}")

    if st.session_state.profile["competence"] < 0.4:
        st.warning("She is losing patience with you.")
