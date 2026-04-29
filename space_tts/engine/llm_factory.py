"""Lightweight LLM client factory for free cloud providers (Hugging Face).

This module returns a small wrapper compatible with the `client` interface
expected by `engine.memory._call_with_fallback` and
`engine.memory.synthesise_deep_profile` (i.e., `client.chat.completions.create(...)`).

Behavior:
- If `HF_API_KEY` is set in the environment, returns a simple Hugging Face
  inference wrapper that POSTS to `https://api-inference.huggingface.co/models/{model}`.
- If no key is present, returns `None` so callers can fall back to local
  synthesiser behaviour.

Notes:
- Hugging Face free-tier keys work but have quotas; choose a hosted model
  that supports text-generation/inference.
"""
import os
import json
import requests
from types import SimpleNamespace
from typing import Optional


def _hf_post_model(api_key: str, model: str, prompt: str, temperature: float = 0.3, max_new_tokens: int = 512):
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "inputs": prompt,
        "parameters": {"temperature": temperature, "max_new_tokens": max_new_tokens},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


class _HFCompletions:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def create(self, model: str, messages: list, temperature: float = 0.3):
        # Convert chat-style messages to a single prompt string
        parts = []
        for m in messages:
            role = (m.get("role") or "user").upper()
            content = m.get("content") or ""
            parts.append(f"[{role}]: {content}")
        prompt = "\n".join(parts)

        out = _hf_post_model(self.api_key, model, prompt, temperature=temperature)

        # Parse common HF shapes
        text = None
        if isinstance(out, list) and out:
            first = out[0]
            if isinstance(first, dict) and "generated_text" in first:
                text = first["generated_text"]
            else:
                text = json.dumps(first)
        elif isinstance(out, dict):
            if "generated_text" in out:
                text = out["generated_text"]
            elif "error" in out:
                raise Exception(out["error"])
            else:
                text = json.dumps(out)
        else:
            text = str(out)

        # Return an object with .choices[0].message.content to mimic other clients
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class HFClientWrapper:
    def __init__(self, api_key: str):
        self.chat = SimpleNamespace(completions=_HFCompletions(api_key))


def get_client(provider: str = "hf") -> Optional[object]:
    """Return a client object for the requested provider, or None.

    Currently only supports Hugging Face (`provider='hf'`).
    Requires `HF_API_KEY` in the environment to return a client.
    """
    if provider != "hf":
        return None

    api_key = os.environ.get("HF_API_KEY")
    if not api_key:
        return None
    return HFClientWrapper(api_key)


__all__ = ["get_client"]
