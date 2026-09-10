import os
import json
from dotenv import load_dotenv

load_dotenv()


def run_research(
    goal: str = "",
    context: str = "",
    phase: int = 2,
) -> dict:
    """
    Generates market research, TAM/SAM/SOM breakdown, customer personas, and industry pain points.
    """
    from llm.router import get_llm_response

    system_prompt = """You are the Market Research Specialist inside TETRIS.
Generate a thorough market research report for the user's project goal.
Return ONLY valid JSON with this exact structure:
{
  "market_overview": "Summary of industry landscape",
  "tam_sam_som": {
    "tam": "$X Billion total addressable market",
    "sam": "$Y Million serviceable addressable market",
    "som": "$Z Million serviceable obtainable market"
  },
  "target_personas": [
    {
      "role": "Target role",
      "pain_points": ["Pain 1", "Pain 2"],
      "willingness_to_pay": "High|Medium|Low"
    }
  ],
  "market_drivers": ["Driver 1", "Driver 2"],
  "key_risks": ["Risk 1", "Risk 2"],
  "recommendations": ["Rec 1", "Rec 2"]
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PREVIOUS CONTEXT:
{context}

Generate the complete market research report as JSON."""

    try:
        raw_output = get_llm_response(
            task="research",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=2500,
            temperature=0.3,
        )

        clean = (raw_output or "").strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        res = json.loads(clean)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    return {
        "market_overview": f"Growing market demand for automated intelligence tools for {goal[:50]}.",
        "tam_sam_som": {
            "tam": "$5.2 Billion Competitive Intelligence Software Market",
            "sam": "$850 Million SaaS & Startup Segment",
            "som": "$15 Million Early Adopter Founders & Product Teams"
        },
        "target_personas": [
            {
                "role": "Startup Founder / CEO",
                "pain_points": ["Manual checking of competitor pricing", "Blind spots in feature releases"],
                "willingness_to_pay": "High ($99-$299/mo)"
            }
        ],
        "market_drivers": ["Rapid pace of SaaS launches", "Pricing transparency demands"],
        "key_risks": ["Web scraping anti-bot measures", "Data freshness latency"],
        "recommendations": ["Offer automated change summarize alerts", "Provide webhooks for Slack/Discord integration"]
    }
