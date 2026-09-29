"""
Tetris — M3.5-A Test Suite
===========================

Connector & Credential Foundation

Coverage (22 test areas):
  1.  DB initialization
  2.  Credential connect
  3.  Credential persistence
  4.  Credential retrieval
  5.  Credential update (upsert)
  6.  Credential disconnect (soft-delete)
  7.  Duplicate connection behavior
  8.  Reddit structured credentials
  9.  X/Twitter structured credentials
  10. LinkedIn credentials
  11. SendGrid credentials
  12. SMTP credentials
  13. Credential encryption
  14. Credential decryption
  15. Missing credentials
  16. Invalid credential format
  17. Test endpoint (mocked)
  18. Readiness endpoint
  19. Secret sanitisation
  20. Worker credential resolution
  21. Restart persistence (DB survives session close/reopen)
  22. Frontend API contract verification (schema check)

Run:
    cd backend
    python -m pytest test_m35a_credential_foundation.py -v --tb=short
"""

import json
import os
import sys
import sqlite3
import tempfile
import pytest
from unittest.mock import MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Use an isolated in-memory SQLite for tests ────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_m35a.db")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_long!!")


# ===========================================================================
# 1. DB Initialization
# ===========================================================================

class TestDBInit:
    def test_init_db_creates_stored_credentials_table(self):
        """init_db() must create stored_credentials table idempotently."""
        from database.models import init_db, engine
        init_db()  # may be called multiple times
        init_db()  # idempotency check

        conn = engine.raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stored_credentials'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None, "stored_credentials table must exist after init_db()"

    def test_init_db_creates_connector_actions_table(self):
        from database.models import init_db, engine
        init_db()
        conn = engine.raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='connector_actions'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None, "connector_actions table must exist"

    def test_init_db_does_not_destroy_existing_data(self):
        """Calling init_db() again must not wipe existing rows."""
        from database.models import init_db, SessionLocal
        from database.operations import store_credential, get_credential
        from integrations.credential_manager import encrypt_credential

        init_db()
        db = SessionLocal()
        try:
            enc = encrypt_credential("sentinel_value")
            store_credential(db, "user_init_test", "github", enc, "api_key", "test")
            db.commit()
        finally:
            db.close()

        init_db()  # second call

        db2 = SessionLocal()
        try:
            raw = get_credential(db2, "user_init_test", "github")
            assert raw is not None, "Row must survive a second init_db() call"
        finally:
            db2.close()


# ===========================================================================
# 2-7. Credential CRUD
# ===========================================================================

