"""
Tetris M2.2 -- Serper Search & Competitor Agent Tests
======================================================

Tests:
1.  Successful Serper response parsing
2.  HTTP/API failure handling
3.  Timeout handling
4.  Missing SERPER_API_KEY
5.  Malformed Serper response
6.  No fake results on failure
7.  Competitor agent invokes search tool
8.  Search results included in LLM context
9.  Source URLs survive into competitor result
10. M2.1 context injection still works
11. /execute/agent response contract unchanged
12. LIVE verification (real Serper call)
"""

from __future__ import annotations

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock
from dataclasses import asdict

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agents.search_agent import (
    search_web,
    format_search_results,
    SearchResult,
    SearchResultItem,
    SearchStatus,
    SERPER_ENDPOINT,
)


# ---------------------------------------------------------------------------
# Helper: build a fake Serper JSON response
# ---------------------------------------------------------------------------

def _fake_serper_response(num_results=3):
    """Build a realistic Serper API JSON response body."""
    organic = []
    for i in range(num_results):
        organic.append({
            "title": f"Test Competitor {i+1} - Best SaaS Tool",
            "link": f"https://example.com/competitor-{i+1}",
            "snippet": f"This is a snippet about competitor {i+1} and their pricing.",
            "position": i + 1,
        })
    return {"organic": organic, "searchParameters": {"q": "test query"}}


# ===================================================================
# TEST GROUP 1: Search Agent (search_agent.py)
# ===================================================================

class TestSerperParsing(unittest.TestCase):
    """Test 1: Successful Serper response parsing."""

    @patch("agents.search_agent.requests.post")
    def test_successful_parse(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(3)
        mock_post.return_value = mock_resp

        result = search_web("AI competitor intelligence SaaS", 5)

        self.assertEqual(result.status, SearchStatus.SUCCESS)
        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.total_results, 3)
        self.assertIsNone(result.error)

        # Check structure
        item = result.results[0]
        self.assertIn("example.com", item.url)
        self.assertIn("Test Competitor 1", item.title)
        self.assertTrue(len(item.snippet) > 0)
        print(f"[PASS] Parsed {result.total_results} results successfully")


