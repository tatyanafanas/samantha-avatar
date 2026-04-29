"""Prompt registry: centralized storage and rendering for prompt fragments.

This simple registry lets the app register named prompt fragments (strings
or callables) and fetch or render them in a consistent way. It's intentionally
small — a foundation for more advanced prompt templating later.
"""
from typing import Callable, Dict, Any


class PromptRegistry:
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def register(self, name: str, value: Any):
        """Register a string or callable under `name`.

        If `value` is callable it will be called with any kwargs passed to
        `render` when fetching.
        """
        self._store[name] = value

    def get(self, name: str):
        return self._store.get(name)

    def render(self, name: str, **kwargs) -> str | None:
        v = self._store.get(name)
        if v is None:
            return None
        if callable(v):
            return v(**kwargs)
        return v


# module-level singleton
registry = PromptRegistry()


def register(name: str, value: Any):
    registry.register(name, value)


def get(name: str):
    return registry.get(name)


def render(name: str, **kwargs):
    return registry.render(name, **kwargs)
