"""
Tetris LLM Layer — Structured Types
====================================

Defines the failure contract for the LLM provider abstraction.

LLMResponse replaces the raw-string return value with a structured
object that distinguishes SUCCESS / DEGRADED / FAILED outcomes.

This module is imported by:
  - llm/providers/base.py
  - llm/router.py
  - (future) specialist agents, octopus workers

It does NOT import anything from the Tetris codebase — it is a leaf
dependency with no side effects.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional


class LLMCallStatus(str, enum.Enum):
    """
    Three-way outcome for an LLM routing attempt.

    SUCCESS   — a provider returned usable content.
    DEGRADED  — a fallback provider answered (not the preferred one).
    FAILED    — every provider in the chain failed.
    """

    SUCCESS = "SUCCESS"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LLMAttempt:
    """
    Diagnostic record for a single provider attempt.

    Never contains credentials — only provider name, model ID,
    wall-clock latency, and an optional error message.
    """

    provider: str          # "claude", "groq", "gpt4"
    model: str             # exact model ID used
    latency_ms: float      # wall-clock milliseconds
    success: bool          # did this attempt return content?
    error: Optional[str] = None  # human-readable error if failed


@dataclass(frozen=True)
class LLMResponse:
    """
    Structured return value from ``get_llm_result()``.

    Callers check ``response.status`` (or ``response.success``) to decide
    how to handle the result.

    Fields
    ------
    status : LLMCallStatus
        SUCCESS / DEGRADED / FAILED.
    success : bool
        Convenience shortcut: True when status != FAILED.
    content : str
        Raw LLM text.  Empty string on failure — never None.
    provider : str
        Which provider answered ("claude", "groq", "gpt4", "none").
    model : str
        Exact model ID that produced the content ("" on failure).
    task : str
        The task key that was passed to the router.
    latency_ms : float
        Total wall-clock time for the entire routing attempt (ms).
    fallback_used : bool
        True if the winning provider was not the preferred one.
    retry_count : int
        How many providers were attempted before one succeeded (or all
        failed).
    error : Optional[str]
        Human-readable diagnostic when status == FAILED.
    attempts : List[LLMAttempt]
        Per-provider attempt records for observability.
    """

    status: LLMCallStatus
    success: bool
    content: str
    provider: str
    model: str
    task: str
    latency_ms: float
    fallback_used: bool = False
    retry_count: int = 0
    error: Optional[str] = None
    attempts: List[LLMAttempt] = field(default_factory=list)


class LLMError(Exception):
    """
    Raised when all providers fail and the caller requested ``strict=True``.

    Attributes
    ----------
    task : str
        The routing task key.
    attempts : List[LLMAttempt]
        Diagnostic records for every provider that was tried.
    """

    def __init__(self, task: str, attempts: List[LLMAttempt]) -> None:
        self.task = task
        self.attempts = attempts
        providers = ", ".join(a.provider for a in attempts) or "none configured"
        super().__init__(
            f"All LLM providers failed for task '{task}'. "
            f"Attempted: [{providers}]"
        )