class TestHTTPFailure(unittest.TestCase):
    """Test 2: HTTP/API failure handling."""

    @patch("agents.search_agent.requests.post")
    def test_http_500(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertIn("500", result.error)
        self.assertEqual(len(result.results), 0)
        print("[PASS] HTTP 500 produces FAILED status")

    @patch("agents.search_agent.requests.post")
    def test_http_401_unauthorized(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value = mock_resp

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertIn("401", result.error)
        print("[PASS] HTTP 401 produces FAILED status")


class TestTimeout(unittest.TestCase):
    """Test 3: Timeout handling."""

    @patch("agents.search_agent.requests.post")
    def test_request_timeout(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.Timeout("Connection timed out")

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertIn("timed out", result.error.lower())
        self.assertEqual(len(result.results), 0)
        print("[PASS] Timeout produces FAILED status")


class TestMissingAPIKey(unittest.TestCase):
    """Test 4: Missing SERPER_API_KEY."""

    @patch.dict(os.environ, {"SERPER_API_KEY": ""}, clear=False)
    def test_empty_api_key(self):
        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertIn("SERPER_API_KEY", result.error)
        self.assertEqual(len(result.results), 0)
        print("[PASS] Empty API key produces FAILED with clear error")

    @patch.dict(os.environ, {}, clear=False)
    def test_missing_api_key_env(self):
        # Remove the key entirely
        original = os.environ.pop("SERPER_API_KEY", None)
        try:
            result = search_web("test query", 5)
            self.assertEqual(result.status, SearchStatus.FAILED)
            self.assertIn("SERPER_API_KEY", result.error)
            print("[PASS] Missing API key env var produces FAILED")
        finally:
            if original is not None:
                os.environ["SERPER_API_KEY"] = original


class TestMalformedResponse(unittest.TestCase):
    """Test 5: Malformed Serper response."""

    @patch("agents.search_agent.requests.post")
    def test_invalid_json(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_post.return_value = mock_resp

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertIn("JSON", result.error)
        print("[PASS] Invalid JSON produces FAILED")

    @patch("agents.search_agent.requests.post")
    def test_missing_organic_field(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"searchParameters": {"q": "test"}}  # no 'organic'
        mock_post.return_value = mock_resp

        result = search_web("test query", 5)

        # Should be DEGRADED (200 OK but no results)
        self.assertIn(result.status, [SearchStatus.DEGRADED, SearchStatus.FAILED])
        self.assertEqual(len(result.results), 0)
        print("[PASS] Missing 'organic' field handled gracefully")

    @patch("agents.search_agent.requests.post")
    def test_organic_not_a_list(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"organic": "not a list"}
        mock_post.return_value = mock_resp

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.DEGRADED)
        print("[PASS] Non-list 'organic' produces DEGRADED")


class TestNoFakeOnFailure(unittest.TestCase):
    """Test 6: No fake results on failure."""

    @patch("agents.search_agent.requests.post")
    def test_failure_returns_empty_results(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError("Network down")

        result = search_web("test query", 5)

        self.assertEqual(result.status, SearchStatus.FAILED)
        self.assertEqual(len(result.results), 0)
        self.assertEqual(result.total_results, 0)

        # Format should clearly indicate failure
        formatted = format_search_results(result)
        self.assertIn("FAILED", formatted)
        self.assertNotIn("SUCCESS", formatted)
        print("[PASS] Failed search produces zero results, not fake data")


class TestFormatting(unittest.TestCase):
    """Test search result formatting."""

    def test_format_success(self):
        result = SearchResult(
            status=SearchStatus.SUCCESS,
            query="test query",
            results=[
                SearchResultItem(title="Result 1", url="https://example.com/1", snippet="Snippet 1", position=1),
                SearchResultItem(title="Result 2", url="https://example.com/2", snippet="Snippet 2", position=2),
            ],
            total_results=2,
        )
        formatted = format_search_results(result)
        self.assertIn("[SEARCH SUCCESS]", formatted)
        self.assertIn("https://example.com/1", formatted)
        self.assertIn("Result 1", formatted)
        print("[PASS] SUCCESS format includes URLs and titles")

    def test_format_failed(self):
        result = SearchResult(
            status=SearchStatus.FAILED,
            query="test query",
            error="API key invalid",
        )
        formatted = format_search_results(result)
        self.assertIn("[SEARCH FAILED]", formatted)
        self.assertIn("NOT based on live web data", formatted)
        print("[PASS] FAILED format includes integrity warning")

    def test_format_legacy_list(self):
        """Backward compat: format_search_results should handle raw lists."""
        legacy = [{"title": "Old Result", "url": "https://old.com", "snippet": "old"}]
        formatted = format_search_results(legacy)
        self.assertIn("Old Result", formatted)
        print("[PASS] Legacy list format backward-compat works")


# ===================================================================
# TEST GROUP 2: Competitor Agent Integration
# ===================================================================

class TestCompetitorAgentSearch(unittest.TestCase):
    """Test 7-9: Competitor agent uses search and preserves sources."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_agent_invokes_search(self, mock_llm, mock_serper_post):
        """Test 7: Competitor agent actually invokes search_web."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(3)
        mock_serper_post.return_value = mock_resp

        mock_llm.return_value = json.dumps({
            "competitors": [{"name": "Rival", "pricing": "$10/mo", "target_customer": "SMBs", "weakness": "slow", "source": "https://example.com/competitor-1"}],
            "market_gap": "Speed",
            "recommended_price_range": "$5-$15/mo",
            "pricing_strategy": "undercut",
            "key_differentiators": ["Fast"],
            "total_competitors_found": 1,
        })

        from agents.specialist.competitor_intel_agent import run_competitor_intel
        result = run_competitor_intel("Build an AI tool", "saas")

        # Serper was called 3 times (discovery, pricing, weakness)
        self.assertEqual(mock_serper_post.call_count, 3, "search_web must be called 3 times")
        print(f"[PASS] Serper called {mock_serper_post.call_count} times")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_search_results_in_llm_context(self, mock_llm, mock_serper_post):
        """Test 8: Search results are included in the LLM user_message."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper_post.return_value = mock_resp

        mock_llm.return_value = json.dumps({
            "competitors": [],
            "market_gap": "Unknown",
            "recommended_price_range": "Unknown",
            "pricing_strategy": "match",
            "key_differentiators": [],
            "total_competitors_found": 0,
        })

        from agents.specialist.competitor_intel_agent import run_competitor_intel
        result = run_competitor_intel("Build an AI tool", "saas")

        call_kwargs = mock_llm.call_args
        user_message = call_kwargs.kwargs.get("user_message", "")

        self.assertIn("SEARCH SUCCESS", user_message, "LLM must see [SEARCH SUCCESS]")
        self.assertIn("example.com", user_message, "LLM must see search URLs")
        self.assertIn("Test Competitor", user_message, "LLM must see search titles")
        print("[PASS] Search results appear in LLM user_message")

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_source_urls_preserved(self, mock_llm, mock_serper_post):
        """Test 9: Source URLs survive into the competitor result."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(3)
        mock_serper_post.return_value = mock_resp

        mock_llm.return_value = json.dumps({
            "competitors": [{"name": "Rival", "pricing": "$10", "target_customer": "devs", "weakness": "none", "source": "https://example.com/competitor-1"}],
            "market_gap": "Speed",
            "recommended_price_range": "$5-$15",
            "pricing_strategy": "match",
            "key_differentiators": ["Fast"],
            "total_competitors_found": 1,
        })

        from agents.specialist.competitor_intel_agent import run_competitor_intel
        result = run_competitor_intel("Build an AI tool", "saas")

        self.assertIn("source_urls", result, "Result must contain source_urls field")
        self.assertGreater(len(result["source_urls"]), 0, "source_urls must not be empty")
        self.assertTrue(
            any("example.com" in u for u in result["source_urls"]),
            "source_urls must contain actual search result URLs"
        )
        self.assertEqual(result["search_status"], "SUCCESS")
        self.assertEqual(result["research_source"], "live_web_search")
        print(f"[PASS] {len(result['source_urls'])} source URLs preserved in result")


class TestM21ContextStillWorks(unittest.TestCase):
    """Test 10: M2.1 Phase 1 context injection still works with new search."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_phase1_context_reaches_llm(self, mock_llm, mock_serper_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(1)
        mock_serper_post.return_value = mock_resp

        mock_llm.return_value = json.dumps({
            "competitors": [],
            "market_gap": "Unknown",
            "recommended_price_range": "Unknown",
            "pricing_strategy": "match",
            "key_differentiators": [],
            "total_competitors_found": 0,
        })

        phase1_context = "--- Phase 1 (code) Output ---\nFiles: index.html, app.js\nFeatures: dashboard, streak tracker"

        from orchestrator.router import route_to_specialist
        result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "Build a habit tracker", "idea_type": "saas"},
            context=phase1_context,
            phase=2,
        )

        call_kwargs = mock_llm.call_args
        user_message = call_kwargs.kwargs.get("user_message", "")

        self.assertIn("Phase 1", user_message, "Phase 1 context must still reach LLM")
        self.assertIn("streak tracker", user_message, "Phase 1 details must be present")
        print("[PASS] M2.1 context injection still works with M2.2 search")


class TestResponseContract(unittest.TestCase):
    """Test 11: /execute/agent response contract unchanged."""

    @patch("agents.search_agent.requests.post")
    @patch("llm.router.get_llm_response")
    def test_output_has_required_fields(self, mock_llm, mock_serper_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _fake_serper_response(2)
        mock_serper_post.return_value = mock_resp

        mock_llm.return_value = json.dumps({
            "competitors": [{"name": "X", "pricing": "$5", "target_customer": "all", "weakness": "none", "source": "web"}],
            "market_gap": "Gap",
            "recommended_price_range": "$5-$10",
            "pricing_strategy": "freemium",
            "key_differentiators": ["diff"],
            "total_competitors_found": 1,
        })

        from agents.specialist.competitor_intel_agent import run_competitor_intel
        result = run_competitor_intel("Build something", "saas")

        # Original contract fields
        required_fields = [
            "competitors", "market_gap", "recommended_price_range",
            "pricing_strategy", "key_differentiators", "total_competitors_found",
        ]
        for field in required_fields:
            self.assertIn(field, result, f"Missing required field: {field}")

        # New M2.2 metadata fields
        self.assertIn("research_source", result)
        self.assertIn("search_status", result)
        self.assertIn("source_urls", result)

        print("[PASS] Response contract intact with new metadata fields")


# ===================================================================
# TEST GROUP 3: LIVE Verification (real Serper API call)
# ===================================================================

class TestLiveSerper(unittest.TestCase):
    """Test 12: Live Serper API verification (requires SERPER_API_KEY)."""

    def test_live_search(self):
        """Execute ONE real search to prove Serper integration works."""
        api_key = os.environ.get("SERPER_API_KEY", "").strip()
        if not api_key:
            self.skipTest("SERPER_API_KEY not configured - skipping live test")

        result = search_web("AI competitor intelligence SaaS", 5)

        # Report full details
        print(f"\n{'='*60}")
        print(f"LIVE SERPER VERIFICATION")
        print(f"{'='*60}")
        print(f"Search request -> {result.status.value}")
        print(f"Results -> {result.total_results}")
        print(f"URLs -> {len([r for r in result.results if r.url])}")

        if result.status == SearchStatus.FAILED:
            print(f"ERROR: {result.error}")
            self.fail(f"Live search failed: {result.error}")

        self.assertIn(result.status, [SearchStatus.SUCCESS, SearchStatus.DEGRADED])
        self.assertGreater(result.total_results, 0, "Live search must return at least 1 result")

        # Verify structure
        for item in result.results:
            self.assertTrue(len(item.url) > 0, "Each result must have a URL")
            self.assertTrue(len(item.title) > 0, "Each result must have a title")

        # Print results for proof
        for item in result.results:
            print(f"  [{item.position}] {item.title[:60]}")
            print(f"       {item.url}")

        # Format and verify
        formatted = format_search_results(result)
        self.assertIn("[SEARCH SUCCESS]", formatted)
        print(f"\nFormatted output length: {len(formatted)} chars")
        print(f"{'='*60}")
        print("[PASS] LIVE Serper search verified with real results")


if __name__ == "__main__":
    unittest.main(verbosity=2)
