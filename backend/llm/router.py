"""
Tetris LLM Router
==================

Central routing layer for all LLM calls.

Two public APIs
---------------
``get_llm_result(...)  -> LLMResponse``
    Structured API.  Returns an ``LLMResponse`` with status, content,
    provider metadata, and per-attempt diagnostics.
    Callers check ``result.success`` to decide how to proceed.

``get_llm_response(...) -> str``
    **Legacy compatibility wrapper.**  Returns the raw text string
    exactly as the original router did.  Existing specialist agents
    import and call this function — it MUST NOT change its return type.

Provider fallback chain
-----------------------
Each task is mapped to a *preferred* provider via ``LLM_ASSIGNMENTS``.
If the preferred provider fails, the router tries the remaining
configured providers in order.  Only providers with valid API keys
are attempted.

Configuration
-------------
- ``LLM_ASSIGNMENTS`` — task → preferred provider mapping
- ``CLAUDE_MODEL``    — env var for Claude model ID
- ``OPENAI_MODEL``    — env var for OpenAI model ID
- ``GROQ_MODEL``      — env var for Groq model ID
- ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GROQ_API_KEY`` — credentials
"""

from __future__ import annotations

import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .types import LLMAttempt, LLMCallStatus, LLMError, LLMResponse
from .providers import ClaudeProvider, GPT4Provider, GroqProvider
from .providers.base import BaseLLMProvider


# ── Task → preferred provider mapping ─────────────────────────────────────────
# Preserved from the original router.  New tasks can be added here.

LLM_ASSIGNMENTS = {
    "intake": "claude",
    "planning": "claude",
    "research": "groq",
    "search": "groq",
    "code": "claude",
    "review": "claude",
    "simulation": "groq",
    "pricing": "groq",
    "competitor_intel": "groq",
    "deployment": "groq",
    "summarization": "groq",
    "json_extraction": "groq",
    "general": "groq",
}


# ── Singleton provider instances ──────────────────────────────────────────────
# Created once, reused across calls.  No state beyond env-var reads.

_PROVIDERS: dict[str, BaseLLMProvider] = {
    "claude": ClaudeProvider(),
    "gpt4": GPT4Provider(),
    "groq": GroqProvider(),
}

# Fallback ordering when the preferred provider fails.
# The preferred provider is tried first; remaining providers are tried
# in the order they appear in this list.
_FALLBACK_ORDER = ["claude", "gpt4", "groq"]


# ── Structured API ────────────────────────────────────────────────────────────

