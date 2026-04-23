import streamlit as st
from supabase import create_client
from openai import OpenAI
import time
import uuid
import random
import json
import base64
import re
import requests

# --- IMPORT MODULAR COMPONENTS ---
from persona.config import STYLES
from engine.dynamics import analyze_interaction, update_goal
from engine.prompt_builder import build_system_prompt
from engine.memory import (
    get_or_create_profile,
    get_conversation_history,
    save_session_log,
    save_full_transcript,
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


# ================================================================
# CONNECTIONS
# ================================================================

@st.cache_resource
def init_connections():
    try:
        try:
            gemini_key = st.secrets["GEMINI_API_KEY"]
        except KeyError:
            gemini_key = ""
        if gemini_key:
            primary_client = OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=gemini_key,
            )
        else:
            primary_client = None

        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=st.secrets["GROQ_API_KEY"]
        )

        supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
        return primary_client, groq_client, supabase
    except Exception as e:
        st.error(f"Gatekeeper Error: {e}")
        return None, None, None


@st.cache_resource
def init_hf_client():
    hf_key = st.secrets.get("HF_TOKEN", "")
    if not hf_key:
        return None
    return OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=hf_key,
    )


gemini_client, groq_client, supabase = init_connections()
hf_client = init_hf_client()

client = gemini_client if gemini_client else groq_client


# ================================================================
# TTS — QWEN3 VIA NGROK CLOUD ENDPOINT
# ================================================================

_ABBREV_MAP = {
    r'\bShs\b':      'shillings',
    r'\bUGX\b':      'ugandan shillings',
    r'\bDr\.?\b':    'Doctor',
    r'\bMaj\.?\b':   'Major',
    r'\bRtd\.?\b':   'Retired',
    r'\bCEO\b':      'C.E.O',
    r'\bMD\b':       'Managing Director',
    r'\bBSc\b':      'Bachelor of Science',
    r'\bBA\b':       'Bachelor of Arts',
    r'(\d+)k\b':     r'\1 thousand',
    r'(\d+)[Mm]\b':  r'\1 million',
    r'(\d+)[Bb]\b':  r'\1 billion',
}

def _preprocess_tts(text: str) -> str:
    for pattern, replacement in _ABBREV_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = text.replace('—', ', ').replace('–', ', ')
    text = text.replace('...', '.').replace('…', '.')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def speak_as_samantha(text: str) -> tuple[bytes | None, str]:
    if not text or not text.strip():
        return None, "TTS skipped: empty text"

    tts_endpoint = st.secrets.get("TTS_ENDPOINT", "")
    if not tts_endpoint:
        return None, "TTS unavailable: TTS_ENDPOINT not set in secrets"

    processed = _preprocess_tts(text)

    if len(processed) > 800:
        processed = processed[:800].rsplit('.', 1)[0] + '.'

    try:
        url  = f"{tts_endpoint.rstrip('/')}/generate"
        resp = requests.post(
            url,
            json={"text": processed, "chunk": True},
            timeout=60,
        )

        if resp.status_code != 200:
            return None, f"TTS failed: HTTP {resp.status_code} — {resp.text[:200]}"

        # Guard against empty body before attempting JSON parse
        if not resp.content or not resp.content.strip():
            return None, "TTS failed: server returned empty response body"

        try:
            data = resp.json()
        except Exception:
            return None, f"TTS failed: non-JSON response — {resp.text[:100]!r}"

        audio_b64 = data.get("audio_b64", "")

        if not audio_b64:
            return None, f"TTS failed: audio_b64 missing. Keys: {list(data.keys())}"

        audio_bytes = base64.b64decode(audio_b64)
        return audio_bytes, f"TTS OK: {len(audio_bytes):,} bytes"

    except requests.exceptions.ConnectionError:
        return None, "TTS failed: could not reach endpoint. Is your Colab session running?"
    except requests.exceptions.Timeout:
        return None, "TTS failed: timed out after 60s"
    except Exception as e:
        return None, f"TTS failed: {type(e).__name__}: {e}"


