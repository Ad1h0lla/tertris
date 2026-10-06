"""
Tetris — Milestone 3.5 Phase C Test Suite
==========================================

Reddit Provider Abstraction Tests:
1. RedditAPIs search success
2. RedditAPIs authentication failure
3. RedditAPIs timeout/network failure
4. RedditAPIs post blocked when session credentials are missing
5. RedditAPIs comment blocked when session credentials are missing
6. PRAW behavior remains unchanged
7. Provider selection (explicit, no silent fallback)
8. Normalized receipt (consistent receipt format across both providers)
9. No credential leakage (secrets never exposed in errors or receipts)
10. Cross-user credential isolation (user A cannot access user B credentials)
"""

import os
import json
import pytest
import requests
from unittest.mock import MagicMock, patch

from execution.distribution_models import (
    create_distribution_action,
    ActionWorker,
    ActionPlatform,
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)
from execution.reddit_executor import (
    BaseRedditProvider,
    NativeRedditProvider,
    RedditAPIsProvider,
    execute_reddit_action,
    resolve_redditapis_credentials,
    resolve_reddit_credentials,
)


# ===========================================================================
# 1. RedditAPIs Search Success
# ===========================================================================

class TestRedditAPIsSearchSuccess:
    def test_search_success_with_mocked_response(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "posts": [
                {
                    "id": "1oel5ab",
                    "title": "is there any API testing tool better than postman?",
                    "permalink": "/r/webdev/comments/1oel5ab/is_there_any_api_testing_tool_better_than_postman/",
                    "subreddit": "webdev",
                    "author": "dev_user",
                    "upvotes": 42,
                    "comments": 15,
                }
            ],
            "after": "t3_1oel5ab",
        }
        mock_session.get.return_value = mock_resp

        provider = RedditAPIsProvider(
            api_key="test_api_key",
            session=mock_session,
        )

        res = provider.search(query="api", subreddit="webdev", limit=10)

        assert res["success"] is True
        assert res["provider"] == "redditapis"
        assert res["count"] == 1
        assert len(res["posts"]) == 1

        post = res["posts"][0]
        assert post["id"] == "1oel5ab"
        assert post["external_id"] == "t3_1oel5ab"
        assert post["title"] == "is there any API testing tool better than postman?"
        assert post["permalink"].startswith("https://www.reddit.com/r/webdev")
        assert post["subreddit"] == "webdev"
        assert post["score"] == 42


# ===========================================================================
# 2. RedditAPIs Authentication Failure
# ===========================================================================

