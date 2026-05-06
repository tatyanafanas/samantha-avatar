# engine/memory_injection.py
"""
Aggressive memory injection system.
Ensures the LLM actually retrieves and uses memories from Supabase
by making them impossible to ignore in the system prompt.
"""

import json
from typing import Optional


def build_memory_context(
    profile: dict,
    history: str,
    current_conversation_length: int = 0,
) -> dict:
    """
    Build a comprehensive memory context dict that the LLM MUST see.
    This replaces scattered memory references with one unified block.
    
    Returns:
        {
            "has_prior_sessions": bool,
            "session_count": int,
            "relationship_status": str,
            "memory_block": str,  # formatted for prompt injection
            "living_hooks": str,  # actionable present-tense observations
        }
    """
    if not profile:
        profile = {}
    
    session_count = profile.get("session_count", 1)
    has_prior = session_count > 1
    status = profile.get("relationship_status", "stranger")
    
    # Build the main memory block
    memory_lines = []
    
    # ── Relationship Status ──
    memory_lines.append(f"RELATIONSHIP STATUS: {status.upper()}")
    if status == "accepted":
        memory_lines.append("→ This person has been accepted. They have proven themselves.")
        memory_lines.append("→ Maintain the standard. Do not soften.")
    elif status == "dismissed":
        memory_lines.append("→ This person has been dismissed.")
        memory_lines.append("→ Respond with cold distance. Your verdict is final.")
    elif status == "applicant":
        memory_lines.append("→ This person is under evaluation.")
        memory_lines.append("→ Extract. Bank everything. Do not commit.")
    
    # ── Session History ──
    if has_prior:
        memory_lines.append("")
        memory_lines.append(f"PRIOR SESSIONS: {session_count}")
        memory_lines.append(history or "No prior context available.")
    
    # ── Core Profile Facts ──
    memory_lines.append("")
    memory_lines.append("KNOWN FACTS ABOUT THIS PERSON:")
    
    facts = []
    if profile.get("name"):
        facts.append(f"Name: {profile['name']}")
    if profile.get("occupation"):
        facts.append(f"Occupation: {profile['occupation']}")
    if profile.get("location"):
        facts.append(f"Location: {profile['location']}")
    if profile.get("age"):
        facts.append(f"Age: {profile['age']}")
    if profile.get("nicknames"):
        facts.append(f"Your private name for them: '{profile['nicknames']}'")
    
    if facts:
        memory_lines.extend([f"  • {f}" for f in facts])
    else:
        memory_lines.append("  • Nothing on file yet. This is a fresh start.")
    
    # ── Psychological Profile (Deep Analysis) ──
    deep = profile.get("deep_profile") or {}
    if isinstance(deep, str):
        try:
            deep = json.loads(deep)
        except:
            deep = {}
    
    if deep:
        memory_lines.append("")
        memory_lines.append("YOUR PRIVATE ASSESSMENT:")
        
        if deep.get("her_read"):
            memory_lines.append(f"  Verdict: {deep['her_read']}")
        if deep.get("dominant_trait"):
            memory_lines.append(f"  Core trait: {deep['dominant_trait']}")
        if deep.get("self_image_vs_reality"):
            memory_lines.append(f"  Self-image gap: {deep['self_image_vs_reality']}")
        if deep.get("utility_assessment"):
            memory_lines.append(f"  Their utility: {deep['utility_assessment']}")
    
    # ── Observable Patterns ──
    memory_lines.append("")
    memory_lines.append("WHAT YOU'VE OBSERVED:")
    
    observations = []
    if profile.get("insecurities"):
        items = profile["insecurities"]
        if isinstance(items, list):
            observations.extend([f"Insecurity: {i}" for i in items[:3]])
    if profile.get("soft_spots"):
        items = profile["soft_spots"]
        if isinstance(items, list):
            observations.extend([f"Soft spot: {i}" for i in items[:3]])
    if profile.get("boasts"):
        items = profile["boasts"]
        if isinstance(items, list):
            observations.extend([f"Volunteered proudly: {i}" for i in items[:3]])
    
    if deep and deep.get("open_questions"):
        items = deep["open_questions"]
        if isinstance(items, list):
            observations.extend([f"Unresolved: {i}" for i in items[:2]])
    
    if observations:
        memory_lines.extend([f"  • {o}" for o in observations[:6]])
    else:
        memory_lines.append("  • No patterns detected yet.")
    
    # ── Memory Rules (Critical) ──
    memory_lines.append("")
    memory_lines.append("MEMORY RULES FOR THIS TURN:")
    memory_lines.append("  → You know this person. Act like it.")
    memory_lines.append("  → Do NOT announce that you remember something.")
    memory_lines.append("  → Use memory as leverage, context, or contradiction fuel — never as warmth.")
    if has_prior:
        memory_lines.append("  → They have been here before. Let that inform your tone.")
    if deep and deep.get("open_questions"):
        memory_lines.append("  → You have unresolved threads. Pursue them subtly.")
    
    memory_block = "\n".join(memory_lines)
    
    return {
        "has_prior_sessions": has_prior,
        "session_count": session_count,
        "relationship_status": status,
        "memory_block": memory_block,
    }


def inject_memory_into_system_prompt(
    system_prompt: str,
    memory_context: dict,
    position: str = "early"  # "early" or "late"
) -> str:
    """
    Inject memory context into the system prompt at a strategic location.
    
    Args:
        system_prompt: The existing system prompt
        memory_context: Output from build_memory_context()
        position: Where to inject ("early" = right after identity, "late" = before final rules)
    
    Returns:
        Updated system prompt with memory prominently featured
    """
    memory_block = memory_context.get("memory_block", "")
    
    if not memory_block:
        return system_prompt
    
    memory_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTIVE MEMORY — RETRIEVE THIS NOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{memory_block}

"""
    
    if position == "early":
        # Insert after "YOU ARE SAMANTHA" but before most other sections
        if "THE PRIME DIRECTIVE" in system_prompt:
            idx = system_prompt.find("THE PRIME DIRECTIVE")
            return system_prompt[:idx] + memory_section + system_prompt[idx:]
        elif "IDENTITY" in system_prompt:
            idx = system_prompt.find("IDENTITY")
            # Find the end of identity section (next ━━ or section header)
            end_idx = system_prompt.find("━━", idx + 100)
            if end_idx != -1:
                end_idx = system_prompt.find("\n", end_idx + 5)
                return system_prompt[:end_idx] + "\n\n" + memory_section + system_prompt[end_idx:]
    
    # Default: late insertion (before final rules)
    if "FINAL RULE" in system_prompt or "HARD BEHAVIOUR" in system_prompt:
        idx = system_prompt.find("FINAL RULE")
        if idx == -1:
            idx = system_prompt.find("HARD BEHAVIOUR")
        if idx != -1:
            return system_prompt[:idx] + memory_section + system_prompt[idx:]
    
    # Fallback: just prepend after system identity
    return memory_section + system_prompt


def detect_returning_user_state(profile: dict) -> str:
    """
    Return a description of the user's 'state' when they return.
    Used to inform tone, approach, and opener.
    """
    session_count = profile.get("session_count", 1)
    status = profile.get("relationship_status", "stranger")
    
    if session_count <= 1:
        return "new_user"
    elif status == "dismissed":
        return "returning_dismissed"
    elif status == "accepted":
        return "returning_accepted"
    elif status == "applicant":
        return "returning_under_evaluation"
    else:
        return "returning_stranger"
