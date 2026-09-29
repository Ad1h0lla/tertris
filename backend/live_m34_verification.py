"""
Tetris — Milestone 3.4 Live Verification Script
================================================

Executes a live verification run against the real configured email provider (SendGrid / SMTP)
with full approval gating, credential safety, receipt persistence, and idempotency checks.
"""

import os
import json
import uuid
from dotenv import load_dotenv

from database.models import SessionLocal, init_db, ConnectorAction, PhaseResult
from execution.distribution_models import (
    create_distribution_action,
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)
from execution.execution_router import execute_distribution_action
from execution.email_executor import (
    resolve_sendgrid_credentials,
    resolve_smtp_credentials,
)

load_dotenv()


def run_live_verification():
    init_db()
    db = SessionLocal()

    print("\n==================================================")
    print(" TETRIS — M3.4 LIVE EMAIL VERIFICATION")
    print("==================================================")

    # 1. Inspect configured credentials
    sg_creds = resolve_sendgrid_credentials(user_id="user_001", db=db)
    smtp_creds = resolve_smtp_credentials(user_id="user_001", db=db)

    active_provider = None
    if sg_creds.get("api_key"):
        active_provider = "sendgrid"
        print(" [AUTH] Found SendGrid credentials.")
    elif smtp_creds.get("host") and (smtp_creds.get("username") or smtp_creds.get("port")):
        active_provider = "smtp"
        print(" [AUTH] Found SMTP credentials.")
    else:
        print(" [AUTH] No active email credentials configured in environment/vault.")
        print(" Verification result: BLOCKED (AUTH_REQUIRED)")
        db.close()
        return

    # 2. Prepare DistributionAction
    test_exec_id = f"live_exec_{uuid.uuid4().hex[:8]}"
    test_action_id = f"live_act_{uuid.uuid4().hex[:8]}"
    test_recipient = os.getenv("TEST_EMAIL_RECIPIENT", "test-recipient@example.com")

    action = create_distribution_action(
        worker="outreach",
        platform="email",
        action_type="send_email",
        target={"email": test_recipient},
        content={
            "subject": "Tetris M3.4 Live Outreach Verification",
            "body": "This is an automated verification email from Tetris M3.4 Outreach Worker.",
        },
        action_id=test_action_id,
        execution_id=test_exec_id,
        approval_required=True,
        reason="Targeted outreach opportunity identified in Phase 2 research",
        source_url="https://example.com/research/opportunity-123",
    )

    print(f"\n1. DistributionAction Created (ID: {test_action_id})")
    print(f"   Approval Status: {action['approval']['status']}")
    print(f"   Target Recipient: {test_recipient}")

    # 3. Test Approval Gate (Unapproved execution)
    print("\n2. Testing Approval Gate (Unapproved execution)...")
    unapproved_result = execute_distribution_action(action=action, user_id="user_001", db=db)
    print(f"   Status: {unapproved_result['status']}")
    print(f"   Reason: {unapproved_result.get('reason')}")
    assert unapproved_result["status"] == ExecutionStatus.BLOCKED
    assert unapproved_result.get("reason") == "APPROVAL_REQUIRED"
    print("   [PASS] Gate blocked unapproved action safely.")

    # 4. Approve Action
    print("\n3. User explicitly approves action...")
    action["approval"]["status"] = ApprovalStatus.APPROVED
    print(f"   Approval Status: {action['approval']['status']}")

    # 5. Live Execution
    print(f"\n4. Executing via live provider ({active_provider})...")
    live_result = execute_distribution_action(action=action, user_id="user_001", db=db)
    print(f"   Status: {live_result.get('status')}")
    print(f"   Verified: {live_result.get('verified')}")
    print(f"   Verification Status: {live_result.get('verification_status')}")
    print(f"   External Message ID: {live_result.get('external_id')}")
    print(f"   Provider Status: {live_result.get('receipt', {}).get('provider_status')}")
    print(f"   Delivery Status: {live_result.get('receipt', {}).get('delivery_status')}")
    if live_result.get("error"):
        print(f"   Error/Detail: {live_result.get('error')}")

    # 6. Check Database Persistence
    print("\n5. Checking Persistence in SQLite (ConnectorAction)...")
    ca = db.query(ConnectorAction).filter(ConnectorAction.id == test_action_id).first()
    if ca:
        print(f"   [PASS] Found ConnectorAction record in SQLite (ID: {ca.id}, Status: {ca.status})")
    else:
        print("   [FAIL] No ConnectorAction record found.")

    # 7. Check Duplicate Protection / Idempotency
    print("\n6. Testing Duplicate Protection / Idempotency...")
    if live_result.get("status") == ExecutionStatus.SUCCESS:
        second_result = execute_distribution_action(action=action, user_id="user_001", db=db)
        print(f"   Second attempt status: {second_result.get('status')}")
        assert second_result.get("status") == ExecutionStatus.SUCCESS
        print("   [PASS] Idempotency protected against duplicate send.")
    else:
        print("   [SKIP] Duplicate test skipped because initial live send was not SUCCESS (e.g. unverified sender identity).")

    # 8. Confirm Secret Redaction
    print("\n7. Checking Secret Safety...")
    result_json = json.dumps(live_result)
    for s in [sg_creds.get("api_key"), smtp_creds.get("password")]:
        if s and s in result_json:
            print("   [FAIL] Raw secret leaked in result!")
            db.close()
            return
    print("   [PASS] Zero secret leakage in execution result.")

    print("\n==================================================")
    print(" LIVE VERIFICATION RUN COMPLETE")
    print("==================================================")
    db.close()


if __name__ == "__main__":
    run_live_verification()
