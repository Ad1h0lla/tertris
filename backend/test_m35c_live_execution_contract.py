"""
Tetris — M3.5-C Test Suite
===========================

Live Execution Contract & Failure Honesty Verification:
1. Approval Required (gate must hold before dispatch)
2. User-Scoped DB Required (db=None strictly forbidden)
3. Successful Worker Result with Verified Receipt
4. Successful Worker Result without Verification (missing receipt cannot be SUCCESS)
5. Provider Failure (auth failure, quota exceeded, rate limit, network error)
6. Receipt Preservation (external_id, external_url, message_id)
7. Persistence (fresh DB session recovers exact receipt and state)
8. Idempotent Second Execution (successful actions skipped, no second dispatch)
9. Secret Redaction (credentials absent from state, events, and responses)
10. Campaign Aggregation (deterministic terminal status)
"""

import copy
import json
import os
import sys
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_m35c.db")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_long!!")

from database.models import (
    init_db,
    SessionLocal,
    DistributionCampaign,
    StoredCredential,
    PhaseResult,
)
from database.operations import (
    create_execution,
    save_phase_result,
    store_credential,
)
from execution.distribution_models import (
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
    create_distribution_action,
)
from integrations.credential_manager import (
    encrypt_credential,
    connect_app,
)
from orchestration.distribution_orchestrator import (
    CampaignStatus,
    ActionStatus,
    ObservabilityEvent,
    create_campaign,
    check_connector_readiness,
    approve_actions,
    execute_campaign,
    retry_failed_actions,
    get_canonical_campaign,
)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ===========================================================================
# 1. Approval Required
# ===========================================================================

class TestApprovalRequired:
    def test_unapproved_action_cannot_execute(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)

        mock_router = MagicMock()
        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)

        # Worker was never dispatched
        assert mock_router.call_count == 0
        assert res["actions"][0]["status"] == ExecutionStatus.BLOCKED
        assert res["actions"][0]["reason"] == "APPROVAL_REQUIRED"
        assert res["status"] == CampaignStatus.BLOCKED


# ===========================================================================
# 2. User-Scoped DB Required
# ===========================================================================

class TestUserScopedDBRequired:
    def test_db_none_raises_value_error(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]

        with pytest.raises(ValueError, match="User-scoped DB session is mandatory"):
            execute_campaign(db=None, campaign_id=cid, user_id=user_id)


# ===========================================================================
# 3. Successful Worker Result with Receipt
# ===========================================================================