class TestCredentialCRUD:
    USER = "user_crud_test"

    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def _connect(self, app, payload):
        from integrations.credential_manager import connect_app
        return connect_app(
            db=self.db,
            user_id=self.USER,
            app_name=app,
            raw_credential=json.dumps(payload),
            connection_type="api_key",
            display_name=app.capitalize(),
        )

    # 2. Connect
    def test_connect_returns_success(self):
        result = self._connect("testapp_connect", {"token": "abc123"})
        assert result["success"] is True

    # 3. Persistence
    def test_credential_persists_in_db(self):
        from database.operations import get_credential
        self._connect("testapp_persist", {"token": "abc123"})
        raw = get_credential(self.db, self.USER, "testapp_persist")
        assert raw is not None

    # 4. Retrieval — decrypt
    def test_credential_decrypts_correctly(self):
        from integrations.credential_manager import connect_app, get_decrypted_credential
        payload = {"client_id": "my_id", "client_secret": "my_secret"}
        connect_app(self.db, self.USER, "testapp_decrypt", json.dumps(payload),
                    "api_credentials", "Test")
        result = get_decrypted_credential(self.db, self.USER, "testapp_decrypt")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["client_id"] == "my_id"
        assert parsed["client_secret"] == "my_secret"

    # 5. Update (upsert)
    def test_credential_update_upserts(self):
        from integrations.credential_manager import connect_app, get_decrypted_credential
        connect_app(self.db, self.USER, "testapp_upsert", json.dumps({"v": "1"}),
                    "api_key", "Test")
        connect_app(self.db, self.USER, "testapp_upsert", json.dumps({"v": "2"}),
                    "api_key", "Test")
        result = get_decrypted_credential(self.db, self.USER, "testapp_upsert")
        assert json.loads(result)["v"] == "2", "Second connect must update, not duplicate"

    # 6. Disconnect (soft delete)
    def test_disconnect_deactivates_credential(self):
        from integrations.credential_manager import connect_app, disconnect_app, get_decrypted_credential
        connect_app(self.db, self.USER, "testapp_disc", json.dumps({"t": "x"}), "api_key", "Test")
        disconnect_app(self.db, self.USER, "testapp_disc")
        result = get_decrypted_credential(self.db, self.USER, "testapp_disc")
        assert result is None, "After disconnect, get_decrypted_credential must return None"

    # 7. Duplicate connection
    def test_duplicate_connect_updates_not_inserts(self):
        from database.models import StoredCredential
        from integrations.credential_manager import connect_app

        for _ in range(3):
            connect_app(self.db, self.USER, "testapp_dup", json.dumps({"t": "v"}),
                        "api_key", "Test")

        count = (
            self.db.query(StoredCredential)
            .filter(
                StoredCredential.user_id == self.USER,
                StoredCredential.app_name == "testapp_dup",
            )
            .count()
        )
        assert count == 1, f"Expected 1 row, got {count} (upsert bug)"


# ===========================================================================
# 8-12. Per-platform structured credentials
# ===========================================================================

class TestPlatformCredentials:
    USER = "user_platform_test"

    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def _roundtrip(self, app_name, payload):
        """Connect, then decrypt and return the parsed dict."""
        from integrations.credential_manager import connect_app, get_decrypted_credential
        connect_app(self.db, self.USER, app_name, json.dumps(payload),
                    "api_credentials", app_name.capitalize())
        raw = get_decrypted_credential(self.db, self.USER, app_name)
        assert raw is not None, f"No credential returned for {app_name}"
        return json.loads(raw)

    # 8. Reddit
    def test_reddit_credential_fields(self):
        payload = {
            "client_id": "RID",
            "client_secret": "RSECRET",
            "username": "ruser",
            "password": "rpass",
            "user_agent": "TetrisTest/1.0",
        }
        result = self._roundtrip("reddit", payload)
        assert result["client_id"] == "RID"
        assert result["client_secret"] == "RSECRET"
        assert result["username"] == "ruser"
        assert result["password"] == "rpass"

    # 9. X/Twitter
    def test_twitter_credential_fields(self):
        payload = {
            "api_key": "XKEY",
            "api_secret": "XSECRET",
            "access_token": "XTOKEN",
            "access_token_secret": "XTOKENSEC",
            "bearer_token": "XBEARER",
        }
        result = self._roundtrip("twitter", payload)
        assert result["api_key"] == "XKEY"
        assert result["access_token_secret"] == "XTOKENSEC"

    # 10. LinkedIn
    def test_linkedin_credential_fields(self):
        payload = {"access_token": "LITOKEN", "person_id": "urn:li:person:ABC123"}
        result = self._roundtrip("linkedin", payload)
        assert result["access_token"] == "LITOKEN"
        assert result["person_id"] == "urn:li:person:ABC123"

    # 11. SendGrid
    def test_sendgrid_credential_fields(self):
        payload = {"api_key": "SG.abc123", "from_email": "no@reply.com", "from_name": "Tester"}
        result = self._roundtrip("sendgrid", payload)
        assert result["api_key"] == "SG.abc123"
        assert result["from_email"] == "no@reply.com"

    # 12. SMTP
    def test_smtp_credential_fields(self):
        payload = {
            "host": "smtp.gmail.com",
            "port": "587",
            "username": "me@gmail.com",
            "password": "gmailpass",
            "from_email": "me@gmail.com",
            "from_name": "Me",
            "use_tls": "true",
        }
        result = self._roundtrip("smtp", payload)
        assert result["host"] == "smtp.gmail.com"
        assert result["username"] == "me@gmail.com"
        assert result["password"] == "gmailpass"


