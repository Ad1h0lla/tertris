"""
Tetris — Milestone 3.3 Test Suite
==================================

Social Distribution Worker — X (Twitter) + LinkedIn Execution & Verification Tests.

Tests:
1.  X: Missing credentials -> BLOCKED (AUTH_REQUIRED)
2.  X: Approval missing / PENDING_APPROVAL -> BLOCKED (APPROVAL_REQUIRED)
3.  X: Invalid action type -> BLOCKED (UNSUPPORTED_ACTION)
4.  X: Empty tweet body -> FAILED
5.  X: Credential sanitization (credentials never leak in errors or receipts)
6.  X: Successful mocked tweet creation + verification (PASS)
7.  X: Tweet created but verification fails -> FAILED (never SUCCESS)
8.  X: Rate limit handling (RATE_LIMITED)
9.  X: Auth failure categorization
10. X: 280 character limit enforcement
11. LI: Missing credentials -> BLOCKED (AUTH_REQUIRED)
12. LI: Approval missing / PENDING_APPROVAL -> BLOCKED (APPROVAL_REQUIRED)
13. LI: Invalid action type -> BLOCKED (UNSUPPORTED_ACTION)
14. LI: Empty post body -> FAILED
15. LI: Credential sanitization
16. LI: Successful mocked LinkedIn post creation
17. LI: LinkedIn API error categorization (401/403/429)
18. LI: Verification status is NOT_TESTED (honest, never faked as PASS)
19. Router: social+twitter dispatches to x_executor
20. Router: social+linkedin dispatches to linkedin_executor
21. Router: platform alias 'x' dispatches correctly
22. Router: unsupported social platform returns BLOCKED
23. M3.1 DistributionAction full compatibility (X)
24. M3.1 DistributionAction full compatibility (LinkedIn)
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from execution.distribution_models import (
    create_distribution_action,
    validate_distribution_action,
    ActionWorker,
    ActionPlatform,
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)
from execution.x_executor import (
    execute_x_action,
    resolve_x_credentials,
    verify_x_tweet,
    persist_x_receipt,
)
from execution.linkedin_executor import (
    execute_linkedin_action,
    resolve_linkedin_credentials,
    publish_linkedin_post,
    create_linkedin_post_payload,
    persist_linkedin_receipt,
)
from execution.execution_router import execute_distribution_action, route_execution


# ===========================================================================
# HELPERS
# ===========================================================================

def _make_x_action(action_type="create_post", approved=True, body="Hello from Tetris!"):
    """Helper: creates a minimal X DistributionAction."""
    action = create_distribution_action(
        worker="social",
        platform="twitter",
        action_type=action_type,
        target={},
        content={"body": body},
    )
    if approved:
        action["approval"]["status"] = ApprovalStatus.APPROVED
    return action


def _make_linkedin_action(action_type="create_post", approved=True, body="Hello from Tetris on LinkedIn!"):
    """Helper: creates a minimal LinkedIn DistributionAction."""
    action = create_distribution_action(
        worker="social",
        platform="linkedin",
        action_type=action_type,
        target={},
        content={"body": body},
    )
    if approved:
        action["approval"]["status"] = ApprovalStatus.APPROVED
    return action


def _mock_tweepy_client(tweet_id="123456789", tweet_text="Hello from Tetris!", verify_success=True):
    """Creates a mock Tweepy client that simulates create_tweet + get_tweet."""
    client = MagicMock()

    # create_tweet response
    tweet_response = MagicMock()
    tweet_response.data = {"id": tweet_id, "text": tweet_text}
    client.create_tweet.return_value = tweet_response

    # get_tweet response (verification)
    if verify_success:
        verify_data = MagicMock()
        verify_data.id = tweet_id
        verify_data.text = tweet_text
        verify_data.created_at = "2026-01-01T00:00:00Z"
        verify_data.author_id = "9999"
        verify_response = MagicMock()
        verify_response.data = verify_data
        client.get_tweet.return_value = verify_response
    else:
        client.get_tweet.return_value = MagicMock(data=None)

    return client


def _mock_linkedin_http_client(success=True, post_id="urn:li:ugcPost:123456", status_code=201, error_body=""):
    """Creates a mock HTTP client for LinkedIn API."""
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = status_code

    if success:
        resp.json.return_value = {"id": post_id}
        resp.text = json.dumps({"id": post_id})
    else:
        resp.json.return_value = {"message": error_body or "Error"}
        resp.text = error_body or "Error"

    client.post.return_value = resp
    return client


# ===========================================================================
# X (TWITTER) TESTS
# ===========================================================================

class TestXCredentials:
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_returns_blocked(self):
        """T1: Missing X credentials -> BLOCKED (AUTH_REQUIRED)"""
        action = _make_x_action()
        result = execute_x_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "AUTH_REQUIRED"
        assert result["verified"] is False
        assert result["status"] != ExecutionStatus.SUCCESS

    def test_credential_sanitization_in_errors(self):
        """T5: Credentials never leak in error messages"""
        mock_client = MagicMock()
        secret_key = "super_secret_api_key_12345"
        secret_access = "super_secret_access_token_secret_67890"
        mock_client.create_tweet.side_effect = Exception(f"Failed with secret {secret_access}")

        action = _make_x_action()
        with patch.dict(os.environ, {
            "X_API_KEY": "key",
            "X_API_SECRET": secret_key,
            "X_ACCESS_TOKEN": "tok",
            "X_ACCESS_TOKEN_SECRET": secret_access,
        }):
            result = execute_x_action(
                action=action,
                tweepy_client_override=mock_client,
            )
        error_str = str(result.get("error", ""))
        # The secrets should NOT appear in the error
        assert secret_access not in error_str
        assert secret_key not in json.dumps(result)


class TestXApprovalGate:
    def test_unapproved_action_returns_blocked(self):
        """T2: PENDING_APPROVAL -> BLOCKED (APPROVAL_REQUIRED)"""
        action = _make_x_action(approved=False)
        result = execute_x_action(action=action, tweepy_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "APPROVAL_REQUIRED"
        assert "PENDING_APPROVAL" in result["error"]

    def test_rejected_action_returns_blocked(self):
        """Rejected actions are also blocked."""
        action = _make_x_action(approved=False)
        action["approval"]["status"] = ApprovalStatus.REJECTED
        result = execute_x_action(action=action, tweepy_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "APPROVAL_REQUIRED"


class TestXActionValidation:
    def test_invalid_action_type_returns_blocked(self):
        """T3: Invalid action type -> BLOCKED (UNSUPPORTED_ACTION)"""
        action = _make_x_action(action_type="reply_to_post")
        result = execute_x_action(action=action, tweepy_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "UNSUPPORTED_ACTION"
        assert "reply_to_post" in result["error"]

    def test_empty_body_returns_failed(self):
        """T4: Empty tweet body -> FAILED"""
        action = _make_x_action(body="")
        result = execute_x_action(action=action, tweepy_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.FAILED
        assert "body" in result["error"].lower() or "text" in result["error"].lower()

    def test_whitespace_only_body_returns_failed(self):
        """Whitespace-only body -> FAILED"""
        action = _make_x_action(body="   \n  ")
        result = execute_x_action(action=action, tweepy_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.FAILED


class TestXExecution:
    def test_successful_tweet_with_verification(self):
        """T6: Successful mocked tweet creation + verification = SUCCESS + PASS"""
        mock_client = _mock_tweepy_client(
            tweet_id="1234567890",
            tweet_text="Test tweet",
            verify_success=True,
        )
        action = _make_x_action(body="Test tweet")
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        assert result["status"] == ExecutionStatus.SUCCESS
        assert result["verified"] is True
        assert result["verification_status"] == VerificationStatus.PASS
        assert result["external_id"] == "1234567890"
        assert "x.com" in result["external_url"]
        assert result["executed_at"] is not None
        mock_client.create_tweet.assert_called_once()

    def test_tweet_created_but_verification_fails(self):
        """T7: Tweet posted but verification fails -> FAILED (never SUCCESS)"""
        mock_client = _mock_tweepy_client(
            tweet_id="9876543210",
            verify_success=False,
        )
        action = _make_x_action()
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        assert result["status"] == ExecutionStatus.FAILED
        assert result["verified"] is not True or result["verification_status"] != VerificationStatus.PASS
        assert result["external_id"] == "9876543210"

    def test_rate_limit_handling(self):
        """T8: Rate limit -> categorized as RATE_LIMITED"""
        mock_client = MagicMock()
        mock_client.create_tweet.side_effect = Exception("429 Too Many Requests - rate limit exceeded")

        action = _make_x_action()
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        assert result["status"] == ExecutionStatus.FAILED
        assert result["reason"] == "RATE_LIMITED"

    def test_auth_failure_categorization(self):
        """T9: Auth failure -> categorized as AUTH_FAILED"""
        mock_client = MagicMock()
        mock_client.create_tweet.side_effect = Exception("401 Unauthorized - invalid token")

        action = _make_x_action()
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "AUTH_FAILED"

    def test_280_character_limit_enforcement(self):
        """T10: Tweet text is truncated to 280 characters"""
        long_body = "A" * 500
        mock_client = _mock_tweepy_client(verify_success=True)
        action = _make_x_action(body=long_body)
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        # The call was made -> check what text was passed
        call_args = mock_client.create_tweet.call_args
        passed_text = call_args[1].get("text") if call_args[1] else call_args[0][0] if call_args[0] else ""
        assert len(passed_text) <= 280


# ===========================================================================
# LINKEDIN TESTS
# ===========================================================================

class TestLinkedInCredentials:
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_returns_blocked(self):
        """T11: Missing LinkedIn credentials -> BLOCKED (AUTH_REQUIRED)"""
        action = _make_linkedin_action()
        result = execute_linkedin_action(action=action)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "AUTH_REQUIRED"
        assert result["verified"] is False

    def test_credential_sanitization(self):
        """T15: LinkedIn credentials never leak in error messages"""
        secret_token = "li_secret_access_token_xyz123"
        mock_http = _mock_linkedin_http_client(success=False, status_code=500, error_body=f"Err {secret_token}")

        action = _make_linkedin_action()
        # Provide credentials via env so the gate passes
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": secret_token, "LINKEDIN_PERSON_ID": "abc123"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)
        
        error_str = str(result.get("error", ""))
        assert secret_token not in error_str


class TestLinkedInApprovalGate:
    def test_unapproved_action_returns_blocked(self):
        """T12: PENDING_APPROVAL -> BLOCKED (APPROVAL_REQUIRED)"""
        action = _make_linkedin_action(approved=False)
        result = execute_linkedin_action(action=action, http_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "APPROVAL_REQUIRED"


class TestLinkedInActionValidation:
    def test_invalid_action_type_returns_blocked(self):
        """T13: Invalid action type -> BLOCKED (UNSUPPORTED_ACTION)"""
        action = _make_linkedin_action(action_type="reply_to_post")
        result = execute_linkedin_action(action=action, http_client_override=MagicMock())
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "UNSUPPORTED_ACTION"

    def test_empty_body_returns_failed(self):
        """T14: Empty post body -> FAILED"""
        action = _make_linkedin_action(body="")
        mock_http = _mock_linkedin_http_client()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)
        assert result["status"] == ExecutionStatus.FAILED


class TestLinkedInExecution:
    def test_successful_linkedin_post(self):
        """T16: Successful mocked LinkedIn post creation = SUCCESS"""
        mock_http = _mock_linkedin_http_client(
            success=True,
            post_id="urn:li:ugcPost:9876543",
            status_code=201,
        )
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "valid_token", "LINKEDIN_PERSON_ID": "person_123"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)

        assert result["status"] == ExecutionStatus.SUCCESS
        assert result["external_id"] == "urn:li:ugcPost:9876543"
        assert "linkedin.com" in result["external_url"]
        assert result["executed_at"] is not None
        mock_http.post.assert_called_once()

    def test_linkedin_api_401_categorization(self):
        """T17a: 401 -> AUTH_FAILED"""
        mock_http = _mock_linkedin_http_client(success=False, status_code=401, error_body="Unauthorized")
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)
        assert result["status"] == ExecutionStatus.BLOCKED
        assert result["reason"] == "AUTH_FAILED"

    def test_linkedin_api_403_categorization(self):
        """T17b: 403 -> PERMISSION_DENIED"""
        mock_http = _mock_linkedin_http_client(success=False, status_code=403, error_body="Forbidden")
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)
        assert result["reason"] == "PERMISSION_DENIED"

    def test_linkedin_api_429_categorization(self):
        """T17c: 429 -> RATE_LIMITED"""
        mock_http = _mock_linkedin_http_client(success=False, status_code=429, error_body="rate limit")
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)
        assert result["reason"] == "RATE_LIMITED"

    def test_verification_status_is_not_tested(self):
        """T18: LinkedIn verification_status is NOT_TESTED (honest, never faked)"""
        mock_http = _mock_linkedin_http_client(success=True, post_id="urn:li:ugcPost:111")
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)

        assert result["status"] == ExecutionStatus.SUCCESS
        assert result["verification_status"] == VerificationStatus.NOT_TESTED
        assert result["verified"] is False  # honest: not verified
        # Receipt should also reflect this
        assert result["receipt"]["verification_status"] == VerificationStatus.NOT_TESTED


# ===========================================================================
# ROUTER DISPATCH TESTS
# ===========================================================================

class TestRouterSocialDispatch:
    def test_social_twitter_dispatches_to_x_executor(self):
        """T19: social+twitter -> x_executor"""
        action = _make_x_action()
        mock_client = _mock_tweepy_client(verify_success=True)
        result = execute_distribution_action(
            action=action,
            tweepy_client_override=mock_client,
        )
        # Should route to X executor and get a structured result
        assert result["platform"] == ActionPlatform.TWITTER
        assert result["worker"] == ActionWorker.SOCIAL
        assert result["status"] == ExecutionStatus.SUCCESS

    def test_social_linkedin_dispatches_to_linkedin_executor(self):
        """T20: social+linkedin -> linkedin_executor"""
        action = _make_linkedin_action()
        mock_http = _mock_linkedin_http_client(success=True)
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_distribution_action(
                action=action,
                http_client_override=mock_http,
            )
        assert result["platform"] == ActionPlatform.LINKEDIN
        assert result["worker"] == ActionWorker.SOCIAL
        assert result["status"] == ExecutionStatus.SUCCESS

    def test_platform_alias_x_dispatches_correctly(self):
        """T21: platform='x' dispatches to X executor"""
        action = create_distribution_action(
            worker="social",
            platform="x",
            action_type="create_post",
            target={},
            content={"body": "Test via x alias"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED

        mock_client = _mock_tweepy_client(verify_success=True)
        result = execute_distribution_action(
            action=action,
            tweepy_client_override=mock_client,
        )
        # x alias should be normalized to twitter by distribution_models
        assert result["status"] == ExecutionStatus.SUCCESS
        assert result["platform"] == ActionPlatform.TWITTER

    def test_unsupported_social_platform_returns_blocked(self):
        """T22: social+mastodon -> BLOCKED (UNSUPPORTED_PLATFORM)"""
        action = create_distribution_action(
            worker="social",
            platform="mastodon",
            action_type="create_post",
            target={},
            content={"body": "Test"},
        )
        action["approval"]["status"] = ApprovalStatus.APPROVED
        result = execute_distribution_action(action=action)
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "UNSUPPORTED_PLATFORM"


# ===========================================================================
# M3.1 CONTRACT COMPATIBILITY TESTS
# ===========================================================================

class TestM31ContractCompatibility:
    def test_x_action_validates_against_m31_contract(self):
        """T23: X DistributionAction passes M3.1 validate_distribution_action"""
        action = _make_x_action()
        assert validate_distribution_action(action) is True
        assert action["phase"] == 3
        assert action["worker"] == ActionWorker.SOCIAL
        assert action["platform"] == ActionPlatform.TWITTER
        assert action["approval"]["status"] in ApprovalStatus.VALID_STATUSES
        assert action["execution"]["status"] in ExecutionStatus.VALID_STATUSES
        assert action["receipt"]["verification_status"] in VerificationStatus.VALID_STATUSES

    def test_linkedin_action_validates_against_m31_contract(self):
        """T24: LinkedIn DistributionAction passes M3.1 validate_distribution_action"""
        action = _make_linkedin_action()
        assert validate_distribution_action(action) is True
        assert action["phase"] == 3
        assert action["worker"] == ActionWorker.SOCIAL
        assert action["platform"] == ActionPlatform.LINKEDIN
        assert action["approval"]["status"] in ApprovalStatus.VALID_STATUSES
        assert action["execution"]["status"] in ExecutionStatus.VALID_STATUSES
        assert action["receipt"]["verification_status"] in VerificationStatus.VALID_STATUSES

    def test_x_receipt_has_required_fields(self):
        """X execution result has all required receipt fields."""
        mock_client = _mock_tweepy_client(verify_success=True)
        action = _make_x_action()
        result = execute_x_action(action=action, tweepy_client_override=mock_client)

        # Required fields from M3.1 contract
        assert "action_id" in result
        assert "execution_id" in result
        assert "phase" in result
        assert result["phase"] == 3
        assert "worker" in result
        assert "platform" in result
        assert "action_type" in result
        assert "approval" in result
        assert "execution" in result
        assert "receipt" in result
        assert "status" in result

    def test_linkedin_receipt_has_required_fields(self):
        """LinkedIn execution result has all required receipt fields."""
        mock_http = _mock_linkedin_http_client(success=True)
        action = _make_linkedin_action()
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": "tok", "LINKEDIN_PERSON_ID": "pid"}):
            result = execute_linkedin_action(action=action, http_client_override=mock_http)

        assert "action_id" in result
        assert "execution_id" in result
        assert result["phase"] == 3
        assert "worker" in result
        assert "platform" in result
        assert "action_type" in result
        assert "approval" in result
        assert "execution" in result
        assert "receipt" in result
        assert "status" in result
