"""
TETRIS Milestone 3.5 Phase D — RedditAPIs Write Authentication Setup Tests
========================================================================

Verifies:
1. RedditAPIs connection/readiness check distinguishing:
   - API key configured
   - Reddit session configured
   - write-ready
   - AUTH_REQUIRED / READ_ONLY / WRITE_READY
2. User-scoped storage mechanism for RedditAPIs session credentials in StoredCredential
3. Cross-user credential isolation
4. Campaign orchestrator readiness gating (AWAITING_CONNECTION when session missing)
5. Zero plaintext password persistence and zero secret leakage
6. Zero external writes executed
"""

import json
import os
import uuid
import pytest
from unittest.mock import MagicMock, patch

from database.models import init_db, SessionLocal, StoredCredential, DistributionCampaign
from database.operations import (
    store_credential,
    get_credential,
    delete_credential,
    save_distribution_campaign,
    get_distribution_campaign_by_id,
)
from integrations.credential_manager import (
    connect_app,
    get_decrypted_credential,
    decrypt_credential,
)
from execution.reddit_executor import (
    RedditAPIsProvider,
    check_redditapis_readiness,
    resolve_redditapis_credentials,
    execute_reddit_action,
)
from orchestration.distribution_orchestrator import (
    create_campaign,
    check_connector_readiness,
    CampaignStatus,
    _resolve_required_connector,
)
from routes.credentials import _test_redditapis, CONNECTOR_FIELD_SCHEMAS


@pytest.fixture(scope="module")
def db_engine():
    init_db()
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def db(db_engine):
    yield db_engine


# ===========================================================================
# 1. Readiness Evaluation Tests
# ===========================================================================

class TestReadinessEvaluation:
    def test_readiness_no_credentials(self, db):
        user_id = f"test_user_empty_{uuid.uuid4().hex[:6]}"
        with patch.dict(os.environ, {}, clear=True):
            readiness = check_redditapis_readiness(user_id=user_id, db=db)
            assert readiness["api_key_configured"] is False
            assert readiness["session_configured"] is False
            assert readiness["write_ready"] is False
            assert readiness["status"] == "AUTH_REQUIRED"
            assert "api_key" in readiness["missing"]

    def test_readiness_api_key_only_read_only(self, db):
        user_id = f"test_user_keyonly_{uuid.uuid4().hex[:6]}"
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "RAPIS_KEY_123"}),
            connection_type="api_key",
            display_name="RedditAPIs",
        )
        readiness = check_redditapis_readiness(user_id=user_id, db=db)
        assert readiness["api_key_configured"] is True
        assert readiness["session_configured"] is False
        assert readiness["write_ready"] is False
        assert readiness["status"] == "READ_ONLY"
        assert "reddit_session" in readiness["missing"]
        assert "loid" in readiness["missing"]

    def test_readiness_partial_session_missing_loid(self, db):
        user_id = f"test_user_part_{uuid.uuid4().hex[:6]}"
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({
                "api_key": "RAPIS_KEY_123",
                "reddit_session": "sess_abc",
            }),
            connection_type="api_key",
            display_name="RedditAPIs",
        )
        readiness = check_redditapis_readiness(user_id=user_id, db=db)
        assert readiness["api_key_configured"] is True
        assert readiness["session_configured"] is False
        assert readiness["write_ready"] is False
        assert readiness["status"] == "READ_ONLY"
        assert "loid" in readiness["missing"]
        assert "reddit_session" not in readiness["missing"]

    def test_readiness_full_session_write_ready(self, db):
        user_id = f"test_user_ready_{uuid.uuid4().hex[:6]}"
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({
                "api_key": "RAPIS_KEY_123",
                "reddit_session": "sess_valid_abc",
                "loid": "loid_valid_xyz",
            }),
            connection_type="api_key",
            display_name="RedditAPIs",
        )
        readiness = check_redditapis_readiness(user_id=user_id, db=db)
        assert readiness["api_key_configured"] is True
        assert readiness["session_configured"] is True
        assert readiness["write_ready"] is True
        assert readiness["status"] == "WRITE_READY"
        assert len(readiness["missing"]) == 0
        assert readiness["error"] is None

    def test_provider_check_readiness_instance_method(self):
        # Empty
        prov_empty = RedditAPIsProvider(api_key=None)
        assert prov_empty.check_readiness()["status"] == "AUTH_REQUIRED"
        assert prov_empty.check_readiness()["write_ready"] is False

        # Key only
        prov_key = RedditAPIsProvider(api_key="KEY_XYZ")
        assert prov_key.check_readiness()["status"] == "READ_ONLY"
        assert prov_key.check_readiness()["write_ready"] is False

        # Full session
        prov_full = RedditAPIsProvider(
            api_key="KEY_XYZ",
            session_cookies={"reddit_session": "s1", "loid": "l1"},
        )
        assert prov_full.check_readiness()["status"] == "WRITE_READY"
        assert prov_full.check_readiness()["write_ready"] is True


# ===========================================================================
# 2. User-Scoped Encrypted Storage & Cross-User Isolation
# ===========================================================================