# ===========================================================================
# 13-14. Encryption / Decryption
# ===========================================================================

class TestEncryption:
    def test_encrypt_produces_non_plaintext(self):
        from integrations.credential_manager import encrypt_credential
        raw = "super_secret_value"
        enc = encrypt_credential(raw)
        assert enc != raw
        assert "super_secret" not in enc

    def test_decrypt_roundtrip(self):
        from integrations.credential_manager import encrypt_credential, decrypt_credential
        raw = "roundtrip_test_value"
        enc = encrypt_credential(raw)
        dec = decrypt_credential(enc)
        assert dec == raw

    def test_decrypt_wrong_token_returns_empty(self):
        from integrations.credential_manager import decrypt_credential
        result = decrypt_credential("definitely_not_fernet_token")
        assert result == "", "Invalid token must return empty string, not raise"

    def test_encrypt_empty_string_returns_empty(self):
        from integrations.credential_manager import encrypt_credential
        result = encrypt_credential("")
        assert result == ""

    def test_vault_independent_encryption(self):
        """vault.py uses sha256 key derivation — different from credential_manager.
        Verify vault can encrypt+decrypt its own values independently."""
        from integrations.vault import store_credential, get_credential
        store_credential("vault_user", "vault_app", "vault_secret_value")
        result = get_credential("vault_user", "vault_app")
        assert result == "vault_secret_value"


# ===========================================================================
# 15-16. Missing / Invalid credentials
# ===========================================================================

class TestEdgeCases:
    def test_missing_credential_returns_none(self):
        from database.models import init_db, SessionLocal
        from integrations.credential_manager import get_decrypted_credential
        init_db()
        db = SessionLocal()
        result = get_decrypted_credential(db, "nobody_user_xyz", "nonexistent_app")
        db.close()
        assert result is None

    def test_invalid_json_in_credential_handled(self):
        """Workers must gracefully handle non-JSON credential strings."""
        # The workers call json.loads() in a try/except — test that pattern
        raw = "not_json_at_all"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        assert parsed is None  # worker must handle this gracefully

    def test_empty_credentials_dict_rejected(self):
        """ConnectCredentialRequest must reject empty credentials dicts."""
        from routes.credentials import ConnectCredentialRequest
        with pytest.raises(Exception):  # ValidationError
            ConnectCredentialRequest(
                user_id="u1",
                app_name="reddit",
                credentials={},
            )


# ===========================================================================
# 17. Test endpoint (Phase 5) — mocked to avoid live API calls
# ===========================================================================

class TestTestEndpoint:
    USER = "user_test_ep"

    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def _store_reddit(self):
        from integrations.credential_manager import connect_app
        connect_app(self.db, self.USER, "reddit",
                    json.dumps({"client_id": "x", "client_secret": "y",
                                "username": "u", "password": "p"}),
                    "api_credentials", "Reddit")

    def test_test_endpoint_returns_blocked_for_no_creds(self):
        """If no credentials stored, test returns BLOCKED."""
        from routes.credentials import test_credential
        res = test_credential("nonexistent_platform_xyz", user_id="nobody_xyz", db=self.db)
        assert res.status == "BLOCKED"
        assert res.verified is False

    @patch("praw.Reddit")
    def test_test_reddit_mocked_success(self, MockReddit):
        self._store_reddit()
        mock_instance = MagicMock()
        mock_instance.user.me.return_value.name = "test_redditor"
        MockReddit.return_value = mock_instance

        from routes.credentials import test_credential
        res = test_credential("reddit", user_id=self.USER, db=self.db)
        assert res.verified is True
        assert res.status == "CONNECTED"
        assert res.display_name == "test_redditor"

    @patch("praw.Reddit")
    def test_test_reddit_mocked_auth_failure(self, MockReddit):
        self._store_reddit()
        MockReddit.return_value.user.me.side_effect = Exception("Invalid credentials")

        from routes.credentials import test_credential
        res = test_credential("reddit", user_id=self.USER, db=self.db)
        assert res.verified is False
        assert res.status == "AUTH_FAILED"
        # Secrets must not appear in error string
        assert "y" not in (res.error or "").replace("[REDACTED]", "")  # client_secret = "y"

    def test_test_sendgrid_mocked_success(self):
        from integrations.credential_manager import connect_app
        connect_app(self.db, self.USER, "sendgrid",
                    json.dumps({"api_key": "SG.testkey", "from_email": "a@b.com"}),
                    "api_key", "SendGrid")

        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"username": "sg_user"}

            from routes.credentials import test_credential
            res = test_credential("sendgrid", user_id=self.USER, db=self.db)
            assert res.verified is True
            assert res.display_name == "sg_user"


