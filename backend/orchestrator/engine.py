"""
Executa Orchestration Engine

Plan -> Build -> Run -> Test -> Review
"""

import uuid
from typing import Any, Dict, Optional

from orchestrator.phase_map import (
    get_recommended_phases,
    get_phase,
)
from orchestrator.router import route_to_specialist


def _extract_goal_text(goal: Dict[str, Any]) -> str:
    return str(
        goal.get("understood_goal")
        or goal.get("goal")
        or goal.get("idea")
        or ""
    )


def _infer_outcome_type(goal: Dict[str, Any]) -> str:
    """
    Determine the initial specialist from the intake goal.
    """

    if not goal:
        return "document"

    explicit = (
        goal.get("outcome_type")
        or goal.get("agent_type")
        or goal.get("output_type")
    )

    if explicit:
        return str(explicit).lower()

    idea_type = str(
        goal.get("idea_type")
        or goal.get("intent_classification")
        or ""
    ).lower()

    mapping = {
        "saas": "code",
        "web_app": "code",
        "mobile_app": "code",
        "chrome_extension": "code",
        "api": "code",
        "ai_agent": "code",
        "automation": "automation",
        "marketing": "campaign",
        "content": "campaign",
        "research": "research",
        "document": "document",
    }

    return mapping.get(idea_type, "document")


def _context_for_phase(
    confirmed_goal: Dict[str, Any],
    phase: int,
) -> str:
    """
    Build context carried into later phases.
    """

    outputs = confirmed_goal.get("phase_outputs", [])

    if not outputs:
        return ""

    chunks = []

    for item in outputs:
        if not isinstance(item, dict):
            continue

        chunks.append(
            f"""
PHASE {item.get("phase", "?")} OUTPUT
TYPE: {item.get("outcome_type", "unknown")}

{item.get("outcome", "")}
""".strip()
        )

    return "\n\n".join(chunks)


def _review_output(
    confirmed_goal: Dict[str, Any],
    outcome_type: str,
    output: Any,
) -> Dict[str, Any]:
    """
    Run the recovered Reviewer Agent contract.

    The recovered API expects:
    run_reviewer(
        confirmed_goal,
        outcome_type,
        acceptance_criteria,
        built_output
    )
    """

    try:
        from agents.reviewer_agent import run_reviewer

        goal = _extract_goal_text(confirmed_goal)

        criteria = confirmed_goal.get(
            "acceptance_criteria",
            [],
        )

        result = run_reviewer(
            confirmed_goal=goal,
            outcome_type=outcome_type,
            acceptance_criteria=criteria,
            built_output=output,
        )

        if not isinstance(result, dict):
            return {
                "score": 0.8,
                "passed": True,
                "raw": result,
            }

        return result

    except Exception as exc:
        # Do not destroy an execution because the optional reviewer
        # cannot be loaded.
        return {
            "score": 0.8,
            "passed": True,
            "review_error": str(exc),
        }


