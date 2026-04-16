import streamlit as st
from openai import OpenAI

# --- CONFIG ---
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")
HF_API_KEY = st.secrets.get("HF_API_KEY", "")

OPENROUTER_MODEL = "openrouter/mistral-7b-instruct:free"
HF_MODEL = "HuggingFaceH4/zephyr-7b-beta:featherless-ai"

# --- CLIENTS ---
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

hf_client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_API_KEY,
)

# --- HF FALLBACK ---
def query_hf(messages):
    try:
        completion = hf_client.chat.completions.create(
            model=HF_MODEL,
            messages=messages,
            temperature=0.7,
        )
        return completion.choices[0].message.content

    except Exception as e:
        return f"[HF ROUTER FAILED] {str(e)}"


# --- MAIN GENERATION ---
def generate_reply(messages):
    try:
        completion = openrouter_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            temperature=0.7,
            timeout=30,
        )
        return completion.choices[0].message.content

    except Exception as e:
        print("⚠️ OpenRouter failed, switching to HF:", e)
        return query_hf(messages)


# --- STREAMLIT UI ---
st.set_page_config(page_title="AI Chat", layout="centered")
st.title("AI Chat")

# --- STATE INIT ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "system",
            "content": "You are a consistent persona. Maintain memory, tone, and continuity across messages.",
        }
    ]

# --- DISPLAY CHAT ---
for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

# --- INPUT ---
user_input = st.chat_input("Type your message...")

if user_input:
    st.session_state.messages.append(
        {"role": "user", "content": user_input}
    )

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply = generate_reply(st.session_state.messages)
            st.write(reply)

    st.session_state.messages.append(
        {"role": "assistant", "content": reply}
    )

    # --- MEMORY TRIM ---
    MAX_MESSAGES = 20
    if len(st.session_state.messages) > MAX_MESSAGES:
        st.session_state.messages = (
            [st.session_state.messages[0]] +
            st.session_state.messages[-(MAX_MESSAGES - 1):]
        )
