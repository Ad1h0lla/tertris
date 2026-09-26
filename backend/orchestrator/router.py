"""
Executa Specialist Router

Routes an execution request to the appropriate specialist agent.

The public contract recovered from main.py is:

route_to_specialist(
    outcome_type,
    confirmed_goal,
    context,
    phase
)
"""

from typing import Any, Dict


def _goal_text(confirmed_goal: Dict[str, Any]) -> str:
    if not confirmed_goal:
        return ""

    return str(
        confirmed_goal.get("understood_goal")
        or confirmed_goal.get("goal")
        or confirmed_goal.get("idea")
        or ""
    )


def _normalise_agent_type(value: Any) -> str:
    if not value:
        return "document"

    value = str(value).strip().lower()

    aliases = {
        "code_generation": "code",
        "coding": "code",
        "developer": "code",
        "dev": "code",

        "researcher": "research",
        "market_research": "research",
        "competitor": "competitor_intel",
        "competitor_intel": "competitor_intel",
        "business_plan": "competitor_intel",

        "pricing": "pricing",

        "deployment": "deployment_prep",
        "deployment_prep": "deployment_prep",

        "campaign": "campaign",
        "marketing": "campaign",

        "workflow": "automation",
        "integration": "automation",

        "docs": "document",
        "documentation": "document",

        "plan": "planner",
        "planning": "planner",
    }

    return aliases.get(value, value)


def _build_prompt(
    agent_type: str,
    confirmed_goal: Dict[str, Any],
    context: str,
    phase: int,
) -> str:
    goal = _goal_text(confirmed_goal)

    acceptance = confirmed_goal.get(
        "acceptance_criteria",
        [],
    ) if confirmed_goal else []

    return f"""
You are the {agent_type} specialist inside Executa.

Execution phase: {phase}

USER GOAL:
{goal}

ACCEPTANCE CRITERIA:
{acceptance}

PREVIOUS / ADDITIONAL CONTEXT:
{context}

Produce a concrete, useful outcome.

Do not return generic advice.
Do not use TODO placeholders.
Do not describe what you would do instead of doing it.

The output must be usable by the next execution stage.
""".strip()


def route_to_specialist(
    outcome_type: str,
    confirmed_goal: Dict[str, Any],
    context: str = "",
    phase: int = 1,
):
    """
    Route to one of Executa's specialist agents.

    Returns the specialist's output.
    """
    import json

    agent_type = _normalise_agent_type(outcome_type)

    prompt = _build_prompt(
        agent_type,
        confirmed_goal or {},
        context or "",
        phase,
    )

    try:
        if agent_type == "code":
            from agents.specialist.code_agent import write_code
            return write_code(
                goal=_goal_text(confirmed_goal),
                context=context,
                phase=phase,
                prompt=prompt,
                workspace_path=(confirmed_goal.get("_workspace_path") or confirmed_goal.get("workspace_path")) if isinstance(confirmed_goal, dict) else None,
                execution_id=(confirmed_goal.get("_execution_id") or confirmed_goal.get("execution_id")) if isinstance(confirmed_goal, dict) else None,
                feedback=(confirmed_goal.get("_feedback") or confirmed_goal.get("feedback")) if isinstance(confirmed_goal, dict) else None,
            )

        if agent_type == "competitor_intel":
            from agents.specialist.competitor_intel_agent import run_competitor_intel
            return run_competitor_intel(
                confirmed_goal=_goal_text(confirmed_goal),
                idea_type=confirmed_goal.get("idea_type", "saas") if isinstance(confirmed_goal, dict) else "saas",
                context=context,
            )

        if agent_type == "pricing":
            from agents.specialist.pricing_agent import run_pricing
            return run_pricing(
                confirmed_goal=_goal_text(confirmed_goal),
                competitor_data={},
                idea_type=confirmed_goal.get("idea_type", "saas") if isinstance(confirmed_goal, dict) else "saas",
            )

        if agent_type == "deployment_prep":
            from agents.specialist.deployment_prep_agent import run_deployment_prep
            return run_deployment_prep(
                code_output=context,
                project_name=_goal_text(confirmed_goal)[:30] or "Project",
                outcome_type=outcome_type,
            )

        if agent_type == "automation":
            try:
                from agents.specialist.automation_agent import run_automation
                return run_automation(
                    goal=_goal_text(confirmed_goal),
                    context=context,
                    phase=phase,
                    prompt=prompt,
                )
            except ImportError:
                from agents.specialist.automation_agent import run_automation_agent
                return run_automation_agent(
                    goal=_goal_text(confirmed_goal),
                    context=context,
                    phase=phase,
                )

        if agent_type == "research":
            from agents.specialist.research_agent import run_research
            return run_research(
                goal=_goal_text(confirmed_goal),
                context=context,
                phase=phase,
            )

        if agent_type == "campaign":
            from agents.specialist.campaign_agent import run_campaign
            return run_campaign(
                goal=_goal_text(confirmed_goal),
                context=context,
                phase=phase,
            )

        if agent_type == "planner":
            from agents.planner_agent import run_planner
            return run_planner(
                goal=_goal_text(confirmed_goal),
                context=context,
            )

        if agent_type == "document":
            from agents.specialist.document_agent import run_document
            return run_document(
                goal=_goal_text(confirmed_goal),
                context=context,
                phase=phase,
            )

        # Fallback:
        try:
            from agents.agent_router import route_agent
            return route_agent(
                agent_type=agent_type,
                goal=_goal_text(confirmed_goal),
                context=context,
                phase=phase,
            )
        except (ImportError, AttributeError):
            pass

        raise ValueError(
            f"Unsupported specialist agent type: {outcome_type}"
        )

    except Exception as exc:
        raise RuntimeError(f"Agent type `{agent_type}` execution failed: {exc}") from exc


__all__ = ["route_to_specialist"]
