"""
Tetris — Milestone 3.4 Test Suite
==================================

Outreach Worker — Real Email Execution & Verification Tests.

Tests:
CREDENTIALS
1.  missing SendGrid credentials -> BLOCKED (AUTH_REQUIRED)
2.  missing SMTP credentials -> BLOCKED (AUTH_REQUIRED)
3.  credentials sanitized (no raw keys/passwords in error strings)
4.  credentials absent from result receipt

APPROVAL
5.  pending approval -> BLOCKED (APPROVAL_REQUIRED)
6.  rejected approval -> BLOCKED (APPROVAL_REQUIRED)
7.  no provider call before approval

VALIDATION
8.  missing recipient -> FAILED (INVALID_RECIPIENT)
9.  invalid email format -> FAILED (INVALID_RECIPIENT)
10. missing subject -> FAILED (INVALID_CONTENT)
11. missing body -> FAILED (INVALID_CONTENT)

SENDGRID
12. mocked successful SendGrid response (202 Accepted)
13. actual provider message ID parsed from X-Message-Id header
14. provider acceptance persisted in DB
15. provider failure handled (401/403/500)
16. rate-limit handled (429 -> RATE_LIMITED)

SMTP
17. mocked successful SMTP response (250 OK)
18. SMTP response persisted in DB
19. SMTP failure handled (auth error / refused)
20. ambiguous timeout handled safely (no duplicate retry)

VERIFICATION
21. delivery not falsely reported (delivery_status is UNKNOWN, not DELIVERED)
22. NOT_SUPPORTED / UNKNOWN delivery status handled
23. provider acceptance vs delivery distinguished

PERSISTENCE
24. ConnectorAction persisted in SQLite
25. PhaseResult distribution_plan updated
26. status endpoint exposes receipt

ROUTING
27. outreach/email routes correctly via execute_distribution_action
28. Reddit routing still works
29. X routing still works
30. LinkedIn routing still works

IDEMPOTENCY
31. already successful action does not send twice

SECURITY
32. credentials absent from DistributionAction
33. credentials absent from logs/errors
34. credentials absent from API result
"""

import os
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch

from execution.distribution_models import (
    create_distribution_action,
    validate_distribution_action,
    ActionWorker,
    ActionPlatform,
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)
from execution.email_executor import (
    execute_email_action,
    resolve_sendgrid_credentials,
    resolve_smtp_credentials,
    validate_email_address,
    validate_email_payload,
    sanitize_email_secrets,
    check_email_idempotency,
    persist_email_receipt,
    SendGridEmailProvider,
    SMTPEmailProvider,
    EmailProvider,
)
from execution.execution_router import execute_distribution_action, route_execution
from database.models import SessionLocal, init_db, ConnectorAction, PhaseResult, Execution
from database.operations import save_connector_action, save_phase_result


# ===========================================================================
# HELPERS & FIXTURES
# ===========================================================================

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()


def _make_email_action(
    action_type="send_email",
    approved=True,
    to_email="founder@targetco.com",
    subject="Tetris Integration Discussion",
    body="Hi, we noticed you are scaling your platform and wanted to share how Tetris automates workflows.",
    action_id=None,
    execution_id=None,
):
    """Helper: creates a minimal valid Outreach DistributionAction."""
    action = create_distribution_action(
        worker="outreach",
        platform="email",
        action_type=action_type,
        target={"email": to_email},
        content={"subject": subject, "body": body},
        action_id=action_id or str(uuid.uuid4()),
        execution_id=execution_id or str(uuid.uuid4()),
    )
    if approved:
        action["approval"]["status"] = ApprovalStatus.APPROVED
    return action


