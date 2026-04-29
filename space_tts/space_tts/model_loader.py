"""Small model loader for the Space.

Default behaviour: if `model/samantha.wav` exists in the repo, return that file
for any input text (useful when you already have a single cloned voice file).

To use a real model, replace `generate()` with a call into your TTS model
API (Qwen3-TTS, Coqui TTS, etc.) that returns WAV bytes or a filepath.
"""
import os
from pathlib import Path

MODEL_WAV = Path("model") / "samantha.wav"


def load_model():
    """Placeholder: load model resources if needed. Returns a model handle or None."""
    if MODEL_WAV.exists():
        return True
    return None


def generate(text: str):
    """Generate speech for `text`.

    Returns either bytes (wav) or a path to a wav file.
    Default: return the static `model/samantha.wav` file if present.
    """
    if MODEL_WAV.exists():
        return str(MODEL_WAV)

    # Example placeholder for integrating a real model:
    # model = load_qwen_tts(...)
    # wav_bytes = model.generate_voice_clone(text=..., ref_audio=..., ref_text=...)
    # return wav_bytes

    raise RuntimeError(
        "No model available. Place a WAV file at 'model/samantha.wav' or implement generate() to call your TTS model."
    )
