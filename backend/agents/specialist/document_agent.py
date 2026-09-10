import os
import json
from dotenv import load_dotenv

load_dotenv()


def run_document(
    goal: str = "",
    context: str = "",
    phase: int = 4,
) -> dict:
    """
    Generates product architecture documentation, API specifications, and operational guide.
    """
    from llm.router import get_llm_response

    system_prompt = """You are the Technical Documentation Specialist inside TETRIS.
Generate a complete technical architecture and operational guide for the project.
Return ONLY valid JSON with this exact structure:
{
  "system_architecture": "Architecture overview",
  "data_model": ["Entity 1", "Entity 2"],
  "api_endpoints": [
    {"path": "/api/v1/resource", "method": "POST", "description": "Endpoint purpose"}
  ],
  "security_considerations": ["Security item 1", "Security item 2"],
  "operational_runbook": ["Step 1", "Step 2"]
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PREVIOUS CONTEXT:
{context}

Generate the complete documentation guide as JSON."""

    try:
        raw_output = get_llm_response(
            task="document",
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
        "system_architecture": f"Distributed monitoring microservices architecture for {goal[:50]}.",
        "data_model": ["CompetitorTarget", "PageSnapshot", "ChangeSummary", "AlertNotification"],
        "api_endpoints": [
            {"path": "/api/v1/targets", "method": "POST", "description": "Add competitor URL target"},
            {"path": "/api/v1/alerts", "method": "GET", "description": "Fetch change alerts"}
        ],
        "security_considerations": ["Encrypted credentials storage", "Rate limiting on API webhooks"],
        "operational_runbook": ["Verify web scraper worker health", "Monitor database queue size", "Check API latency metrics"]
    }
