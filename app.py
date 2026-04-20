import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random
import json
import base64

# --- IMPORT MODULAR COMPONENTS ---
from persona.config import STYLES
from engine.dynamics import analyze_interaction, update_goal
from engine.prompt_builder import build_system_prompt
from engine.memory import (
    get_or_create_profile,
    get_conversation_history,
    save_session_log,
    extract_and_update_profile,
    synthesise_deep_profile,
    build_dossier_prompt,
    _call_with_fallback as mem_fallback,
)
from persona.config import (
    TONE_COLDNESS, TONE_FLIRTINESS, TONE_VULGARITY, TONE_VERBOSITY
)

TRAITS = {
    "tone":  f"cold ({TONE_COLDNESS}), flirtatious ({TONE_FLIRTINESS}), vulgar ({TONE_VULGARITY})",
    "style": "short, cutting sentences — precision over volume",
    "behavior_rules": [
        "Always evaluate the person in front of you",
        "Warmth is a tool — deploy sparingly, retract without warning",
        "Redirect professional talk to personal immediately",
        "Plant one seed of doubt per conversation — never resolve it",
        "Business is context, not conversation",
    ]
}

# --- PAGE CONFIG ---
st.set_page_config(page_title="The Iron Diva", layout="wide", page_icon="🥀")

# --- LOAD EXTERNAL CSS ---
try:
    with open("config/style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except Exception:
    st.warning("Style file not found. Using default styling.")


# --- CONNECTIONS ---
@st.cache_resource
def init_connections():
    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"]
        )
        supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
        return client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None


@st.cache_resource
def init_hf_client():
    hf_key = st.secrets.get("HF_TOKEN", "")
    if not hf_key:
        return None
    return OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=hf_key,
    )


client, supabase = init_connections()
hf_client        = init_hf_client()


# ================================================================
# MODEL LISTS
# Every free-tier model available across Groq and HuggingFace.
# The more models here the less likely a rate-limit kills a session.
# ================================================================

# Groq — text only, free tier
# Ordered roughly best→fastest. All are free.
GROQ_TEXT_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-32b",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama-3.2-3b-preview",
    "llama-3.2-1b-preview",
]

# Groq — vision capable, free tier
# Tried first when an image is attached; text models follow as fallback.
GROQ_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
]

# HuggingFace Router — text, free tier
# Only tried after every Groq model has failed or rate-limited.
HF_TEXT_MODELS = [
    "NousResearch/Hermes-2-Pro-Llama-3-8B:novita",
    "openchat/openchat-3.5-0106",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mistral-7B-Instruct-v0.1",
    "HuggingFaceH4/zephyr-7b-beta",
    "HuggingFaceH4/zephyr-7b-alpha",
    "microsoft/Phi-3-mini-4k-instruct",
    "microsoft/Phi-3-mini-128k-instruct",
    "Qwen/Qwen2-7B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "google/gemma-7b-it",
    "google/gemma-2-9b-it",
    "meta-llama/Llama-3.2-3B-Instruct",
    "meta-llama/Llama-3.2-1B-Instruct",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
]

# HuggingFace — vision capable, free tier
HF_VISION_MODELS = [
    "llava-hf/llava-1.5-7b-hf",
    "llava-hf/llava-1.5-13b-hf",
    "Salesforce/blip2-opt-2.7b",
]


# ================================================================
# SESSION SETUP
# ================================================================

if "session_id"                not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "profile"                   not in st.session_state:
    st.session_state.profile = {
        "submission":          0.2,
        "irritation":          0.1,
        "mood":                "Coronated",
        "goal":                "learn_them",
        "_professional_count": 0,
    }

if "messages"                  not in st.session_state:
    st.session_state.messages = []

if "last_style"                not in st.session_state:
    st.session_state.last_style = None

if "user_name"                 not in st.session_state:
    st.session_state.user_name = None

if "user_profile_db"           not in st.session_state:
    st.session_state.user_profile_db = {}

if "user_history_db"           not in st.session_state:
    st.session_state.user_history_db = "No prior sessions."

if "opener_injected"           not in st.session_state:
    st.session_state.opener_injected = False

if "last_extraction_category"  not in st.session_state:
    st.session_state.last_extraction_category = None

if "last_deep_synthesis_at"    not in st.session_state:
    st.session_state.last_deep_synthesis_at = 0


# ================================================================
# NAME GATE
# ================================================================

