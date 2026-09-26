import os
import json

from groq import Groq
from dotenv import load_dotenv

try:
    from agents.search_agent import search_web, format_search_results
except ImportError:
    def search_web(query, num_results=5):
        return []

    def format_search_results(results):
        return "Search results unavailable."


load_dotenv()


def run_competitor_intel(
    confirmed_goal: str,
    idea_type: str,
    context: str = "",
) -> dict:

    default_response = {
        "competitors": [],
        "market_gap": "Unknown",
        "recommended_price_range": "Unknown",
        "pricing_strategy": "match",
        "key_differentiators": [],
        "total_competitors_found": 0
    }

    try:
        client = Groq(
            api_key=os.environ.get("GROQ_API_KEY")
        )

        discovery_results = search_web(
            f"{confirmed_goal} best {idea_type} apps competitors 2024 2025",
            5
        )

        pricing_results = search_web(
            f"top {idea_type} app pricing plans how much cost per month",
            5
        )

        weakness_results = search_web(
            f"{confirmed_goal} {idea_type} app alternatives complaints problems",
            5
        )

        discovery_text = format_search_results(
            discovery_results
        )

        pricing_text = format_search_results(
            pricing_results
        )

        weakness_text = format_search_results(
            weakness_results
        )

        system_prompt = """You are a Market & Competitor Intelligence Specialist.
Analyze the product idea and any provided search results to identify real or typical existing market competitors, market gaps, pricing strategy, and key differentiators.
If search results are limited or unavailable, use your comprehensive knowledge base to identify 3 to 5 established or representative competitors in this space.
Return ONLY valid JSON with this structure:
{
  "competitors": [
    {
      "name": "Competitor Name",
      "pricing": "e.g. $49/mo or Free tier available",
      "target_customer": "Target audience description",
      "weakness": "Known pain points or gaps",
      "source": "Market analysis"
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
        )

        from llm.router import get_llm_response

        raw_content = get_llm_response(
            task="competitor_intel",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.2,
        )

        clean = raw_content.strip()

        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        return json.loads(clean.strip())

    except json.JSONDecodeError:
        return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["market_gap"] = f"Error: {str(e)}"
        error_response["success"] = False
        error_response["error"] = None
        return error_response
