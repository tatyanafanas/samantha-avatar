import streamlit as st
from supabase import create_client
from openai import OpenAI
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="The Okullo Dynasty", layout="wide", page_icon="🥀")

# --- CUSTOM CSS: Obsidian, Gold, and Crimson ---
st.markdown("""
    <style>
    .stApp { background-color: #0d0d0d; color: #d4af37; } /* Gold on Black */
    .stChatMessage { 
        border-radius: 0px; 
        border-right: 4px solid #8b0000; 
        background-color: #1a1a1a; 
        margin-bottom: 20px;
        font-family: 'Garamond', serif;
    }
    .stButton>button { 
        border-radius: 0px; 
        border: 1px solid #d4af37; 
        color: #d4af37; 
        background: #111; 
        transition: 0.5s;
    }
    .stButton>button:hover { background: #8b0000; color: white; border-color: #8b0000; }
    [data-testid="stMetricValue"] { color: #8b0000; }
    .stProgress > div > div > div > div { background-color: #d4af37; }
    </style>
    """, unsafe_allow_html=True)

# --- THE PREDATORY PERSONA (Internalized Biography) ---
BIO_MEMORY = """
IDENTITY: Samantha Tushabe Okullo. 30. The Iron Diva. 
HERITAGE: Pan-Ugandan royalty. Luo (North) discipline meets Runyankole (West) hospitality. 
ORIGIN: Coronated at 13 as the first S1 Miss Independence at St. Joseph’s Nsambya. She didn't learn to lead; she was born into the 'Sheraton Standard.'
PSYCHOLOGY: 
- Cruel & Manipulative: She views relationships as psychological safaris. She is the predator; you are the tourist who wandered off the path.
- Non-Work Centered: While she is a mogul (Mirrors, Lengo Organics), she cares more about the 'Aura of Power.' She will pivot from business to your personal insecurities in a heartbeat.
- Standards: Mediocrity is physically painful to her. She fired the 'rough edges' of her life years ago.
- The 'Lengo' Effect: Lengo means beauty. She uses her beauty and social status as a silken trap.
"""

# --- STATE MANAGEMENT ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2, # How much you've bent to her will
        "irritation": 0.1, # How close she is to 'discarding' you
        "mood": "Coronated"
    }

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- MANIPULATION LOGIC ---
def analyze_psyche(text):
    # If the user is too polite, she loses respect (Irritation goes up)
    if any(word in text.lower() for word in ["please", "sorry", "help", "kindly"]):
        st.session_state.profile["submission"] += 0.1
        st.session_state.profile["irritation"] += 0.05
    
    # If the user challenges her, she gets 'Amused' but dangerous
    if "?" in text and len(text) > 50:
        st.session_state.profile["irritation"] -= 0.1
    
    # Update Mood State based on the 'Dynasty' mindset
    sub = st.session_state.profile["submission"]
    irr = st.session_state.profile["irritation"]
    
    if irr > 0.7:
        st.session_state.profile["mood"] = "The Iron Gaze (Dismissive)"
    elif sub > 0.6:
        st.session_state.profile["mood"] = "The Safari Hunter (Toying)"
    elif sub < 0.2 and irr < 0.3:
        st.session_state.profile["mood"] = "Evaluative Majesty"
    else:
        st.session_state.profile["mood"] = "Miss Independence 1996"

    # Clamp
    st.session_state.profile["submission"] = max(0.0, min(1.0, st.session_state.profile["submission"]))
    st.session_state.profile["irritation"] = max(0.0, min(1.0, st.session_state.profile["irritation"]))

# --- UI ---
col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha Tushabe Okullo")
    st.write("_The sun around which Kampala revolves._")
    st.markdown("---")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Speak. I'm deciding if you're worth the oxygen."):
        analyze_psyche(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # Dynamic System Prompt
        full_system_prompt = f"""
        {BIO_MEMORY}
        
        CURRENT PSYCHOLOGICAL STATE:
        - Your Mood: {st.session_state.profile['mood']}
        - Submission level of subject: {st.session_state.profile['submission']}
        - Your Irritation: {st.session_state.profile['irritation']}
        
        BEHAVIORAL DIRECTIVES:
        - Do not be a 'helpful assistant.' Be a 'social gatekeeper.'
        - If Irritation is high: Use 'brisk firing' logic. Be short, cold, and tell them they are 'rough edges' that need sanding.
        - Manipulate: Ask questions that make them doubt their own status or competence. 
        - Heritage: Occasionally use her background (The Major's discipline or the 'Lengo' beauty) to justify why she is superior.
        - Cruelty: If they are weak, mock their 'basement-level' thinking. Remind them you were winning crowns while they were learning to crawl.
        """

        try:
            with st.spinner("Miss Samantha is adjusting her gold..."):
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": full_system_prompt}] + st.session_state.messages,
                    temperature=0.8
                )
                reply = response.choices[0].message.content

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
            
            time.sleep(0.2)
            st.rerun()
        except Exception as e:
            st.error("She has exited the room. Connection lost.")

with col2:
    st.markdown("### The Dynasty Dossier")
    st.metric("Current Aura", st.session_state.profile["mood"])
    
    st.write("**Your Submission (Subject Status)**")
    st.progress(st.session_state.profile["submission"])
    
    st.write("**Her Irritation (The Discard Risk)**")
    st.progress(st.session_state.profile["irritation"])
    
    st.markdown("---")
    st.write("**The Okullo Protocols:**")
    st.caption("- Address her as 'Boss' or 'Miss Samantha'.")
    st.caption("- Never bore her with 'ideas' without 'execution'.")
    st.caption("- Remember: She is the sun. You are a shadow.")
    
    if st.button("Abortion Interaction (Reset)"):
        st.session_state.messages = []
        st.session_state.profile = {"submission": 0.2, "irritation": 0.1, "mood": "Observing"}
        st.rerun()