class TestUserScopedEncryptedStorage:
    def test_stored_credential_is_encrypted_at_rest(self, db):
        user_id = f"user_enc_{uuid.uuid4().hex[:6]}"
        raw_secret_json = json.dumps({
            "api_key": "SECRET_KEY_12345",
            "reddit_session": "SUPER_SECRET_SESSION_999",
            "loid": "SUPER_SECRET_LOID_888",
        })
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=raw_secret_json,
            connection_type="api_key",
            display_name="RedditAPIs",
        )

        row = db.query(StoredCredential).filter(
            StoredCredential.user_id == user_id,
            StoredCredential.app_name == "redditapis",
        ).first()

        assert row is not None
        # Plaintext secrets must NEVER appear in the raw database column
        assert "SECRET_KEY_12345" not in row.credential_encrypted
        assert "SUPER_SECRET_SESSION_999" not in row.credential_encrypted
        assert "SUPER_SECRET_LOID_888" not in row.credential_encrypted

        # Must be decryptable with credential_manager
        decrypted = decrypt_credential(row.credential_encrypted)
        assert "SECRET_KEY_12345" in decrypted

    def test_cross_user_isolation(self, db):
        user_a = f"user_a_{uuid.uuid4().hex[:6]}"
        user_b = f"user_b_{uuid.uuid4().hex[:6]}"
        user_c = f"user_c_{uuid.uuid4().hex[:6]}"

        # User A: Write Ready
        connect_app(
            db=db,
            user_id=user_a,
            app_name="redditapis",
            raw_credential=json.dumps({
                "api_key": "KEY_A",
                "reddit_session": "SESS_A",
                "loid": "LOID_A",
            }),
            connection_type="api_key",
            display_name="RedditAPIs",
        )

        # User B: Read Only
        connect_app(
            db=db,
            user_id=user_b,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "KEY_B"}),
            connection_type="api_key",
            display_name="RedditAPIs",
        )

        # User C: No credentials
        readiness_a = check_redditapis_readiness(user_id=user_a, db=db)
        readiness_b = check_redditapis_readiness(user_id=user_b, db=db)
        with patch.dict(os.environ, {}, clear=True):
            readiness_c = check_redditapis_readiness(user_id=user_c, db=db)

        assert readiness_a["status"] == "WRITE_READY"
        assert readiness_a["write_ready"] is True

        assert readiness_b["status"] == "READ_ONLY"
        assert readiness_b["write_ready"] is False

        assert readiness_c["status"] == "AUTH_REQUIRED"
        assert readiness_c["write_ready"] is False

    def test_nested_session_cookies_supported(self, db):
        user_id = f"user_nested_{uuid.uuid4().hex[:6]}"
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({
                "api_key": "KEY_NESTED",
                "session_cookies": {
                    "reddit_session": "SESS_NESTED",
                    "loid": "LOID_NESTED",
                },
            }),
            connection_type="api_key",
            display_name="RedditAPIs",
        )
        resolved = resolve_redditapis_credentials(user_id=user_id, db=db)
        assert resolved["api_key"] == "KEY_NESTED"
        assert resolved["session_cookies"]["reddit_session"] == "SESS_NESTED"
        assert resolved["session_cookies"]["loid"] == "LOID_NESTED"

        readiness = check_redditapis_readiness(user_id=user_id, db=db)
        assert readiness["write_ready"] is True


# ===========================================================================
# 3. Routes & Schemas Integration Tests
# ===========================================================================

class TestRoutesAndSchemas:
    def test_connector_field_schemas_has_redditapis(self):
        assert "redditapis" in CONNECTOR_FIELD_SCHEMAS
        schema = CONNECTOR_FIELD_SCHEMAS["redditapis"]
        keys = [f["key"] for f in schema["fields"]]
        assert "api_key" in keys
        assert "reddit_session" in keys
        assert "loid" in keys

    def test_test_redditapis_route_auth_required_when_key_missing(self):
        res = _test_redditapis("redditapis", {})
        assert res.status == "AUTH_REQUIRED"
        assert res.verified is False

    def test_test_redditapis_route_read_only_when_session_missing(self):
        with patch.object(RedditAPIsProvider, "search") as mock_search:
            mock_search.return_value = {"success": True, "posts": []}
            res = _test_redditapis("redditapis", {"api_key": "VALID_KEY"})
            assert res.status == "CONNECTED"
            assert res.verified is True
            assert "Read Only" in res.display_name
            assert "session" in (res.error or "").lower()

    def test_test_redditapis_route_write_ready_when_session_present(self):
        with patch.object(RedditAPIsProvider, "search") as mock_search:
            mock_search.return_value = {"success": True, "posts": []}
            res = _test_redditapis("redditapis", {
                "api_key": "VALID_KEY",
                "reddit_session": "S1",
                "loid": "L1",
            })
            assert res.status == "CONNECTED"
            assert res.verified is True
            assert "Write Ready" in res.display_name
            assert res.error is None


# ===========================================================================
# 4. Campaign Orchestrator Gating Tests
# ===========================================================================

