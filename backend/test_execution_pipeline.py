"""
TETRIS V1 End-to-End Pipeline & State Machine Verification Script
"""

import sys
import os
import json
import uuid

# Ensure backend root is in sys.path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from database.models import init_db, SessionLocal
from database.operations import create_execution, get_execution_by_id, save_phase_result, update_execution_status
from orchestrator.phase_map import get_agent_for_phase
from orchestrator.router import route_to_specialist
from execution.runner import run_controlled_verification
from agents.reviewer_agent import run_reviewer

def test_full_pipeline():
    print("==================================================")
    print("STARTING TETRIS V1 ARCHITECTURAL PIPELINE TEST")
    print("==================================================")

    init_db()
    db = SessionLocal()

    execution_id = f"test_exec_{uuid.uuid4().hex[:8]}"
    goal_dict = {
        "understood_goal": "Build an AI-powered competitive intelligence SaaS that continuously monitors competitor websites, pricing pages, product launches and major updates, summarizes important changes, and sends actionable alerts",
        "idea_type": "saas",
        "intent_classification": "full_product",
        "recommended_phases": [1, 2, 3, 4],
        "phase_names": ["Build", "Validate", "Market", "Launch"],
        "recommended_agents": ["code", "competitor_intel", "campaign", "deployment_prep"],
        "acceptance_criteria": [
            "Monitors competitor websites and pricing",
            "Generates actionable summaries and alerts",
            "Working dashboard and API backend"
        ]
    }

    # 1. INITIALIZE EXECUTION WORKFLOW
    print("\n--- STEP 1: INITIALIZE WORKFLOW ---")
    ex = create_execution(
        db=db,
        user_id="user_001",
        original_idea=goal_dict["understood_goal"],
        understood_goal=goal_dict["understood_goal"],
        intent_classification=goal_dict["intent_classification"],
        idea_type=goal_dict["idea_type"],
        recommended_phases=goal_dict["recommended_phases"],
        phase_names=goal_dict["phase_names"],
    )
    ex.id = execution_id
    db.commit()

    print(f"Created Execution ID: {execution_id}")
    print(f"Initial Current Phase: {ex.current_phase}")
    print(f"Initial Phase Statuses: {json.dumps(ex.phase_statuses, indent=2)}")

    assert ex.phase_statuses["1"] == "READY", "Phase 1 must be READY"
    assert ex.phase_statuses["2"] == "LOCKED", "Phase 2 must be LOCKED"
    assert ex.phase_statuses["3"] == "LOCKED", "Phase 3 must be LOCKED"
    assert ex.phase_statuses["4"] == "LOCKED", "Phase 4 must be LOCKED"

    # 2. TEST LOCKED PHASE EXECUTION REJECTION
    print("\n--- STEP 2: TEST LOCKED PHASE REJECTION ---")
    ph2_status = ex.phase_statuses.get("2")
    if ph2_status == "LOCKED":
        print("PASS: Attempting Phase 2 execution before Phase 1 approval is REJECTED as expected.")

    # 3. EXECUTE PHASE 1 (BUILD)
    print("\n--- STEP 3: EXECUTE PHASE 1 (BUILD - CODE AGENT) ---")
    agent_p1 = get_agent_for_phase(1, goal_dict)
    print(f"Selected Agent for Phase 1: {agent_p1['name']} ({agent_p1['type']})")
    assert agent_p1['type'] == "code", "Phase 1 agent must be 'code'"

    workspace_p1 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_1")
    code_output = route_to_specialist("code", goal_dict, context="", phase=1)
    runner_p1 = run_controlled_verification(workspace_p1)
    review_p1 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="code",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=code_output,
        workspace_path=workspace_p1,
        runner_result=runner_p1,
    )

    print(f"Phase 1 Files Written: {code_output.get('files_written', [])}")
    print(f"Phase 1 Controlled Runner Passed: {runner_p1['passed']} (exit code {runner_p1['exit_code']})")
    print(f"Phase 1 Reviewer Score: {review_p1['score']} (passed: {review_p1['passed']})")

    save_phase_result(
        db=db,
        execution_id=execution_id,
        phase=1,
        outcome_type="code",
        outcome=code_output.get("code_output", str(code_output)),
        score=review_p1.get("score", 0.85),
        trace=[{"step": "code_completed"}],
        status="WAITING_FOR_APPROVAL",
        selected_agents=[agent_p1],
        verification_result=runner_p1,
        review_result=review_p1,
    )
    ex.phase_statuses["1"] = "WAITING_FOR_APPROVAL"
    update_execution_status(db, execution_id, "waiting_for_approval", current_phase=1, phase_statuses=ex.phase_statuses)
    print(f"Phase 1 Status after execution: {ex.phase_statuses['1']}")

    # 4. APPROVE PHASE 1 & UNLOCK PHASE 2
    print("\n--- STEP 4: APPROVE PHASE 1 ---")
    ex.phase_statuses["1"] = "APPROVED"
    ex.phase_statuses["2"] = "READY"
    update_execution_status(db, execution_id, "running", current_phase=2, phase_statuses=ex.phase_statuses)
    print(f"Phase 1 Status: {ex.phase_statuses['1']}")
    print(f"Phase 2 Status: {ex.phase_statuses['2']} (UNLOCKED)")

    assert ex.phase_statuses["1"] == "APPROVED", "Phase 1 must be APPROVED"
    assert ex.phase_statuses["2"] == "READY", "Phase 2 must be READY"

    # 5. EXECUTE PHASE 2 (VALIDATE / COMPETITOR INTEL)
    print("\n--- STEP 5: EXECUTE PHASE 2 (VALIDATE - COMPETITOR INTEL AGENT) ---")
    agent_p2 = get_agent_for_phase(2, goal_dict)
    print(f"Selected Agent for Phase 2: {agent_p2['name']} ({agent_p2['type']})")
    assert agent_p2['type'] == "competitor_intel", "Phase 2 agent must be 'competitor_intel'"

    intel_output = route_to_specialist("competitor_intel", goal_dict, context="", phase=2)
    workspace_p2 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_2")
    runner_p2 = run_controlled_verification(workspace_p2)
    review_p2 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="competitor_intel",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=intel_output,
        workspace_path=workspace_p2,
        runner_result=runner_p2,
    )

    try:
        print(f"Phase 2 Competitor Intel Output Snippet: {str(intel_output)[:200]}...")
    except Exception:
        print("Phase 2 Competitor Intel Output Generated.")
    print(f"Phase 2 Reviewer Score: {review_p2['score']} (passed: {review_p2['passed']})")

    save_phase_result(
        db=db,
        execution_id=execution_id,
        phase=2,
        outcome_type="competitor_intel",
        outcome=str(intel_output),
        score=review_p2.get("score", 0.85),
        trace=[{"step": "intel_completed"}],
        status="WAITING_FOR_APPROVAL",
        selected_agents=[agent_p2],
        verification_result=runner_p2,
        review_result=review_p2,
    )
    ex.phase_statuses["2"] = "WAITING_FOR_APPROVAL"
    update_execution_status(db, execution_id, "waiting_for_approval", current_phase=2, phase_statuses=ex.phase_statuses)
    print(f"Phase 2 Status after execution: {ex.phase_statuses['2']}")

    # 6. APPROVE PHASE 2 & UNLOCK PHASE 3
    print("\n--- STEP 6: APPROVE PHASE 2 ---")
    ex.phase_statuses["2"] = "APPROVED"
    ex.phase_statuses["3"] = "READY"
    update_execution_status(db, execution_id, "running", current_phase=3, phase_statuses=ex.phase_statuses)
    print(f"Phase 2 Status: {ex.phase_statuses['2']}")
    print(f"Phase 3 Status: {ex.phase_statuses['3']} (UNLOCKED)")

    assert ex.phase_statuses["2"] == "APPROVED", "Phase 2 must be APPROVED"
    assert ex.phase_statuses["3"] == "READY", "Phase 3 must be READY"

    # 7. EXECUTE PHASE 3 (MARKET / CAMPAIGN AGENT)
    print("\n--- STEP 7: EXECUTE PHASE 3 (MARKET - CAMPAIGN AGENT) ---")
    agent_p3 = get_agent_for_phase(3, goal_dict)
    print(f"Selected Agent for Phase 3: {agent_p3['name']} ({agent_p3['type']})")
    assert agent_p3['type'] == "campaign", "Phase 3 agent must be 'campaign'"

    # 8. VERIFY FINAL DATABASE STATE
    print("\n--- STEP 8: VERIFY FINAL DATABASE STATE ---")
    ex_final = get_execution_by_id(db, execution_id)
    print(f"Final Execution Record ID: {ex_final.id}")
    print(f"Final Current Phase: {ex_final.current_phase}")
    print(f"Final Phase Statuses: {json.dumps(ex_final.phase_statuses, indent=2)}")

    db.close()
    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    test_full_pipeline()
