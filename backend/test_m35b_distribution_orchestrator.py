"""
Tetris — M3.5-B Test Suite
===========================

Distribution Orchestrator:
- Campaign Model & Lifecycle (PLANNED, AWAITING_CONNECTION, AWAITING_APPROVAL, READY, RUNNING, PARTIAL, COMPLETED, BLOCKED, FAILED)
- Persistence & Restart Recovery
- Connector Readiness Evaluation & User Isolation
- Strict Approval Lifecycle (PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY)
- Action Dispatch & Sequential Execution
- Mandatory User-Scoped DB Session Enforcement (db=None is strictly forbidden)
- Idempotency (SUCCESS not duplicated, RUNNING not duplicated, FAILED requires explicit retry)
- Receipts Preservation & Integrity (never fabricate receipts, missing receipt cannot be SUCCESS)
- Campaign Status Aggregation
- Security: No credential leakage in responses or logs
- FastAPI Route Integration & Extended Status Endpoint
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

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_m35b.db")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_long!!")

from database.models import (
    init_db,
    SessionLocal,
    DistributionCampaign,
    StoredCredential,
    PhaseResult,
    Execution,
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


def _make_sample_plan(execution_id="exec_test_001"):
    return {
        "recommended_workers": ["community", "social"],
        "actions": [
            create_distribution_action(
                worker="community",
                platform="reddit",
                action_type="create_post",
                target={"community": "startups"},
                content={"title": "Launching Tetris", "body": "Check out our tool."},
                execution_id=execution_id,
            ),
            create_distribution_action(
                worker="social",
                platform="twitter",
                action_type="create_post",
                target={},
                content={"body": "We are launching today! #buildinpublic"},
                execution_id=execution_id,
            ),
        ],
    }


# ===========================================================================
# 1. Campaign Creation, Persistence & Reload
# ===========================================================================

class TestCampaignCreationAndPersistence:
    def test_campaign_creation_initial_state(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        plan = _make_sample_plan(exec_id)

        campaign = create_campaign(
            db=db,
            execution_id=exec_id,
            user_id="user_test_01",
            distribution_plan=plan,
        )

        assert campaign["campaign_id"].startswith("cmp_")
        assert campaign["execution_id"] == exec_id
        assert campaign["user_id"] == "user_test_01"
        assert campaign["status"] == CampaignStatus.PLANNED
        assert len(campaign["actions"]) == 2
        assert campaign["summary"]["total"] == 2
        assert campaign["summary"]["pending"] == 2
        assert campaign["summary"]["success"] == 0

        # Verify observability event
        events = campaign["events"]
        assert len(events) >= 1
        assert events[0]["event"] == ObservabilityEvent.CAMPAIGN_CREATED
        assert events[0]["status"] == CampaignStatus.PLANNED

    def test_campaign_persistence_in_database(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        plan = _make_sample_plan(exec_id)

        created = create_campaign(
            db=db,
            execution_id=exec_id,
            user_id="user_test_02",
            distribution_plan=plan,
        )
        cid = created["campaign_id"]

        row = db.query(DistributionCampaign).filter(DistributionCampaign.id == cid).first()
        assert row is not None
        assert row.execution_id == exec_id
        assert row.user_id == "user_test_02"
        assert row.status == CampaignStatus.PLANNED
        assert len(row.actions) == 2

    def test_campaign_reload_after_restart(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        plan = _make_sample_plan(exec_id)

        created = create_campaign(
            db=db,
            execution_id=exec_id,
            user_id="user_test_03",
            distribution_plan=plan,
        )
        cid = created["campaign_id"]

        # Close session and open a fresh session to simulate restart
        db.close()
        fresh_db = SessionLocal()
        try:
            reloaded = get_canonical_campaign(fresh_db, cid)
            assert reloaded["campaign_id"] == cid
            assert reloaded["execution_id"] == exec_id
            assert reloaded["status"] == CampaignStatus.PLANNED
            assert len(reloaded["actions"]) == 2
            assert reloaded["summary"]["total"] == 2
        finally:
            fresh_db.close()

    def test_campaign_auto_discovers_phase_result(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        plan = _make_sample_plan(exec_id)

        # Pre-seed PhaseResult
        save_phase_result(
            db=db,
            execution_id=exec_id,
            phase=3,
            outcome_type="distribution_plan",
            outcome="Plan ready",
            score=1.0,
            trace=[],
            distribution_plan=plan,
        )

        # Call create_campaign without passing distribution_plan or actions
        campaign = create_campaign(
            db=db,
            execution_id=exec_id,
            user_id="user_test_04",
        )
        assert len(campaign["actions"]) == 2
        assert campaign["actions"][0]["worker"] == "community"


# ===========================================================================
# 2. Connector Readiness Evaluation
# ===========================================================================

class TestConnectorReadiness:
    def test_missing_connector_sets_awaiting_connection(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        # User has NO credentials connected
        updated = check_connector_readiness(db, cid, user_id=user_id)

        assert updated["status"] == CampaignStatus.AWAITING_CONNECTION
        reqs = updated["connector_requirements"]
        assert len(reqs) == 2
        platforms = {r["platform"]: r["status"] for r in reqs}
        assert platforms["reddit"] == "NOT_CONNECTED"
        assert platforms["twitter"] == "NOT_CONNECTED"

        # Verify event logged
        events = updated["events"]
        assert any(e["event"] == ObservabilityEvent.AWAITING_CONNECTION for e in events)

    def test_all_connectors_ready_sets_awaiting_approval(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        # Connect reddit and twitter for this user
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c1", "client_secret": "s1", "username": "u1", "password": "p1"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k1", "api_secret": "s1", "access_token": "t1", "access_token_secret": "ts1"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        updated = check_connector_readiness(db, cid, user_id=user_id)

        # Connectors are ready, but actions still need approval
        assert updated["status"] == CampaignStatus.AWAITING_APPROVAL
        reqs = updated["connector_requirements"]
        platforms = {r["platform"]: r["status"] for r in reqs}
        assert platforms["reddit"] == "READY"
        assert platforms["twitter"] == "READY"

    def test_mixed_readiness(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        # Only Reddit is connected
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c1", "client_secret": "s1", "username": "u1", "password": "p1"}), "api_key", "Reddit")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        updated = check_connector_readiness(db, cid, user_id=user_id)

        assert updated["status"] == CampaignStatus.AWAITING_CONNECTION
        reqs = {r["platform"]: r["status"] for r in updated["connector_requirements"]}
        assert reqs["reddit"] == "READY"
        assert reqs["twitter"] == "NOT_CONNECTED"

    def test_cross_user_credential_isolation(self, db):
        """User A credentials must not be visible or usable by User B."""
        user_a = f"user_a_{uuid.uuid4().hex[:6]}"
        user_b = f"user_b_{uuid.uuid4().hex[:6]}"
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"

        # User A connects Reddit
        connect_app(db, user_a, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        # User B creates campaign requiring Reddit
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        campaign = create_campaign(db, exec_id, user_id=user_b, actions=[action])
        cid = campaign["campaign_id"]

        # Readiness for User B must report NOT_CONNECTED
        readiness_b = check_connector_readiness(db, cid, user_id=user_b)
        assert readiness_b["connector_requirements"][0]["status"] == "NOT_CONNECTED"
        assert readiness_b["status"] == CampaignStatus.AWAITING_CONNECTION


# ===========================================================================
# 3. Approval Lifecycle
# ===========================================================================

class TestApprovalLifecycle:
    def test_approve_selected_actions(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        act1_id = campaign["actions"][0]["action_id"]
        act2_id = campaign["actions"][1]["action_id"]

        # Approve only act1
        updated = approve_actions(db, cid, user_id=user_id, action_ids=[act1_id])

        actions_by_id = {a["action_id"]: a for a in updated["actions"]}
        assert actions_by_id[act1_id]["approval_status"] == ApprovalStatus.APPROVED
        assert actions_by_id[act2_id]["approval_status"] == ApprovalStatus.PENDING_APPROVAL

    def test_approve_all_campaign_actions(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        # Connect platforms
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        # Run readiness check so connectors are marked READY
        check_connector_readiness(db, cid, user_id=user_id)

        # Approve all
        updated = approve_actions(db, cid, user_id=user_id, approve_all=True)

        assert updated["status"] == CampaignStatus.READY
        for act in updated["actions"]:
            assert act["approval_status"] == ApprovalStatus.APPROVED

        # Verify event logged
        events = updated["events"]
        assert any(e["event"] == ObservabilityEvent.ACTION_APPROVED for e in events)


# ===========================================================================
# 4. Action Dispatch & DB Session Enforcement
# ===========================================================================

class TestActionDispatch:
    def test_mandatory_db_session_enforcement(self, db):
        """Calling execute_campaign with db=None must raise ValueError immediately."""
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        campaign = create_campaign(db, exec_id, "user_db_test", distribution_plan=_make_sample_plan(exec_id))
        cid = campaign["campaign_id"]

        with pytest.raises(ValueError, match="User-scoped DB session is mandatory"):
            execute_campaign(db=None, campaign_id=cid, user_id="user_db_test")

    def test_unapproved_action_is_blocked_from_execution(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        # Readiness checked, but actions NOT approved
        check_connector_readiness(db, cid, user_id=user_id)

        # Dispatch should NOT execute external router and should block unapproved actions
        mock_router = MagicMock()
        result = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)

        # Router was never invoked because actions were not approved
        assert mock_router.call_count == 0
        for act in result["actions"]:
            assert act["status"] == ExecutionStatus.BLOCKED
            assert act["reason"] == "APPROVAL_REQUIRED"

    def test_sequential_execution_and_router_invocation(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]

        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        call_order = []

        def mock_router(action, user_id, db, **kwargs):
            # Assert user_id and db are passed into worker call
            assert user_id.startswith("user_")
            assert db is not None
            platform = action.get("platform")
            call_order.append(platform)
            return {
                "status": ExecutionStatus.SUCCESS,
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": f"ext_{platform}_123",
                "external_url": f"https://{platform}.com/post/123",
            }

        result = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)

        assert call_order == ["reddit", "twitter"]  # Sequential dispatch order preserved
        assert result["status"] == CampaignStatus.COMPLETED
        assert result["summary"]["success"] == 2
        assert result["summary"]["total"] == 2


# ===========================================================================
# 5. Idempotency & Explicit Retry
# ===========================================================================

class TestIdempotency:
    def test_successful_action_not_duplicated(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        mock_router = MagicMock(return_value={
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "ext_999",
            "external_url": "https://reddit.com/r/test",
        })

        # First run: 2 actions executed
        res1 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 2
        assert res1["status"] == CampaignStatus.COMPLETED

        # Second run: actions are already SUCCESS, must NOT execute again!
        res2 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 2  # No additional calls
        assert res2["status"] == CampaignStatus.COMPLETED

    def test_failed_action_requires_explicit_retry(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")

        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        # First run: Reddit succeeds, Twitter fails
        def router_mixed(action, user_id, db, **kwargs):
            if action.get("platform") == "reddit":
                return {"status": ExecutionStatus.SUCCESS, "verified": True, "verification_status": VerificationStatus.PASS, "external_id": "r1"}
            return {"status": ExecutionStatus.FAILED, "verified": False, "verification_status": VerificationStatus.FAIL, "error": "Twitter rate limit", "reason": "RATE_LIMIT"}

        res1 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=router_mixed)
        assert res1["status"] == CampaignStatus.PARTIAL
        assert res1["summary"]["success"] == 1
        assert res1["summary"]["failed"] == 1

        # Calling normal execute_campaign again should NOT automatically re-attempt the failed action
        mock_spy = MagicMock()
        res2 = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_spy)
        assert mock_spy.call_count == 0  # Not executed!

        # Explicit retry
        mock_retry_router = MagicMock(return_value={
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "t1_fixed",
            "external_url": "https://x.com/post/fixed",
        })
        res3 = retry_failed_actions(db, cid, user_id=user_id, router_dispatch_fn=mock_retry_router)
        assert mock_retry_router.call_count == 1  # Only the failed action retried
        assert res3["status"] == CampaignStatus.COMPLETED
        assert res3["summary"]["success"] == 2


# ===========================================================================
# 6. Campaign Aggregation
# ===========================================================================

class TestCampaignAggregation:
    def test_all_success_is_completed(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        res = execute_campaign(
            db, cid, user_id=user_id,
            router_dispatch_fn=lambda a, u, d: {"status": ExecutionStatus.SUCCESS, "verified": True, "verification_status": VerificationStatus.PASS, "external_id": "ok"}
        )
        assert res["status"] == CampaignStatus.COMPLETED

    def test_mixed_is_partial(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        res = execute_campaign(
            db, cid, user_id=user_id,
            router_dispatch_fn=lambda a, u, d: (
                {"status": ExecutionStatus.SUCCESS, "verified": True, "verification_status": VerificationStatus.PASS, "external_id": "ok"}
                if a.get("platform") == "reddit"
                else {"status": ExecutionStatus.FAILED, "verified": False, "verification_status": VerificationStatus.FAIL, "error": "Fail"}
            )
        )
        assert res["status"] == CampaignStatus.PARTIAL

    def test_all_blocked_is_blocked(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        res = execute_campaign(
            db, cid, user_id=user_id,
            router_dispatch_fn=lambda a, u, d: {"status": ExecutionStatus.BLOCKED, "verified": False, "verification_status": VerificationStatus.FAIL, "reason": "AUTH_REQUIRED", "error": "Expired"}
        )
        assert res["status"] == CampaignStatus.BLOCKED

    def test_all_failed_is_failed(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        plan = _make_sample_plan(exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")
        connect_app(db, user_id, "twitter", json.dumps({"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"}), "api_key", "X")
        campaign = create_campaign(db, exec_id, user_id=user_id, distribution_plan=plan)
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        res = execute_campaign(
            db, cid, user_id=user_id,
            router_dispatch_fn=lambda a, u, d: {"status": ExecutionStatus.FAILED, "verified": False, "verification_status": VerificationStatus.FAIL, "error": "Provider 500 error"}
        )
        assert res["status"] == CampaignStatus.FAILED


# ===========================================================================
# 7. Receipts & Integrity
# ===========================================================================

class TestReceiptsAndIntegrity:
    def test_real_worker_receipt_preserved(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        real_receipt = {
            "status": ExecutionStatus.SUCCESS,
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": "t3_abc123",
            "external_url": "https://www.reddit.com/r/test/comments/abc123",
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda a, u, d: real_receipt)
        act_res = res["actions"][0]
        assert act_res["receipt"]["verified"] is True
        assert act_res["receipt"]["external_id"] == "t3_abc123"
        assert act_res["receipt"]["external_url"] == "https://www.reddit.com/r/test/comments/abc123"

    def test_missing_receipt_cannot_become_success(self, db):
        """Worker returning status=SUCCESS without verified receipt must be coerced to FAILED."""
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)
        approve_actions(db, cid, user_id=user_id, approve_all=True)

        # Worker dishonestly claims SUCCESS with verified=False
        fake_receipt = {
            "status": ExecutionStatus.SUCCESS,
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "external_id": None,
        }

        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=lambda a, u, d: fake_receipt)
        act_res = res["actions"][0]
        assert act_res["status"] == ExecutionStatus.FAILED
        assert act_res["receipt"]["verified"] is False
        assert res["status"] == CampaignStatus.FAILED


# ===========================================================================
# 8. Security & Secret Redaction
# ===========================================================================

class TestSecurity:
    def test_no_credentials_in_canonical_campaign(self, db):
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:6]}"
        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "SECRET_REDDIT_KEY", "username": "u", "password": "SECRET_PASSWORD"}), "api_key", "Reddit")

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)

        canonical = get_canonical_campaign(db, cid)
        canonical_str = json.dumps(canonical)

        assert "SECRET_REDDIT_KEY" not in canonical_str
        assert "SECRET_PASSWORD" not in canonical_str


# ===========================================================================
# 9. FastAPI Route Integration
# ===========================================================================

class TestDistributionAPIRoutes:
    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi.testclient import TestClient
        from main import app
        self.client = TestClient(app)

    def test_api_campaign_full_flow(self, db):
        exec_id = f"exec_api_{uuid.uuid4().hex[:8]}"
        user_id = f"user_api_{uuid.uuid4().hex[:6]}"

        # 1. Connect Reddit and Twitter credentials
        self.client.post("/credentials/connect", json={
            "user_id": user_id,
            "app_name": "reddit",
            "credentials": {"client_id": "c", "client_secret": "s", "username": "u", "password": "p"},
        })
        self.client.post("/credentials/connect", json={
            "user_id": user_id,
            "app_name": "twitter",
            "credentials": {"api_key": "k", "api_secret": "s", "access_token": "a", "access_token_secret": "as"},
        })

        # 2. POST /distribution/campaigns
        plan = _make_sample_plan(exec_id)
        create_resp = self.client.post("/distribution/campaigns", json={
            "execution_id": exec_id,
            "user_id": user_id,
            "distribution_plan": plan,
        })
        assert create_resp.status_code == 200
        camp = create_resp.json()
        cid = camp["campaign_id"]
        assert camp["status"] == "PLANNED"

        # 3. GET /distribution/campaigns/{campaign_id}
        get_resp = self.client.get(f"/distribution/campaigns/{cid}")
        assert get_resp.status_code == 200
        assert get_resp.json()["campaign_id"] == cid

        # 4. POST /distribution/campaigns/{campaign_id}/check-readiness
        readiness_resp = self.client.post(f"/distribution/campaigns/{cid}/check-readiness?user_id={user_id}")
        assert readiness_resp.status_code == 200
        readiness_data = readiness_resp.json()
        assert readiness_data["status"] == "AWAITING_APPROVAL"
        for req in readiness_data["connector_requirements"]:
            assert req["status"] == "READY"

        # 5. POST /distribution/campaigns/{campaign_id}/approve
        approve_resp = self.client.post(f"/distribution/campaigns/{cid}/approve", json={
            "user_id": user_id,
            "approve_all": True,
        })
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "READY"

        # 6. POST /distribution/campaigns/{campaign_id}/execute (with mocked router)
        with patch("orchestration.distribution_orchestrator.execute_distribution_action") as mock_exec:
            mock_exec.return_value = {
                "status": "SUCCESS",
                "verified": True,
                "verification_status": "PASS",
                "external_id": "ext_api_post",
                "external_url": "https://platform.com/post/1",
            }
            exec_resp = self.client.post(f"/distribution/campaigns/{cid}/execute", json={
                "user_id": user_id,
            })
            assert exec_resp.status_code == 200
            final_data = exec_resp.json()
            assert final_data["status"] == "COMPLETED"
            assert final_data["summary"]["success"] == 2

    def test_extended_status_endpoint_includes_distribution_campaign(self, db):
        """GET /executions/{user_id}/{execution_id}/status must return distribution_campaign."""
        exec_id = f"exec_status_{uuid.uuid4().hex[:8]}"
        user_id = f"user_status_{uuid.uuid4().hex[:6]}"

        # Seed an Execution row
        create_execution(
            db=db,
            user_id=user_id,
            original_idea="Test Status Idea",
            understood_goal="Test Status Goal",
            intent_classification="full_product",
            idea_type="saas",
            recommended_phases=[1, 2, 3],
        )
        # Update its ID to match exec_id
        from database.models import Execution
        ex = db.query(Execution).filter(Execution.user_id == user_id).first()
        ex.id = exec_id
        db.commit()

        # Before campaign created: distribution_campaign is None
        resp_before = self.client.get(f"/executions/{user_id}/{exec_id}/status")
        assert resp_before.status_code == 200
        data_before = resp_before.json()
        assert "distribution_campaign" in data_before
        assert data_before["distribution_campaign"] is None

        # Create campaign for this execution
        plan = _make_sample_plan(exec_id)
        self.client.post("/distribution/campaigns", json={
            "execution_id": exec_id,
            "user_id": user_id,
            "distribution_plan": plan,
        })

        # After campaign created: distribution_campaign is populated
        resp_after = self.client.get(f"/executions/{user_id}/{exec_id}/status")
        assert resp_after.status_code == 200
        data_after = resp_after.json()
        assert data_after["distribution_campaign"] is not None
        assert data_after["distribution_campaign"]["execution_id"] == exec_id
        assert data_after["distribution_campaign"]["status"] == "PLANNED"
        assert "workflow" in data_after
        assert "connector_actions" in data_after

    def test_api_retry_endpoint(self, db):
        exec_id = f"exec_retry_{uuid.uuid4().hex[:8]}"
        user_id = f"user_retry_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        action["execution"]["status"] = ExecutionStatus.FAILED
        action["approval"]["status"] = ApprovalStatus.APPROVED
        action["error"] = "Previous failure"

        create_resp = self.client.post("/distribution/campaigns", json={
            "execution_id": exec_id,
            "user_id": user_id,
            "actions": [action],
        })
        cid = create_resp.json()["campaign_id"]

        with patch("orchestration.distribution_orchestrator.execute_distribution_action") as mock_exec:
            mock_exec.return_value = {
                "status": "SUCCESS",
                "verified": True,
                "verification_status": "PASS",
                "external_id": "t3_retried_ok",
                "external_url": "https://reddit.com/r/test/comments/retried",
            }
            retry_resp = self.client.post(f"/distribution/campaigns/{cid}/retry", json={
                "user_id": user_id,
            })
            assert retry_resp.status_code == 200
            retry_data = retry_resp.json()
            assert retry_data["status"] == "COMPLETED"
            assert retry_data["summary"]["success"] == 1


# ===========================================================================
# 10. Platform Aliases & Detailed Isolation
# ===========================================================================

class TestPlatformAliasesAndIsolation:
    def test_email_connector_resolution_sendgrid(self, db):
        exec_id = f"exec_email_{uuid.uuid4().hex[:8]}"
        user_id = f"user_email_{uuid.uuid4().hex[:6]}"

        # User connects SendGrid
        connect_app(db, user_id, "sendgrid", json.dumps({"api_key": "SG.test"}), "api_key", "SendGrid")

        action = create_distribution_action("outreach", "email", "send_email", {"email": "test@example.com"}, {"subject": "Hi", "body": "Hello"}, execution_id=exec_id)
        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]

        readiness = check_connector_readiness(db, cid, user_id=user_id)
        reqs = {r["platform"]: r["status"] for r in readiness["connector_requirements"]}
        assert "sendgrid" in reqs
        assert reqs["sendgrid"] == "READY"

    def test_email_connector_resolution_smtp(self, db):
        exec_id = f"exec_smtp_{uuid.uuid4().hex[:8]}"
        user_id = f"user_smtp_{uuid.uuid4().hex[:6]}"

        # User connects SMTP
        connect_app(db, user_id, "smtp", json.dumps({"host": "smtp.mail.com", "username": "u", "password": "p"}), "smtp", "SMTP")

        action = create_distribution_action("outreach", "email", "send_email", {"email": "test@example.com"}, {"subject": "Hi", "body": "Hello"}, execution_id=exec_id)
        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]

        readiness = check_connector_readiness(db, cid, user_id=user_id)
        reqs = {r["platform"]: r["status"] for r in readiness["connector_requirements"]}
        assert "smtp" in reqs
        assert reqs["smtp"] == "READY"

    def test_rejected_approval_blocks_dispatch(self, db):
        exec_id = f"exec_rej_{uuid.uuid4().hex[:8]}"
        user_id = f"user_rej_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        action["approval"]["status"] = ApprovalStatus.REJECTED

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)

        mock_router = MagicMock()
        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 0
        assert res["actions"][0]["status"] == ExecutionStatus.BLOCKED

    def test_running_action_not_duplicated(self, db):
        exec_id = f"exec_run_{uuid.uuid4().hex[:8]}"
        user_id = f"user_run_{uuid.uuid4().hex[:6]}"

        connect_app(db, user_id, "reddit", json.dumps({"client_id": "c", "client_secret": "s", "username": "u", "password": "p"}), "api_key", "Reddit")

        action = create_distribution_action("community", "reddit", "create_post", {"community": "test"}, {"title": "T", "body": "B"}, execution_id=exec_id)
        action["approval"]["status"] = ApprovalStatus.APPROVED
        action["execution"]["status"] = ExecutionStatus.RUNNING

        campaign = create_campaign(db, exec_id, user_id=user_id, actions=[action])
        cid = campaign["campaign_id"]
        check_connector_readiness(db, cid, user_id=user_id)

        mock_router = MagicMock()
        res = execute_campaign(db, cid, user_id=user_id, router_dispatch_fn=mock_router)
        assert mock_router.call_count == 0  # Was already RUNNING, skipped duplication