class TestCampaignOrchestratorGating:
    def test_resolve_required_connector_for_redditapis(self):
        action_apis = {
            "platform": "reddit",
            "worker": "community",
            "provider": "redditapis",
        }
        action_praw = {
            "platform": "reddit",
            "worker": "community",
            "provider": "praw",
        }
        action_default = {
            "platform": "reddit",
            "worker": "community",
        }

        assert _resolve_required_connector(action_apis, set()) == "redditapis"
        assert _resolve_required_connector(action_praw, set()) == "reddit"
        assert _resolve_required_connector(action_default, set()) == "reddit"

    def test_campaign_blocked_awaiting_connection_when_redditapis_session_missing(self, db):
        user_id = f"user_gating_{uuid.uuid4().hex[:6]}"
        # User only has API key, no session
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "VALID_KEY"}),
            connection_type="api_key",
            display_name="RedditAPIs",
        )

        actions = [{
            "action_id": f"act_{uuid.uuid4().hex[:6]}",
            "platform": "reddit",
            "worker": "community",
            "provider": "redditapis",
            "action_type": "create_post",
            "target": {"subreddit": "test"},
            "content": {"title": "Title", "body": "Body"},
            "approval": {"status": "APPROVED", "required": True},
        }]

        cmp = create_campaign(
            db=db,
            execution_id=f"exec_{uuid.uuid4().hex[:6]}",
            user_id=user_id,
            actions=actions,
        )

        checked = check_connector_readiness(db=db, campaign_id=cmp["campaign_id"], user_id=user_id)
        assert checked["status"] == CampaignStatus.AWAITING_CONNECTION
        reqs = checked["connector_requirements"]
        assert len(reqs) == 1
        assert reqs[0]["platform"] == "redditapis"
        assert reqs[0]["status"] == "NOT_CONNECTED"
        assert reqs[0]["details"]["write_ready"] is False

    def test_campaign_ready_when_redditapis_session_configured(self, db):
        user_id = f"user_ready_cmp_{uuid.uuid4().hex[:6]}"
        # User has full credentials (key + session)
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({
                "api_key": "VALID_KEY",
                "reddit_session": "SESS_123",
                "loid": "LOID_123",
            }),
            connection_type="api_key",
            display_name="RedditAPIs",
        )

        actions = [{
            "action_id": f"act_{uuid.uuid4().hex[:6]}",
            "platform": "reddit",
            "worker": "community",
            "provider": "redditapis",
            "action_type": "create_post",
            "target": {"subreddit": "test"},
            "content": {"title": "Title", "body": "Body"},
            "approval": {"status": "APPROVED", "required": True},
        }]

        cmp = create_campaign(
            db=db,
            execution_id=f"exec_{uuid.uuid4().hex[:6]}",
            user_id=user_id,
            actions=actions,
        )

        checked = check_connector_readiness(db=db, campaign_id=cmp["campaign_id"], user_id=user_id)
        assert checked["status"] == CampaignStatus.READY
        reqs = checked["connector_requirements"]
        assert len(reqs) == 1
        assert reqs[0]["platform"] == "redditapis"
        assert reqs[0]["status"] == "READY"
        assert reqs[0]["details"]["write_ready"] is True


# ===========================================================================
# 5. Security & Safety Guards
# ===========================================================================

class TestSecurityGuards:
    def test_no_passwords_or_session_cookies_in_test_response(self):
        raw_cred = {
            "api_key": "SENSITIVE_KEY_999",
            "reddit_session": "SENSITIVE_SESSION_888",
            "loid": "SENSITIVE_LOID_777",
            "password": "DO_NOT_STORE_PASSWORD",
        }
        with patch.object(RedditAPIsProvider, "search") as mock_search:
            mock_search.return_value = {"success": True, "posts": []}
            res = _test_redditapis("redditapis", raw_cred)
            res_dict = res.model_dump() if hasattr(res, "model_dump") else res.dict()
            res_str = json.dumps(res_dict)
            assert "SENSITIVE_KEY_999" not in res_str
            assert "SENSITIVE_SESSION_888" not in res_str
            assert "SENSITIVE_LOID_777" not in res_str
            assert "DO_NOT_STORE_PASSWORD" not in res_str

    def test_zero_external_write_executed(self, db):
        user_id = f"user_write_blocked_{uuid.uuid4().hex[:6]}"
        connect_app(
            db=db,
            user_id=user_id,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "RAPIS_KEY_ONLY"}),
            connection_type="api_key",
            display_name="RedditAPIs",
        )
        action = {
            "action_id": "act_safety_check",
            "action_type": "create_post",
            "platform": "reddit",
            "provider": "redditapis",
            "target": {"subreddit": "test"},
            "content": {"title": "Title", "body": "Body"},
            "approval": {"status": "APPROVED", "required": True},
        }
        # Without session, execute_reddit_action must block before any network request
        with patch.dict(os.environ, {"REDDIT_SESSION": "", "REDDIT_LOID": ""}):
            with patch("requests.Session.post") as mock_post:
                result = execute_reddit_action(action, user_id=user_id, db=db, provider="redditapis")
                assert result["status"] == "BLOCKED"
                assert result["reason"] == "AUTH_REQUIRED"
                mock_post.assert_not_called()