class MockHTTPResponse:
    def __init__(self, status_code=202, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


# ===========================================================================
# TEST SUITE: 34 TESTS
# ===========================================================================

# --- CREDENTIALS (1-4) ---

def test_1_missing_sendgrid_credentials_blocked():
    """1. Missing SendGrid credentials returns BLOCKED (AUTH_REQUIRED)."""
    with patch.dict(os.environ, {}, clear=True):
        creds = resolve_sendgrid_credentials(user_id="user_unconfigured")
        assert creds["api_key"] is None

        action = _make_email_action(approved=True)
        res = execute_email_action(action=action, user_id="user_unconfigured")
        assert res["status"] == ExecutionStatus.BLOCKED
        assert res["reason"] == "AUTH_REQUIRED"


def test_2_missing_smtp_credentials_blocked():
    """2. Missing SMTP credentials returns BLOCKED (AUTH_REQUIRED)."""
    with patch.dict(os.environ, {}, clear=True):
        creds = resolve_smtp_credentials(user_id="user_unconfigured")
        assert creds["host"] is None or creds["username"] is None

        action = _make_email_action(approved=True)
        res = execute_email_action(action=action, user_id="user_unconfigured")
        assert res["status"] == ExecutionStatus.BLOCKED
        assert res["reason"] == "AUTH_REQUIRED"


def test_3_credentials_sanitized():
    """3. Secrets (API keys, passwords) are sanitized from error strings."""
    secret_key = "SG.super_secret_sendgrid_key_12345"
    secret_pass = "super_secret_smtp_password"
    raw_error = f"Error connecting with key {secret_key} and pass {secret_pass}"
    sanitized = sanitize_email_secrets(raw_error, [secret_key, secret_pass])

    assert secret_key not in sanitized
    assert secret_pass not in sanitized
    assert "[REDACTED]" in sanitized


def test_4_credentials_absent_from_result():
    """4. No raw credentials leak into execution result or receipt."""
    provider = SendGridEmailProvider(api_key="SG.fake_key_abcdef123456")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "msg_sg_12345"})

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    res_str = json.dumps(res)
    assert "SG.fake_key" not in res_str
    assert "api_key" not in res_str
    assert "password" not in res_str


# --- APPROVAL GATE (5-7) ---

def test_5_pending_approval_blocked():
    """5. Action in PENDING_APPROVAL status is BLOCKED before execution."""
    action = _make_email_action(approved=False)
    action["approval"]["status"] = ApprovalStatus.PENDING_APPROVAL

    mock_provider = MagicMock()
    res = execute_email_action(action=action, provider_override=mock_provider)

    assert res["status"] == ExecutionStatus.BLOCKED
    assert res["reason"] == "APPROVAL_REQUIRED"
    mock_provider.send.assert_not_called()


def test_6_rejected_approval_blocked():
    """6. Action in REJECTED status is BLOCKED before execution."""
    action = _make_email_action(approved=False)
    action["approval"]["status"] = ApprovalStatus.REJECTED

    mock_provider = MagicMock()
    res = execute_email_action(action=action, provider_override=mock_provider)

    assert res["status"] == ExecutionStatus.BLOCKED
    assert res["reason"] == "APPROVAL_REQUIRED"
    mock_provider.send.assert_not_called()


def test_7_no_provider_call_before_approval():
    """7. Zero provider calls happen when approval is missing or not APPROVED."""
    action = _make_email_action(approved=False)
    mock_provider = MagicMock()

    execute_email_action(action=action, provider_override=mock_provider)
    assert mock_provider.send.call_count == 0


# --- VALIDATION (8-11) ---

def test_8_missing_recipient_failed():
    """8. Missing recipient fails with INVALID_RECIPIENT."""
    action = _make_email_action(to_email="", approved=True)
    action["target"] = {}

    res = execute_email_action(action=action, provider_override=MagicMock())
    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "INVALID_RECIPIENT"


def test_9_invalid_email_failed():
    """9. Malformed recipient fails with INVALID_RECIPIENT."""
    action = _make_email_action(to_email="not-an-email", approved=True)

    res = execute_email_action(action=action, provider_override=MagicMock())
    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "INVALID_RECIPIENT"
    assert "Invalid email format" in res["error"]


def test_10_missing_subject_failed():
    """10. Empty subject fails with INVALID_CONTENT."""
    action = _make_email_action(subject="", approved=True)

    res = execute_email_action(action=action, provider_override=MagicMock())
    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "INVALID_CONTENT"


def test_11_missing_body_failed():
    """11. Empty body fails with INVALID_CONTENT."""
    action = _make_email_action(body="", approved=True)

    res = execute_email_action(action=action, provider_override=MagicMock())
    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "INVALID_CONTENT"


# --- SENDGRID (12-16) ---

def test_12_mocked_successful_sendgrid_response():
    """12. SendGrid provider returns HTTP 202 -> SUCCESS and ACCEPTED."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_msg_998877"})

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["status"] == ExecutionStatus.SUCCESS
    assert res["verified"] is True
    assert res["verification_status"] == VerificationStatus.PASS
    assert res["receipt"]["provider"] == "sendgrid"
    assert res["receipt"]["provider_status"] == "ACCEPTED"


def test_13_actual_provider_message_id_parsed():
    """13. Actual message ID from SendGrid X-Message-Id header is captured without fabrication."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    expected_id = "real_sendgrid_id_abcdef123"
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": expected_id})

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["external_id"] == expected_id
    assert res["receipt"]["external_id"] == expected_id


