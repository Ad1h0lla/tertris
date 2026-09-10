import os
import json
from dotenv import load_dotenv

load_dotenv()


def run_plan(
    goal: str = "",
    context: str = "",
    phase: int = 1,
) -> dict:
    """
    Generates strategic roadmap and product execution milestones.
    """
    from llm.router import get_llm_response

    system_prompt = """You are the Product Planning Specialist inside TETRIS.
Generate a milestone roadmap and feature breakdown.
Return ONLY valid JSON with this exact structure:
{
  "milestones": [
    {"name": "M1: MVP Core", "timeline": "Week 1-2", "deliverables": ["Core feature 1", "Core feature 2"]},
    {"name": "M2: Beta Testing", "timeline": "Week 3-4", "deliverables": ["Integration 1", "Analytics"]}
  ],
  "risk_mitigation": ["Risk mitigation 1"],
  "resource_allocation": ["Resource 1"]
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PREVIOUS CONTEXT:
{context}

Generate product planning roadmap as JSON."""

    try:
        raw_output = get_llm_response(
            task="planning",
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
        "milestones": [
            {"name": "M1: Core Scraper & Engine", "timeline": "Week 1-2", "deliverables": ["Web Monitor", "Diff Engine"]},
            {"name": "M2: User Dashboard & Alerts", "timeline": "Week 3-4", "deliverables": ["Web App", "Slack/Email Alerts"]}
        ],
        "risk_mitigation": ["Implement proxies to avoid scraper rate-limits"],
        "resource_allocation": ["1 Fullstack Dev", "1 AI/Backend Dev"]
    }