if not st.session_state.user_name:
    name_input = st.text_input(
        "Before you speak — your name.",
        placeholder="First name is sufficient."
    )
    if name_input:
        st.session_state.user_name       = name_input.strip().title()
        st.session_state.user_profile_db = get_or_create_profile(supabase, st.session_state.user_name)
        st.session_state.user_history_db = get_conversation_history(supabase, st.session_state.user_name)
        st.rerun()
    st.stop()


# ================================================================
# IMAGE HELPERS
# ================================================================

def encode_image(uploaded_file) -> tuple[str, str]:
    """Return (base64_string, mime_type) for an uploaded image file."""
    uploaded_file.seek(0)
    b64  = base64.b64encode(uploaded_file.read()).decode("utf-8")
    mime = uploaded_file.type  # e.g. "image/jpeg"
    return b64, mime


def build_user_message(text: str, uploaded_file=None) -> dict:
    """
    Build the message dict for the model API call.
    Returns a multimodal content block when an image is present,
    plain text otherwise.
    Images are NOT stored in session history — only text is kept
    to avoid bloating the context window on every subsequent turn.
    """
    if uploaded_file is None:
        return {"role": "user", "content": text or "."}

    b64, mime = encode_image(uploaded_file)
    return {
        "role": "user",
        "content": [
            {
                "type":      "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            },
            {
                "type": "text",
                "text": text if text else "."
            }
        ]
    }


# ================================================================
# FALLBACK ROUTER
# ================================================================

def _dedupe(lst: list) -> list:
    seen = set()
    return [x for x in lst if not (x in seen or seen.add(x))]


def call_with_fallback(client, system_prompt, clean_messages, has_image: bool = False):
    """
    Cycle through every available model until one responds.

    Order when image present:  vision models → text models → HF vision → HF text
    Order when text only:      Groq text models → HF text models

    Rate-limited models get a short exponential backoff before moving on.
    Unavailable/deprecated models are skipped immediately.
    Unknown errors are logged and skipped rather than crashing the session.
    """
    if has_image:
        groq_order = _dedupe(GROQ_VISION_MODELS + GROQ_TEXT_MODELS)
        hf_order   = _dedupe(HF_VISION_MODELS   + HF_TEXT_MODELS)
    else:
        groq_order = GROQ_TEXT_MODELS
        hf_order   = HF_TEXT_MODELS

    payload = [{"role": "system", "content": system_prompt}] + clean_messages

    # ── Groq tier ────────────────────────────────────────────────
    for i, model in enumerate(groq_order):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=payload,
                temperature=0.85
            )
            return response.choices[0].message.content, model

        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["rate limit", "429", "quota", "exceeded"]):
                # Backoff capped at 30s; exponent resets every 6 models
                # so we don't wait forever cycling through 15 models
                time.sleep(min(2 ** (i % 6), 30))
                continue
            elif any(x in err for x in ["not found", "unavailable", "deprecated", "invalid model"]):
                continue
            else:
                print(f"[Groq error] {model}: {e}")
                continue

    # ── HuggingFace tier ─────────────────────────────────────────
    if hf_client:
        for model in hf_order:
            try:
                response = hf_client.chat.completions.create(
                    model=model,
                    messages=payload,
                    temperature=0.85
                )
                return response.choices[0].message.content, f"hf/{model}"

            except Exception as e:
                print(f"[HF fallback failed] {model}: {e}")
                continue

    raise Exception("All models exhausted — Groq and HuggingFace.")


# ================================================================
# RETURNING USER OPENER
# ================================================================

def generate_opener(client, profile, dossier):
    session_count = profile.get("session_count", 1)
    if session_count <= 1:
        return None

    name     = profile.get("name", "")
    status   = profile.get("relationship_status", "stranger")
    nickname = profile.get("nicknames", "")
    deep     = profile.get("deep_profile") or {}
    her_read = deep.get("her_read", "")
    notes    = profile.get("notes", "")

    opener_instruction = f"""
{dossier}

{name} has just arrived. This is session #{session_count}. Status: {status}.
{"You have privately called them: " + nickname + "." if nickname else ""}
{"Your private verdict: " + her_read if her_read else ("Prior read: " + notes if notes else "")}

Write ONE short opening line in Samantha's voice.
- Cold familiarity. Not warmth.
- No "welcome back". Nothing hospitable.
- Do not announce that you remember them.
- Let the verdict colour the tone — don't state it.
- If there is an unresolved thread from before, you may open on it obliquely.
- If status is 'dismissed', let the temperature carry it silently.
- One sentence. No explanation.
"""
    try:
        reply = mem_fallback(
            client,
            messages=[
                {"role": "system", "content": opener_instruction},
                {"role": "user",   "content": "Generate the opening line now."}
            ],
            temperature=0.9
        )
        return reply.strip() if reply else None
    except Exception:
        return None