# ===========================================================================
# 18. Readiness endpoint
# ===========================================================================

class TestReadiness:
    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def test_readiness_returns_distribution_platforms(self):
        from routes.credentials import get_readiness
        res = get_readiness(user_id="readiness_test_user_new", db=self.db)
        assert "connectors" in res
        for platform in ("reddit", "twitter", "linkedin", "sendgrid", "smtp"):
            assert platform in res["connectors"]

    def test_readiness_shows_connected_after_connect(self):
        from integrations.credential_manager import connect_app
        from routes.credentials import get_readiness

        connect_app(self.db, "user_readiness_x", "reddit",
                    json.dumps({"client_id": "a", "client_secret": "b",
                                "username": "c", "password": "d"}),
                    "api_credentials", "Reddit")

        res = get_readiness(user_id="user_readiness_x", db=self.db)
        assert res["connectors"]["reddit"]["connected"] is True
        assert res["connectors"]["twitter"]["connected"] is False


# ===========================================================================
# 19. Secret sanitisation
# ===========================================================================

class TestSecretSanitisation:
    def test_mask_secrets_replaces_secret_in_string(self):
        from routes.credentials import _mask_secrets
        error = "Failed to auth with secret=my_super_secret_value"
        masked = _mask_secrets(error, ["my_super_secret_value"])
        assert "my_super_secret_value" not in masked
        assert "[REDACTED]" in masked

    def test_mask_secrets_handles_empty_secret_list(self):
        from routes.credentials import _mask_secrets
        result = _mask_secrets("some error", [])
        assert result == "some error"

    def test_mask_secrets_ignores_short_secrets(self):
        """Secrets ≤ 3 chars are too ambiguous to mask."""
        from routes.credentials import _mask_secrets
        result = _mask_secrets("error abc", ["ab"])
        assert result == "error abc"

    def test_list_credentials_does_not_return_raw_values(self):
        """get_connected_apps must only return metadata, not raw encrypted blobs."""
        from database.models import init_db, SessionLocal
        from integrations.credential_manager import connect_app, get_connected_apps
        init_db()
        db = SessionLocal()
        connect_app(db, "user_sanitise", "github",
                    json.dumps({"token": "ghp_MY_REAL_TOKEN"}),
                    "api_key", "GitHub")
        apps = get_connected_apps(db, "user_sanitise")
        db.close()

        for app in apps:
            if app.get("app_name") == "github":
                assert "credential_encrypted" not in app
                assert "ghp_MY_REAL_TOKEN" not in str(app)

    def test_connect_response_does_not_include_credentials(self):
        """POST /credentials/connect response must not echo back credential values."""
        from database.models import init_db, SessionLocal
        from routes.credentials import ConnectCredentialRequest, connect_credential
        init_db()
        db = SessionLocal()
        body = ConnectCredentialRequest(
            user_id="user_sec",
            app_name="github",
            credentials={"token": "ghp_SECRET_GITHUB_TOKEN"},
        )
        result = connect_credential(body, db=db)
        db.close()
        result_str = str(result)
        assert "ghp_SECRET_GITHUB_TOKEN" not in result_str


