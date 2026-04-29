"""Batch-run deep profile synthesis for all local profiles.

Tries to call `memory.synthesise_deep_profile` with a provided `client`.
If no `client` is provided and `use_local_fallback=True`, synthesises a
lightweight deep profile using local heuristics and persists it via
`memory.update_profile`.

Run like:
    python -m engine.deep_profile_batch
"""
import json
from pathlib import Path
from typing import Optional

from engine import memory


DATA_DIR = Path("data")
PROFILES_DIR = DATA_DIR / "profiles"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"


def _gather_messages_for_user(name: str) -> list:
    messages = []
    if not TRANSCRIPTS_DIR.exists():
        return messages
    for p in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if obj.get("user_name") == name:
                msgs = obj.get("messages") or []
                if isinstance(msgs, list):
                    messages.extend(msgs)
        except Exception:
            continue
    return messages


def _local_synthesiser(name: str, messages: list, profile: dict) -> dict:
    """Create a conservative deep_profile using available local fields.

    This avoids failing when no LLM client is configured.
    """
    notes = profile.get("notes") or ""
    insecurities = profile.get("insecurities") or []
    soft_spots = profile.get("soft_spots") or []
    nick = profile.get("nicknames") or profile.get("nick_name") or ""

    her_read = notes.splitlines()[0] if notes else f"Limited data on {name}."
    dominant = (insecurities[0] if isinstance(insecurities, list) and insecurities else
                (soft_spots[0] if isinstance(soft_spots, list) and soft_spots else "unknown"))

    deep = {
        "her_read": her_read[:200],
        "dominant_trait": dominant,
        "pressure_points": soft_spots[:5] if isinstance(soft_spots, list) else [],
        "open_questions": [],
        "recurring_patterns": insecurities[:5] if isinstance(insecurities, list) else [],
        "self_image_vs_reality": "",
        "utility_assessment": "",
        "nicknames": nick,
    }
    return deep


def _merge_deep_profiles(existing: dict, new: dict) -> dict:
    """Merge two deep_profile dicts conservatively and return the merged result.

    - Arrays are unioned (deduplicated).
    - Scalars prefer `new` when non-empty, otherwise keep `existing`.
    """
    merged = dict(existing or {})
    # Merge array fields
    for arr_field in ["pressure_points", "open_questions", "recurring_patterns"]:
        old = existing.get(arr_field) if isinstance(existing.get(arr_field), list) else []
        new_items = new.get(arr_field) if isinstance(new.get(arr_field), list) else []
        merged[arr_field] = list({*old, *new_items})

    # Scalars: prefer new when present
    scalar_fields = [
        "her_read", "dominant_trait", "self_image_vs_reality",
        "utility_assessment", "nicknames"
    ]
    for f in scalar_fields:
        n = new.get(f)
        if n:
            merged[f] = n
        else:
            if existing.get(f) is not None:
                merged[f] = existing.get(f)

    return merged


def synthesize_all(client: Optional[object] = None, use_local_fallback: bool = True, merge_existing: bool = False) -> dict:
    """Synthesize deep_profile for every profile in `data/profiles`.

    - If `client` is provided, calls `memory.synthesise_deep_profile(client, None, ...)`.
    - Otherwise, if `use_local_fallback` is True, writes a conservative
      `deep_profile` produced by `_local_synthesiser`.

    Returns a summary dict with counts.
    """
    results = {"processed": 0, "synthesised": 0, "skipped": 0}

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for p in PROFILES_DIR.glob("*.json"):
        try:
            profile = json.loads(p.read_text(encoding="utf-8"))
            name = profile.get("name") or p.stem
            messages = _gather_messages_for_user(name)
            results["processed"] += 1

            if client:
                # Let memory.synthesise_deep_profile produce a new deep profile dict
                new_deep = memory.synthesise_deep_profile(client, None, name, messages, profile)
                if new_deep:
                    # If requested, merge with existing deep_profile
                    if merge_existing:
                        existing_raw = profile.get("deep_profile") or {}
                        try:
                            existing = json.loads(existing_raw) if isinstance(existing_raw, str) else existing_raw
                        except Exception:
                            existing = existing_raw or {}
                        merged = _merge_deep_profiles(existing, new_deep)
                        memory.update_profile(None, name, {"deep_profile": json.dumps(merged)})
                    results["synthesised"] += 1
                else:
                    results["skipped"] += 1
            else:
                if use_local_fallback:
                    new_deep = _local_synthesiser(name, messages, profile)
                    if merge_existing:
                        existing_raw = profile.get("deep_profile") or {}
                        try:
                            existing = json.loads(existing_raw) if isinstance(existing_raw, str) else existing_raw
                        except Exception:
                            existing = existing_raw or {}
                        merged = _merge_deep_profiles(existing, new_deep)
                        memory.update_profile(None, name, {"deep_profile": json.dumps(merged)})
                    else:
                        # Persist as JSON string to match existing behavior
                        memory.update_profile(None, name, {"deep_profile": json.dumps(new_deep)})
                    results["synthesised"] += 1
                else:
                    results["skipped"] += 1

        except Exception:
            results["skipped"] += 1
            continue

    return results


if __name__ == "__main__":
    print("Running batch deep profile synthesis (local fallback enabled)...")
    out = synthesize_all(client=None, use_local_fallback=True)
    print("Done:", out)