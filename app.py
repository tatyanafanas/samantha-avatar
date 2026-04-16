import streamlit as st
import requests
from openai import OpenAI

# --- CONFIG ---
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")
HF_API_KEY = st.secrets.get("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", "")

OPENROUTER_MODEL = "openrouter/mistral-7b-instruct:free"
HF_MODEL = "HuggingFaceH4/zephyr-7b-beta"

# --- OPENROUTER CLIENT ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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",
)

# --- HUGGING FACE FALLBACK ---
def query_hf(messages):
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }

    # Convert chat → prompt (Zephyr expects plain text)
    prompt = ""
    for m in messages:
        role = m["role"]
        content = m["content"]

        if role == "system":
            prompt += f"[SYSTEM]\n{content}\n"
        elif role == "user":
            prompt += f"[USER]\n{content}\n"
        elif role == "assistant":
            prompt += f"[ASSISTANT]\n{content}\n"

    response = requests.post(
        f"https://api-inference.huggingface.co/models/{HF_MODEL}",
        headers=headers,
        json={
            "inputs": prompt,
            "parameters": {
                "temperature": 0.7,
                "max_new_tokens": 300,
                "return_full_text": False,
            },
        },
        timeout=60,
    )

    if response.status_code != 200:
        return f"[HF ERROR {response.status_code}] {response.text}"

    data = response.json()

    if isinstance(data, list) and "generated_text" in data[0]:
        return data[0]["generated_text"]

    return str(data)


# --- MAIN GENERATION ---
def generate_reply(messages):
    try:
        completion = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            temperature=0.7,
        )

        return completion.choices[0].message.content

    except Exception as e:
        print("⚠️ OpenRouter failed, switching to HuggingFace:", e)
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
    # Add user message
    st.session_state.messages.append(
        {"role": "user", "content": user_input}
    )

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply = generate_reply(st.session_state.messages)
            st.write(reply)

    # Store reply
    st.session_state.messages.append(
        {"role": "assistant", "content": reply}
    )

    # --- OPTIONAL: trim memory (prevents slowdown) ---
    MAX_MESSAGES = 20
    if len(st.session_state.messages) > MAX_MESSAGES:
        st.session_state.messages = (
            [st.session_state.messages[0]]  # keep system prompt
            + st.session_state.messages[-(MAX_MESSAGES - 1):]
        )
