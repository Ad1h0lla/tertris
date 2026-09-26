"""
Tetris LLM Providers — Groq
=============================

Wraps the ``groq`` SDK behind ``BaseLLMProvider``.

Model selection
---------------
Reads ``GROQ_MODEL`` from the environment.  Falls back to
``llama-3.3-70b-versatile`` — a known-valid Groq model.

The original recovered code used ``openai/gpt-oss-120b`` which is a
suspicious/unverified model identifier.  This provider uses the
well-documented Llama 3.3 model by default.

Credentials
-----------
Reads ``GROQ_API_KEY`` from the environment.
Never logs or exposes the key value.
"""

from __future__ import annotations

import os

from .base import BaseLLMProvider

# Llama 3.3 70B: verified production model on Groq.
_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqProvider(BaseLLMProvider):
    """Groq adapter (OpenAI-compatible API)."""

    name = "groq"

    def is_available(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    def get_model(self) -> str:
        return os.getenv("GROQ_MODEL", _DEFAULT_MODEL)

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

        from groq import Groq

        client = Groq(api_key=api_key)

        model = self.get_model()

        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()

        raise RuntimeError(
            f"Groq returned empty content (model={model})"
        )
