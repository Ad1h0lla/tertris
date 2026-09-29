"""
Tetris M2.3 -- Phase 2 Agent Chaining Tests
============================================

Tests:
1.  Competitor executes before Pricing in sequential chain
2.  Competitor output is actually passed into Pricing
3.  Pricing no longer receives hardcoded {} in real path
4.  Competitor source URLs survive into Phase 2 result
5.  Pricing can reference competitor evidence
6.  Competitor failure propagates as DEGRADED/FAILED
7.  Pricing does not fabricate competitor evidence after upstream failure
8.  Phase 1 context from M2.1 still reaches Competitor
9.  Existing M2.2 Serper tests remain passing (run separately)
10. /execute/agent response contract remains compatible
11. Phase 2 result can be persisted and retrieved
"""

from __future__ import annotations

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock, call
from collections import OrderedDict

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_serper_response(n=3):
    return {
        "organic": [
            {"title": f"Competitor {i}", "link": f"https://real-source-{i}.com/pricing", "snippet": f"Pricing info for competitor {i}"}
            for i in range(1, n + 1)
        ]
    }

FAKE_COMPETITOR_LLM_RESPONSE = json.dumps({
    "competitors": [
        {"name": "RivalApp", "pricing": "$29/mo", "target_customer": "SMBs", "weakness": "No API", "source": "https://real-source-1.com/pricing"},
        {"name": "CompeteCo", "pricing": "$49/mo", "target_customer": "Enterprise", "weakness": "Complex", "source": "https://real-source-2.com/pricing"},
    ],
    "market_gap": "Simple API-first approach",
    "recommended_price_range": "$15-$35/month",
    "pricing_strategy": "undercut",
    "key_differentiators": ["API-first", "Simple UX"],
    "total_competitors_found": 2,
})

FAKE_PRICING_LLM_RESPONSE = json.dumps({
    "pricing_model": "freemium",
    "tiers": [
        {"name": "Free", "price": "$0/month", "features": ["Basic"], "target": "Individuals"},
        {"name": "Pro", "price": "$19/month", "features": ["Basic", "API"], "target": "SMBs"},
    ],
    "stripe_config": {"products_to_create": ["Pro - $19/mo"], "trial_days": 14, "annual_discount_percent": 20},
    "launch_price": "Start at $19/mo based on competitor undercut",
    "when_to_raise_prices": "At 500 paying users",
    "reasoning": "RivalApp charges $29 so $19 undercuts while CompeteCo at $49 leaves room for growth",
})

PHASE_1_CONTEXT = (
    "--- Phase 1 (code) Output ---\n"
    "Files: index.html, app.js, style.css\n"
    "Features: dashboard, API endpoints, user auth"
)


# ===================================================================
# TEST GROUP 1: Chain Ordering & Data Flow
# ===================================================================

