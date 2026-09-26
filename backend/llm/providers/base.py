"""
Tetris LLM Providers — Base Class
==================================

Abstract base for all LLM provider adapters.

Each provider must implement:
  - ``is_available()`` — check if API key is configured
  - ``call()`` — make the actual API call and return raw text

Providers MUST raise on failure (the router handles fallback).
Providers MUST NOT return fake/canned content.
Providers MUST NOT log or expose credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM provider adapters.

    Attributes
    ----------
    name : str
        Provider identifier ("claude", "groq", "gpt4").
    """

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if this provider is configured with valid credentials.

        Must NOT make a network call — only check environment/config.
        """

    @abstractmethod
    def get_model(self) -> str:
        """
        Return the model identifier that will be used for the next call.

        This is read from environment or config, never hardcoded.
        """

    @abstractmethod
    def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Make the actual API call and return the raw response text.

        Raises
        ------
        Exception
            Any exception is acceptable — the router catches it and
            records it as an ``LLMAttempt`` with ``success=False``.

        Returns
        -------
        str
            Non-empty response text.  Returning an empty string is
            treated as a failure by the router.
        """
