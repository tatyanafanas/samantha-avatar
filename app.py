import streamlit as st
import requests
from openai import OpenAI
import time

# --- CONFIG ---
OPENROUTER_API_KEY = st.secrets.get("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", "")
HF_API_KEY = st.secrets.get("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", "")

OPENROUTER_MODEL = "openrouter/mistral-7b-instruct:free"
HF_MODEL = "HuggingFaceH4/zephyr-7b-beta"

# --- OPENROUTER CLIENT ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# --- HUGGING FACE FALLBACK ---
def query_hf(messages):
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }

    # Better formatting for Zephyr
    prompt = ""
    for m in messages:
        if m["role"] == "system":
            prompt += f"<|system|>\n{m['content']}\n"
        elif m["role"] == "user":
            prompt += f"<|user|>\n{m['content']}\n"
        elif m["role"] == "assistant":
            prompt += f"<|assistant|>\n{m['content']}\n"

    # Retry loop (handles cold starts)
    for attempt in range(3):
        try:
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

            if response.status_code == 200:
                data = response.json()

                if isinstance(data, list) and "generated_text" in data[0]:
                    return data[0]["generated_text"]

                return str(data)

            # Model loading (very common)
            if response.status_code == 503:
                time.sleep(5)
                continue

            return f"[HF ERROR {response.status_code}] {response.text}"

        except Exception as e:
            if attempt == 2:
                return f"[HF FAILED] {str(e)}"
            time.sleep(3)

    return "[HF FAILED COMPLETELY]"


# --- MAIN GENERATION ---
def generate_reply(messages):
    try:
        completion = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            temperature=0.7,
            timeout=30,
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