class TestChainOrdering(unittest.TestCase):
    """Tests 1-3: Chain execution order and data flow."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_competitor_executes_before_pricing(self, mock_llm, mock_serper):
        """Test 1: Competitor agent runs first, then pricing."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper.return_value = mock_resp

        # Track call order
        call_order = []
        def llm_side_effect(**kwargs):
            task = kwargs.get("task", "")
            call_order.append(task)
            if task == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            elif task == "pricing":
                return FAKE_PRICING_LLM_RESPONSE
            return "{}"

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a SaaS tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # Verify ordering
        self.assertEqual(call_order, ["competitor_intel", "pricing"],
                         f"Expected competitor_intel before pricing, got: {call_order}")
        print(f"[PASS] Chain order verified: {call_order}")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_competitor_output_passed_to_pricing(self, mock_llm, mock_serper):
        """Test 2: Competitor result is actually fed into pricing LLM prompt."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper.return_value = mock_resp

        llm_calls = []
        def llm_side_effect(**kwargs):
            llm_calls.append(kwargs)
            task = kwargs.get("task", "")
            if task == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            elif task == "pricing":
                return FAKE_PRICING_LLM_RESPONSE
            return "{}"

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a SaaS tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # Pricing LLM call is the second one
        self.assertEqual(len(llm_calls), 2, "Must have exactly 2 LLM calls")
        pricing_user_msg = llm_calls[1].get("user_message", "")

        # Pricing must see the actual competitor names from upstream
        self.assertIn("RivalApp", pricing_user_msg, "Pricing must see RivalApp from competitor result")
        self.assertIn("$29/mo", pricing_user_msg, "Pricing must see competitor pricing")
        self.assertIn("CompeteCo", pricing_user_msg, "Pricing must see CompeteCo")
        print("[PASS] Competitor output appears in pricing LLM prompt")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_pricing_not_hardcoded_empty(self, mock_llm, mock_serper):
        """Test 3: Pricing no longer receives hardcoded {} in the Phase 2 path."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper.return_value = mock_resp

        llm_calls = []
        def llm_side_effect(**kwargs):
            llm_calls.append(kwargs)
            task = kwargs.get("task", "")
            if task == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            elif task == "pricing":
                return FAKE_PRICING_LLM_RESPONSE
            return "{}"

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        pricing_user_msg = llm_calls[1].get("user_message", "")

        # The pricing prompt must NOT contain just "{}" as competitor data
        # It should have real competitor names
        self.assertNotEqual(
            pricing_user_msg.count("{}"), pricing_user_msg.count("Competitor Data"),
            "Pricing should not receive empty {} as competitor data"
        )
        self.assertIn("competitors", pricing_user_msg.lower())
        print("[PASS] Pricing receives real competitor data, not hardcoded {}")


# ===================================================================
# TEST GROUP 2: Source URL Preservation & Evidence
# ===================================================================

class TestSourceURLs(unittest.TestCase):
    """Tests 4-5: URL preservation and evidence referencing."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_source_urls_in_phase2_result(self, mock_llm, mock_serper):
        """Test 4: Competitor source URLs survive into Phase 2 combined result."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(3)
        mock_serper.return_value = mock_resp

        def llm_side_effect(**kwargs):
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        self.assertIn("source_urls", result, "Phase 2 result must have source_urls")
        self.assertGreater(len(result["source_urls"]), 0, "source_urls must not be empty")
        self.assertTrue(
            any("real-source" in url for url in result["source_urls"]),
            "Source URLs must contain actual search result URLs"
        )
        print(f"[PASS] {len(result['source_urls'])} source URLs preserved in Phase 2 result")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_pricing_can_reference_evidence(self, mock_llm, mock_serper):
        """Test 5: Pricing output can reference competitor evidence."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper.return_value = mock_resp

        def llm_side_effect(**kwargs):
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        pricing = result.get("pricing", {})
        # Pricing must have upstream_status showing it received real data
        self.assertIn("upstream_status", pricing)
        self.assertEqual(pricing["upstream_status"], "SUCCESS")
        # Pricing must have competitor source URLs
        self.assertIn("competitor_source_urls", pricing)
        print(f"[PASS] Pricing references upstream evidence (status: {pricing['upstream_status']})")


# ===================================================================
# TEST GROUP 3: Failure Propagation
# ===================================================================

class TestFailurePropagation(unittest.TestCase):
    """Tests 6-7: Failure propagation and no fake evidence."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_competitor_failure_propagates(self, mock_llm, mock_serper):
        """Test 6: Competitor search failure propagates to Phase 2 status."""
        import requests as req
        mock_serper.side_effect = req.exceptions.ConnectionError("Network down")

        def llm_side_effect(**kwargs):
            # Competitor agent will still call LLM even if search fails
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # Phase 2 overall should NOT be SUCCESS when search failed
        self.assertIn("phase_2_status", result)
        self.assertNotEqual(result["phase_2_status"], "SUCCESS",
                           "Phase 2 must not be SUCCESS when search failed")
        self.assertIn(result["search_status"], ["FAILED", "DEGRADED", "UNKNOWN"])
        print(f"[PASS] Failure propagated: phase_2={result['phase_2_status']}, search={result['search_status']}")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_pricing_knows_upstream_failed(self, mock_llm, mock_serper):
        """Test 7: Pricing does not fabricate evidence after upstream failure."""
        import requests as req
        mock_serper.side_effect = req.exceptions.ConnectionError("Network down")

        llm_calls = []
        def llm_side_effect(**kwargs):
            llm_calls.append(kwargs)
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # The pricing LLM call must contain the FAILED status
        pricing_call = [c for c in llm_calls if c.get("task") == "pricing"]
        self.assertEqual(len(pricing_call), 1)
        pricing_msg = pricing_call[0].get("user_message", "")
        pricing_sys = pricing_call[0].get("system_prompt", "")

        # Either user_message or system_prompt should mention failure
        combined = pricing_msg + pricing_sys
        has_failure_signal = (
            "FAILED" in combined
            or "failed" in combined.lower()
            or "DEGRADED" in combined
        )
        self.assertTrue(has_failure_signal,
                       "Pricing must be told that upstream research failed")
        print("[PASS] Pricing agent is aware of upstream failure")


