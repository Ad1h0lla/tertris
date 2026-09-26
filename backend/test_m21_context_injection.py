"""
Tetris M2.1 — Phase 2 Context Injection Verification
=====================================================

Proves that Phase 2 (competitor_intel) receives Phase 1 output
through the entire chain:

    main.py DB retrieval → route_to_specialist → run_competitor_intel → LLM prompt

All tests use mocked LLM boundaries — no real API calls.
"""

from __future__ import annotations

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PHASE_1_CONTEXT = (
    "--- Phase 1 (code) Output ---\n"
    "Files created: index.html, style.css, app.js\n"
    "Features: dashboard, streak tracker, daily check-in modal\n"
    "Tech stack: vanilla HTML/CSS/JS\n"
    "Acceptance criteria met: 3/3"
)


class TestPhase2ContextInjection(unittest.TestCase):
    """Verifies that Phase 2 receives and uses Phase 1 context."""

    @patch("agents.specialist.competitor_intel_agent.search_web", return_value=[])
    @patch("agents.specialist.competitor_intel_agent.format_search_results", return_value="No results.")
    @patch("llm.router.get_llm_response")
    def test_context_reaches_llm_prompt(self, mock_llm, mock_fmt, mock_search):
        """The LLM user_message must contain the Phase 1 output text."""
        mock_llm.return_value = json.dumps({
            "competitors": [{"name": "Habitica", "pricing": "Free/Premium", "target_customer": "Gamers", "weakness": "Complex", "source": "Analysis"}],
            "market_gap": "Student-focused simplicity",
            "recommended_price_range": "$0 - $5/month",
            "pricing_strategy": "freemium",
            "key_differentiators": ["College-focused UX"],
            "total_competitors_found": 1,
        })

        from orchestrator.router import route_to_specialist

        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={
                "understood_goal": "Build a habit tracker for college students",
                "idea_type": "saas",
            },
            context=PHASE_1_CONTEXT,
            phase=2,
        )

        # 1. LLM was called
        mock_llm.assert_called_once()

        # 2. Phase 1 content appears in user_message
        call_kwargs = mock_llm.call_args
        user_message = call_kwargs.kwargs.get("user_message") or call_kwargs[1].get("user_message", "")
        if not user_message:
            # Positional args: task, system_prompt, user_message
            user_message = call_kwargs[0][2] if len(call_kwargs[0]) > 2 else ""

        self.assertIn("Phase 1", user_message, "Phase 1 header must appear in user_message")
        self.assertIn("streak tracker", user_message, "Phase 1 feature details must appear")
        self.assertIn("dashboard", user_message, "Phase 1 feature details must appear")

        # 3. Result is valid competitor_intel JSON
        self.assertIn("competitors", result)
        self.assertGreater(result["total_competitors_found"], 0)
        print(f"[PASS] Context injection verified: user_message contains Phase 1 output")
        print(f"  user_message length: {len(user_message)} chars")

    @patch("agents.specialist.competitor_intel_agent.search_web", return_value=[])
    @patch("agents.specialist.competitor_intel_agent.format_search_results", return_value="No results.")
    @patch("llm.router.get_llm_response")
    def test_empty_context_no_crash(self, mock_llm, mock_fmt, mock_search):
        """Phase 2 must work when context is empty (backward compat)."""
        mock_llm.return_value = json.dumps({
            "competitors": [],
            "market_gap": "Unknown",
            "recommended_price_range": "Unknown",
            "pricing_strategy": "match",
            "key_differentiators": [],
            "total_competitors_found": 0,
        })

        from orchestrator.router import route_to_specialist

        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={
                "understood_goal": "Build something",
                "idea_type": "saas",
            },
            context="",
            phase=2,
        )

        mock_llm.assert_called_once()

        # user_message should NOT contain Phase 1 header when context is empty
        call_kwargs = mock_llm.call_args
        user_message = call_kwargs.kwargs.get("user_message") or call_kwargs[1].get("user_message", "")
        if not user_message:
            user_message = call_kwargs[0][2] if len(call_kwargs[0]) > 2 else ""

        self.assertNotIn("Prior Phase Output", user_message,
                         "Empty context must not inject prior phase section")
        print(f"[PASS] Empty context backward-compat verified")

    @patch("agents.specialist.competitor_intel_agent.search_web", return_value=[])
    @patch("agents.specialist.competitor_intel_agent.format_search_results", return_value="No results.")
    @patch("llm.router.get_llm_response")
    def test_context_is_truncated_at_3000_chars(self, mock_llm, mock_fmt, mock_search):
        """Very long Phase 1 output must be capped to avoid token overflow."""
        mock_llm.return_value = json.dumps({
            "competitors": [],
            "market_gap": "Unknown",
            "recommended_price_range": "Unknown",
            "pricing_strategy": "match",
            "key_differentiators": [],
            "total_competitors_found": 0,
        })

        huge_context = "X" * 10000

        from orchestrator.router import route_to_specialist

        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={
                "understood_goal": "Build something big",
                "idea_type": "saas",
            },
            context=huge_context,
            phase=2,
        )

        mock_llm.assert_called_once()

        call_kwargs = mock_llm.call_args
        user_message = call_kwargs.kwargs.get("user_message") or call_kwargs[1].get("user_message", "")
        if not user_message:
            user_message = call_kwargs[0][2] if len(call_kwargs[0]) > 2 else ""

        # The context portion must be capped — full user_message may be longer
        # due to other sections, but the X's should not exceed 3000
        x_count = user_message.count("X")
        self.assertLessEqual(x_count, 3000,
                             f"Context must be capped at 3000 chars, got {x_count} X's")
        print(f"[PASS] Context truncation verified: {x_count} of 10000 chars kept")


class TestDirectAgentSignature(unittest.TestCase):
    """Verifies the agent function accepts context parameter."""

    def test_run_competitor_intel_accepts_context(self):
        """run_competitor_intel() must accept a 'context' keyword arg."""
        import inspect
        from agents.specialist.competitor_intel_agent import run_competitor_intel

        sig = inspect.signature(run_competitor_intel)
        param_names = list(sig.parameters.keys())

        self.assertIn("context", param_names,
                      "run_competitor_intel must have a 'context' parameter")

        # context must have a default value (backward compat)
        ctx_param = sig.parameters["context"]
        self.assertNotEqual(ctx_param.default, inspect.Parameter.empty,
                            "context parameter must have a default value")
        print(f"[PASS] Signature verified: {sig}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