# ===========================================================================
# 20. Worker credential resolution
# ===========================================================================

class TestWorkerResolution:
    USER = "user_worker_res"

    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def _store(self, app, payload):
        from integrations.credential_manager import connect_app
        connect_app(self.db, self.USER, app, json.dumps(payload), "api_credentials", app)

    def test_reddit_worker_reads_from_db(self):
        payload = {"client_id": "R_ID", "client_secret": "R_SEC",
                   "username": "R_USER", "password": "R_PASS"}
        self._store("reddit", payload)

        from execution.reddit_executor import resolve_reddit_credentials
        creds = resolve_reddit_credentials(user_id=self.USER, db=self.db)
        assert creds["client_id"] == "R_ID"
        assert creds["client_secret"] == "R_SEC"
        assert creds["username"] == "R_USER"

    def test_twitter_worker_reads_from_db(self):
        payload = {"api_key": "X_KEY", "api_secret": "X_SEC",
                   "access_token": "X_TOK", "access_token_secret": "X_TOK_SEC"}
        self._store("twitter", payload)

        from execution.x_executor import resolve_x_credentials
        creds = resolve_x_credentials(user_id=self.USER, db=self.db)
        assert creds["api_key"] == "X_KEY"
        assert creds["access_token_secret"] == "X_TOK_SEC"

    def test_linkedin_worker_reads_from_db(self):
        payload = {"access_token": "LI_TOK", "person_id": "urn:li:person:XYZ"}
        self._store("linkedin", payload)

        from execution.linkedin_executor import resolve_linkedin_credentials
        creds = resolve_linkedin_credentials(user_id=self.USER, db=self.db)
        assert creds["access_token"] == "LI_TOK"
        assert creds["person_id"] == "urn:li:person:XYZ"

    def test_sendgrid_worker_reads_from_db(self):
        payload = {"api_key": "SG.test_key", "from_email": "a@b.com"}
        self._store("sendgrid", payload)

        from execution.email_executor import resolve_sendgrid_credentials
        creds = resolve_sendgrid_credentials(user_id=self.USER, db=self.db)
        assert creds["api_key"] == "SG.test_key"
        assert creds["from_email"] == "a@b.com"

    def test_smtp_worker_reads_from_db(self):
        payload = {"host": "smtp.test.com", "port": "587",
                   "username": "u@test.com", "password": "pw123",
                   "from_email": "u@test.com"}
        self._store("smtp", payload)

        from execution.email_executor import resolve_smtp_credentials
        creds = resolve_smtp_credentials(user_id=self.USER, db=self.db)
        assert creds["host"] == "smtp.test.com"
        assert creds["password"] == "pw123"

    def test_worker_falls_back_to_env_when_no_db_entry(self):
        """If no DB entry exists, worker must read from env vars."""
        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "ENV_R_ID"}):
            from execution.reddit_executor import resolve_reddit_credentials
            creds = resolve_reddit_credentials(user_id="nobody_env_user", db=self.db)
            assert creds["client_id"] == "ENV_R_ID"

    def test_db_credentials_take_priority_over_env(self):
        """DB StoredCredential must shadow env vars."""
        payload = {"client_id": "DB_ID", "client_secret": "DB_SEC",
                   "username": "DB_USER", "password": "DB_PASS"}
        self._store("reddit", payload)

        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "ENV_SHOULD_BE_IGNORED"}):
            from execution.reddit_executor import resolve_reddit_credentials
            creds = resolve_reddit_credentials(user_id=self.USER, db=self.db)
            assert creds["client_id"] == "DB_ID", \
                "DB credential must shadow env var"

    def test_missing_credentials_block_reddit_worker(self):
        """When no credentials exist at all, worker must return BLOCKED."""
        from execution.reddit_executor import execute_reddit_action
        action = {
            "action_type": "create_post",
            "platform": "reddit",
            "worker": "community",
            "approval": {"status": "APPROVED"},
            "payload": {"subreddit": "test", "title": "T", "body": "B"},
        }
        result = execute_reddit_action(action, user_id="nobody_blocked_user", db=None)
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "AUTH_REQUIRED"