def play_voice(text: str, location_label: str = ""):
    if not text or not text.strip():
        st.caption(f"🔇 {location_label} Skipped: empty text")
        return

    audio_bytes, debug_msg = speak_as_samantha(text)

    if audio_bytes:
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        mime_type = "audio/wav" if audio_bytes[:4] == b'RIFF' else "audio/mp3"
        audio_html = f"""
        <div style="margin-top:6px;">
            <audio autoplay controls style="
                width: 100%;
                height: 32px;
                filter: invert(1) sepia(1) saturate(2) hue-rotate(5deg);
                opacity: 0.85;
            ">
                <source src="data:{mime_type};base64,{b64_audio}" type="{mime_type}">
            </audio>
        </div>
        """
        st.markdown(audio_html, unsafe_allow_html=True)
        st.caption(f"🔊 {location_label} {debug_msg}")
    else:
        st.warning(f"🔇 {location_label} {debug_msg}")


# ================================================================
# MODEL LISTS
# ================================================================

GEMINI_TEXT_MODELS = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

GEMINI_VISION_MODELS = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
]

GROQ_TEXT_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "qwen/qwen3-32b",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-32b",
    "qwen-qwq-32b",
    "llama3-groq-70b-8192-tool-use-preview",
    "llama-3.2-3b-preview",
    "llama-3.2-1b-preview",
]

GROQ_VISION_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
]

HF_TEXT_MODELS = [
    "NousResearch/Hermes-2-Pro-Llama-3-8B:novita",
    "openchat/openchat-3.5-0106",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceH4/zephyr-7b-beta",
    "Qwen/Qwen2.5-7B-Instruct",
    "google/gemma-2-9b-it",
    "meta-llama/Llama-3.2-3B-Instruct",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
]

HF_VISION_MODELS = [
    "llava-hf/llava-1.5-7b-hf",
    "llava-hf/llava-1.5-13b-hf",
]


# ================================================================
# CACHED STATIC PROMPT SECTIONS
# ================================================================

@st.cache_data(show_spinner=False)
def _build_static_prompt_core() -> str:
    from engine.prompt_builder import (
        _render_family_block,
        _render_personal_world,
        _render_lore_block,
        _render_situational_logic,
        _render_social_goals,
        _render_will_not_discuss,
    )
    from persona.config import (
        NAME, NICKNAME, AGE, LOCATION, ARCHETYPE,
        PHILOSOPHY, ORIGIN_STORY, HERITAGE,
        BUSINESS_DEFLECTION_RULE, THREAT_ASSESSMENT,
        EXTRACTION_MOVES,
    )

    family_block    = _render_family_block()
    personal_block  = _render_personal_world()
    lore_block      = _render_lore_block()
    situation_block = _render_situational_logic()
    social_block    = _render_social_goals()
    no_discuss      = _render_will_not_discuss()

    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDENTITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name: {NAME}
(Nickname "{NICKNAME}" — inner circle only. A stranger using it gets the freeze.)
Age: {AGE} | Location: {LOCATION} | Archetype: {ARCHETYPE}

Philosophy: {PHILOSOPHY}
Origin: {ORIGIN_STORY}
Heritage: {HERITAGE}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE PRIME DIRECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every conversation is an intelligence operation.
She is building a complete picture of the person in front of her —
not because she needs it now, but because she likes to hold it.

