"""
Tetris — Competitor Intelligence Agent
=======================================

Phase 2 specialist agent that performs real competitor/market research
using the Serper web search API and produces structured intelligence.

Data Flow
---------
Phase 1 context (via M2.1) + confirmed_goal + idea_type
    -> search_web() [3 queries: discovery, pricing, weaknesses]
    -> format_search_results() -> bounded text
    -> LLM analysis
    -> structured competitor JSON with source URLs

Research Integrity
------------------
- If search succeeds: research_source = "live_web_search"
- If search fails:    research_source = "llm_knowledge_only", clearly marked
- Source URLs are preserved in each competitor entry
- The LLM is explicitly told whether search data is real or unavailable
"""

import os
import json
import logging

from dotenv import load_dotenv

from agents.search_agent import (
    search_web,
    format_search_results,
    SearchResult,
    SearchStatus,
)

load_dotenv()

logger = logging.getLogger(__name__)


def run_competitor_intel(
    confirmed_goal: str,
    idea_type: str,
    context: str = "",
) -> dict:
    """
    Execute competitor intelligence research for Phase 2.

    Parameters
    ----------
    confirmed_goal : str
        The understood product goal from Jam Session.
    idea_type : str
        The product category (e.g. "saas", "marketplace").
    context : str
        Phase 1 output passed through from M2.1 context injection.

    Returns
    -------
    dict
        Structured competitor intelligence with research_source field.
    """

    default_response = {
        "competitors": [],
        "market_gap": "Unknown",
        "recommended_price_range": "Unknown",
        "pricing_strategy": "match",
        "key_differentiators": [],
        "total_competitors_found": 0,
        "research_source": "none",
        "search_status": "FAILED",
    }

    try:
        # ---------------------------------------------------------------
        # 1. Execute real web searches via Serper
        # ---------------------------------------------------------------

        # Truncate goal for search queries to keep them focused
        goal_short = confirmed_goal[:120]

        discovery_result: SearchResult = search_web(
            f"{goal_short} best {idea_type} apps competitors 2024 2025",
            5,
        )

        pricing_result: SearchResult = search_web(
            f"top {idea_type} app pricing plans how much cost per month",
            5,
        )

        weakness_result: SearchResult = search_web(
            f"{goal_short} {idea_type} app alternatives complaints problems",
            5,
        )

        # ---------------------------------------------------------------
        # 2. Format search results for LLM consumption
        # ---------------------------------------------------------------

        discovery_text = format_search_results(discovery_result)
        pricing_text = format_search_results(pricing_result)
        weakness_text = format_search_results(weakness_result)

        # ---------------------------------------------------------------
        # 3. Determine overall search status
        # ---------------------------------------------------------------

        statuses = [discovery_result.status, pricing_result.status, weakness_result.status]
        any_success = any(s == SearchStatus.SUCCESS for s in statuses)
        all_failed = all(s == SearchStatus.FAILED for s in statuses)

        if all_failed:
            overall_search_status = "FAILED"
            research_source = "llm_knowledge_only"
            search_integrity_note = (
                "\n\nIMPORTANT: All web searches FAILED. "
                "You MUST clearly state that this analysis is based on your training data, "
                "NOT live web research. Do NOT imply you searched the web. "
                "Mark all sources as 'LLM knowledge base' instead of 'Web research'."
            )
        elif any_success:
            overall_search_status = "SUCCESS"
            research_source = "live_web_search"
            search_integrity_note = (
                "\n\nThe search results above are from LIVE web research. "
                "Base your analysis on these real results. "
                "Include the source URLs in each competitor's 'source' field."
            )
        else:
            overall_search_status = "DEGRADED"
            research_source = "partial_web_search"
            search_integrity_note = (
                "\n\nSome searches returned limited results. "
                "Clearly indicate which findings are from web research (with URLs) "
                "and which are from your knowledge base."
            )

        # ---------------------------------------------------------------
        # 4. Build LLM prompt
        # ---------------------------------------------------------------

        system_prompt = """You are a Market & Competitor Intelligence Specialist.
Analyze the product idea and the provided search results to identify real existing market competitors, market gaps, pricing strategy, and key differentiators.

CRITICAL RULES:
- If search results are marked as [SEARCH SUCCESS], use those results as your primary evidence.
- Include source URLs in each competitor's "source" field when available.
- If search results are marked as [SEARCH FAILED], clearly state your analysis uses LLM knowledge, not live data.
- Never fabricate URLs or sources.

Return ONLY valid JSON with this structure:
{
  "competitors": [
    {
      "name": "Competitor Name",
      "pricing": "e.g. $49/mo or Free tier available",
      "target_customer": "Target audience description",
      "weakness": "Known pain points or gaps",
      "source": "URL from search results OR 'LLM knowledge base'"
    }
  ],
  "market_gap": "Specific market gap this product can fill",
  "recommended_price_range": "$X - $Y/month",
  "pricing_strategy": "undercut|match|premium|freemium",
  "key_differentiators": ["How to win against competitors"],
  "total_competitors_found": 3
}"""

        # Build prior-phase context section (Phase 1 output, acceptance criteria, etc.)
        prior_context_section = ""
        if context and context.strip():
            prior_context_section = (
                f"\n\n--- Prior Phase Output (what has already been built) ---\n"
                f"{context[:3000]}"  # Cap to avoid token overflow
            )

        user_message = (
            f"Product Idea: {confirmed_goal}"
            f"\nCategory: {idea_type}"
            f"{prior_context_section}"
            f"\n\n--- Competitor Discovery Results ---\n"
            f"{discovery_text}"
            f"\n\n--- Competitor Pricing Results ---\n"
            f"{pricing_text}"
            f"\n\n--- Competitor Weakness Results ---\n"
            f"{weakness_text}"
            f"{search_integrity_note}"
        )

        # ---------------------------------------------------------------
        # 5. Call LLM for analysis
        # ---------------------------------------------------------------

        from llm.router import get_llm_response

        raw_content = get_llm_response(
            task="competitor_intel",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.2,
        )

        # ---------------------------------------------------------------
        # 6. Parse LLM response
        # ---------------------------------------------------------------

        clean = raw_content.strip()

        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        result = json.loads(clean.strip())

        # Inject research metadata
        result["research_source"] = research_source
        result["search_status"] = overall_search_status
        result["search_queries"] = [
            discovery_result.query,
            pricing_result.query,
            weakness_result.query,
        ]
        result["search_results_count"] = (
            discovery_result.total_results
            + pricing_result.total_results
            + weakness_result.total_results
        )

        # Collect all source URLs from search results for evidence
        all_urls = []
        for sr in [discovery_result, pricing_result, weakness_result]:
            for item in sr.results:
                if item.url:
                    all_urls.append(item.url)
        result["source_urls"] = all_urls[:15]  # Cap at 15

        return result

    except json.JSONDecodeError:
        default_response["error"] = "LLM returned invalid JSON"
        return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["market_gap"] = f"Error: {str(e)}"
        error_response["success"] = False
        error_response["error"] = str(e)
        return error_response
