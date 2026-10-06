"""
Tetris — Live Reddit Comment Preflight & Controlled Single Execution
===================================================================

Executes the verification and controlled single comment write against:
https://www.reddit.com/r/n8n/comments/1wxsr8b/how_do_you_actually_hand_off_an_n8n_instagram/

Safety & Compliance Rules:
1. No credential values are logged or exposed.
2. Complete preflight verification across steps 1-5.
3. Strict approval gate enforcement check.
4. Exactly ONE real write dispatched if preflight passes.
5. Real outcome recorded to SQLite database (connector_actions).
6. No fabrication of SUCCESS.
"""

import sys
import os
import uuid
import json
import logging
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from dotenv import load_dotenv
load_dotenv()

from database.models import init_db, SessionLocal, ConnectorAction
from execution.reddit_executor import (
    RedditAPIsProvider,
    resolve_redditapis_credentials,
    check_redditapis_readiness,
    execute_reddit_action,
)
from execution.distribution_models import ExecutionStatus, VerificationStatus

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TARGET_URL = "https://www.reddit.com/r/n8n/comments/1wxsr8b/how_do_you_actually_hand_off_an_n8n_instagram/"
TARGET_THREAD_ID = "1wxsr8b"
TARGET_SUBREDDIT = "n8n"
COMMENT_TEXT = (
    "Interesting question – the handoff problem is exactly where a lot of automation "
    "workflows seem to break down. Curious to see how others are handling the transition "
    "from an n8n-built workflow to something maintainable for the end user."
)