def test_14_provider_acceptance_persisted():
    """14. Provider acceptance is persisted to SQLite ConnectorAction."""
    db = SessionLocal()
    try:
        action_id = str(uuid.uuid4())
        exec_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id, execution_id=exec_id)

        provider = SendGridEmailProvider(api_key="SG.test_key")
        mock_http = MagicMock()
        mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_msg_persistence_test"})

        res = execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)
        assert res["status"] == ExecutionStatus.SUCCESS

        ca = db.query(ConnectorAction).filter(ConnectorAction.id == action_id).first()
        assert ca is not None
        assert ca.connector_id == "email"
        assert ca.action == "send_email"
        assert ca.status == ExecutionStatus.SUCCESS
        assert ca.result["receipt"]["provider_status"] == "ACCEPTED"
    finally:
        db.close()


def test_15_sendgrid_failure_handled():
    """15. SendGrid rejection (401/403/500) is handled safely."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(401, text="The provided authorization grant is invalid")

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["status"] == ExecutionStatus.BLOCKED
    assert res["reason"] == "AUTH_FAILED"
    assert res["verified"] is False
    assert res["verification_status"] == VerificationStatus.FAIL


def test_16_sendgrid_rate_limit_handled():
    """16. SendGrid 429 response is mapped to RATE_LIMITED."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(429, text="Rate limit exceeded")

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "RATE_LIMITED"
    assert res["verified"] is False


# --- SMTP (17-20) ---

def test_17_mocked_successful_smtp_response():
    """17. Mocked successful SMTP transmission returns ACCEPTED status."""
    provider = SMTPEmailProvider(host="smtp.example.com", port=587, username="user@example.com", password="pwd")
    mock_smtp = MagicMock()
    mock_smtp.send_message.return_value = {}  # Empty dict means no refused recipients
    mock_smtp.last_response = (250, b"2.0.0 OK message queued")

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, smtp_client=mock_smtp)

    assert res["status"] == ExecutionStatus.SUCCESS
    assert res["receipt"]["provider"] == "smtp"
    assert res["receipt"]["provider_status"] == "ACCEPTED"
    assert "250" in res["receipt"]["smtp_response"]
    assert res["verified"] is True
    assert res["verification_status"] == VerificationStatus.PASS


def test_18_smtp_response_persisted():
    """18. SMTP acceptance and response metadata are persisted to SQLite."""
    db = SessionLocal()
    try:
        action_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id)

        provider = SMTPEmailProvider(host="smtp.example.com", port=587)
        mock_smtp = MagicMock()
        mock_smtp.send_message.return_value = {}
        mock_smtp.last_response = (250, b"2.0.0 OK queued as 12345")

        res = execute_email_action(action=action, db=db, provider_override=provider, smtp_client=mock_smtp)
        assert res["status"] == ExecutionStatus.SUCCESS

        ca = db.query(ConnectorAction).filter(ConnectorAction.id == action_id).first()
        assert ca is not None
        assert ca.result["receipt"]["provider"] == "smtp"
        assert "250" in ca.result["receipt"]["smtp_response"]
    finally:
        db.close()


def test_19_smtp_failure_handled():
    """19. SMTP recipient refusal is handled as REJECTED/FAILED."""
    provider = SMTPEmailProvider(host="smtp.example.com", port=587)
    mock_smtp = MagicMock()
    mock_smtp.send_message.return_value = {"founder@targetco.com": (550, b"5.1.1 User unknown")}

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, smtp_client=mock_smtp)

    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "RECIPIENT_REFUSED"
    assert res["verified"] is False


def test_20_ambiguous_timeout_handled_safely():
    """20. Ambiguous network timeout returns TIMEOUT without blind retry."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    import requests
    mock_http.post.side_effect = requests.Timeout("Connection timed out after 15s")

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["status"] == ExecutionStatus.FAILED
    assert res["reason"] == "TIMEOUT"
    assert "not retrying blindly" in res["error"]


# --- VERIFICATION (21-23) ---

def test_21_delivery_not_falsely_reported():
    """21. Delivery status is UNKNOWN (never falsely claimed as DELIVERED)."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_123"})

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    assert res["receipt"]["delivery_status"] == "UNKNOWN"
    assert res["receipt"]["delivery_status"] != "DELIVERED"


def test_22_not_supported_or_unknown_handled():
    """22. Failure cases leave delivery_status as NOT_TESTED / UNKNOWN."""
    action = _make_email_action(approved=False)
    res = execute_email_action(action=action)

    assert res["receipt"]["delivery_status"] == "NOT_TESTED"


