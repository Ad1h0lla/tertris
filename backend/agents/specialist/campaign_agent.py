import os
import json
from dotenv import load_dotenv

load_dotenv()


def run_campaign(
    goal: str = "",
    context: str = "",
    phase: int = 3,
) -> dict:
    """
    Generates a complete marketing campaign, positioning, and copy for the project.
    """
    from llm.router import get_llm_response

    system_prompt = """You are the Marketing Campaign & Growth Specialist inside TETRIS.
Generate a comprehensive, actionable marketing campaign strategy and launch copy.
Return ONLY valid JSON with this exact structure:
{
  "target_audience": "Specific audience description",
  "positioning_statement": "Clear positioning statement",
  "key_channels": ["Channel 1", "Channel 2", "Channel 3"],
  "campaign_angle": "Core campaign theme/angle",
  "ad_copy": [
    {"headline": "Headline 1", "body": "Ad body text", "cta": "Call to action"},
    {"headline": "Headline 2", "body": "Ad body text", "cta": "Call to action"}
  ],
  "email_sequence": [
    {"subject": "Welcome Email", "preview": "Preview text", "body": "Email body"}
  ],
  "launch_offer": "Initial offer details",
  "acquisition_funnel": ["Step 1", "Step 2", "Step 3"]
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PREVIOUS CONTEXT:
{context}

Generate the complete marketing campaign and acquisition strategy as JSON."""

    try:
        raw_output = get_llm_response(
            task="campaign",
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
        "target_audience": "Startup founders, product managers, and growth teams",
        "positioning_statement": f"Automated competitive intelligence for {goal[:60]}",
        "key_channels": ["Product Hunt", "Reddit", "LinkedIn", "Hacker News"],
        "campaign_angle": "Never get caught off-guard by competitor pricing or feature launches",
        "ad_copy": [
            {
                "headline": "Track Competitor Pricing Changes Automatically",
                "body": "Monitor competitor websites, product launches, and pricing changes 24/7 with instant AI alerts.",
                "cta": "Try Competitive Intel Free"
            }
        ],
        "email_sequence": [
            {
                "subject": "Welcome to Automated Competitive Intelligence",
                "preview": "Your first intelligence report is ready",
                "body": "Welcome! Your automated monitoring agent is now scanning competitor websites and updates."
            }
        ],
        "launch_offer": "14-day free trial on Pro tier",
        "acquisition_funnel": ["Landing Page", "Free Sign Up", "Competitor URL Setup", "First Alert Delivered"],
    }