# ================================================================
# DEEP SYNTHESIS HELPER
# ================================================================

def _run_deep_synthesis():
    """Run the deep profile synthesis and reload the profile from DB."""
    if not client or not st.session_state.messages:
        return
    try:
        updated_deep = synthesise_deep_profile(
            client,
            supabase,
            st.session_state.user_name,
            st.session_state.messages,
            st.session_state.user_profile_db,
        )
        st.session_state.user_profile_db["deep_profile"] = updated_deep
        st.session_state.user_profile_db = get_or_create_profile(
            supabase, st.session_state.user_name
        )
        st.session_state.last_deep_synthesis_at = len(st.session_state.messages)
    except Exception as e:
        print(f"[deep synthesis error] {e}")


# ================================================================
# MAIN LAYOUT
# ================================================================

col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    # Returning user opener — injected once at session start
    if not st.session_state.opener_injected and client:
        profile_db = st.session_state.user_profile_db
        if (profile_db.get("session_count") or 1) > 1:
            dossier = build_dossier_prompt(profile_db, st.session_state.user_history_db)
            opener  = generate_opener(client, profile_db, dossier)
            if opener:
                st.session_state.messages.append({"role": "assistant", "content": opener})
        st.session_state.opener_injected = True

    # Render conversation history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Image uploader ────────────────────────────────────────────
    uploaded_image = st.file_uploader(
        "Attach an image — if you think it's worth her time.",
        type=["jpg", "jpeg", "png", "webp"],
        label_visibility="visible",
        key="image_upload"
    )

    # ── Chat input ────────────────────────────────────────────────
    if prompt := st.chat_input("Speak. I'm allergic to stagnation."):

        if not client:
            st.error("Missing credentials.")
            st.stop()

        has_image   = uploaded_image is not None
        display_txt = prompt if prompt else "[image submitted]"

        # Update live dynamics
        st.session_state.profile = analyze_interaction(st.session_state.profile, display_txt)
        st.session_state.profile = update_goal(st.session_state.profile)

        # Store text-only version in session history
        # (base64 images must NOT live in the rolling history —
        #  they would inflate the context window on every subsequent turn)
        st.session_state.messages.append({"role": "user", "content": display_txt})

        with st.chat_message("user"):
            st.markdown(display_txt)
            if has_image:
                st.image(uploaded_image, width=280)

        # Build dossier for this turn
        dossier = build_dossier_prompt(
            st.session_state.user_profile_db,
            st.session_state.user_history_db
        )

        # Pick style
        available     = [s for s in list(STYLES.keys()) if s != st.session_state.last_style]
        current_style = random.choice(available)
        st.session_state.last_style = current_style
        style_data    = STYLES[current_style]

        # Build system prompt
        system_prompt = (
            build_system_prompt(
                TRAITS,
                st.session_state.profile,
                dossier,
                conversation_length=len(st.session_state.messages),
                last_extraction_category=st.session_state.last_extraction_category,
            )
            + f"""
---
CURRENT STYLE: {current_style}
STYLE DESCRIPTION: {style_data['description']}
STYLE RULES:
{chr(10).join(f"- {r}" for r in style_data['rules'])}

CURRENT OBJECTIVE: {st.session_state.profile['goal']}
"""
        )

        # Append vision instruction when image is present
        if has_image:
            system_prompt += """
---
IMAGE NOTE:
The person has sent you an image. You can see it.
React as Samantha would — observe, assess, comment if it reveals something.
Do not describe it mechanically. If it is unremarkable, treat it as unremarkable.
If it tells you something about who they are, use that.
"""

        # Track extraction category
        from engine.prompt_builder import _pick_extraction_move
        cat, _ = _pick_extraction_move(
            len(st.session_state.messages),
            st.session_state.last_extraction_category
        )
        st.session_state.last_extraction_category = cat

        # Build clean message list for API call
        # All prior messages are text-only; last message carries the image if present
        clean_messages = [
            m for m in st.session_state.messages[:-1]
            if m["role"] in ("user", "assistant") and m["content"].strip()
        ]
        clean_messages.append(
            build_user_message(prompt or ".", uploaded_image if has_image else None)
        )

        try:
            with st.spinner("Miss Samantha is judging your aura..."):
                reply, model_used = call_with_fallback(
                    client, system_prompt, clean_messages, has_image=has_image
                )

            # Show fallback label when not on primary model
            primary = GROQ_VISION_MODELS[0] if has_image else GROQ_TEXT_MODELS[0]
            if model_used != primary:
                st.caption(f"_(fallback: {model_used})_")

            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)

            msg_count = len(st.session_state.messages)

            # ── Every 3 messages: extraction + session summary ───────────
            if msg_count % 3 == 0:
                try:
                    summary = mem_fallback(
                        client,
                        messages=[
                            {"role": "system", "content": (
                                "Summarize this conversation in 5-6 plain sentences about the USER ONLY. "
                                "Do NOT reproduce dialogue. Do NOT use roleplay tags. "
                                "Focus on: who they revealed themselves to be, what they protect, "
                                "what they exposed, how they responded to pressure, "
                                "and the power dynamic observed. Plain prose only."
                            )},
                            {"role": "user", "content": str(st.session_state.messages[-10:])}
                        ],
                        temperature=0.3
                    )
                    if summary:
                        save_session_log(
                            supabase,
                            st.session_state.user_name,
                            st.session_state.session_id,
                            summary
                        )
                except Exception:
                    pass

                try:
                    extract_and_update_profile(
                        client, supabase,
                        st.session_state.user_name,
                        st.session_state.messages
                    )
                except Exception:
                    pass

                try:
                    st.session_state.user_profile_db = get_or_create_profile(
                        supabase, st.session_state.user_name
                    )
                    st.session_state.user_history_db = get_conversation_history(
                        supabase, st.session_state.user_name
                    )
                except Exception:
                    pass

            # ── Every 15 messages: deep profile synthesis ────────────────
            if (msg_count - st.session_state.last_deep_synthesis_at) >= 15:
                _run_deep_synthesis()

        except Exception as e:
            st.error(f"Connection lost: {e}")