def test_23_provider_acceptance_vs_delivery_distinguished():
    """23. Distinguishes provider acceptance (ACCEPTED) from inbox receipt."""
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_verif_99"})

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, http_client=mock_http)

    # Acceptance is PASS / ACCEPTED
    assert res["receipt"]["provider_status"] == "ACCEPTED"
    assert res["receipt"]["verification_status"] == VerificationStatus.PASS
    # Delivery is UNKNOWN
    assert res["receipt"]["delivery_status"] == "UNKNOWN"


# --- PERSISTENCE (24-26) ---

def test_24_connector_action_persisted():
    """24. Execution persists full ConnectorAction model in database."""
    db = SessionLocal()
    try:
        action_id = str(uuid.uuid4())
        exec_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id, execution_id=exec_id)

        provider = SendGridEmailProvider(api_key="SG.test_key")
        mock_http = MagicMock()
        mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_pers_1"})

        execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)

        ca = db.query(ConnectorAction).filter(ConnectorAction.id == action_id).first()
        assert ca is not None
        assert ca.execution_id == exec_id
        assert ca.connector_id == "email"
        assert ca.action == "send_email"
    finally:
        db.close()


def test_25_distribution_plan_updated():
    """25. PhaseResult.distribution_plan is updated with action execution receipt."""
    db = SessionLocal()
    try:
        exec_id = str(uuid.uuid4())
        action_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id, execution_id=exec_id)

        # Pre-seed PhaseResult with distribution_plan
        plan = {"actions": [action]}
        save_phase_result(
            db=db,
            execution_id=exec_id,
            phase=3,
            phase_name="Distribution",
            outcome_type="distribution_plan",
            outcome="Proposed distribution actions",
            score=90.0,
            trace={},
            status="completed",
            distribution_plan=plan,
        )

        provider = SendGridEmailProvider(api_key="SG.test_key")
        mock_http = MagicMock()
        mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_plan_update"})

        res = execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)
        assert res["status"] == ExecutionStatus.SUCCESS

        pr = db.query(PhaseResult).filter(PhaseResult.execution_id == exec_id, PhaseResult.phase_number == 3).first()
        assert pr is not None
        stored_action = pr.distribution_plan["actions"][0]
        assert stored_action["execution"]["status"] == ExecutionStatus.SUCCESS
        assert stored_action["receipt"]["provider_status"] == "ACCEPTED"
    finally:
        db.close()


def test_26_status_endpoint_exposes_receipt():
    """26. Status endpoint structure exposes execution receipt and connector actions."""
    db = SessionLocal()
    try:
        action_id = str(uuid.uuid4())
        exec_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id, execution_id=exec_id)

        provider = SendGridEmailProvider(api_key="SG.test_key")
        mock_http = MagicMock()
        mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_endpoint_test"})

        execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)

        from database.operations import get_connector_actions
        actions = get_connector_actions(db, exec_id)
        assert len(actions) >= 1
        assert actions[0].result["receipt"]["provider_status"] == "ACCEPTED"
    finally:
        db.close()


# --- ROUTING (27-30) ---

def test_27_outreach_email_routes_correctly():
    """27. execute_distribution_action routes worker='outreach', platform='email' to email executor."""
    action = _make_email_action(approved=True)
    provider = SendGridEmailProvider(api_key="SG.test_key")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_route_test"})

    res = execute_distribution_action(
        action=action,
        provider_override=provider,
        http_client=mock_http,
    )
    assert res["status"] == ExecutionStatus.SUCCESS
    assert res["worker"] == ActionWorker.OUTREACH
    assert res["platform"] == ActionPlatform.EMAIL


def test_28_reddit_routing_intact():
    """28. Reddit community routing remains fully functional."""
    reddit_action = create_distribution_action(
        worker="community",
        platform="reddit",
        action_type="create_post",
        target={"community": "startups"},
        content={"title": "Test Title", "body": "Test Body"},
    )
    reddit_action["approval"]["status"] = ApprovalStatus.APPROVED

    mock_reddit_client = MagicMock()
    mock_submission = MagicMock()
    mock_submission.id = "t3_test123"
    mock_submission.permalink = "/r/startups/comments/test123/title/"
    mock_reddit_client.subreddit.return_value.submit.return_value = mock_submission
    mock_reddit_client.submission.return_value = mock_submission

    res = execute_distribution_action(action=reddit_action, reddit_client_override=mock_reddit_client)
    assert res["status"] == ExecutionStatus.SUCCESS
    assert res["platform"] == "reddit"


