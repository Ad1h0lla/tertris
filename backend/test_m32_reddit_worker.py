"""
Tetris — Milestone 3.2 Test Suite
=================================

Community Distribution Worker — Reddit Execution & Verification Tests.

Tests:
1. Missing credentials -> BLOCKED (AUTH_REQUIRED)
2. Approval missing / PENDING_APPROVAL -> BLOCKED (APPROVAL_REQUIRED)
3. Invalid action type -> BLOCKED (UNSUPPORTED_ACTION)
4. Invalid subreddit -> bounded failure
5. create_post payload validation (missing title or body)
6. reply_to_post payload validation (missing thread ID or body)
7. Credential sanitization (credentials never leak in errors or receipts)
8. Successful mocked PRAW submission parsing
9. External ID extraction (t3_ for post, t1_ for comment)
10. Permalink extraction and URL formatting
11. Verification success (PASS)
12. Verification failure (FAIL -> FAILED, never SUCCESS)
13. Rate limit handling (RATE_LIMITED)
14. Database persistence via ConnectorAction
15. Execution router dispatch (execute_distribution_action)
16. M3.1 DistributionAction full compatibility
"""

import os
import json
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
from execution.reddit_executor import (
    execute_reddit_action,
    post_to_reddit,
    resolve_reddit_credentials,
    _clean_subreddit_name,
    _clean_thread_id,
    verify_reddit_submission,
    verify_reddit_comment,
    persist_reddit_receipt,
)
from execution.execution_router import execute_distribution_action, route_execution


# ===========================================================================
# 1. Credential Resolution & Guards
# ===========================================================================