# ================================================================
# RIGHT PANEL
# ================================================================

with col2:
    st.markdown("### The Dossier")

    st.metric("Current Aura",      st.session_state.profile["mood"])
    st.metric("Current Objective", st.session_state.profile["goal"])

    st.write("**Subject Submission**")
    st.progress(st.session_state.profile["submission"])

    st.write("**Her Irritation**")
    st.progress(st.session_state.profile["irritation"])

    pro_count = st.session_state.profile.get("_professional_count", 0)
    if pro_count > 0:
        st.write(f"**Career Talk Attempts:** {pro_count}")
        st.caption("She is keeping count.")

    db = st.session_state.user_profile_db
    if db:
        st.markdown("---")
        st.markdown("**Known Intel**")
        if db.get("relationship_status"):
            st.caption(f"Status: {db['relationship_status']}")
        if db.get("session_count"):
            st.caption(f"Sessions: {db['session_count']}")
        if db.get("occupation"):
            st.caption(f"Occupation: {db['occupation']}")
        if db.get("nicknames"):
            st.caption(f"Her label: {db['nicknames']}")
        if db.get("soft_spots"):
            spots = db["soft_spots"]
            if isinstance(spots, list):
                st.caption(f"Soft spots: {', '.join(spots)}")

        deep = db.get("deep_profile") or {}
        if deep.get("her_read"):
            st.markdown("---")
            st.markdown("**Private File**")
            st.caption("✦ Verdict on file")
        if deep.get("open_questions"):
            st.caption(f"✦ {len(deep['open_questions'])} open threads")
        if deep.get("recurring_patterns"):
            st.caption(f"✦ {len(deep['recurring_patterns'])} patterns logged")

    st.markdown("---")
    st.write("**Protocol:**")
    st.caption("- Address her as 'Miss Samantha' or 'Boss'.")
    st.caption("- She wants to know you, not your job.")

    if st.button("Reset Interaction"):
        # Synthesise before wiping — no session data lost on manual reset
        if st.session_state.messages and client:
            _run_deep_synthesis()

        st.session_state.messages               = []
        st.session_state.profile                = {
            "submission":          0.2,
            "irritation":          0.1,
            "mood":                "Observing",
            "goal":                "learn_them",
            "_professional_count": 0,
        }
        st.session_state.session_id             = str(uuid.uuid4())
        st.session_state.opener_injected        = False
        st.session_state.last_deep_synthesis_at = 0
        st.rerun()