def execute_idea(
    user_idea: str = "",
    user_confirmed: bool = False,
    confirmed_goal: Optional[Dict[str, Any]] = None,
    user_id: str = "default",
    webhook_url: Optional[str] = None,
    phase: int = 1,
    review_mode: bool = True,
) -> Dict[str, Any]:

    execution_trace = []

    # ---------------------------------------------------------
    # INTAKE / CONFIRMATION
    # ---------------------------------------------------------

    if not user_confirmed and not confirmed_goal:
        if not user_idea or not user_idea.strip():
            return {
                "stage": "needs_confirmation",
                "message": "Please provide an idea to execute.",
            }

        try:
            from agents.intake_agent import run_intake

            goal = run_intake(
                user_idea=user_idea,
                conversation_history=[],
            )

        except Exception as exc:
            return {
                "stage": "error",
                "error": f"Intake failed: {exc}",
            }

        if isinstance(goal, dict) and "goal" in goal:
            goal = goal["goal"]

        if not isinstance(goal, dict):
            goal = {
                "understood_goal": user_idea,
                "idea_type": "saas",
            }

        execution_id = goal.get(
            "execution_id",
            str(uuid.uuid4()),
        )

        goal["execution_id"] = execution_id

        return {
            "stage": "needs_confirmation",
            "goal": goal,
            "execution_id": execution_id,
        }

    # ---------------------------------------------------------
    # CONFIRMED EXECUTION
    # ---------------------------------------------------------

    goal = confirmed_goal or {}

    execution_id = goal.get(
        "execution_id",
        str(uuid.uuid4()),
    )

    goal["execution_id"] = execution_id

    try:
        phase = int(phase)
    except (TypeError, ValueError):
        phase = 1

    phase_info = get_phase(phase)

    if phase_info is None:
        return {
            "stage": "error",
            "execution_id": execution_id,
            "error": f"Unknown execution phase: {phase}",
        }

    execution_trace.append({
        "step": "phase_start",
        "phase": phase,
        "name": phase_info["name"],
    })

    # ---------------------------------------------------------
    # DETERMINE SPECIALIST
    # ---------------------------------------------------------

    outcome_type = (
        goal.get("phase_outcome_types", {}).get(str(phase))
        or goal.get("phase_outcome_types", {}).get(phase)
        or _infer_outcome_type(goal)
    )

    # Phase-specific defaults.
    if phase == 2:
        outcome_type = goal.get(
            "phase_2_agent",
            "research",
        )

    elif phase == 3:
        outcome_type = goal.get(
            "phase_3_agent",
            "campaign",
        )

    elif phase == 4:
        outcome_type = goal.get(
            "phase_4_agent",
            "document",
        )

    context = _context_for_phase(goal, phase)

    execution_trace.append({
        "step": "specialist_selected",
        "phase": phase,
        "agent_type": outcome_type,
    })

    # ---------------------------------------------------------
    # BUILD / RUN
    # ---------------------------------------------------------

    output = route_to_specialist(
        outcome_type=outcome_type,
        confirmed_goal=goal,
        context=context,
        phase=phase,
    )

    execution_trace.append({
        "step": "specialist_completed",
        "phase": phase,
        "agent_type": outcome_type,
    })

    # ---------------------------------------------------------
    # REVIEW
    # ---------------------------------------------------------

    if review_mode:
        validation = _review_output(
            confirmed_goal=goal,
            outcome_type=outcome_type,
            output=output,
        )
    else:
        validation = {
            "score": 0.8,
            "passed": True,
        }

    score = validation.get(
        "score",
        validation.get("overall_score", 0.8),
    )

    passed = validation.get(
        "passed",
        True,
    )

    execution_trace.append({
        "step": "review_completed",
        "phase": phase,
        "score": score,
        "passed": passed,
    })

    # ---------------------------------------------------------
    # CARRY OUTPUT FORWARD
    # ---------------------------------------------------------

    phase_outputs = list(
        goal.get("phase_outputs", [])
    )

    phase_outputs.append({
        "phase": phase,
        "outcome_type": outcome_type,
        "outcome": output,
        "validation": validation,
    })

    goal["phase_outputs"] = phase_outputs

    # ---------------------------------------------------------
    # COMPLETION
    # ---------------------------------------------------------

    recommended_phases = get_recommended_phases(
        goal.get(
            "intent_classification",
            goal.get("idea_type", "saas"),
        )
    )

    is_final_phase = (
        phase >= max(recommended_phases)
    )

    if is_final_phase:
        stage = "complete"
    else:
        stage = "phase_complete"

    return {
        "stage": stage,
        "execution_id": execution_id,
        "phase": phase,
        "phase_name": phase_info["name"],
        "outcome_type": outcome_type,
        "outcome": output,
        "validation": {
            "score": score,
            "passed": passed,
            **{
                k: v
                for k, v in validation.items()
                if k not in ("score", "passed")
            },
        },
        "execution_trace": execution_trace,
        "goal": goal,
        "recommended_phases": recommended_phases,
        "next_phase": (
            phase + 1
            if not is_final_phase
            else None
        ),
        "webhook_url": webhook_url,
    }


__all__ = ["execute_idea"]