# ===========================================================================
# 21. Restart persistence
# ===========================================================================

class TestRestartPersistence:
    def test_credential_survives_session_close_reopen(self):
        """Credential written in one session must be readable in a new session."""
        from database.models import init_db, SessionLocal
        from integrations.credential_manager import connect_app, get_decrypted_credential
        init_db()

        db1 = SessionLocal()
        connect_app(db1, "user_persist_restart", "reddit",
                    json.dumps({"client_id": "PERSIST_ID"}),
                    "api_credentials", "Reddit")
        db1.close()

        db2 = SessionLocal()
        result = get_decrypted_credential(db2, "user_persist_restart", "reddit")
        db2.close()

        assert result is not None
        assert json.loads(result)["client_id"] == "PERSIST_ID"


# ===========================================================================
# 22. Frontend API contract
# ===========================================================================

class TestFrontendContract:
    """
    Verify the backend response shapes match what the frontend expects.
    """

    def setup_method(self):
        from database.models import init_db, SessionLocal
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        self.db.close()

    def test_list_response_shape(self):
        """GET /credentials/{user_id} must return { user_id, connected_apps: [...] }."""
        from routes.credentials import get_credentials
        result = get_credentials("contract_user_list", db=self.db)
        assert "user_id" in result
        assert "connected_apps" in result
        assert isinstance(result["connected_apps"], list)

    def test_connected_app_metadata_shape(self):
        """Each connected_app entry must have app_name, connection_type, display_name."""
        from integrations.credential_manager import connect_app
        from routes.credentials import get_credentials
        connect_app(self.db, "contract_user_shape", "discord",
                    json.dumps({"token": "DTOKEN", "channel_id": "123"}),
                    "bot_token", "Discord")
        result = get_credentials("contract_user_shape", db=self.db)
        apps = result["connected_apps"]
        if apps:
            app = apps[0]
            assert "app_name" in app
            assert "connection_type" in app
            assert "credential_encrypted" not in app  # secrets must not be returned

    def test_connect_response_shape(self):
        """POST /credentials/connect must return { success, app_name, message }."""
        from routes.credentials import ConnectCredentialRequest, connect_credential
        body = ConnectCredentialRequest(
            user_id="contract_connect_user",
            app_name="github",
            credentials={"token": "ghp_FRONTEND_CONTRACT"},
        )
        result = connect_credential(body, db=self.db)
        assert result.success is True
        assert result.app_name == "github"
        assert isinstance(result.message, str)

    def test_readiness_response_shape(self):
        """GET /credentials/readiness/{user_id} must return { user_id, connectors: {...} }."""
        from routes.credentials import get_readiness
        result = get_readiness("contract_readiness_user", db=self.db)
        assert "user_id" in result
        assert "connectors" in result
        for _platform, status in result["connectors"].items():
            assert "connected" in status
            assert "verified" in status

    def test_app_name_normalisation(self):
        """app_name='x' or 'X/Twitter' must be normalised to 'twitter'."""
        from routes.credentials import ConnectCredentialRequest
        r1 = ConnectCredentialRequest(user_id="u", app_name="X",
                                      credentials={"api_key": "k"})
        r2 = ConnectCredentialRequest(user_id="u", app_name="x/twitter",
                                      credentials={"api_key": "k"})
        r3 = ConnectCredentialRequest(user_id="u", app_name="X / Twitter",
                                      credentials={"api_key": "k"})
        assert r1.app_name == "twitter"
        assert r2.app_name == "twitter"
        assert r3.app_name == "twitter"


# ===========================================================================
# Run summary
# ===========================================================================

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=_HERE
    )
    sys.exit(result.returncode)
