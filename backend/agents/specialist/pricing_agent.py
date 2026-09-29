"""
Tetris -- Pricing Strategy Agent
=================================

Phase 2 specialist agent that produces pricing recommendations
based on actual competitor intelligence from the upstream agent.

Data Flow
---------
Competitor Intelligence Result (from competitor_intel_agent)
    -> Pricing Agent
    -> LLM analysis with real competitor evidence
    -> Structured pricing JSON

Upstream Integrity
------------------
- If competitor_data has search_status="SUCCESS": uses real evidence
- If competitor_data has search_status="FAILED": marks pricing as DEGRADED
- Never fabricates competitor evidence the upstream agent didn't provide
"""

import os
import json
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def run_pricing(
    confirmed_goal: str,
    competitor_data: dict,
    idea_type: str,
    context: str = "",
) -> dict:
    """
    Generate pricing strategy based on competitor intelligence.

    Parameters
    ----------
    confirmed_goal : str
        The understood product goal.
    competitor_data : dict
        Actual output from competitor_intel_agent (not hardcoded {}).
    idea_type : str
        Product category (e.g. "saas").
    context : str
        Phase 1 output or other prior context.

    Returns
    -------
    dict
        Structured pricing recommendation with upstream_status metadata.
    """

    default_response = {
        "pricing_model": "subscription",
        "tiers": [
            {
                "name": "Standard",
                "price": "$10/month",
                "features": ["Core features"],
                "target": "General users",
            }
        ],
        "stripe_config": {
            "products_to_create": ["Standard Plan - $10/month"],
            "trial_days": 14,
            "annual_discount_percent": 20,
        },
        "launch_price": "Charge standard price on day 1.",
        "when_to_raise_prices": "Upon reaching 100 active customers.",
        "reasoning": "Failed to generate dynamic pricing strategy.",
        "upstream_status": "UNKNOWN",
        "pricing_status": "FAILED",
    }

    try:
        # ---------------------------------------------------------------
        # 1. Determine upstream research quality
        # ---------------------------------------------------------------

        upstream_search_status = "UNKNOWN"
        upstream_source_urls = []

        if isinstance(competitor_data, dict):
            upstream_search_status = competitor_data.get("search_status", "UNKNOWN")
            upstream_source_urls = competitor_data.get("source_urls", [])

        has_real_evidence = (
            upstream_search_status == "SUCCESS"
            and isinstance(competitor_data.get("competitors"), list)
            and len(competitor_data.get("competitors", [])) > 0
        )

        # ---------------------------------------------------------------
        # 2. Build integrity-aware system prompt
        # ---------------------------------------------------------------

        if has_real_evidence:
            evidence_instruction = (
                "The competitor data below is from LIVE web research with real source URLs. "
                "Use this verified evidence to inform your pricing strategy. "
                "Reference specific competitor pricing in your reasoning."
            )
        elif upstream_search_status == "DEGRADED":
            evidence_instruction = (
                "WARNING: The competitor research was DEGRADED (partial results). "
                "Some data may be from LLM knowledge rather than live research. "
                "Clearly indicate which pricing decisions are based on verified data "
                "vs. estimates. Do NOT claim this is based on comprehensive web research."
            )
        else:
            evidence_instruction = (
                "WARNING: The upstream competitor research FAILED. "
                "No verified competitor data is available. "
                "You MUST clearly state that pricing recommendations are based on "
                "general market knowledge, NOT verified competitor evidence. "
                "Do NOT fabricate competitor pricing data."
            )

        system_prompt = f"""{evidence_instruction}

Based on the available competitor data, recommend exact pricing.
Return ONLY valid JSON:
{{
"pricing_model": "subscription|one_time|freemium|commission|usage_based",
"tiers": [
{{"name": "Free", "price": "$0/month", "features": ["f1", "f2"], "target": "who"}},
{{"name": "Pro", "price": "$X/month", "features": ["all free + f3"], "target": "who"}},
{{"name": "Business", "price": "$Y/month", "features": ["all pro + f4"], "target": "who"}}
],
"stripe_config": {{
"products_to_create": ["Pro Plan - $X/month", "Business Plan - $Y/month"],
"trial_days": 14,
"annual_discount_percent": 20
}},
"launch_price": "what to charge on day 1 and why",
"when_to_raise_prices": "milestone that justifies price increase",
"reasoning": "why this beats competitors"
}}"""

        # ---------------------------------------------------------------
        # 3. Build user message with actual competitor evidence
        # ---------------------------------------------------------------

        # Serialize competitor data, capping to avoid token overflow
        competitor_json = json.dumps(competitor_data, indent=2, default=str)
        if len(competitor_json) > 3000:
            competitor_json = competitor_json[:3000] + "\n... [truncated]"

        # Build prior-phase context section
        prior_context_section = ""
        if context and context.strip():
            prior_context_section = (
                f"\n\n--- Prior Phase Context ---\n"
                f"{context[:2000]}"
            )

        user_message = (
            f"Product Idea: {confirmed_goal}"
            f"\nIdea Type: {idea_type}"
            f"\nUpstream Research Status: {upstream_search_status}"
            f"{prior_context_section}"
            f"\n\n--- Competitor Data ---\n"
            f"{competitor_json}"
            f"\n\nPlease generate the exact pricing structure as a JSON object."
        )

        # ---------------------------------------------------------------
        # 4. Call LLM
        # ---------------------------------------------------------------

        from llm.router import get_llm_response

        raw_content = get_llm_response(
            task="pricing",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.2,
        )

        # ---------------------------------------------------------------
        # 5. Parse response
        # ---------------------------------------------------------------

        clean = raw_content.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        result = json.loads(clean)

        # Inject metadata
        result["upstream_status"] = upstream_search_status
        result["pricing_status"] = "SUCCESS" if has_real_evidence else "DEGRADED"
        result["competitor_source_urls"] = upstream_source_urls[:10]

        return result

    except json.JSONDecodeError:
        default_response["upstream_status"] = upstream_search_status
        default_response["pricing_status"] = "FAILED"
        default_response["reasoning"] = "LLM returned invalid JSON for pricing"
        return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["reasoning"] = f"Error during pricing strategy generation: {str(e)}"
        error_response["upstream_status"] = "UNKNOWN"
        error_response["pricing_status"] = "FAILED"
        error_response["success"] = False
        error_response["error"] = str(e)
        return error_response
