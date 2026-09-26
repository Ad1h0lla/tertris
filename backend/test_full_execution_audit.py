"""
TETRIS V1 Full Phase Execution (Phases 1-4) Audit & Verification Test
"""

import sys
import os
import json
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from database.models import init_db, SessionLocal
from database.operations import create_execution, get_execution_by_id, save_phase_result, update_execution_status
from orchestrator.phase_map import get_agent_for_phase
from orchestrator.router import route_to_specialist
from execution.runner import run_controlled_verification
from agents.reviewer_agent import run_reviewer

def run_full_execution_audit():
    print("======================================================================")
    print("STARTING TETRIS V1 FULL END-TO-END PHASE EXECUTION AUDIT (PHASES 1-4)")
    print("======================================================================")

    init_db()
    db = SessionLocal()

    execution_id = f"audit_exec_{uuid.uuid4().hex[:8]}"
    goal_dict = {
        "understood_goal": "Build an AI-powered competitive intelligence SaaS that monitors competitor websites, pricing pages, product launches and major updates, summarizes meaningful changes, and sends actionable alerts to startup founders and product teams.",
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

    # 1. INITIALIZATION
    print("\n--- STEP 1: WORKFLOW INITIALIZATION ---")
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
    goal_dict["execution_id"] = execution_id
    db.commit()

    print(f"Execution ID: {execution_id}")
    print(f"Initial Phase Statuses: {json.dumps(ex.phase_statuses, indent=2)}")

    assert ex.phase_statuses["1"] == "READY"
    assert ex.phase_statuses["2"] == "LOCKED"
    assert ex.phase_statuses["3"] == "LOCKED"
    assert ex.phase_statuses["4"] == "LOCKED"

    # 2. PHASE 1 (BUILD - CODE AGENT)
    print("\n--- STEP 2: EXECUTE PHASE 1 (BUILD - CODE AGENT) ---")
    agent_p1 = get_agent_for_phase(1, goal_dict)
    print(f"Agent: {agent_p1['name']} ({agent_p1['type']})")
    assert agent_p1['type'] == "code"

    ws_p1 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_1")
    os.makedirs(ws_p1, exist_ok=True)
    out_p1 = route_to_specialist("code", goal_dict, context="", phase=1)

    runner_p1 = run_controlled_verification(ws_p1)
    review_p1 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="code",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=out_p1,
        workspace_path=ws_p1,
        runner_result=runner_p1,
    )
    print(f"Phase 1 Files: {out_p1.get('files_written', [])}")
    print(f"Phase 1 Reviewer Score: {review_p1['score']} (passed: {review_p1['passed']})")

    assert review_p1['passed'] is True, "Phase 1 must pass review"

    ex.phase_statuses["1"] = "APPROVED"
    ex.phase_statuses["2"] = "READY"
    update_execution_status(db, execution_id, "running", current_phase=2, phase_statuses=ex.phase_statuses)
    print(f"Phase 1 APPROVED -> Phase 2 UNLOCKED & READY")

    # 3. PHASE 2 (VALIDATE - COMPETITOR INTEL AGENT)
    print("\n--- STEP 3: EXECUTE PHASE 2 (VALIDATE - COMPETITOR INTEL AGENT) ---")
    agent_p2 = get_agent_for_phase(2, goal_dict)
    print(f"Agent: {agent_p2['name']} ({agent_p2['type']})")
    assert agent_p2['type'] == "competitor_intel"

    # Build Phase 1 context to chain into Phase 2 (mirrors main.py lines 299-312)
    phase1_outcome = json.dumps(out_p1, indent=2, default=str) if isinstance(out_p1, dict) else str(out_p1)
    phase1_context = f"--- Phase 1 (code) Output ---\n{phase1_outcome}"

    ws_p2 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_2")
    os.makedirs(ws_p2, exist_ok=True)
    out_p2 = route_to_specialist("competitor_intel", goal_dict, context=phase1_context, phase=2)

    art_file_p2 = os.path.join(ws_p2, "phase_2_deliverable.json")
    with open(art_file_p2, "w", encoding="utf-8") as f:
        f.write(json.dumps(out_p2, indent=2))

    runner_p2 = run_controlled_verification(ws_p2)
    review_p2 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="competitor_intel",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=out_p2,
        workspace_path=ws_p2,
        runner_result=runner_p2,
    )
    print(f"Phase 2 Reviewer Score: {review_p2['score']} (passed: {review_p2['passed']})")
    assert review_p2['passed'] is True, "Phase 2 must pass review"

    ex.phase_statuses["2"] = "APPROVED"
    ex.phase_statuses["3"] = "READY"
    update_execution_status(db, execution_id, "running", current_phase=3, phase_statuses=ex.phase_statuses)
    print(f"Phase 2 APPROVED -> Phase 3 UNLOCKED & READY")

    # 4. PHASE 3 (MARKET - CAMPAIGN AGENT)
    print("\n--- STEP 4: EXECUTE PHASE 3 (MARKET - CAMPAIGN AGENT) ---")
    agent_p3 = get_agent_for_phase(3, goal_dict)
    print(f"Agent: {agent_p3['name']} ({agent_p3['type']})")
    assert agent_p3['type'] == "campaign"

    ws_p3 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_3")
    os.makedirs(ws_p3, exist_ok=True)
    out_p3 = route_to_specialist("campaign", goal_dict, context="", phase=3)

    art_file_p3 = os.path.join(ws_p3, "phase_3_deliverable.json")
    with open(art_file_p3, "w", encoding="utf-8") as f:
        f.write(json.dumps(out_p3, indent=2))

    runner_p3 = run_controlled_verification(ws_p3)
    review_p3 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="campaign",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=out_p3,
        workspace_path=ws_p3,
        runner_result=runner_p3,
    )
    print(f"Phase 3 Campaign Audience: {out_p3.get('target_audience')}")
    print(f"Phase 3 Reviewer Score: {review_p3['score']} (passed: {review_p3['passed']})")
    assert review_p3['passed'] is True, "Phase 3 must pass review"

    ex.phase_statuses["3"] = "APPROVED"
    ex.phase_statuses["4"] = "READY"
    update_execution_status(db, execution_id, "running", current_phase=4, phase_statuses=ex.phase_statuses)
    print(f"Phase 3 APPROVED -> Phase 4 UNLOCKED & READY")

    # 5. PHASE 4 (LAUNCH - DEPLOYMENT PREP AGENT)
    print("\n--- STEP 5: EXECUTE PHASE 4 (LAUNCH - DEPLOYMENT PREP AGENT) ---")
    agent_p4 = get_agent_for_phase(4, goal_dict)
    print(f"Agent: {agent_p4['name']} ({agent_p4['type']})")
    assert agent_p4['type'] == "deployment_prep"

    ws_p4 = os.path.join(_BACKEND_DIR, "generated_projects", execution_id, "phase_4")
    os.makedirs(ws_p4, exist_ok=True)
    out_p4 = route_to_specialist("deployment_prep", goal_dict, context="", phase=4)

    art_file_p4 = os.path.join(ws_p4, "phase_4_deliverable.json")
    with open(art_file_p4, "w", encoding="utf-8") as f:
        f.write(json.dumps(out_p4, indent=2))

    runner_p4 = run_controlled_verification(ws_p4)
    review_p4 = run_reviewer(
        confirmed_goal=goal_dict["understood_goal"],
        outcome_type="deployment_prep",
        acceptance_criteria=goal_dict["acceptance_criteria"],
        built_output=out_p4,
        workspace_path=ws_p4,
        runner_result=runner_p4,
    )
    print(f"Phase 4 Deployment Platform: {out_p4.get('recommended_platform')}")
    print(f"Phase 4 Reviewer Score: {review_p4['score']} (passed: {review_p4['passed']})")
    assert review_p4['passed'] is True, "Phase 4 must pass review"

    ex.phase_statuses["4"] = "APPROVED"
    update_execution_status(db, execution_id, "completed", current_phase=4, phase_statuses=ex.phase_statuses)
    print(f"Phase 4 APPROVED -> Execution STATUS: COMPLETED")

    # 6. VERIFY FINAL DATABASE STATE
    print("\n--- STEP 6: VERIFY FINAL SQLITE DATABASE STATE ---")
    ex_final = get_execution_by_id(db, execution_id)
    print(f"Execution Record ID: {ex_final.id}")
    print(f"Execution Status: {ex_final.status}")
    print(f"Final Phase Statuses: {json.dumps(ex_final.phase_statuses, indent=2)}")

    assert ex_final.status == "completed"
    assert ex_final.phase_statuses["1"] == "APPROVED"
    assert ex_final.phase_statuses["2"] == "APPROVED"
    assert ex_final.phase_statuses["3"] == "APPROVED"
    assert ex_final.phase_statuses["4"] == "APPROVED"

    db.close()
    print("\n======================================================================")
    print("ALL 4 PHASES EXECUTED, VERIFIED, AND APPROVED SUCCESSFULLY!")
    print("======================================================================")

if __name__ == "__main__":
    run_full_execution_audit()