def get_llm_result(
    task: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 3000,
    temperature: float = 0.2,
    strict: bool = False,
) -> LLMResponse:
    """
    Route an LLM call through the provider chain and return a structured
    ``LLMResponse``.

    Parameters
    ----------
    task : str
        Routing key (e.g. "code", "research", "review").
    system_prompt : str
        System prompt for the LLM.
    user_message : str
        User message content.
    max_tokens : int
        Maximum tokens to generate.
    temperature : float
        Sampling temperature.
    strict : bool
        If True, raise ``LLMError`` when all providers fail.
        If False (default), return an ``LLMResponse`` with
        ``status=FAILED``.

    Returns
    -------
    LLMResponse
        Structured result with status, content, and diagnostics.

    Raises
    ------
    LLMError
        Only when ``strict=True`` and all providers fail.
    """

    start_time = time.time()
    preferred_name = LLM_ASSIGNMENTS.get(task, "groq")
    attempts: list[LLMAttempt] = []

    # Build the ordered provider chain: preferred first, then fallbacks.
    # Only include providers that are actually configured.
    chain = _build_provider_chain(preferred_name)

    if not chain:
        # No providers configured at all.
        elapsed = (time.time() - start_time) * 1000
        result = LLMResponse(
            status=LLMCallStatus.FAILED,
            success=False,
            content="",
            provider="none",
            model="",
            task=task,
            latency_ms=elapsed,
            fallback_used=False,
            retry_count=0,
            error="No LLM providers are configured. "
                  "Set at least one of: GROQ_API_KEY, "
                  "ANTHROPIC_API_KEY, OPENAI_API_KEY in .env",
            attempts=[],
        )

        print(
            f"[LLM Router] NO PROVIDERS CONFIGURED for task={task}"
        )

        if strict:
            raise LLMError(task, [])

        return result

    # Try each provider in order.
    for idx, provider in enumerate(chain):
        attempt_start = time.time()
        model = provider.get_model()

        try:
            content = provider.call(
                system=system_prompt,
                user=user_message,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            attempt_ms = (time.time() - attempt_start) * 1000
            total_ms = (time.time() - start_time) * 1000

            attempt = LLMAttempt(
                provider=provider.name,
                model=model,
                latency_ms=attempt_ms,
                success=True,
            )
            attempts.append(attempt)

            is_fallback = (provider.name != preferred_name)
            status = (
                LLMCallStatus.DEGRADED if is_fallback
                else LLMCallStatus.SUCCESS
            )

            print(
                f"[LLM Router] {provider.name} succeeded "
                f"(model={model}, {len(content)} chars, "
                f"{attempt_ms:.0f}ms)"
            )

            return LLMResponse(
                status=status,
                success=True,
                content=content,
                provider=provider.name,
                model=model,
                task=task,
                latency_ms=total_ms,
                fallback_used=is_fallback,
                retry_count=idx,
                error=None,
                attempts=attempts,
            )

        except Exception as e:
            attempt_ms = (time.time() - attempt_start) * 1000
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"

            attempt = LLMAttempt(
                provider=provider.name,
                model=model,
                latency_ms=attempt_ms,
                success=False,
                error=error_msg,
            )
            attempts.append(attempt)

            print(
                f"[LLM Router] {provider.name} failed: "
                f"{error_msg[:120]}"
            )

    # All providers failed.
    total_ms = (time.time() - start_time) * 1000
    attempted_names = ", ".join(a.provider for a in attempts)
    error_summary = (
        f"All LLM providers failed for task '{task}'. "
        f"Attempted: [{attempted_names}]"
    )

    print(f"[LLM Router] ALL PROVIDERS FAILED for task={task}")

    if strict:
        raise LLMError(task, attempts)

    return LLMResponse(
        status=LLMCallStatus.FAILED,
        success=False,
        content="",
        provider="none",
        model="",
        task=task,
        latency_ms=total_ms,
        fallback_used=False,
        retry_count=len(attempts),
        error=error_summary,
        attempts=attempts,
    )


def _build_provider_chain(
    preferred: str,
) -> list[BaseLLMProvider]:
    """
    Build an ordered list of available providers.

    The preferred provider comes first, followed by the remaining
    providers in ``_FALLBACK_ORDER``.  Only providers whose
    ``is_available()`` returns True are included.
    """

    chain: list[BaseLLMProvider] = []
    seen: set[str] = set()

    # Preferred provider first.
    if preferred in _PROVIDERS:
        provider = _PROVIDERS[preferred]
        if provider.is_available():
            chain.append(provider)
            seen.add(preferred)

    # Then fallbacks in order.
    for name in _FALLBACK_ORDER:
        if name in seen:
            continue
        provider = _PROVIDERS.get(name)
        if provider and provider.is_available():
            chain.append(provider)
            seen.add(name)

    return chain


# ── Legacy compatibility API ──────────────────────────────────────────────────

def get_llm_response(
    task: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 3000,
    temperature: float = 0.2,
) -> str:
    """
    **Legacy wrapper** — returns a plain string, exactly as the
    original router did.

    Existing specialist agents import and call this function.
    Its signature and return type MUST NOT change.

    On success: returns the raw LLM text.
    On failure: returns the same markdown error message the original
    router returned, preserving backward compatibility.
    """

    result = get_llm_result(
        task=task,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=max_tokens,
        temperature=temperature,
        strict=False,
    )

    if result.success:
        return result.content

    # Return the same error format as the original router.
    return (
        "# OUTPUT GENERATION FAILED\n\n"
        f"All LLM providers failed for task: `{task}`\n\n"
        "**Troubleshooting:**\n"
        "1. Check `GROQ_API_KEY` is set in `.env`\n"
        "2. Check the backend terminal for specific error messages\n"
        "3. Verify the backend has internet access\n"
        "4. Check if Groq API is rate-limited at console.groq.com\n"
    )


def get_available_llms() -> dict:
    """Returns which LLMs are currently configured."""

    return {
        name: provider.is_available()
        for name, provider in _PROVIDERS.items()
    }