class TestRedditAPIsAuthFailure:
    def test_search_401_auth_failure(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.ok = False
        mock_resp.json.return_value = {"error": "Invalid API key"}
        mock_session.get.return_value = mock_resp

        provider = RedditAPIsProvider(
            api_key="bad_token_xyz",
            session=mock_session,
        )

        res = provider.search(query="test", subreddit="webdev")

        assert res["success"] is False
        assert res["provider"] == "redditapis"
        assert res["status"] == "AUTH_REQUIRED"
        assert res["reason"] == "AUTH_FAILED"
        assert "bad_token_xyz" not in res["error"]

    def test_search_missing_api_key_blocks_early(self):
        provider = RedditAPIsProvider(api_key=None)
        res = provider.search(query="test")
        assert res["success"] is False
        assert res["status"] == "AUTH_REQUIRED"
        assert res["reason"] == "AUTH_REQUIRED"


# ===========================================================================
# 3. RedditAPIs Timeout / Network Failure
# ===========================================================================

class TestRedditAPIsNetworkFailure:
    def test_timeout_handled_gracefully(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out after 15s")

        provider = RedditAPIsProvider(
            api_key="valid_token",
            session=mock_session,
        )

        res = provider.search(query="test")
        assert res["success"] is False
        assert res["status"] == "FAILED"
        assert res["reason"] == "TIMEOUT"

    def test_connection_error_handled_gracefully(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Failed to resolve host")

        provider = RedditAPIsProvider(
            api_key="valid_token",
            session=mock_session,
        )

        res = provider.search(query="test")
        assert res["success"] is False
        assert res["status"] == "FAILED"
        assert res["reason"] == "NETWORK_ERROR"


# ===========================================================================
# 4. RedditAPIs Post Blocked When Session Missing
# ===========================================================================

class TestRedditAPIsPostBlockedMissingSession:
    def test_direct_provider_create_post_blocked(self):
        # API key exists, but session cookies are missing
        provider = RedditAPIsProvider(
            api_key="valid_bearer_token",
            session_cookies={},
        )

        res = provider.create_post(
            subreddit="test",
            title="My Title",
            text="My Text",
        )

        assert res["success"] is False
        assert res["status"] == "AUTH_REQUIRED"
        assert res["reason"] == "AUTH_REQUIRED"
        assert "session bridge cookies" in res["error"]
        assert res["provider"] == "redditapis"

    def test_worker_action_create_post_blocked_missing_session(self):
        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "Test Title", "body": "Test Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        mock_apis_provider = RedditAPIsProvider(
            api_key="valid_bearer_key",
            session_cookies={},
        )

        receipt = execute_reddit_action(
            action=action,
            provider="redditapis",
            redditapis_provider_override=mock_apis_provider,
        )

        assert receipt["status"] == ExecutionStatus.BLOCKED
        assert receipt["reason"] == "AUTH_REQUIRED"
        assert receipt["provider"] == "redditapis"
        assert receipt["verified"] is False
        assert "session bridge cookies" in receipt["error"]


# ===========================================================================
# 5. RedditAPIs Comment Blocked When Session Missing
# ===========================================================================

class TestRedditAPIsCommentBlockedMissingSession:
    def test_direct_provider_create_comment_blocked(self):
        provider = RedditAPIsProvider(
            api_key="valid_bearer_token",
            session_cookies={},
        )

        res = provider.create_comment(
            post_url_or_id="1oel5ab",
            text="Contextual reply comment",
        )

        assert res["success"] is False
        assert res["status"] == "AUTH_REQUIRED"
        assert res["reason"] == "AUTH_REQUIRED"
        assert "session bridge cookies" in res["error"]
        assert res["provider"] == "redditapis"

    def test_worker_action_reply_blocked_missing_session(self):
        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="reply_to_post",
            target={"post_id": "1oel5ab"},
            content={"body": "Contextual comment text"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        mock_apis_provider = RedditAPIsProvider(
            api_key="valid_bearer_key",
            session_cookies={},
        )

        receipt = execute_reddit_action(
            action=action,
            provider="redditapis",
            redditapis_provider_override=mock_apis_provider,
        )

        assert receipt["status"] == ExecutionStatus.BLOCKED
        assert receipt["reason"] == "AUTH_REQUIRED"
        assert receipt["provider"] == "redditapis"
        assert receipt["verified"] is False
        assert "session bridge cookies" in receipt["error"]


# ===========================================================================
# 6. PRAW Behavior Remains Unchanged
# ===========================================================================

class TestPRAWBehaviorUnchanged:
    def test_praw_create_post_success(self):
        mock_praw = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "prawpost123"
        mock_submission.permalink = "/r/test/comments/prawpost123/title/"
        mock_submission.title = "PRAW Test Title"
        mock_sub.submit.return_value = mock_submission
        mock_praw.subreddit.return_value = mock_sub
        mock_praw.submission.return_value = mock_submission

        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "PRAW Test Title", "body": "PRAW body content"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(
            action=action,
            reddit_client_override=mock_praw,
            provider="praw",
        )

        assert receipt["status"] == ExecutionStatus.SUCCESS
        assert receipt["verified"] is True
        assert receipt["provider"] == "praw"
        assert receipt["external_id"] == "t3_prawpost123"
        assert "https://www.reddit.com/r/test/comments/prawpost123/title/" in receipt["permalink"]

    def test_praw_default_when_provider_unspecified(self):
        mock_praw = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "defaultpost"
        mock_submission.permalink = "/r/test/comments/defaultpost/title/"
        mock_submission.title = "Default Title"
        mock_sub.submit.return_value = mock_submission
        mock_praw.subreddit.return_value = mock_sub
        mock_praw.submission.return_value = mock_submission

        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "Default Title", "body": "Default body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        # Unspecified provider defaults to PRAW
        receipt = execute_reddit_action(
            action=action,
            reddit_client_override=mock_praw,
        )

        assert receipt["status"] == ExecutionStatus.SUCCESS
        assert receipt["provider"] == "praw"


# ===========================================================================
# 7. Provider Selection (Explicit, No Silent Fallback)
# ===========================================================================

class TestProviderSelection:
    def test_unsupported_provider_rejected(self):
        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(
            action=action,
            provider="unknown_provider_xyz",
        )

        assert receipt["status"] == ExecutionStatus.BLOCKED
        assert receipt["reason"] == "UNSUPPORTED_PROVIDER"
        assert "Unsupported Reddit provider" in receipt["error"]

    def test_redditapis_does_not_silently_fallback_to_praw(self):
        mock_praw = MagicMock()

        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        mock_apis_provider = RedditAPIsProvider(
            api_key="valid_token",
            session_cookies={},  # Missing session cookies
        )

        receipt = execute_reddit_action(
            action=action,
            provider="redditapis",
            reddit_client_override=mock_praw,
            redditapis_provider_override=mock_apis_provider,
        )

        # Must report AUTH_REQUIRED under redditapis, NOT fall back to PRAW
        assert receipt["status"] == ExecutionStatus.BLOCKED
        assert receipt["reason"] == "AUTH_REQUIRED"
        assert receipt["provider"] == "redditapis"
        # mock_praw should never have been touched
        assert mock_praw.subreddit.called is False


# ===========================================================================
# 8. Normalized Receipt
# ===========================================================================

class TestNormalizedReceipt:
    REQUIRED_KEYS = {
        "provider",
        "external_id",
        "permalink",
        "action_type",
        "status",
        "verified",
        "created_at",
        "error",
    }

    def test_praw_receipt_normalized(self):
        mock_praw = MagicMock()
        mock_sub = MagicMock()
        mock_submission = MagicMock()
        mock_submission.id = "norm1"
        mock_submission.permalink = "/r/test/comments/norm1/title/"
        mock_submission.title = "Norm Title"
        mock_sub.submit.return_value = mock_submission
        mock_praw.subreddit.return_value = mock_sub
        mock_praw.submission.return_value = mock_submission

        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="create_post",
            target={"community": "test"},
            content={"title": "Norm Title", "body": "Body"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(action=action, reddit_client_override=mock_praw, provider="praw")

        # Top-level contains required keys
        for key in self.REQUIRED_KEYS:
            assert key in receipt, f"Key '{key}' missing from top-level receipt"

        # Inner receipt dict also contains required keys
        inner = receipt["receipt"]
        for key in self.REQUIRED_KEYS:
            assert key in inner, f"Key '{key}' missing from inner receipt"

        assert receipt["provider"] == "praw"
        assert receipt["action_type"] == "create_post"

    def test_redditapis_receipt_normalized(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "success": True,
            "comment_id": "c12345",
            "permalink": "https://www.reddit.com/r/test/comments/xxx/comment/c12345/",
        }
        mock_session.post.return_value = mock_resp

        apis_prov = RedditAPIsProvider(
            api_key="valid_token",
            session_cookies={"reddit_session": "sess_tok", "loid": "loid_tok"},
            session=mock_session,
        )

        action = create_distribution_action(
            worker=ActionWorker.COMMUNITY,
            platform=ActionPlatform.REDDIT,
            action_type="reply_to_post",
            target={"post_id": "xxx"},
            content={"body": "Hello comment"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        receipt = execute_reddit_action(
            action=action,
            provider="redditapis",
            redditapis_provider_override=apis_prov,
        )

        for key in self.REQUIRED_KEYS:
            assert key in receipt, f"Key '{key}' missing from top-level receipt"

        inner = receipt["receipt"]
        for key in self.REQUIRED_KEYS:
            assert key in inner, f"Key '{key}' missing from inner receipt"

        assert receipt["provider"] == "redditapis"
        assert receipt["action_type"] == "reply_to_post"
        assert receipt["status"] == ExecutionStatus.SUCCESS
        assert receipt["verified"] is True
        assert receipt["external_id"] == "t1_c12345"


# ===========================================================================
# 9. No Credential Leakage
# ===========================================================================

class TestNoCredentialLeakage:
    def test_secret_scrubbed_on_error(self):
        secret_key = "super_secret_redditapis_key_999"
        secret_sess = "session_cookie_secret_value_888"

        mock_session = MagicMock()
        mock_session.get.side_effect = Exception(f"Failed with key {secret_key} and sess {secret_sess}")

        provider = RedditAPIsProvider(
            api_key=secret_key,
            session_cookies={"reddit_session": secret_sess},
            session=mock_session,
        )

        res = provider.search(query="test")
        err_msg = res.get("error", "")

        assert secret_key not in err_msg
        assert secret_sess not in err_msg
        assert "[REDACTED]" in err_msg


# ===========================================================================
# 10. Cross-User Credential Isolation
# ===========================================================================

class TestCrossUserIsolation:
    def test_user_credentials_strictly_isolated(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database.models import Base
        from integrations.credential_manager import connect_app

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        user_a = "user_alpha_001"
        user_b = "user_beta_002"

        # Store credentials for User A
        connect_app(
            db=db,
            user_id=user_a,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "user_a_secret_key"}),
            connection_type="api_key",
            display_name="User A RedditAPIs",
        )

        # User A can retrieve User A's credentials
        res_a = resolve_redditapis_credentials(user_id=user_a, db=db)
        assert res_a["api_key"] == "user_a_secret_key"

        # User B queries DB with no environment fallback interference
        with patch.dict(os.environ, {}, clear=True):
            res_b = resolve_redditapis_credentials(user_id=user_b, db=db)
            assert res_b["api_key"] is None

        # Now connect User B with different key
        connect_app(
            db=db,
            user_id=user_b,
            app_name="redditapis",
            raw_credential=json.dumps({"api_key": "user_b_secret_key"}),
            connection_type="api_key",
            display_name="User B RedditAPIs",
        )

        res_b2 = resolve_redditapis_credentials(user_id=user_b, db=db)
        assert res_b2["api_key"] == "user_b_secret_key"
        # User A's key remains completely unchanged
        assert resolve_redditapis_credentials(user_id=user_a, db=db)["api_key"] == "user_a_secret_key"

        db.close()
