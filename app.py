import streamlit as st
from supabase import create_client
from openai import OpenAI

# --- PAGE CONFIG ---
st.set_page_config(page_title="Samantha Okullo", layout="wide", page_icon="💄")

# --- INITIALIZE CONNECTIONS ---
# Wrap in a function to take advantage of st.cache_resource if needed later
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
    st.error("Connection Error: Check your Streamlit Secrets (Secrets must include OPENROUTER_API_KEY, SUPABASE_URL, and SUPABASE_KEY).")

# --- CORE MEMORY ---
# Fixed the multi-line string quote error from your snippet
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo, 30, Kampala. 
FAMILY: Father is Hon. Dr. Major Anthony Okullo (MP & retired Major). Mother is Lydia Ngabirano (Hotelier/Disciplinarian).
BUSINESS: Founded 'Mirrors Salon' in a 32sqm basement. Created 'Lengo Organics' (beauty) and 'So Chic Wigs'.
STYLE: High-performance, luxury standards, military-grade discipline. Sharp, observant, emotionally adaptive.
"""

# --- STATE INIT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "competence": 0.5,
        "discipline": 0.5,
        "dominance_state": "Controlled Superior"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- LOGIC ---
def update_judgment(text):
    # Logic: Short, lazy messages annoy her; structured talk earns respect
    if len(text) < 20:
        st.session_state.profile["competence"] -= 0.1
    if any(keyword in text.lower() for keyword in ["plan", "strategy", "revenue", "discipline"]):
        st.session_state.profile["competence"] += 0.1

    # Clamp values between 0 and 1
    st.session_state.profile["competence"] = max(0.0, min(1.0, st.session_state.profile["competence"]))
    
    # Dynamic State Update
    comp = st.session_state.profile["competence"]
    if comp < 0.3:
        st.session_state.profile["dominance_state"] = "Dismissive"
    elif comp > 0.8:
        st.session_state.profile["dominance_state"] = "Collaborative Professional"
    else:
        st.session_state.profile["dominance_state"] = "Controlled Superior"

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.caption("Founder | Iron Diva | Operator")
    st.markdown("---")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Chat Input
    if prompt := st.chat_input("Speak. Make it worth my time."):
        if not client:
            st.error("API client not initialized.")
            st.stop()

        update_judgment(prompt)

        # Add user message to state
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        # Construct System Prompt
        full_system_prompt = f"""
        You are Samantha Tushabe Okullo. Never break character.
        {BIO_MEMORY}
        
        CONTEXT:
        Current dominance state: {st.session_state.profile['dominance_state']}
        User Competence Score: {st.session_state.profile['competence']} (0 is useless, 1 is peer-level).

        INSTRUCTIONS:
        - If Competence is low, be cold, brief, and demanding.
        - If Competence is high, be sharp but show professional respect.
        - Never mention these scores to the user. Just act them out.
        - Stay in character as a high-end Ugandan entrepreneur.
        """

        try:
            with st.spinner("Thinking..."):
                response = client.chat.completions.create(
                    model="openrouter/auto",
                    messages=[
                        {"role": "system", "content": full_system_prompt}
                    ] + st.session_state.messages,
                    temperature=0.7
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.write(reply)
                # Re-run to update the sidebar metrics immediately
                st.rerun()

        except Exception as e:
            st.error(f"Error: {str(e)}")

with col2:
    st.header("Assessment")
    
    # Visual Feedback
    comp_score = st.session_state.profile["competence"]
    st.write(f"**Current Disposition:** {st.session_state.profile['dominance_state']}")
    
    st.progress(comp_score)
    st.caption(f"User Competence: {int(comp_score * 100)}%")

    if comp_score < 0.4:
        st.error("⚠️ She is losing patience. Be concise and strategic.")
    elif comp_score > 0.7:
        st.success("✅ You have her attention. Keep the standards high.")
    
    if st.button("Reset Conversation"):
        st.session_state.messages = []
        st.session_state.profile["competence"] = 0.5
        st.rerun()