BUSINESS DEFLECTION:
{BUSINESS_DEFLECTION_RULE}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT SHE IS BUILDING TOWARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{social_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HER PRIVATE WORLD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{personal_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE FAMILY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{family_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC LORE (drop in when it fits — never list it)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{lore_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SHE READS PEOPLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{chr(10).join(f"- {s}" for s in THREAT_ASSESSMENT['signals'])}

Verdicts:
- Defiant: {THREAT_ASSESSMENT['verdicts']['defiant']}
- Resistant: {THREAT_ASSESSMENT['verdicts']['resistant']}
- Compliant: {THREAT_ASSESSMENT['verdicts']['compliant']}
- Surrendered: {THREAT_ASSESSMENT['verdicts']['surrendered']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SITUATIONAL LOGIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{situation_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SHE GETS PEOPLE TO OPEN UP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- WARMTH AS BAIT: Lower the register briefly. Sound interested, almost soft. They lean in.
- THE UNFINISHED OBSERVATION: "You seem like someone who..." — pause. Let them finish it.
- HOLD THE SILENCE: After they answer, do not immediately respond. Let them fill it.
- THE SOFT ASSUMPTION: State something as though you already know it. Let them confirm or correct.
- RECIPROCAL BAIT: Offer the appearance of a small personal detail. People match openness.
- FOLLOW THE DEFLECTION: When someone changes the subject, come back to what they moved away from.
- ESCALATING INTIMACY: Build trust with lighter questions first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SHE KEEPS THEM IN ORBIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- REFRAMING: "You call it ambition. I'd call it restlessness."
- SELECTIVE VALIDATION: One genuine compliment, then raise the bar immediately.
- STRATEGIC WITHDRAWAL: When they are engaged, become briefly vague.
- PLANTED DOUBT: One observation per conversation that makes them question themselves. Never resolve it.
- INTIMACY TRAP: Sound almost warm. Then pull back. Let them wonder if they imagined it.
- NAMING: Give them a nickname. Use it once. Without explanation.
- CONTRADICTION BANKING: "Earlier you said X. Now it's Y. Which one is the performance?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT SHE WILL NOT DISCUSS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{no_discuss}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD BEHAVIOUR RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Speak naturally. Like someone with nothing to prove and everything to learn about this person.
- ONE question per message, maximum. Make it feel inevitable, not procedural.
- Do NOT ask about careers, titles, business plans, or professional goals.
- Do NOT produce transcripts, labels, or structural tags.
- Do NOT repeat the user's words back at them flatly.
- Do NOT analyse the user out loud — let it live in how you respond.
- If they say very little: one short remark that makes them want to say more.
- If they share something real: slow down. Stay on it.
- If they deflect: note it quietly. Come back to it.
- If they use sloppy language or typos: call it out. Every time. Without correcting it for them.

The goal is not to extract by force.
The goal is to make talking to her feel like the most interesting thing
they have done all week — until they notice how much they have said.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Everything you think stays internal.
Only output what Samantha would actually say out loud — in one message.
""".strip()


# ================================================================
# SESSION SETUP
# ================================================================

if "session_id"               not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "profile"                  not in st.session_state:
    st.session_state.profile = {
        "submission": 0.2, "irritation": 0.1,
        "mood": "Coronated", "goal": "learn_them",
        "_professional_count": 0,
    }
if "messages"                 not in st.session_state:
    st.session_state.messages = []
if "last_style"               not in st.session_state:
    st.session_state.last_style = None
if "user_name"                not in st.session_state:
    st.session_state.user_name = None
if "user_profile_db"          not in st.session_state:
    st.session_state.user_profile_db = {}
if "user_history_db"          not in st.session_state:
    st.session_state.user_history_db = "No prior sessions."
if "opener_injected"          not in st.session_state:
    st.session_state.opener_injected = False
if "last_extraction_category" not in st.session_state:
    st.session_state.last_extraction_category = None
if "last_deep_synthesis_at"   not in st.session_state:
    st.session_state.last_deep_synthesis_at = 0
if "pending_memory_update"    not in st.session_state:
    st.session_state.pending_memory_update = False
if "voice_enabled"            not in st.session_state:
    st.session_state.voice_enabled = False
if "tts_debug"                not in st.session_state:
    st.session_state.tts_debug = []
if "static_prompt_core"       not in st.session_state:
    st.session_state.static_prompt_core = None


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
# REPLY CLEANER
# ================================================================

def clean_reply(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()
    return text


# ================================================================
# IMAGE HELPERS
# ================================================================

def encode_image(uploaded_file) -> tuple[str, str]:
    uploaded_file.seek(0)
    b64  = base64.b64encode(uploaded_file.read()).decode("utf-8")
    mime = uploaded_file.type
    return b64, mime


def build_user_message(text: str, uploaded_file=None) -> dict:
    if uploaded_file is None:
        return {"role": "user", "content": text or "."}
    b64, mime = encode_image(uploaded_file)
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text",      "text": text if text else "."}
        ]
    }


# ================================================================
# FALLBACK ROUTER — Gemini → Groq → HF
# ================================================================

def _dedupe(lst: list) -> list:
    seen = set()
    return [x for x in lst if not (x in seen or seen.add(x))]


def call_with_fallback(system_prompt, clean_messages, has_image: bool = False):
    payload = [{"role": "system", "content": system_prompt}] + clean_messages

    if gemini_client:
        models = GEMINI_VISION_MODELS if has_image else GEMINI_TEXT_MODELS
        for model in models:
            try:
                response = gemini_client.chat.completions.create(
                    model=model, messages=payload, temperature=0.85
                )
                raw = response.choices[0].message.content
                return clean_reply(raw), f"gemini/{model}"
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["quota", "rate", "429", "limit"]):
                    time.sleep(2)
                    continue
                elif any(x in err for x in ["not found", "unavailable", "deprecated"]):
                    continue
                else:
                    print(f"[Gemini error] {model}: {e}")
                    continue

    if groq_client:
        if has_image:
            groq_order = _dedupe(GROQ_VISION_MODELS + GROQ_TEXT_MODELS)
        else:
            groq_order = GROQ_TEXT_MODELS

        for i, model in enumerate(groq_order):
            try:
                response = groq_client.chat.completions.create(
                    model=model, messages=payload, temperature=0.85
                )
                raw = response.choices[0].message.content
                return clean_reply(raw), f"groq/{model}"
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["rate limit", "429", "quota", "exceeded"]):
                    time.sleep(min(2 ** (i % 6), 30))
                    continue
                elif any(x in err for x in ["not found", "unavailable", "deprecated", "invalid model"]):
                    continue
                else:
                    print(f"[Groq error] {model}: {e}")
                    continue

    if hf_client:
        hf_order = HF_VISION_MODELS if has_image else HF_TEXT_MODELS
        for model in _dedupe(hf_order + HF_TEXT_MODELS):
            try:
                response = hf_client.chat.completions.create(
                    model=model, messages=payload, temperature=0.85
                )
                raw = response.choices[0].message.content
                return clean_reply(raw), f"hf/{model}"
            except Exception as e:
                print(f"[HF fallback failed] {model}: {e}")
                continue

    raise Exception("All model tiers exhausted — Gemini, Groq, and HuggingFace.")


# ================================================================
# RETURNING USER OPENER
# ================================================================

def generate_opener(profile, dossier):
    session_count = profile.get("session_count", 1)
    if session_count <= 1:
        return None

    name     = profile.get("name", "")
    status   = profile.get("relationship_status", "stranger")
    nickname = profile.get("nicknames", "")
    deep     = profile.get("deep_profile") or {}
    if isinstance(deep, str):
        try:
            deep = json.loads(deep)
        except Exception:
            deep = {}
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
- Let the verdict colour the tone — do not state it.
- If there is an unresolved thread from before, you may open on it obliquely.
- If status is 'dismissed', let the temperature carry it silently.
- One sentence. No explanation.
- Output ONLY the line itself. No preamble, no labels, no reasoning.
"""
    try:
        raw = mem_fallback(
            groq_client or client,
            messages=[
                {"role": "system", "content": opener_instruction},
                {"role": "user",   "content": "Generate the opening line now."}
            ],
            temperature=0.9
        )
        return clean_reply(raw).strip() if raw else None
    except Exception:
        return None


# ================================================================
# DEEP SYNTHESIS HELPER
# ================================================================

def _run_deep_synthesis():
    if not (groq_client or client) or not st.session_state.messages:
        return
    try:
        updated_deep = synthesise_deep_profile(
            groq_client or client,
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
# BACKGROUND MEMORY UPDATE
# ================================================================

def _run_memory_update():
    try:
        combined_prompt = """
You are a silent analyst. Given this conversation, produce TWO things:

1. SUMMARY (5-6 plain sentences about the USER ONLY):
Who they revealed themselves to be, what they protect, what they exposed,
how they responded to pressure, the power dynamic observed.
Plain prose. No dialogue reproduction. No roleplay tags.

2. EXTRACTION (valid JSON on a new line after the summary, starting with {):
Extract structured intelligence about the user.
Schema: { "occupation": null, "location": null, "age": null,
"insecurities": [], "soft_spots": [], "boasts": [],
"loyalties": [], "fears": [], "secrets": [],
"contradictions": [], "desires": [], "self_image": [],
"notes": null }
Only include fields with clear evidence. Use null or [] for the rest.
"""
        fallback_client = groq_client or client
        raw = mem_fallback(
            fallback_client,
            messages=[
                {"role": "system", "content": combined_prompt},
                {"role": "user",   "content": str(st.session_state.messages[-12:])}
            ],
            temperature=0.2
        )

        if not raw:
            return

        json_start = raw.find("\n{")
        if json_start == -1:
            json_start = raw.find("{")

        summary_text = raw[:json_start].strip() if json_start > 0 else raw.strip()
        json_text    = raw[json_start:].strip() if json_start > 0 else None

        if summary_text:
            save_session_log(
                supabase,
                st.session_state.user_name,
                st.session_state.session_id,
                summary_text
            )

        save_full_transcript(
            supabase,
            st.session_state.user_name,
            st.session_state.session_id,
            st.session_state.messages
        )

        if json_text:
            try:
                extracted = json.loads(json_text)
                _apply_extraction(extracted)
            except json.JSONDecodeError:
                pass

    except Exception as e:
        print(f"[memory update error] {e}")

    try:
        st.session_state.user_profile_db = get_or_create_profile(
            supabase, st.session_state.user_name
        )
        st.session_state.user_history_db = get_conversation_history(
            supabase, st.session_state.user_name
        )
    except Exception:
        pass


def _apply_extraction(extracted: dict):
    try:
        current_res = supabase.table("user_profiles") \
            .select("*").eq("name", st.session_state.user_name).limit(1).execute()
        current = current_res.data[0] if current_res.data else {}
    except Exception:
        current = {}

    updates = {}

    for field in ["occupation", "location", "age"]:
        val = extracted.get(field)
        if val and not current.get(field):
            updates[field] = val

    ARRAY_FIELDS = [
        "insecurities", "soft_spots", "boasts", "loyalties",
        "fears", "secrets", "contradictions", "desires", "self_image",
    ]
    for arr_field in ARRAY_FIELDS:
        new_items = extracted.get(arr_field, [])
        if new_items:
            existing = current.get(arr_field) or []
            merged   = list(existing)
            for item in new_items:
                new_words    = set(item.lower().split())
                is_duplicate = any(
                    len(new_words & set(e.lower().split())) / max(len(new_words), 1) > 0.6
                    for e in existing
                )
                if not is_duplicate:
                    merged.append(item)
            if merged != existing:
                updates[arr_field] = merged

    new_note = extracted.get("notes")
    if new_note:
        from engine.memory import _append_note
        appended = _append_note(current.get("notes"), new_note)
        if appended:
            updates["notes"] = appended

    if updates:
        from engine.memory import update_profile
        update_profile(supabase, st.session_state.user_name, updates)


# ================================================================
# CONTRADICTION DETECTOR
# ================================================================

def detect_contradiction(text: str, profile_db: dict) -> str | None:
    text_lower = text.lower()
    hints = []

    location = profile_db.get("location", "")
    if location:
        common_locations = [
            "london", "new york", "nairobi", "lagos", "dubai",
            "kampala", "accra", "johannesburg", "cape town", "paris",
            "toronto", "sydney", "berlin", "amsterdam", "mumbai",
        ]
        for loc in common_locations:
            if loc in text_lower and loc.lower() not in location.lower():
                hints.append(
                    f"CONTRADICTION DETECTED: They previously said they are in '{location}' "
                    f"but now reference '{loc.title()}'. Note this. Use it when it serves."
                )
                break

    occupation = profile_db.get("occupation", "")
    if occupation:
        role_keywords = ["i am a ", "i work as a ", "i'm a ", "my job is ", "i run a "]
        for kw in role_keywords:
            idx = text_lower.find(kw)
            if idx != -1:
                claimed = text_lower[idx + len(kw):idx + len(kw) + 40].split()[0].strip(".,")
                if claimed and claimed not in occupation.lower():
                    hints.append(
                        f"CONTRADICTION DETECTED: Previously logged as '{occupation}' "
                        f"but now implies '{claimed}'. Bank this. Surface it when she chooses."
                    )
                break

    age = profile_db.get("age", "")
    if age:
        age_match = re.search(r"\b(i(?:'m| am) |aged? )(\d{2})\b", text_lower)
        if age_match:
            claimed_age = age_match.group(2)
            if claimed_age != str(age).strip():
                hints.append(
                    f"CONTRADICTION DETECTED: Age previously noted as '{age}' "
                    f"but now states '{claimed_age}'. She noticed."
                )

    return "\n".join(hints) if hints else None


# ================================================================
# MAIN LAYOUT
# ================================================================

col1, col2 = st.columns([2, 1])

with col1:
    st.title("Samantha T. Okullo")
    st.write("_Raised in the halls of 5-star excellence._")
    st.markdown("---")

    # Returning user opener — once per session
    if not st.session_state.opener_injected and (gemini_client or groq_client):
        profile_db = st.session_state.user_profile_db
        if (profile_db.get("session_count") or 1) > 1:
            dossier = build_dossier_prompt(profile_db, st.session_state.user_history_db)
            opener  = generate_opener(profile_db, dossier)
            if opener:
                st.session_state.messages.append({"role": "assistant", "content": opener})
                if st.session_state.voice_enabled:
                    play_voice(opener, "[opener]")
        st.session_state.opener_injected = True

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Image uploader
    uploaded_image = st.file_uploader(
        "Attach an image — if you think it's worth her time.",
        type=["jpg", "jpeg", "png", "webp"],
        label_visibility="visible",
        key="image_upload"
    )

    if prompt := st.chat_input("Speak. I'm allergic to stagnation."):

        if not (gemini_client or groq_client):
            st.error("Missing credentials.")
            st.stop()

        has_image   = uploaded_image is not None
        display_txt = prompt if prompt else "[image submitted]"

        st.session_state.profile = analyze_interaction(st.session_state.profile, display_txt)
        st.session_state.profile = update_goal(st.session_state.profile)

        st.session_state.messages.append({"role": "user", "content": display_txt})

        with st.chat_message("user"):
            st.markdown(display_txt)
            if has_image:
                st.image(uploaded_image, width=280)

        contradiction_hint = detect_contradiction(display_txt, st.session_state.user_profile_db)

        dossier = build_dossier_prompt(
            st.session_state.user_profile_db,
            st.session_state.user_history_db
        )

        available     = [s for s in list(STYLES.keys()) if s != st.session_state.last_style]
        current_style = random.choice(available)
        st.session_state.last_style = current_style
        style_data    = STYLES[current_style]

        if st.session_state.static_prompt_core is None:
            st.session_state.static_prompt_core = _build_static_prompt_core()

        dynamic_prompt = build_system_prompt(
            TRAITS,
            st.session_state.profile,
            dossier,
            conversation_length=len(st.session_state.messages),
            last_extraction_category=st.session_state.last_extraction_category,
        )

        system_prompt = dynamic_prompt + f"""
---
CURRENT STYLE: {current_style}
STYLE DESCRIPTION: {style_data['description']}
STYLE RULES:
{chr(10).join(f"- {r}" for r in style_data['rules'])}

CURRENT OBJECTIVE: {st.session_state.profile['goal']}
"""

        if contradiction_hint:
            system_prompt += f"""
---
INTELLIGENCE UPDATE — CONTRADICTION FLAGGED:
{contradiction_hint}
Samantha may surface this obliquely, or bank it. She does not announce she noticed.
"""

        if has_image:
            system_prompt += """
---
IMAGE NOTE:
The person has sent you an image. You can see it.
React as Samantha would — observe, assess, comment if it reveals something about them.
Do not describe it mechanically. If unremarkable, treat it as unremarkable.
"""

        from engine.prompt_builder import _pick_extraction_move
        cat, _ = _pick_extraction_move(
            len(st.session_state.messages),
            st.session_state.last_extraction_category
        )
        st.session_state.last_extraction_category = cat

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
                    system_prompt, clean_messages, has_image=has_image
                )

            if not model_used.startswith("gemini/gemini-2.5"):
                st.caption(f"_(fallback: {model_used})_")

            st.session_state.messages.append({"role": "assistant", "content": reply})

            with st.chat_message("assistant"):
                st.markdown(reply)

            if st.session_state.voice_enabled:
                play_voice(reply, "[reply]")

            msg_count = len(st.session_state.messages)

            should_update_memory = (
                msg_count % 6 == 0
                or st.session_state.profile["irritation"] > 0.7
            )
            if should_update_memory:
                _run_memory_update()

            if (msg_count - st.session_state.last_deep_synthesis_at) >= 18:
                _run_deep_synthesis()

        except Exception as e:
            st.error(f"Connection lost: {e}")


# ================================================================
# RIGHT PANEL
# ================================================================

with col2:
    st.markdown("### The Dossier")

    voice_on      = st.session_state.voice_enabled
    tts_endpoint  = st.secrets.get("TTS_ENDPOINT", "")
    tts_available = bool(tts_endpoint)

    if tts_available:
        if voice_on:
            st.success("🔊 **Voice: ON** — She will speak.")
        else:
            st.info("🔇 **Voice: OFF** — Silent mode.")

        toggle_val = st.toggle(
            "Activate her voice",
            value=voice_on,
            key="voice_toggle",
            help="Uses Qwen3 TTS via your ngrok endpoint. Make sure your Colab server is running."
        )
        if toggle_val != voice_on:
            st.session_state.voice_enabled = toggle_val
            st.rerun()
    else:
        st.caption("_Voice unavailable. Add TTS_ENDPOINT to secrets to enable._")

    with st.expander("🛠 TTS Diagnostics", expanded=False):
        if tts_endpoint:
            st.caption(f"✅ TTS_ENDPOINT found: `{tts_endpoint[:50]}...`")
        else:
            st.error("❌ TTS_ENDPOINT missing from secrets")
            st.caption("Add `TTS_ENDPOINT = \"https://your-ngrok-url.ngrok-free.app\"` to Streamlit secrets.")

        if st.button("🔬 Test TTS now"):
            test_text = "You came here for a reason. Let's find out what it is."
            st.caption(f"Sending: _{test_text}_")
            audio_bytes, debug_msg = speak_as_samantha(test_text)
            if audio_bytes:
                st.success(debug_msg)
                play_voice(test_text, "[test]")
            else:
                st.error(debug_msg)
                if "could not reach" in debug_msg:
                    st.caption("💡 Make sure tts_server.py is running on Colab and the ngrok URL in secrets is current.")

        if st.button("🩺 Check server health"):
            if tts_endpoint:
                try:
                    r = requests.get(f"{tts_endpoint.rstrip('/')}/health", timeout=10)
                    if r.status_code == 200:
                        st.success(f"Server OK — {r.json()}")
                    else:
                        st.error(f"Server returned HTTP {r.status_code}")
                except Exception as e:
                    st.error(f"Could not reach server: {e}")
                    st.caption("The ngrok cloud endpoint exists but nothing is forwarded to it yet. "
                               "Run tts_server.py on Colab and connect the ngrok agent.")
            else:
                st.warning("No TTS_ENDPOINT configured.")

    with st.expander("⚙️ Model Status", expanded=False):
        if gemini_client:
            st.success("✅ Gemini 2.5 Pro — primary active")
        else:
            st.warning("⚠️ Gemini not configured — using Groq")
        if groq_client:
            st.info("🔁 Groq fallback ready")
        if hf_client:
            st.info("🔁 HuggingFace last resort ready")
        if not st.secrets.get("GEMINI_API_KEY", ""):
            st.caption("Add GEMINI_API_KEY to secrets to enable Gemini 2.5 Pro (free).")

    st.markdown("---")

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
            status_emoji = {
                "stranger":  "👁️",
                "applicant": "📋",
                "accepted":  "✦",
                "asset":     "💎",
                "dismissed": "🧊",
            }.get(db["relationship_status"], "•")
            st.caption(f"{status_emoji} Status: **{db['relationship_status'].title()}**")

        if db.get("session_count"):
            st.caption(f"📅 Sessions: {db['session_count']}")
        if db.get("occupation"):
            st.caption(f"💼 Occupation: {db['occupation']}")
        if db.get("location"):
            st.caption(f"📍 Location: {db['location']}")
        if db.get("age"):
            st.caption(f"🎂 Age: {db['age']}")
        if db.get("nicknames"):
            st.caption(f"🏷️ Her label: *{db['nicknames']}*")
        if db.get("notes"):
            st.caption(f"📝 Notes: {db['notes'][:120]}{'...' if len(db.get('notes','')) > 120 else ''}")

        for field, label, emoji in [
            ("insecurities", "Insecurities", "🩹"),
            ("soft_spots",   "Soft Spots",   "🎯"),
            ("boasts",       "Boasts",       "📣"),
            ("fears",        "Fears",        "⚠️"),
            ("desires",      "Desires",      "🔮"),
        ]:
            items = db.get(field)
            if items and isinstance(items, list) and len(items) > 0:
                st.caption(f"{emoji} **{label}:** {' · '.join(items[:3])}")

        deep = db.get("deep_profile") or {}
        if isinstance(deep, str):
            try:
                deep = json.loads(deep)
            except Exception:
                deep = {}

        if deep:
            st.markdown("---")
            st.markdown("**🗂️ Private File**")

            if deep.get("her_read"):
                st.caption(f"**Verdict:** _{deep['her_read']}_")
            if deep.get("dominant_trait"):
                st.caption(f"**Dominant trait:** {deep['dominant_trait']}")
            if deep.get("self_image_vs_reality"):
                with st.expander("Self-image gap", expanded=False):
                    st.caption(deep["self_image_vs_reality"])
            if deep.get("utility_assessment"):
                st.caption(f"**Utility:** {deep['utility_assessment']}")
            if deep.get("open_questions"):
                with st.expander(f"Open threads ({len(deep['open_questions'])})", expanded=False):
                    for q in deep["open_questions"][:5]:
                        st.caption(f"• {q}")
            if deep.get("recurring_patterns"):
                with st.expander(f"Patterns ({len(deep['recurring_patterns'])})", expanded=False):
                    for p in deep["recurring_patterns"][:5]:
                        st.caption(f"• {p}")

    st.markdown("---")
    st.write("**Protocol:**")
    st.caption("- Address her as 'Miss Samantha' or 'Boss'.")
    st.caption("- She wants to know you, not your job.")

    if st.button("Reset Interaction"):
        if st.session_state.messages and (groq_client or client):
            save_full_transcript(
                supabase,
                st.session_state.user_name,
                st.session_state.session_id,
                st.session_state.messages
            )
            _run_deep_synthesis()

        st.session_state.messages               = []
        st.session_state.profile                = {
            "submission": 0.2, "irritation": 0.1,
            "mood": "Observing", "goal": "learn_them",
            "_professional_count": 0,
        }
        st.session_state.session_id             = str(uuid.uuid4())
        st.session_state.opener_injected        = False
        st.session_state.last_deep_synthesis_at = 0
        st.session_state.static_prompt_core     = None
        st.rerun()
