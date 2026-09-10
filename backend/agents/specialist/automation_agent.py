import os
import json
from dotenv import load_dotenv

load_dotenv()


def run_automation(
    goal: str = "",
    context: str = "",
    phase: int = 1,
    prompt: str = "",
) -> dict:
    """
    Generates automated workflow automation and integration configurations.
    """
    from llm.router import get_llm_response

    system_prompt = """You are the Workflow Automation Specialist inside TETRIS.
Generate a complete automation workflow definition and integration manifest.
Return ONLY valid JSON with this exact structure:
{
  "workflow_name": "Automation workflow name",
  "triggers": ["Trigger 1", "Trigger 2"],
  "actions": ["Action 1", "Action 2"],
  "connectors": ["Stripe", "Slack", "Webhook"],
  "script_definition": "// JavaScript / Python automation logic snippet"
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PREVIOUS CONTEXT:
{context}

Generate the automation workflow specification as JSON."""

    try:
        raw_output = get_llm_response(
            task="automation",
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
        "workflow_name": f"Competitive Alert Automation for {goal[:50]}",
        "triggers": ["Page HTML Hash Change", "Pricing Table DOM Update", "Scheduled 6-Hour Cron"],
        "actions": ["Extract Changed Diff", "Summarize via LLM", "Dispatch Slack Notification"],
        "connectors": ["Slack", "Discord", "Custom Webhook"],
        "script_definition": "async function onWebPageChange(diff) { const summary = await summarize(diff); await sendSlackAlert(summary); }"
    }


def run_automation_agent(*args, **kwargs):
    return run_automation(*args, **kwargs)
