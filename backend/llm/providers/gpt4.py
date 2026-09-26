"""
Tetris LLM Providers — OpenAI GPT
===================================

Wraps the ``openai`` SDK behind ``BaseLLMProvider``.

Model selection
---------------
Reads ``OPENAI_MODEL`` from the environment.  Falls back to
``gpt-4o`` — still accessible via the OpenAI API as of 2026-09.

Credentials
-----------
Reads ``OPENAI_API_KEY`` from the environment.
Never logs or exposes the key value.
"""

from __future__ import annotations

import os

from .base import BaseLLMProvider

# GPT-4o remains accessible via API.  Configurable for migration.
_DEFAULT_MODEL = "gpt-4o"


class GPT4Provider(BaseLLMProvider):
    """OpenAI GPT adapter."""

    name = "gpt4"

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def get_model(self) -> str:
        return os.getenv("OPENAI_MODEL", _DEFAULT_MODEL)

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        from openai import OpenAI

        client = OpenAI(api_key=api_key)

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
            f"OpenAI returned empty content (model={model})"
        )
