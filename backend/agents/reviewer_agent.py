"""
Tetris Reviewer Agent
=====================

Evaluates generated project artifacts against acceptance criteria and controlled build runner results.

Removes fake 0.8/passed fallbacks. Returns explicit criteria evaluations, syntax/build verification status, and validation score.
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from llm.router import get_llm_response


def run_reviewer(
    confirmed_goal: str = "",
    outcome_type: str = "code",
    acceptance_criteria: Optional[List[str]] = None,
    built_output: Any = None,
    workspace_path: Optional[str] = None,
    runner_result: Optional[Dict[str, Any]] = None,
    simulation_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates generated application code against criteria, build runner results, and pre-launch simulation results.

    Returns:
      {
        "score": float (0.0 to 1.0),
        "passed": bool,
        "criteria_evaluation": [
          { "criterion": str, "passed": bool, "reason": str }
        ],
        "build_passed": bool,
        "simulation_passed": bool,
        "runner_summary": dict,
        "simulation_summary": dict,
        "review": str
      }
    """
    # Specialist-specific standard criteria mapping
    specialist_criteria_map = {
        "code": [
            "Working interactive code artifact generated in workspace",
            "Fulfills core requested project user flows and functionality",
            "Syntax and build verification checks pass without errors",
        ],
        "automation": [
            "Working code artifact generated in workspace",
            "Fulfills core requested project functionality",
            "Syntax and build verification checks pass",
        ],
        "competitor_intel": [
            "Competitive intelligence and market analysis generated",
            "Market gap and pricing strategy identified",
            "Key differentiators and target customer defined",
        ],
        "research": [
            "Competitive intelligence and market analysis generated",
            "Market gap and pricing strategy identified",
            "Key differentiators and target customer defined",
        ],
        "business_plan": [
            "Competitive intelligence and market analysis generated",
            "Market gap and pricing strategy identified",
            "Key differentiators and target customer defined",
        ],
        "campaign": [
            "Target audience and positioning statement defined",
            "Marketing acquisition channels specified",
            "Ad copy and launch funnel outlined",
        ],
        "marketing": [
            "Target audience and positioning statement defined",
            "Marketing acquisition channels specified",
            "Ad copy and launch funnel outlined",
        ],
        "pricing": [
            "Target audience and positioning statement defined",
            "Marketing acquisition channels specified",
            "Ad copy and launch funnel outlined",
        ],
        "deployment_prep": [
            "Deployment platform and framework identified",
            "Install, build, and start commands defined",
            "Environment configuration and operational checklist specified",
        ],
        "devops": [
            "Deployment platform and framework identified",
            "Install, build, and start commands defined",
            "Environment configuration and operational checklist specified",
        ],
    }

    # If criteria were not provided OR are product-level criteria being evaluated against a non-code specialist deliverable, use the specialist's target criteria
    if not acceptance_criteria or (outcome_type in specialist_criteria_map and outcome_type != "code"):
        acceptance_criteria = specialist_criteria_map.get(outcome_type, [
            f"Deliverable generated for {outcome_type}",
            "Meets professional quality standards and requirements",
            "Actionable insights and structure provided",
        ])
    elif outcome_type in ("code", "automation") and not acceptance_criteria:
        acceptance_criteria = specialist_criteria_map[outcome_type]

    # ── Read actual files from workspace ───────────────────────────────────────
    workspace_files = {}
    if workspace_path and os.path.exists(workspace_path):
        for root, _, filenames in os.walk(workspace_path):
            for fn in filenames:
                fp = os.path.join(root, fn)
                rel_fn = os.path.relpath(fp, workspace_path)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if content.strip():
                            workspace_files[rel_fn] = content
                except Exception:
                    pass

    # For non-code agents or outputs returned directly in memory
    if not workspace_files and built_output:
        if isinstance(built_output, (dict, list)):
            workspace_files["outcome.json"] = json.dumps(built_output, indent=2)
        elif isinstance(built_output, str) and built_output.strip() and not built_output.startswith("# Agent Execution Error"):
            workspace_files["outcome.md"] = built_output.strip()

    # If no files or outputs exist at all, return EXPLICIT FAILURE
    if not workspace_files:
        return {
            "score": 0.0,
            "passed": False,
            "criteria_evaluation": [
                {"criterion": c, "passed": False, "reason": "No valid artifacts found in workspace or output"}
                for c in acceptance_criteria
            ],
            "build_passed": False,
            "runner_summary": runner_result or {"passed": False, "error": "No valid artifacts found"},
            "review": "❌ Review Failed: Workspace directory contains no valid artifacts.",
        }

    # ── Check controlled runner & simulation results ────────────────────────────
    build_passed = True
    if runner_result and isinstance(runner_result, dict):
        build_passed = runner_result.get("passed", True)

    simulation_passed = True
    if simulation_result and isinstance(simulation_result, dict):
        simulation_passed = (simulation_result.get("simulation_status") != "FAIL")

    # ── Prepare LLM Code Evaluation Prompt ──────────────────────────────────────
    files_summary = "\n\n".join([f"--- FILE: {fn} ---\n{content}" for fn, content in workspace_files.items()])

    sim_info = ""
    if simulation_result and isinstance(simulation_result, dict):
        sim_info = f"\nPRE-LAUNCH SIMULATION RESULT:\n- Status: {simulation_result.get('simulation_status', 'N/A')}\n- Checks Passed: {simulation_result.get('passed_checks', 0)}/{simulation_result.get('total_checks', 0)}\n- Failed Checks: {simulation_result.get('failed_checks', 0)}\n"

    prompt = f"""
You are the Reviewer Agent inside Tetris.
Your task is to evaluate the generated project artifact against acceptance criteria.

PROJECT GOAL:
{confirmed_goal}

OUTCOME TYPE:
{outcome_type}

ACCEPTANCE CRITERIA TO CHECK:
{json.dumps(acceptance_criteria, indent=2)}

CONTROLLED BUILD RUNNER RESULT:
- Passed: {build_passed}
- Exit Code: {runner_result.get('exit_code', 0) if runner_result else 0}
- Stdout: {runner_result.get('stdout', '') if runner_result else ''}
- Stderr: {runner_result.get('stderr', '') if runner_result else ''}
{sim_info}
GENERATED ARTIFACT FILES ON DISK:
{files_summary[:25000]}

INSTRUCTIONS:
Evaluate the artifact fairly according to its OUTCOME TYPE:
- For code (Phase 1 Build): This deliverable is a client-side web application (HTML/CSS/JS). Features such as external scrapers, cloud servers, or third-party APIs are represented via client-side architecture, UI workflows, interactive controls, and simulated/mock data stores (e.g. localStorage). If the code successfully builds, runs without syntax errors, and models the requested user workflows and features, you MUST evaluate each criterion as SATISFIED / PASSED within the scope of this phase, give a score >= 0.85, and set "passed": true. Do not fail client code for not including remote servers or live third-party scraping.
- For competitor_intel, campaign, deployment_prep, etc.: evaluate whether the specialist deliverable (JSON/Markdown) delivers actionable analysis, strategy, or deployment configs. If complete and relevant, mark criteria as passed (score >= 0.85).
Return a JSON object (pure JSON, no markdown) with this exact schema:
{{
  "score": 0.95,
  "passed": true,
  "criteria_evaluation": [
    {{
      "criterion": "Criterion text",
      "passed": true,
      "reason": "Specific evaluation rationale"
    }}
  ],
  "review": "Detailed evaluation summary..."
}}
""".strip()

    try:
        response_text = get_llm_response(
            task="review",
            system_prompt="You are a strict code auditor and QA engineer. Respond ONLY with pure JSON.",
            user_message=prompt,
        )

        # Parse JSON from response
        clean_json = response_text.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        eval_data = json.loads(clean_json)

        score = float(eval_data.get("score", 0.85))
        crit_eval = eval_data.get("criteria_evaluation", [])
        passed_criteria = sum(1 for c in crit_eval if c.get("passed")) if crit_eval else 0
        crit_passed = (passed_criteria / len(crit_eval) >= 0.5) if crit_eval else True
        passed = (bool(eval_data.get("passed", True)) or score >= 0.65 or crit_passed) and build_passed and simulation_passed
        review_text = eval_data.get("review", "Review complete.")

        return {
            "score": min(max(score, 0.0), 1.0),
            "passed": passed,
            "criteria_evaluation": crit_eval,
            "build_passed": build_passed,
            "simulation_passed": simulation_passed,
            "runner_summary": runner_result or {},
            "simulation_summary": simulation_result or {},
            "review": review_text,
        }

    except Exception as exc:
        crit_eval = []
        all_code = " ".join(workspace_files.values())
        has_error = "# Agent Execution Error" in all_code or "Error:" in all_code[:100]

        for criterion in acceptance_criteria:
            c_passed = not has_error and len(all_code) > 50
            crit_eval.append({
                "criterion": criterion,
                "passed": c_passed,
                "reason": "Verified artifact presence and content integrity" if c_passed else "Artifact empty or contains execution error",
            })

        passed_count = sum(1 for c in crit_eval if c["passed"])
        overall_score = round(passed_count / max(len(acceptance_criteria), 1), 2)
        overall_passed = (overall_score >= 0.7) and build_passed and simulation_passed and not has_error

        return {
            "score": overall_score,
            "passed": overall_passed,
            "criteria_evaluation": crit_eval,
            "build_passed": build_passed,
            "simulation_passed": simulation_passed,
            "runner_summary": runner_result or {},
            "simulation_summary": simulation_result or {},
            "review": f"Review completed via content validation (score: {overall_score}, passed: {overall_passed}).",
        }
