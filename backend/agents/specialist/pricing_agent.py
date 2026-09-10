import os
import json

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def run_pricing(
    confirmed_goal: str,
    competitor_data: dict,
    idea_type: str
) -> dict:

    default_response = {
        "pricing_model": "subscription",
        "tiers": [
            {
                "name": "Standard",
                "price": "$10/month",
                "features": ["Core features"],
                "target": "General users"
            }
        ],
        "stripe_config": {
            "products_to_create": [
                "Standard Plan - $10/month"
            ],
            "trial_days": 14,
            "annual_discount_percent": 20
        },
        "launch_price": "Charge standard price on day 1.",
        "when_to_raise_prices": "Upon reaching 100 active customers.",
        "reasoning": "Failed to generate dynamic pricing strategy."
    }

    try:
        client = get_groq_client()

        system_prompt = """Based on this competitor data, recommend exact pricing.
Return ONLY valid JSON:
{
"pricing_model": "subscription|one_time|freemium|commission|usage_based",
"tiers": [
{"name": "Free", "price": "$0/month", "features": ["f1", "f2"], "target": "who"},
{"name": "Pro", "price": "$X/month", "features": ["all free + f3"], "target": "who"},
{"name": "Business", "price": "$Y/month", "features": ["all pro + f4"], "target": "who"}
],
"stripe_config": {
"products_to_create": ["Pro Plan - $X/month", "Business Plan - $Y/month"],
"trial_days": 14,
"annual_discount_percent": 20
},
"launch_price": "what to charge on day 1 and why",
"when_to_raise_prices": "milestone that justifies price increase",
"reasoning": "why this beats competitors"
}"""

        user_message = (
            f"Product Idea: {confirmed_goal}"
            f"\nIdea Type: {idea_type}"
            f"\n\n--- Competitor Data ---\n"
            f"{json.dumps(competitor_data, indent=2)}"
            f"\n\nPlease generate the exact pricing structure as a JSON object."
        )

        from llm.router import get_llm_response

        raw_content = get_llm_response(
            task="pricing",
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

        return json.loads(clean)

    except json.JSONDecodeError:
        return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["reasoning"] = (
            f"Error during pricing strategy generation: {str(e)}"
        )
        error_response["success"] = False
        error_response["error"] = None

        return error_response
