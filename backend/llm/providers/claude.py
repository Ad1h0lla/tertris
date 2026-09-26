"""
Tetris LLM Providers — Anthropic Claude
=========================================

Wraps the ``anthropic`` SDK behind ``BaseLLMProvider``.

Model selection
---------------
Reads ``CLAUDE_MODEL`` from the environment.  Falls back to
``claude-sonnet-4-20250514`` — a known-valid, production-grade model ID.

The provider does NOT attempt model fallback internally.
The *router* handles provider-level fallback.

Credentials
-----------
Reads ``ANTHROPIC_API_KEY`` from the environment.
Never logs or exposes the key value.
"""

from __future__ import annotations

import os

from .base import BaseLLMProvider

# Sensible default: Claude Sonnet 4 — balanced cost/quality, known valid.
_DEFAULT_MODEL = "claude-sonnet-4-20250514"


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude adapter."""

    name = "claude"

    def is_available(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

    def get_model(self) -> str:
        return os.getenv("CLAUDE_MODEL", _DEFAULT_MODEL)

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        model = self.get_model()

        msg = client.messages.create(
            model=model,
            max_tokens=min(max_tokens, 8096),
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        content = msg.content
        if content and hasattr(content[0], "text"):
            text = content[0].text.strip()
            if text:
                return text

        if isinstance(content, str) and content.strip():
            return content.strip()

        raise RuntimeError(
            f"Claude returned empty content (model={model})"
        )
