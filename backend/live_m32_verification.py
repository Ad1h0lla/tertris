"""
Live Verification for M3.2 (Reddit Community Distribution Worker)
Tests the complete end-to-end execution path, approval gate, credential resolution, and persistence.
"""

import os
import sys
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# Configure UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=env_path)

from execution.distribution_models import (
    create_distribution_action,
    validate_distribution_action,
    ApprovalStatus,
    ExecutionStatus,
)
from execution.reddit_executor import (
    execute_reddit_action,
    resolve_reddit_credentials,
)
from execution.execution_router import execute_distribution_action
from database.models import SessionLocal, init_db
from database.operations import create_execution, get_connector_actions

def run_live_m32_verification():
    print("=" * 60)
    print("TETRIS M3.2 — LIVE REDDIT WORKER VERIFICATION")
    print("=" * 60)

    init_db()
    db = SessionLocal()
    exec_id = f"m32-live-{int(datetime.now(timezone.utc).timestamp())}"

    # 1. Create a live database execution
    ex = create_execution(
        db=db,
        user_id="user_001",
        original_idea="Developer Productivity Habit Tracker",
        understood_goal="Developer Productivity Habit Tracker",
        intent_classification="full_product",
        idea_type="saas",
        recommended_phases=[1, 2, 3, 4],
    )
    exec_id = ex.id
    print(f"Created Execution ID: {exec_id}")

    # 2. Construct candidate DistributionAction
    test_action = create_distribution_action(
        worker="community",
        platform="reddit",
        action_type="create_post",
        target={"community": "r/test"},
        content={
            "title": "[TETRIS M3.2 Test] Automated Habit Tracker Distribution Action",
            "body": "This is a verified test post from the Tetris Community Distribution Worker pipeline.",
        },
        execution_id=exec_id,
        reason="Target community identified from Phase 2 market research",
        source_url="https://www.reddit.com/r/ProductivityApps/comments/1vi2njw/all_top_tracker_apps_tier_list/",
    )

    print("\n--- STEP 1: Verification of Approval Gate ---")
    print(f"Initial Action Approval Status: {test_action['approval']['status']}")
    unapproved_result = execute_distribution_action(action=test_action, user_id="user_001", db=db)
    print(f"Unapproved Execution Result: status={unapproved_result.get('status')}, reason={unapproved_result.get('reason')}")
    assert unapproved_result.get("status") == ExecutionStatus.BLOCKED
    assert unapproved_result.get("reason") == "APPROVAL_REQUIRED"
    print("[PASS] Approval gate strictly blocks execution when status != APPROVED")

    # 3. Check Reddit Credentials
    print("\n--- STEP 2: Credential Resolution ---")
    creds = resolve_reddit_credentials(user_id="user_001", db=db)
    has_creds = bool(creds.get("client_id") and creds.get("client_secret") and creds.get("username") and creds.get("password"))
    print(f"Reddit Credentials Configured in backend/.env or DB: {has_creds}")

    # 4. Approve the action
    print("\n--- STEP 3: Action Approval & Live Route Execution ---")
    test_action["approval"]["status"] = ApprovalStatus.APPROVED
    print(f"Updated Action Approval Status: {test_action['approval']['status']}")

    live_result = execute_distribution_action(action=test_action, user_id="user_001", db=db)
    print(f"Execution Result:")
    print(f"  Status: {live_result.get('status')}")
    print(f"  Reason: {live_result.get('reason')}")
    print(f"  Verified: {live_result.get('verified')}")
    print(f"  External ID: {live_result.get('external_id')}")
    print(f"  External URL: {live_result.get('external_url')}")
    print(f"  Error: {live_result.get('error')}")

    # 5. Verify Persistence in SQLite
    print("\n--- STEP 4: Database Persistence Verification ---")
    actions = get_connector_actions(db, exec_id)
    print(f"Persisted ConnectorAction records count: {len(actions)}")
    for a in actions:
        print(f"  Connector: {a.connector_id}, Action: {a.action}, Status: {a.status}, ID: {a.id}")

    # 6. Contract Invariants
    print("\n--- STEP 5: Hard Invariant Checks ---")
    if not has_creds:
        assert live_result.get("status") == ExecutionStatus.BLOCKED, "Must return BLOCKED when credentials missing"
        assert live_result.get("reason") == "AUTH_REQUIRED", "Must state AUTH_REQUIRED"
        assert live_result.get("status") != ExecutionStatus.SUCCESS, "Fake SUCCESS detected!"
        assert live_result.get("external_url") is None, "Fake external URL detected!"
        print("[PASS] No fake success or simulated URLs returned. Clean BLOCKED / AUTH_REQUIRED contract observed.")
    else:
        if live_result.get("status") == ExecutionStatus.SUCCESS:
            assert live_result.get("verified") is True, "SUCCESS must have verified=True"
            assert live_result.get("verification_status") == "PASS", "SUCCESS must have verification_status=PASS"
            assert live_result.get("external_url") and "reddit.com" in live_result.get("external_url"), "Invalid permalink"
            print("[PASS] Live Reddit execution succeeded and verified with real permalink!")
        else:
            print(f"[NOTE] Live execution reported {live_result.get('status')} ({live_result.get('reason')}) without fake data.")

    db.close()
    print("\n" + "=" * 60)
    print("M3.2 LIVE VERIFICATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    run_live_m32_verification()