def test_29_x_routing_intact():
    """29. X social routing remains fully functional."""
    x_action = create_distribution_action(
        worker="social",
        platform="twitter",
        action_type="create_post",
        target={},
        content={"body": "Hello from Tetris regression test!"},
    )
    x_action["approval"]["status"] = ApprovalStatus.APPROVED

    mock_tweepy = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = {"id": "1234567890", "text": "Hello from Tetris regression test!"}
    mock_tweepy.create_tweet.return_value = mock_resp

    verify_data = MagicMock()
    verify_data.id = "1234567890"
    verify_data.text = "Hello from Tetris regression test!"
    verify_resp = MagicMock()
    verify_resp.data = verify_data
    mock_tweepy.get_tweet.return_value = verify_resp

    res = execute_distribution_action(action=x_action, tweepy_client_override=mock_tweepy)
    assert res["status"] == ExecutionStatus.SUCCESS
    assert res["platform"] == "twitter"


def test_30_linkedin_routing_intact():
    """30. LinkedIn social routing remains fully functional."""
    li_action = create_distribution_action(
        worker="social",
        platform="linkedin",
        action_type="create_post",
        target={},
        content={"body": "Hello from LinkedIn regression test!"},
    )
    li_action["approval"]["status"] = ApprovalStatus.APPROVED

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.headers = {"x-restli-id": "urn:li:share:1234567"}
    mock_resp.json.return_value = {"id": "urn:li:share:1234567"}
    mock_http.post.return_value = mock_resp

    with patch("execution.linkedin_executor.resolve_linkedin_credentials") as mock_creds:
        mock_creds.return_value = {"access_token": "mock_tok", "person_id": "mock_pid"}
        res = execute_distribution_action(action=li_action, http_client_override=mock_http)
        assert res["status"] == ExecutionStatus.SUCCESS
        assert res["platform"] == "linkedin"


# --- IDEMPOTENCY & DUPLICATE PROTECTION (31) ---

def test_31_idempotency_does_not_send_twice():
    """31. An already successfully executed action_id is not dispatched twice."""
    db = SessionLocal()
    try:
        action_id = str(uuid.uuid4())
        action = _make_email_action(approved=True, action_id=action_id)

        provider = SendGridEmailProvider(api_key="SG.test_key")
        mock_http = MagicMock()
        mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_idemp_1"})

        # First send
        res1 = execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)
        assert res1["status"] == ExecutionStatus.SUCCESS
        assert mock_http.post.call_count == 1

        # Second send attempt with same action_id
        res2 = execute_email_action(action=action, db=db, provider_override=provider, http_client=mock_http)
        assert res2["status"] == ExecutionStatus.SUCCESS
        # HTTP client should NOT have been called a second time
        assert mock_http.post.call_count == 1
    finally:
        db.close()


# --- SECURITY (32-34) ---

def test_32_credentials_absent_from_distribution_action():
    """32. Raw credentials must not exist in DistributionAction payload."""
    action = _make_email_action(approved=True)
    assert validate_distribution_action(action) is True

    # Inject forbidden key
    action["api_key"] = "SG.secret"
    assert validate_distribution_action(action) is False


def test_33_credentials_absent_from_logs_and_errors():
    """33. Exception logs and error fields have secrets redacted."""
    provider = SMTPEmailProvider(host="smtp.example.com", username="admin", password="super_secret_smtp_password")
    mock_smtp = MagicMock()
    mock_smtp.send_message.side_effect = Exception("Auth failed with pass super_secret_smtp_password")

    action = _make_email_action(approved=True)
    res = execute_email_action(action=action, provider_override=provider, smtp_client=mock_smtp)

    assert "super_secret_smtp_password" not in str(res["error"])
    assert "[REDACTED]" in str(res["error"])


def test_34_credentials_absent_from_api_result():
    """34. DistributionAction / route_execution API responses contain zero secrets."""
    payload = {
        "to_email": "prospect@example.com",
        "subject": "Intro to Tetris",
        "body": "Hello prospect!",
    }
    provider = SendGridEmailProvider(api_key="SG.secret_api_key_xyz")
    mock_http = MagicMock()
    mock_http.post.return_value = MockHTTPResponse(202, headers={"X-Message-Id": "sg_api_test"})

    with patch("execution.email_executor.resolve_sendgrid_credentials") as mock_res:
        mock_res.return_value = {"api_key": "SG.secret_api_key_xyz", "from_email": "noreply@executa.ai", "from_name": "Tetris"}
        res = route_execution("send_email", payload, user_id="user_001")

        res_str = json.dumps(res)
        assert "SG.secret_api_key_xyz" not in res_str
        assert "password" not in res_str
