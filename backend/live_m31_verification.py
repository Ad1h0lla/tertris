"""
Live Pipeline Verification for M3.1
Runs live Phase 2 (with real Serper search) -> passes distribution intelligence to Phase 3 -> generates proposed actions.
"""
import os
import sys
import json
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Explicitly load .env from backend directory
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=env_path)

from orchestrator.router import route_to_specialist
from agents.specialist.campaign_agent import run_campaign
from execution.distribution_models import validate_distribution_action, ApprovalStatus, ExecutionStatus

def run_live_verification():
    print("=== STEP 1: Executing Real Phase 2 (Competitor Intel + Pricing + Distribution Intel) ===")
    goal = "Minimalist habit tracker web app for developers"
    goal_dict = {
        "understood_goal": goal,
        "idea_type": "saas",
    }
    
    phase2_res = route_to_specialist(
        outcome_type="competitor_intel",
        confirmed_goal=goal_dict,
        context="Phase 1: Responsive Single-Page HTML/JS Habit Tracker with streak analytics",
        phase=2,
    )
    
    print(f"Phase 2 Status: {phase2_res.get('phase_2_status')}")
    print(f"Research Source: {phase2_res.get('research_source')}")
    print(f"Search Status: {phase2_res.get('search_status')}")
    print(f"Source URLs count: {len(phase2_res.get('source_urls', []))}")
    print(f"Distribution Intelligence keys: {list(phase2_res.get('distribution_intelligence', {}).keys())}")
    
    dist_intel = phase2_res.get("distribution_intelligence", {})
    print("Communities discovered:", json.dumps(dist_intel.get("communities", []), indent=2))
    print("Customer problems:", json.dumps(dist_intel.get("customer_problems", []), indent=2))
    
    print("\n=== STEP 2: Executing Phase 3 Distribution Planning with Phase 2 Context ===")
    phase3_res = route_to_specialist(
        outcome_type="campaign",
        confirmed_goal=goal_dict,
        context=json.dumps(phase2_res, indent=2),
        phase=3,
    )
    
    plan = phase3_res.get("distribution_plan", {})
    actions = plan.get("actions", [])
    print(f"Distribution Plan Recommended Workers: {plan.get('recommended_workers')}")
    print(f"Total Proposed Actions: {len(actions)}")
    for idx, act in enumerate(actions, 1):
        print(f"\nAction #{idx}:")
        print(f"  Worker: {act.get('worker')}")
        print(f"  Platform: {act.get('platform')}")
        print(f"  Action Type: {act.get('action_type')}")
        print(f"  Target: {json.dumps(act.get('target'))}")
        print(f"  Approval Status: {act.get('approval', {}).get('status')}")
        print(f"  Execution Status: {act.get('execution', {}).get('status')}")
        print(f"  Verification Status: {act.get('receipt', {}).get('verification_status')}")
        print(f"  Source URL: {act.get('source_url')}")
    
    print("\n=== VERIFICATION CHECKS ===")
    assert phase2_res.get("phase_2_status") in ("SUCCESS", "DEGRADED"), "Phase 2 failed"
    assert "distribution_intelligence" in phase2_res, "Missing distribution_intelligence in Phase 2"
    assert len(actions) > 0, "No distribution actions proposed"
    for act in actions:
        assert validate_distribution_action(act) is True, f"Action failed contract validation: {act}"
        assert act.get("approval", {}).get("status") == ApprovalStatus.PENDING_APPROVAL, "Action not PENDING_APPROVAL"
        assert act.get("execution", {}).get("status") == ExecutionStatus.NOT_STARTED, "Action not NOT_STARTED"
        assert act.get("execution", {}).get("status") != ExecutionStatus.SUCCESS, "Fake SUCCESS detected!"
    print("\nALL LIVE PIPELINE VERIFICATION CHECKS PASSED!")

if __name__ == "__main__":
    run_live_verification()