# ===================================================================
# TEST GROUP 4: Backward Compatibility
# ===================================================================

class TestM21ContextStillWorks(unittest.TestCase):
    """Test 8: Phase 1 context still reaches Competitor through chain."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_phase1_context_in_chain(self, mock_llm, mock_serper):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(1)
        mock_serper.return_value = mock_resp

        llm_calls = []
        def llm_side_effect(**kwargs):
            llm_calls.append(kwargs)
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a habit tracker", "idea_type": "saas"},
            context=PHASE_1_CONTEXT,
            phase=2,
        )

        # Competitor LLM call (first) must contain Phase 1 context
        competitor_msg = llm_calls[0].get("user_message", "")
        self.assertIn("Phase 1", competitor_msg, "Phase 1 context must reach competitor agent")
        self.assertIn("dashboard", competitor_msg, "Phase 1 features must be visible")
        print("[PASS] M2.1 context injection still works in M2.3 chain")


class TestResponseContract(unittest.TestCase):
    """Test 10: /execute/agent response contract compatibility."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_phase2_result_is_dict(self, mock_llm, mock_serper):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(1)
        mock_serper.return_value = mock_resp

        def llm_side_effect(**kwargs):
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # Must be a dict (main.py expects isinstance(agent_output, dict))
        self.assertIsInstance(result, dict)

        # Must have chain metadata
        self.assertIn("phase_2_status", result)
        self.assertIn("competitor_intel", result)
        self.assertIn("pricing", result)
        self.assertIn("chain", result)
        self.assertEqual(result["chain"], ["competitor_intel", "pricing"])

        # Must be JSON-serializable (for save_phase_result)
        serialized = json.dumps(result, indent=2, default=str)
        self.assertGreater(len(serialized), 100)
        print(f"[PASS] Response is dict, JSON-serializable ({len(serialized)} bytes)")


class TestPersistence(unittest.TestCase):
    """Test 11: Phase 2 result can be persisted and retrieved."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_phase2_result_persistence(self, mock_llm, mock_serper):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper.return_value = mock_resp

        def llm_side_effect(**kwargs):
            if kwargs.get("task") == "competitor_intel":
                return FAKE_COMPETITOR_LLM_RESPONSE
            return FAKE_PRICING_LLM_RESPONSE

        mock_llm.side_effect = llm_side_effect

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a tool", "idea_type": "saas"},
            context="",
            phase=2,
        )

        # Simulate what main.py does: serialize to JSON for save_phase_result
        outcome_json = json.dumps(result, indent=2, default=str)

        # Verify it can be deserialized back
        recovered = json.loads(outcome_json)
        self.assertEqual(recovered["phase_2_status"], result["phase_2_status"])
        self.assertEqual(recovered["chain"], ["competitor_intel", "pricing"])

        # Verify competitor data survives roundtrip
        competitor = recovered["competitor_intel"]
        self.assertIn("competitors", competitor)
        self.assertIn("source_urls", recovered)

        # Verify pricing data survives roundtrip
        pricing = recovered["pricing"]
        self.assertIn("pricing_model", pricing)
        self.assertIn("upstream_status", pricing)

        print(f"[PASS] Phase 2 result survives JSON roundtrip ({len(outcome_json)} bytes)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