def run_preflight_and_execution():
    print("\n" + "=" * 75)
    print("  TETRIS LIVE REDDIT COMMENT — PREFLIGHT & CONTROLLED EXECUTION")
    print("=" * 75 + "\n")

    init_db()
    db = SessionLocal()
    user_id = "user_001"

    # -------------------------------------------------------------------------
    # 1. Verify all four Reddit session credentials are loaded (NO printing values)
    # -------------------------------------------------------------------------
    print("[1/5] Verifying Reddit session credentials are loaded...")
    creds = resolve_redditapis_credentials(user_id=user_id, db=db)
    api_key = creds.get("api_key")
    cookies = creds.get("session_cookies") or {}

    has_api_key = bool(api_key and str(api_key).strip())
    has_session = bool(cookies.get("reddit_session") and str(cookies.get("reddit_session")).strip())
    has_loid = bool(cookies.get("loid") and str(cookies.get("loid")).strip())
    has_token_v2 = bool(cookies.get("token_v2") and str(cookies.get("token_v2")).strip())
    has_csrf = bool(cookies.get("csrf_token") and str(cookies.get("csrf_token")).strip())

    print(f"       REDDITAPIS_API_KEY  : {'PRESENT (Loaded)' if has_api_key else 'MISSING'}")
    print(f"       REDDIT_SESSION      : {'PRESENT (Loaded)' if has_session else 'MISSING'}")
    print(f"       REDDIT_LOID         : {'PRESENT (Loaded)' if has_loid else 'MISSING'}")
    print(f"       REDDIT_TOKEN_V2     : {'PRESENT (Loaded)' if has_token_v2 else 'MISSING'}")
    print(f"       REDDIT_CSRF_TOKEN   : {'PRESENT (Loaded)' if has_csrf else 'MISSING'}")

    if not (has_api_key and has_session and has_loid and has_token_v2 and has_csrf):
        print("\n[PREFLIGHT FAILED] Missing one or more required Reddit credentials. Aborting write.")
        return {"preflight_passed": False, "reason": "MISSING_CREDENTIALS"}

    print("       -> Preflight Check 1 PASS: All 4 session credentials + API key present.")

    # -------------------------------------------------------------------------
    # 2. Verify RedditAPIs authenticated read still returns HTTP 200
    # -------------------------------------------------------------------------
    print("\n[2/5] Verifying RedditAPIs authenticated read...")
    prov = RedditAPIsProvider(api_key=api_key, session_cookies=cookies)
    read_res = prov.search(query="n8n", subreddit="n8n", limit=3)
    
    if not read_res.get("success"):
        print(f"       [FAIL] Authenticated read failed: {read_res.get('error')}")
        print("\n[PREFLIGHT FAILED] Read test did not return success. Aborting write.")
        return {"preflight_passed": False, "reason": "READ_AUTH_FAILED", "error": read_res.get("error")}

    print(f"       -> Authenticated read HTTP 200 OK. Found {read_res.get('count', 0)} posts.")
    print("       -> Preflight Check 2 PASS: Authenticated read verified.")

    # -------------------------------------------------------------------------
    # 3. Verify the target post is active
    # -------------------------------------------------------------------------
    print(f"\n[3/5] Verifying target post is active: {TARGET_URL}...")
    post_verif = prov.verify_post(post_id=TARGET_THREAD_ID, subreddit=TARGET_SUBREDDIT)
    print(f"       Post verified       : {post_verif.get('verified')}")
    print(f"       Post external ID    : {post_verif.get('external_id')}")
    print(f"       Post title          : {post_verif.get('title')}")

    if not post_verif.get("verified"):
        print(f"       [FAIL] Target post verification failed: {post_verif.get('error')}")
        print("\n[PREFLIGHT FAILED] Target post is inactive or inaccessible. Aborting write.")
        return {"preflight_passed": False, "reason": "TARGET_POST_INACCESSIBLE", "error": post_verif.get("error")}

    print("       -> Preflight Check 3 PASS: Target post is active on Reddit.")

    # -------------------------------------------------------------------------
    # 4. Verify the RedditAPIs write payload includes token_v2 and csrf_token
    # -------------------------------------------------------------------------
    print("\n[4/5] Verifying RedditAPIs write payload construction (mocked call)...")
    captured_payload = {}
    
    def fake_post(url, json=None, headers=None, timeout=None):
        nonlocal captured_payload
        captured_payload = json or {}
        # Return a dummy response to avoid actual execution during payload check
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"comment_id": "test_dry_run_id", "permalink": "/r/test"}
        return mock_resp

    test_session = MagicMock()
    test_session.post = fake_post
    mock_prov = RedditAPIsProvider(api_key=api_key, session_cookies=cookies, session=test_session)
    
    mock_prov.create_comment(post_url_or_id=TARGET_URL, text=COMMENT_TEXT)

    has_payload_token_v2 = bool(captured_payload.get("token_v2"))
    has_payload_csrf = bool(captured_payload.get("csrf_token"))
    has_payload_session = bool(captured_payload.get("reddit_session"))
    has_payload_loid = bool(captured_payload.get("loid"))
    has_payload_post_url = bool(captured_payload.get("post_url"))

    print(f"       Payload post_url    : {captured_payload.get('post_url')}")
    print(f"       Payload session     : {'INCLUDED' if has_payload_session else 'MISSING'}")
    print(f"       Payload loid        : {'INCLUDED' if has_payload_loid else 'MISSING'}")
    print(f"       Payload token_v2    : {'INCLUDED' if has_payload_token_v2 else 'MISSING'}")
    print(f"       Payload csrf_token  : {'INCLUDED' if has_payload_csrf else 'MISSING'}")

    if not (has_payload_token_v2 and has_payload_csrf and has_payload_session and has_payload_loid):
        print("\n[PREFLIGHT FAILED] Write payload is missing required tokens. Aborting write.")
        return {"preflight_passed": False, "reason": "PAYLOAD_INCOMPLETE"}

    print("       -> Preflight Check 4 PASS: Write payload includes token_v2, csrf_token, reddit_session, loid.")

    # -------------------------------------------------------------------------
    # 5. Verify the existing approval gate remains required
    # -------------------------------------------------------------------------
    print("\n[5/5] Verifying approval gate enforcement...")
    unapproved_action = {
        "action_id": "act_gate_test",
        "execution_id": "exec_gate_test",
        "worker": "community",
        "platform": "reddit",
        "provider": "redditapis",
        "action_type": "reply_to_post",
        "target": {"url": TARGET_URL, "thread_id": TARGET_THREAD_ID},
        "content": {"body": COMMENT_TEXT},
        "approval": {"status": "PENDING_APPROVAL", "required": True},
    }
    gate_receipt = execute_reddit_action(action=unapproved_action, user_id=user_id, db=db, provider="redditapis")
    if gate_receipt.get("status") != ExecutionStatus.BLOCKED or gate_receipt.get("reason") != "APPROVAL_REQUIRED":
        print(f"       [FAIL] Approval gate did not block unapproved action! Status: {gate_receipt.get('status')}")
        return {"preflight_passed": False, "reason": "APPROVAL_GATE_BREACHED"}

    print(f"       Unapproved action status : {gate_receipt.get('status')} (Reason: {gate_receipt.get('reason')})")
    print("       -> Preflight Check 5 PASS: Approval gate strictly blocks execution when status != APPROVED.")

    # =========================================================================
    # ALL PREFLIGHT CHECKS PASSED -> Controlled Real Write (Exactly ONE Comment)
    # =========================================================================
    print("\n" + "=" * 75)
    print("  ALL PREFLIGHT CHECKS PASSED — EXECUTING CONTROLLED REAL WRITE (1 COMMENT)")
    print("=" * 75)

    action_id = f"act_reddit_live_{uuid.uuid4().hex[:8]}"
    execution_id = f"exec_reddit_live_{uuid.uuid4().hex[:8]}"

    live_action = {
        "action_id": action_id,
        "execution_id": execution_id,
        "worker": "community",
        "platform": "reddit",
        "provider": "redditapis",
        "action_type": "reply_to_post",
        "target": {
            "url": TARGET_URL,
            "subreddit": TARGET_SUBREDDIT,
            "thread_id": TARGET_THREAD_ID,
            "post_id": TARGET_THREAD_ID,
        },
        "content": {
            "body": COMMENT_TEXT,
        },
        "approval": {
            "status": "APPROVED",
            "required": True,
        },
    }

    print(f"\nDispatching single live Reddit comment via execute_reddit_action...")
    print(f"Action ID   : {action_id}")
    print(f"Execution ID: {execution_id}")
    print(f"Target URL  : {TARGET_URL}")

    receipt = execute_reddit_action(
        action=live_action,
        user_id=user_id,
        db=db,
        provider="redditapis",
    )

    status = receipt.get("status")
    reason = receipt.get("reason")
    error = receipt.get("error")
    verified = receipt.get("verified", False)
    ext_id = receipt.get("external_id")
    permalink = receipt.get("permalink")

    print("\n" + "-" * 75)
    print("  LIVE EXECUTION OUTCOME:")
    print("-" * 75)
    print(f"  Status          : {status}")
    print(f"  Reason          : {reason}")
    print(f"  Verified        : {verified}")
    print(f"  External ID     : {ext_id}")
    print(f"  Permalink       : {permalink}")
    print(f"  Error           : {error}")

    # -------------------------------------------------------------------------
    # 10. Persist check in connector_actions
    # -------------------------------------------------------------------------
    print("\nVerifying persistence to connector_actions in SQLite...")
    saved_action = db.query(ConnectorAction).filter(ConnectorAction.id == action_id).first()
    if saved_action:
        print(f"  [OK] Saved in SQLite ConnectorAction: ID={saved_action.id}, Status={saved_action.status}")
    else:
        print(f"  [WARN] Action ID {action_id} not found in ConnectorAction table.")

    db.close()

    result_summary = {
        "preflight_passed": True,
        "action_id": action_id,
        "execution_id": execution_id,
        "target": TARGET_URL,
        "status": status,
        "verified": verified,
        "external_id": ext_id,
        "permalink": permalink,
        "error": error,
        "reason": reason,
        "persisted_in_db": bool(saved_action),
    }

    print("\n" + "=" * 75)
    print("  RESULT SUMMARY:")
    print(json.dumps(result_summary, indent=2))
    print("=" * 75 + "\n")

    return result_summary


if __name__ == "__main__":
    run_preflight_and_execution()