class TestRedditCredentials:
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_returns_blocked(self):
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Test Title", "body": "Test Body"},
        )
        # Mark approved so approval gate passes
        action["approval"]["status"] = ApprovalStatus.APPROVED

        result = execute_reddit_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "AUTH_REQUIRED"
        assert result["verified"] is False
        assert result["status"] != ExecutionStatus.SUCCESS

    def test_credential_sanitization_in_errors(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        secret_password = "super_secret_password_12345"
        mock_sub.submit.side_effect = Exception(f"Failed with pass {secret_password}")
        mock_client.subreddit.return_value = mock_sub

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Test", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        with patch("execution.reddit_executor.resolve_reddit_credentials") as mock_creds:
            mock_creds.return_value = {
                "client_id": "test_id",
                "client_secret": "test_secret",
                "username": "test_user",
                "password": secret_password,
                "user_agent": "test_agent",
            }
            result = execute_reddit_action(action=action, reddit_client_override=mock_client)

            assert result["status"] == ExecutionStatus.FAILED
            assert secret_password not in result.get("error", "")
            assert "[REDACTED]" in result.get("error", "") or secret_password not in str(result)


# ===========================================================================
# 2. Approval Gate Tests
# ===========================================================================

class TestApprovalGate:
    def test_pending_approval_blocks_execution(self):
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/productivity"},
            content={"title": "Title", "body": "Body"},
        )
        # Default is PENDING_APPROVAL
        assert action["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL

        result = execute_reddit_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "APPROVAL_REQUIRED"
        assert "Approval required" in result["error"]
        assert result["verified"] is False

    def test_rejected_approval_blocks_execution(self):
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/productivity"},
            content={"title": "Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.REJECTED

        result = execute_reddit_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "APPROVAL_REQUIRED"


# ===========================================================================
# 3. Action Type & Payload Validation Tests
# ===========================================================================

class TestPayloadValidation:
    def test_unsupported_action_type_blocked(self):
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="mass_spam_dm",
            target={"community": "r/test"},
            content={"title": "Spam", "body": "Spam"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        result = execute_reddit_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "UNSUPPORTED_ACTION"
        assert "Unsupported Reddit action type" in result["error"]

    def test_create_post_missing_title_fails(self):
        mock_client = MagicMock()
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/saas"},
            content={"title": "", "body": "Some body content"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        result = execute_reddit_action(action=action, reddit_client_override=mock_client)
        assert result["status"] == ExecutionStatus.FAILED
        assert "title" in result["error"].lower()

    def test_create_post_missing_body_fails(self):
        mock_client = MagicMock()
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/saas"},
            content={"title": "Good Title", "body": ""},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        result = execute_reddit_action(action=action, reddit_client_override=mock_client)
        assert result["status"] == ExecutionStatus.FAILED
        assert "body" in result["error"].lower()

    def test_reply_to_post_missing_thread_id_fails(self):
        mock_client = MagicMock()
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="reply_to_post",
            target={"community": "r/saas", "context_thread_id": ""},
            content={"body": "Helpful comment reply"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        result = execute_reddit_action(action=action, reddit_client_override=mock_client)
        assert result["status"] == ExecutionStatus.FAILED
        assert "thread id" in result["error"].lower()


# ===========================================================================
# 4. Helper & Cleaning Functions
# ===========================================================================

class TestHelpers:
    def test_clean_subreddit_name(self):
        assert _clean_subreddit_name("r/productivity") == "productivity"
        assert _clean_subreddit_name("/r/startups/") == "startups"
        assert _clean_subreddit_name("  r/webdev  ") == "webdev"
        assert _clean_subreddit_name("technology") == "technology"

    def test_clean_thread_id(self):
        assert _clean_thread_id("t3_1abc23") == "1abc23"
        assert _clean_thread_id("t1_9xyz87") == "9xyz87"
        assert _clean_thread_id("https://www.reddit.com/r/saas/comments/1ol6p0t/title/") == "1ol6p0t"
        assert _clean_thread_id("1ol6p0t") == "1ol6p0t"


# ===========================================================================
# 5. Successful Execution & Mocked PRAW Verification
# ===========================================================================

class TestSuccessfulExecution:
    def test_create_post_success_and_verification(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "1j1x4ol"
        mock_submission.title = "How to automate competitor pricing intelligence"
        mock_submission.permalink = "/r/ProductivityApps/comments/1j1x4ol/how_to_automate/"
        mock_sub.submit.return_value = mock_submission
        mock_client.subreddit.return_value = mock_sub
        mock_client.submission.return_value = mock_submission

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/ProductivityApps"},
            content={
                "title": "How to automate competitor pricing intelligence",
                "body": "Detailed breakdown of using automated scanning agents...",
            },
            execution_id="exec-m32-test",
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_client)

        assert receipt["status"] == ExecutionStatus.SUCCESS
        assert receipt["external_id"] == "t3_1j1x4ol"
        assert receipt["external_url"] == "https://www.reddit.com/r/ProductivityApps/comments/1j1x4ol/how_to_automate/"
        assert receipt["verified"] is True
        assert receipt["receipt"]["verification_status"] == VerificationStatus.PASS
        assert receipt["executed_at"] is not None
        assert receipt["error"] is None

    def test_reply_to_post_success_and_verification(self):
        mock_client = MagicMock()
        mock_parent_sub = MagicMock()
        mock_comment = MagicMock()
        mock_comment.id = "m987xyz"
        mock_comment.body = "Great point. We solved this by adding continuous sync hooks."
        mock_comment.permalink = "/r/saas/comments/1ol6p0t/title/m987xyz/"
        mock_parent_sub.reply.return_value = mock_comment
        mock_client.submission.return_value = mock_parent_sub
        mock_client.comment.return_value = mock_comment

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="reply_to_post",
            target={"community": "r/saas", "context_thread_id": "1ol6p0t"},
            content={"body": "Great point. We solved this by adding continuous sync hooks."},
            execution_id="exec-m32-reply",
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_client)

        assert receipt["status"] == ExecutionStatus.SUCCESS
        assert receipt["external_id"] == "t1_m987xyz"
        assert receipt["external_url"] == "https://www.reddit.com/r/saas/comments/1ol6p0t/title/m987xyz/"
        assert receipt["verified"] is True
        assert receipt["receipt"]["verification_status"] == VerificationStatus.PASS


# ===========================================================================
# 6. Verification Failure Guard (Never Fake Success)
# ===========================================================================

class TestVerificationFailureGuard:
    def test_failed_verification_does_not_return_success(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "bad_id_123"
        mock_submission.permalink = "/r/test/comments/bad_id_123/"
        mock_sub.submit.return_value = mock_submission
        mock_client.subreddit.return_value = mock_sub

        # Verification fails: fetching submission raises NotFound
        mock_client.submission.side_effect = Exception("404 Not Found on Reddit")

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Test Title", "body": "Test Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_client)

        # HARD RULE: Must be FAILED, NEVER SUCCESS
        assert receipt["status"] != ExecutionStatus.SUCCESS
        assert receipt["status"] == ExecutionStatus.FAILED
        assert receipt["verified"] is False
        assert receipt["receipt"]["verification_status"] == VerificationStatus.FAIL
        assert "Verification failed" in receipt["error"]


# ===========================================================================
# 7. Rate Limits & Network Errors
# ===========================================================================

class TestErrorHandling:
    def test_rate_limit_error_handled(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_sub.submit.side_effect = Exception("429 Too Many Requests: Ratelimit reached, try again in 5 minutes")
        mock_client.subreddit.return_value = mock_sub

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_client)
        assert receipt["status"] == ExecutionStatus.FAILED
        assert receipt["reason"] == "RATE_LIMITED"
        assert "rate limit" in receipt["error"].lower()

    def test_subreddit_not_found_handled(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_sub.submit.side_effect = Exception("404 Subreddit not found")
        mock_client.subreddit.return_value = mock_sub

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/nonexistent_community_999999"},
            content={"title": "Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_client)
        assert receipt["status"] == ExecutionStatus.FAILED
        assert receipt["reason"] == "SUBREDDIT_NOT_FOUND"


# ===========================================================================
# 8. Persistence & Router Integration Tests
# ===========================================================================

class TestPersistenceAndRouter:
    def test_receipt_persisted_in_database(self):
        from database.models import SessionLocal, init_db, ConnectorAction
        from database.operations import get_connector_actions
        import uuid

        init_db()
        db = SessionLocal()
        test_exec_id = f"exec-test-{uuid.uuid4()}"

        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "persist123"
        mock_submission.title = "Persistence Test Post"
        mock_submission.permalink = "/r/test/comments/persist123/test/"
        mock_sub.submit.return_value = mock_submission
        mock_client.subreddit.return_value = mock_sub
        mock_client.submission.return_value = mock_submission

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Persistence Test Post", "body": "Body content..."},
            execution_id=test_exec_id,
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        try:
            receipt = execute_reddit_action(action=action, db=db, reddit_client_override=mock_client)
            assert receipt["status"] == ExecutionStatus.SUCCESS

            # Check database for persisted ConnectorAction
            actions = get_connector_actions(db, test_exec_id)
            assert len(actions) >= 1
            saved = actions[0]
            assert saved.connector_id == "reddit"
            assert saved.action == "create_post"
            assert saved.status == "SUCCESS"
            assert saved.result["external_id"] == "t3_persist123"
        finally:
            db.close()

    def test_execution_router_dispatch(self):
        mock_client = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "router123"
        mock_submission.title = "Router Test"
        mock_submission.permalink = "/r/test/comments/router123/router/"
        mock_sub.submit.return_value = mock_submission
        mock_client.subreddit.return_value = mock_sub
        mock_client.submission.return_value = mock_submission

        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/test"},
            content={"title": "Router Test", "body": "Test via execution router"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED
        result = execute_distribution_action(action, reddit_client_override=mock_client)
        assert result["status"] == ExecutionStatus.SUCCESS
        assert result["external_id"] == "t3_router123"