class TestSuccessfulWorkerWithReceipt:
    def test_real_receipt_recorded_as_success(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        action = create_distribution_action("community", "reddit", "create_post", {"community": "startups"}, {"title": "Tetris Launch", "body": "Live announcement"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        authentic_receipt = {
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "t3_live_12345",
            "external_url": "https://www.reddit.com/r/startups/comments/live_12345/tetris_launch/",
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda **kw: authentic_receipt)
        act = res["actions"][0]

        assert act["status"] == ExecutionStatus.SUCCESS
        assert act["receipt"]["verified"] is True
        assert act["receipt"]["verification_status"] == VerificationStatus.PASS
        assert act["receipt"]["external_id"] == "t3_live_12345"
        assert act["receipt"]["external_url"] == "https://www.reddit.com/r/startups/comments/live_12345/tetris_launch/"
        assert res["status"] == CampaignStatus.COMPLETED


# ===========================================================================
# 4. Successful Worker Result without Verification
# ===========================================================================

class TestMissingVerificationFailure:
    def test_missing_receipt_coerced_to_failure(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        action = create_distribution_action("social", "twitter", "create_post", {}, {"body": "Post without receipt"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        unverified_result = {
            "status": ExecutionStatus.SUCCESS,
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "external_id": None,
            "external_url": None,
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda **kw: unverified_result)
        act = res["actions"][0]

        assert act["status"] == ExecutionStatus.FAILED
        assert act["receipt"]["verified"] is False
        assert res["status"] == CampaignStatus.FAILED


# ===========================================================================
# 5. Provider Failure
# ===========================================================================

class TestProviderFailure:
    def test_sendgrid_quota_exceeded_honestly_fails(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "sendgrid", json.dumps({"api_key": "SG.test_key"}), "api_key", "SendGrid")
        action = create_distribution_action("outreach", "email", "send_email", {"email": "dev@example.com"}, {"subject": "Test", "body": "Body"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        provider_401_error = {
            "status": ExecutionStatus.FAILED,
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "reason": "AUTH_FAILED",
            "error": "SendGrid authentication/permission error (401): Maximum credits exceeded",
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda **kw: provider_401_error)
        act = res["actions"][0]

        assert act["status"] == ExecutionStatus.FAILED
        assert act["reason"] == "AUTH_FAILED"
        assert "Maximum credits exceeded" in act["error"]
        assert res["status"] == CampaignStatus.FAILED


# ===========================================================================
# 6. Receipt Preservation
# ===========================================================================

class TestReceiptPreservation:
    def test_receipt_fields_preserved_completely(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        action = create_distribution_action("social", "twitter", "create_post", {}, {"body": "Preserve receipts"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        tweet_receipt = {
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "1840123456789012345",
            "external_url": "https://x.com/tetris_app/status/1840123456789012345",
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda **kw: tweet_receipt)
        receipt = res["actions"][0]["receipt"]

        assert receipt["external_id"] == "1840123456789012345"
        assert receipt["external_url"] == "https://x.com/tetris_app/status/1840123456789012345"
        assert receipt["verified"] is True
        assert receipt["verification_status"] == VerificationStatus.PASS


# ===========================================================================
# 7. Persistence Across DB Sessions
# ===========================================================================

class TestPersistenceAcrossSessions:
    def test_fresh_session_recovers_receipt_and_state(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        action = create_distribution_action("community", "reddit", "create_post", {"community": "startups"}, {"title": "T", "body": "B"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        receipt = {
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "t3_persist_check",
            "external_url": "https://reddit.com/r/startups/comments/persist_check",
        }
        execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda **kw: receipt)

        # Close session and open a fresh session
        db.close()
        fresh_db = SessionLocal()
        try:
            reloaded = get_canonical_campaign(fresh_db, cid)
            assert reloaded["status"] == CampaignStatus.COMPLETED
            act = reloaded["actions"][0]
            assert act["status"] == ExecutionStatus.SUCCESS
            assert act["receipt"]["external_id"] == "t3_persist_check"
            assert act["receipt"]["external_url"] == "https://reddit.com/r/startups/comments/persist_check"
            assert act["receipt"]["verified"] is True
        finally:
            fresh_db.close()


# ===========================================================================
# 8. Idempotent Second Execution
# ===========================================================================

class TestIdempotentSecondExecution:
    def test_second_execution_skips_successful_action(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        action = create_distribution_action("community", "reddit", "create_post", {"community": "startups"}, {"title": "T", "body": "B"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        mock_router = MagicMock(return_value={
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "t3_idempotent_1",
            "external_url": "https://reddit.com/comments/idempotent_1",
        })

        # Run 1: executed once
        res1 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 1
        assert res1["status"] == CampaignStatus.COMPLETED

        # Run 2: already successful, MUST NOT call router again!
        res2 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 1  # Still 1, not 2
        assert res2["status"] == CampaignStatus.COMPLETED
        assert res2["actions"][0]["receipt"]["external_id"] == "t3_idempotent_1"


# ===========================================================================
# 9. Secret Redaction
# ===========================================================================

class TestSecretRedaction:
    def test_secrets_never_leak_in_state_or_events(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        # Add target or error with sensitive token
        action["target"]["bearer_token"] = "SECRET_BEARER_TOKEN_xyz"

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]

        canonical = get_canonical_campaign(db, cid)
        canonical_str = json.dumps(canonical)

        assert "SECRET_BEARER_TOKEN_xyz" not in canonical_str
        assert "[REDACTED]" in canonical_str


# ===========================================================================
# 10. Campaign Aggregation
# ===========================================================================

class TestCampaignAggregationContracts:
    def test_aggregation_contract_states(self, db):
        exec_id = f"exec_m35c_{uuid.uuid4().hex[:8]}"
        user_id = f"user_m35c_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        act1 = create_distribution_action("community", "reddit", "create_post", {"community": "t1"}, {"title": "T1", "body": "B1"}, execution_id=exec_id)
        act2 = create_distribution_action("social", "twitter", "create_post", {}, {"body": "B2"}, execution_id=exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[act1, act2])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        # 1 succeeds, 1 fails -> PARTIAL
        def mixed_dispatch(action, user_id, db, **kwargs):
            if action.get("platform") == "reddit":
                return {"status": ExecutionStatus.SUCCESS, "verified": True, "verification_status": VerificationStatus.PASS, "external_id": "r1"}
            return {"status": ExecutionStatus.FAILED, "verified": False, "verification_status": VerificationStatus.FAIL, "error": "Fail"}

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mixed_dispatch)
        assert res["status"] == CampaignStatus.PARTIAL
        assert res["summary"]["success"] == 1
        assert res["summary"]["failed"] == 1
        assert res["summary"]["total"] == 2
