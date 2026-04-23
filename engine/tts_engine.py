"""
engine/tts_engine.py
TTS voice generation for Samantha using Qwen3-TTS voice cloning.
Designed to run on a separate Colab/server instance and be called via HTTP,
OR run locally if a GPU is available.

Two modes:
  1. LOCAL  — model loaded in-process (GPU required)
  2. REMOTE — calls a FastAPI endpoint wrapping the model (recommended for Streamlit Cloud)
"""

import io
import os
import re
import time
import base64
import hashlib
import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# TEXT PREPROCESSING
# Better punctuation → better prosody
# ---------------------------------------------------------------------------

# Ugandan currency / common abbreviations Samantha would say
_ABBREV_MAP = {
    r'\bShs\b': 'shillings',
    r'\bUGX\b': 'ugandan shillings',
    r'\bMPs?\b': 'Member of Parliament',
    r'\bDr\.?\b': 'Doctor',
    r'\bMaj\.?\b': 'Major',
    r'\bRtd\.?\b': 'Retired',
    r'\bBSc\b': 'Bachelor of Science',
    r'\bBA\b': 'Bachelor of Arts',
    r'\bCEO\b': 'C.E.O',
    r'\bMD\b': 'Managing Director',
    r'\bPR\b': 'P.R',
    r'(\d+)k\b': r'\1 thousand',
    r'(\d+)[Mm]\b': r'\1 million',
    r'(\d+)[Bb]\b': r'\1 billion',
}

def preprocess_text(text: str) -> str:
    """
    Clean and normalize text before TTS synthesis.
    - Expand abbreviations
    - Normalize punctuation for natural pausing
    - Chunk-safe: strip trailing whitespace
    """
    for pattern, replacement in _ABBREV_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Em-dash and ellipsis → pause-friendly punctuation
    text = text.replace('—', ', ')
    text = text.replace('–', ', ')
    text = text.replace('...', '.')
    text = text.replace('…', '.')

    # Normalise multiple spaces / newlines
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def chunk_text(text: str, max_chars: int = 200) -> list[str]:
    """
    Split text into sentence-level chunks for better TTS quality.
    Long single-pass generations drift — chunking keeps prosody tight.
    Each chunk ends at a sentence boundary where possible.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ''

    for sentence in sentences:
        if len(current) + len(sentence) <= max_chars:
            current = (current + ' ' + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# AUDIO UTILITIES
# ---------------------------------------------------------------------------

def audio_to_base64(audio_data: np.ndarray, sample_rate: int) -> str:
    """Convert numpy audio array to base64-encoded WAV string."""
    buffer = io.BytesIO()
    sf.write(buffer, audio_data, sample_rate, format='WAV')
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')


def concat_audio(chunks: list[tuple[np.ndarray, int]]) -> tuple[np.ndarray, int]:
    """Concatenate audio chunks with a small silence gap between each."""
    if not chunks:
        return np.array([]), 22050

    sr = chunks[0][1]
    silence = np.zeros(int(sr * 0.15))  # 150ms silence between chunks

    arrays = []
    for i, (audio, _) in enumerate(chunks):
        audio = np.squeeze(audio)
        arrays.append(audio)
        if i < len(chunks) - 1:
            arrays.append(silence)

    return np.concatenate(arrays), sr


# ---------------------------------------------------------------------------
# LOCAL MODE — model loaded in-process
# Use this if running Streamlit with GPU access (Colab with tunnel, etc.)
# ---------------------------------------------------------------------------

_local_model = None
_local_model_config = {}

def load_local_model(
    model_name: str = 'Qwen/Qwen2.5-Omni-7B',
    ref_audio_path: str = 'voice/samantha_ref.wav',
    ref_text: str = '',
    language: str = 'en',
):
    """Load the TTS model once and cache it."""
    global _local_model, _local_model_config
    if _local_model is not None:
        return  # already loaded

    try:
        # Import only if running locally — avoids import errors on CPU-only hosts
        from qwen_tts import QwenTTS  # adjust to actual import path for your model
        _local_model = QwenTTS.from_pretrained(model_name)
        _local_model_config = {
            'ref_audio': ref_audio_path,
            'ref_text': ref_text,
            'language': language,
        }
    except ImportError:
        raise RuntimeError(
            "qwen_tts not available in this environment. "
            "Use REMOTE mode or run on a GPU Colab instance."
        )


def generate_local(text: str) -> tuple[np.ndarray, int] | None:
    """Generate audio locally using the loaded model."""
    if _local_model is None:
        raise RuntimeError("Model not loaded. Call load_local_model() first.")

    chunks = chunk_text(preprocess_text(text))
    audio_chunks = []

    for chunk in chunks:
        wavs, sr = _local_model.generate_voice_clone(
            text=chunk,
            language=_local_model_config['language'],
            ref_audio=_local_model_config['ref_audio'],
            ref_text=_local_model_config['ref_text'],
        )
        audio = wavs[0] if isinstance(wavs, list) else wavs
        if hasattr(audio, 'cpu'):
            audio = audio.cpu().numpy()
        audio_chunks.append((audio, sr))

    return concat_audio(audio_chunks)


# ---------------------------------------------------------------------------
# REMOTE MODE — calls a FastAPI endpoint (recommended)
# Deploy the model on Colab + ngrok or a GPU server, call it from Streamlit.
# ---------------------------------------------------------------------------

def generate_remote(
    text: str,
    endpoint_url: str,
    timeout: int = 60,
) -> tuple[np.ndarray, int] | None:
    """
    Call a remote TTS API endpoint.

    Expected endpoint: POST /generate
    Request body:  { "text": "...", "chunk": true }
    Response body: { "audio_b64": "...", "sample_rate": 22050 }
    """
    import requests

    processed = preprocess_text(text)

    try:
        resp = requests.post(
            f"{endpoint_url.rstrip('/')}/generate",
            json={"text": processed, "chunk": True},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        audio_bytes = base64.b64decode(data['audio_b64'])
        buffer = io.BytesIO(audio_bytes)
        audio, sr = sf.read(buffer)
        return audio, sr

    except Exception as e:
        print(f"[TTS Remote] Error: {e}")
        return None


# ---------------------------------------------------------------------------
# UNIFIED INTERFACE
# Used by app.py — auto-selects local or remote based on config.
# ---------------------------------------------------------------------------

def generate_speech(
    text: str,
    mode: str = 'remote',         # 'local' or 'remote'
    endpoint_url: str | None = None,
) -> str | None:
    """
    Generate speech and return base64-encoded WAV string.
    Returns None on failure (app continues without audio).

    Args:
        text:         The text to synthesize (Samantha's reply)
        mode:         'local' (GPU in-process) or 'remote' (API call)
        endpoint_url: Required for remote mode. Set via st.secrets['TTS_ENDPOINT'].
    """
    try:
        if mode == 'local':
            result = generate_local(text)
        elif mode == 'remote':
            if not endpoint_url:
                return None
            result = generate_remote(text, endpoint_url)
        else:
            return None

        if result is None:
            return None

        audio, sr = result
        return audio_to_base64(audio, sr)

    except Exception as e:
        print(f"[TTS] Speech generation failed: {e}")
        return None
