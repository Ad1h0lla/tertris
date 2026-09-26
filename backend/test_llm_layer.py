"""
Tetris LLM Layer — Milestone 1A Unit Tests
============================================

Tests the LLM provider abstraction and failure contract.

Test coverage
-------------
1. Primary provider success
2. Primary failure → fallback success (DEGRADED)
3. All providers fail (FAILED)
4. No providers configured at all
5. Legacy get_llm_response() returns a string
6. Structured get_llm_result() returns LLMResponse
7. strict=True raises LLMError on total failure
8. Provider chain ordering
9. LLMResponse fields are correct
10. get_available_llms() reflects config

All tests use mocked provider boundaries — no real API calls.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure .env is loaded before imports
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from llm.types import LLMResponse, LLMCallStatus, LLMAttempt, LLMError
from llm.providers.base import BaseLLMProvider
from llm.providers.claude import ClaudeProvider
from llm.providers.gpt4 import GPT4Provider
from llm.providers.groq import GroqProvider
from llm.router import (
    get_llm_result,
    get_llm_response,
    get_available_llms,
    _build_provider_chain,
    _PROVIDERS,
    LLM_ASSIGNMENTS,
)


class TestLLMTypes(unittest.TestCase):
    """Test the type definitions."""

    def test_llm_call_status_values(self):
        self.assertEqual(LLMCallStatus.SUCCESS, "SUCCESS")
        self.assertEqual(LLMCallStatus.DEGRADED, "DEGRADED")
        self.assertEqual(LLMCallStatus.FAILED, "FAILED")

    def test_llm_response_success_fields(self):
        resp = LLMResponse(
            status=LLMCallStatus.SUCCESS,
            success=True,
            content="Hello world",
            provider="groq",
            model="llama-3.3-70b-versatile",
            task="test",
            latency_ms=123.4,
            fallback_used=False,
            retry_count=0,
            error=None,
            attempts=[],
        )
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Hello world")
        self.assertEqual(resp.provider, "groq")
        self.assertIsNone(resp.error)

    def test_llm_response_failure_fields(self):
        resp = LLMResponse(
            status=LLMCallStatus.FAILED,
            success=False,
            content="",
            provider="none",
            model="",
            task="code",
            latency_ms=500.0,
            retry_count=3,
            error="All providers failed",
            attempts=[],
        )
        self.assertFalse(resp.success)
        self.assertEqual(resp.content, "")
        self.assertEqual(resp.provider, "none")
        self.assertEqual(resp.error, "All providers failed")

    def test_llm_attempt_dataclass(self):
        attempt = LLMAttempt(
            provider="claude",
            model="claude-sonnet-4-20250514",
            latency_ms=200.0,
            success=True,
        )
        self.assertTrue(attempt.success)
        self.assertIsNone(attempt.error)

    def test_llm_error_exception(self):
        attempts = [
            LLMAttempt(provider="groq", model="x", latency_ms=100, success=False, error="timeout"),
        ]
        err = LLMError("code", attempts)
        self.assertIn("code", str(err))
        self.assertIn("groq", str(err))
        self.assertEqual(err.task, "code")
        self.assertEqual(len(err.attempts), 1)

    def test_llm_response_is_frozen(self):
        resp = LLMResponse(
            status=LLMCallStatus.SUCCESS,
            success=True, content="x", provider="groq",
            model="m", task="t", latency_ms=1.0,
        )
        with self.assertRaises(AttributeError):
            resp.content = "changed"  # type: ignore


class TestProviders(unittest.TestCase):
    """Test provider classes in isolation."""

    def test_claude_not_available_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            p = ClaudeProvider()
            self.assertFalse(p.is_available())

    def test_claude_available_with_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            p = ClaudeProvider()
            self.assertTrue(p.is_available())

    def test_gpt4_not_available_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            p = GPT4Provider()
            self.assertFalse(p.is_available())

    def test_gpt4_available_with_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            p = GPT4Provider()
            self.assertTrue(p.is_available())

    def test_groq_not_available_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GROQ_API_KEY", None)
            p = GroqProvider()
            self.assertFalse(p.is_available())

    def test_groq_available_with_key(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}):
            p = GroqProvider()
            self.assertTrue(p.is_available())

    def test_model_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            # Clear any custom model env vars
            for key in ("CLAUDE_MODEL", "OPENAI_MODEL", "GROQ_MODEL"):
                os.environ.pop(key, None)
            self.assertEqual(ClaudeProvider().get_model(), "claude-sonnet-4-20250514")
            self.assertEqual(GPT4Provider().get_model(), "gpt-4o")
            self.assertEqual(GroqProvider().get_model(), "llama-3.3-70b-versatile")

    def test_model_from_env(self):
        with patch.dict(os.environ, {
            "CLAUDE_MODEL": "claude-opus-5",
            "OPENAI_MODEL": "gpt-5.6-terra",
            "GROQ_MODEL": "llama-4-scout-17b-16e-instruct",
        }):
            self.assertEqual(ClaudeProvider().get_model(), "claude-opus-5")
            self.assertEqual(GPT4Provider().get_model(), "gpt-5.6-terra")
            self.assertEqual(GroqProvider().get_model(), "llama-4-scout-17b-16e-instruct")

    def test_claude_call_raises_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            p = ClaudeProvider()
            with self.assertRaises(RuntimeError):
                p.call("sys", "usr", 100, 0.1)

    def test_groq_call_raises_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GROQ_API_KEY", None)
            p = GroqProvider()
            with self.assertRaises(RuntimeError):
                p.call("sys", "usr", 100, 0.1)

    def test_gpt4_call_raises_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            p = GPT4Provider()
            with self.assertRaises(RuntimeError):
                p.call("sys", "usr", 100, 0.1)

    def test_provider_names(self):
        self.assertEqual(ClaudeProvider.name, "claude")
        self.assertEqual(GPT4Provider.name, "gpt4")
        self.assertEqual(GroqProvider.name, "groq")

    def test_base_provider_is_abstract(self):
        with self.assertRaises(TypeError):
            BaseLLMProvider()  # type: ignore


class TestProviderChain(unittest.TestCase):
    """Test the provider chain builder."""

    def test_chain_with_all_providers(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk_test",
            "ANTHROPIC_API_KEY": "sk_test",
            "OPENAI_API_KEY": "sk_test",
        }):
            chain = _build_provider_chain("claude")
            names = [p.name for p in chain]
            self.assertEqual(names[0], "claude")
            self.assertIn("groq", names)
            self.assertIn("gpt4", names)
            self.assertEqual(len(names), 3)

    def test_chain_preferred_first(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk_test",
            "ANTHROPIC_API_KEY": "sk_test",
        }):
            os.environ.pop("OPENAI_API_KEY", None)
            chain = _build_provider_chain("groq")
            names = [p.name for p in chain]
            self.assertEqual(names[0], "groq")
            self.assertIn("claude", names)
            self.assertNotIn("gpt4", names)

    def test_chain_empty_when_no_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            for key in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
                os.environ.pop(key, None)
            chain = _build_provider_chain("groq")
            self.assertEqual(len(chain), 0)

    def test_chain_skips_unconfigured_preferred(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            chain = _build_provider_chain("claude")
            names = [p.name for p in chain]
            # Claude is preferred but not configured, so groq is the only entry.
            self.assertEqual(names, ["groq"])


class TestGetLLMResult(unittest.TestCase):
    """Test the structured get_llm_result() API."""

    def _mock_provider(self, name, available=True, response="test output", raises=None):
        """Create a mocked provider."""
        provider = MagicMock(spec=BaseLLMProvider)
        provider.name = name
        provider.is_available.return_value = available
        provider.get_model.return_value = f"test-model-{name}"
        if raises:
            provider.call.side_effect = raises
        else:
            provider.call.return_value = response
        return provider

    def test_primary_provider_success(self):
        """Test 1: Primary provider returns content → SUCCESS."""
        mock_groq = self._mock_provider("groq", response="LLM output text")

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": self._mock_provider("claude", available=False), "gpt4": self._mock_provider("gpt4", available=False)}):
            result = get_llm_result(
                task="research",
                system_prompt="You are a researcher.",
                user_message="Analyze the market.",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.status, LLMCallStatus.SUCCESS)
        self.assertEqual(result.content, "LLM output text")
        self.assertEqual(result.provider, "groq")
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.retry_count, 0)
        self.assertIsNone(result.error)
        self.assertGreater(result.latency_ms, 0)
        self.assertEqual(len(result.attempts), 1)
        self.assertTrue(result.attempts[0].success)

    def test_primary_failure_fallback_success(self):
        """Test 2: Primary fails, fallback succeeds → DEGRADED."""
        mock_claude = self._mock_provider("claude", raises=RuntimeError("API timeout"))
        mock_groq = self._mock_provider("groq", response="Fallback output")
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "groq": mock_groq, "gpt4": mock_gpt4}):
            result = get_llm_result(
                task="code",  # preferred=claude
                system_prompt="Code gen",
                user_message="Build an app",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.status, LLMCallStatus.DEGRADED)
        self.assertEqual(result.content, "Fallback output")
        self.assertEqual(result.provider, "groq")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.retry_count, 1)
        self.assertIsNone(result.error)
        # Two attempts: claude (failed) + groq (succeeded)
        self.assertEqual(len(result.attempts), 2)
        self.assertFalse(result.attempts[0].success)
        self.assertTrue(result.attempts[1].success)

    def test_all_providers_fail(self):
        """Test 3: Every provider fails → FAILED."""
        mock_claude = self._mock_provider("claude", raises=RuntimeError("fail 1"))
        mock_gpt4 = self._mock_provider("gpt4", raises=RuntimeError("fail 2"))
        mock_groq = self._mock_provider("groq", raises=RuntimeError("fail 3"))

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "gpt4": mock_gpt4, "groq": mock_groq}):
            result = get_llm_result(
                task="code",
                system_prompt="x",
                user_message="y",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.status, LLMCallStatus.FAILED)
        self.assertEqual(result.content, "")
        self.assertEqual(result.provider, "none")
        self.assertIn("All LLM providers failed", result.error)
        self.assertEqual(len(result.attempts), 3)

    def test_no_providers_configured(self):
        """Test 4: No API keys set at all → FAILED with clear error."""
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)
        mock_groq = self._mock_provider("groq", available=False)

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "gpt4": mock_gpt4, "groq": mock_groq}):
            result = get_llm_result(
                task="general",
                system_prompt="x",
                user_message="y",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.status, LLMCallStatus.FAILED)
        self.assertIn("No LLM providers are configured", result.error)
        self.assertEqual(len(result.attempts), 0)

    def test_strict_mode_raises_on_failure(self):
        """Test 7: strict=True raises LLMError when all fail."""
        mock_groq = self._mock_provider("groq", raises=RuntimeError("fail"))
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            with self.assertRaises(LLMError) as ctx:
                get_llm_result(
                    task="general",
                    system_prompt="x",
                    user_message="y",
                    strict=True,
                )
            self.assertEqual(ctx.exception.task, "general")

    def test_strict_mode_raises_no_providers(self):
        """strict=True raises LLMError even with no providers."""
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)
        mock_groq = self._mock_provider("groq", available=False)

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "gpt4": mock_gpt4, "groq": mock_groq}):
            with self.assertRaises(LLMError):
                get_llm_result(
                    task="general",
                    system_prompt="x",
                    user_message="y",
                    strict=True,
                )

    def test_response_task_field(self):
        """The task field in LLMResponse matches what was requested."""
        mock_groq = self._mock_provider("groq", response="output")
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            result = get_llm_result(task="research", system_prompt="x", user_message="y")
            self.assertEqual(result.task, "research")

    def test_model_field_populated(self):
        """The model field records which model was used."""
        mock_groq = self._mock_provider("groq", response="out")
        mock_groq.get_model.return_value = "llama-3.3-70b-versatile"
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            result = get_llm_result(task="general", system_prompt="x", user_message="y")
            self.assertEqual(result.model, "llama-3.3-70b-versatile")


class TestGetLLMResponseLegacy(unittest.TestCase):
    """Test the legacy get_llm_response() wrapper."""

    def _mock_provider(self, name, available=True, response="test", raises=None):
        provider = MagicMock(spec=BaseLLMProvider)
        provider.name = name
        provider.is_available.return_value = available
        provider.get_model.return_value = f"model-{name}"
        if raises:
            provider.call.side_effect = raises
        else:
            provider.call.return_value = response
        return provider

    def test_legacy_returns_string_on_success(self):
        """Test 5: get_llm_response() returns str on success."""
        mock_groq = self._mock_provider("groq", response="Hello from LLM")
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            result = get_llm_response(
                task="general",
                system_prompt="sys",
                user_message="usr",
            )

        self.assertIsInstance(result, str)
        self.assertEqual(result, "Hello from LLM")

    def test_legacy_returns_error_string_on_failure(self):
        """Test 5 cont: get_llm_response() returns error markdown on failure."""
        mock_groq = self._mock_provider("groq", raises=RuntimeError("fail"))
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            result = get_llm_response(
                task="general",
                system_prompt="sys",
                user_message="usr",
            )

        self.assertIsInstance(result, str)
        self.assertIn("OUTPUT GENERATION FAILED", result)
        self.assertIn("general", result)

    def test_legacy_returns_error_string_no_providers(self):
        """Legacy wrapper returns error string even with zero providers."""
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)
        mock_groq = self._mock_provider("groq", available=False)

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "gpt4": mock_gpt4, "groq": mock_groq}):
            result = get_llm_response(task="code", system_prompt="x", user_message="y")

        self.assertIsInstance(result, str)
        self.assertIn("OUTPUT GENERATION FAILED", result)

    def test_legacy_never_raises(self):
        """get_llm_response() must never raise, even on total failure."""
        mock_groq = self._mock_provider("groq", raises=RuntimeError("boom"))
        mock_claude = self._mock_provider("claude", available=False)
        mock_gpt4 = self._mock_provider("gpt4", available=False)

        with patch.dict("llm.router._PROVIDERS", {"groq": mock_groq, "claude": mock_claude, "gpt4": mock_gpt4}):
            try:
                result = get_llm_response(task="general", system_prompt="x", user_message="y")
                self.assertIsInstance(result, str)
            except Exception:
                self.fail("get_llm_response() raised an exception")


class TestGetAvailableLLMs(unittest.TestCase):
    """Test get_available_llms()."""

    def test_reflects_config(self):
        mock_claude = MagicMock(spec=BaseLLMProvider)
        mock_claude.is_available.return_value = True
        mock_gpt4 = MagicMock(spec=BaseLLMProvider)
        mock_gpt4.is_available.return_value = False
        mock_groq = MagicMock(spec=BaseLLMProvider)
        mock_groq.is_available.return_value = True

        with patch.dict("llm.router._PROVIDERS", {"claude": mock_claude, "gpt4": mock_gpt4, "groq": mock_groq}):
            result = get_available_llms()

        self.assertEqual(result, {"claude": True, "gpt4": False, "groq": True})


class TestLLMAssignments(unittest.TestCase):
    """Test that the task assignment map is preserved."""

    def test_known_assignments(self):
        self.assertEqual(LLM_ASSIGNMENTS["code"], "claude")
        self.assertEqual(LLM_ASSIGNMENTS["research"], "groq")
        self.assertEqual(LLM_ASSIGNMENTS["review"], "claude")
        self.assertEqual(LLM_ASSIGNMENTS["general"], "groq")

    def test_unknown_task_defaults_to_groq(self):
        """Unknown tasks should default to groq."""
        self.assertEqual(LLM_ASSIGNMENTS.get("nonexistent_task", "groq"), "groq")


if __name__ == "__main__":
    unittest.main()
