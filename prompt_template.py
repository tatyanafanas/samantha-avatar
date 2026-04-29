"""Minimal template renderer for prompt composition.

Supports simple placeholders like {{name}} and fragment references
like {{fragment:static_prompt_core}} which call into the prompt registry.

This is intentionally small and dependency-free to keep behavior deterministic
and easily auditable for persona-sensitive prompts.
"""
import re
from typing import Mapping
from engine import prompt_registry


_PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+)\s*}}")


def render_template(template: str, context: Mapping[str, object] | None = None) -> str:
    """Render `template` by replacing placeholders with `context` values.

    - If a placeholder starts with `fragment:NAME`, it will call
      `prompt_registry.render(NAME, **context)` and insert the result.
    - Missing keys are replaced with an empty string.
    - Values are converted to str() before insertion.
    """
    context = context or {}

    def _repl(match):
        key = match.group(1).strip()
        if key.startswith("fragment:"):
            frag = key.split(":", 1)[1].strip()
            try:
                return str(prompt_registry.render(frag, **context) or "")
            except Exception:
                return ""
        # simple context lookup
        val = context.get(key)
        return "" if val is None else str(val)

    return _PLACEHOLDER_RE.sub(_repl, template)
