"""
Tetris — X (Twitter) Social Distribution Worker
=================================================

Executes authorized social distribution actions on X/Twitter via the Tweepy library.

Supported Action Types:
- create_post : Publishes a tweet

Lifecycle & Contracts:
- PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY
- Hard Gate: Only executes if approval.status == "APPROVED"
- Never returns SUCCESS without verified external Twitter object
- Credentials resolved via:
    1. StoredCredential / credential manager
    2. Vault
    3. Environment variables (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN)
- Missing/invalid credentials return status = "BLOCKED", reason = "AUTH_REQUIRED"
"""

from typing import Dict, Any, Optional
import os
import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from execution.distribution_models import (
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
    ActionWorker,
    ActionPlatform,
)

load_dotenv()
logger = logging.getLogger(__name__)


def resolve_x_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[str]]:
    """
    Resolves X/Twitter credentials in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables

    Returns a dict with keys: api_key, api_secret, access_token, access_token_secret, bearer_token.
    """
    api_key = None
    api_secret = None
    access_token = None
    access_token_secret = None
    bearer_token = None

    # 1. Check DB StoredCredential
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "twitter")
            if cred_str:
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        api_key = cred_json.get("api_key")
                        api_secret = cred_json.get("api_secret")
                        access_token = cred_json.get("access_token")
                        access_token_secret = cred_json.get("access_token_secret")
                        bearer_token = cred_json.get("bearer_token")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"DB credential retrieval note: {e}")

    # 2. Check Vault
    if not (api_key and api_secret and access_token and access_token_secret):
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "twitter")
            if vault_cred:
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        api_key = api_key or cred_json.get("api_key")
                        api_secret = api_secret or cred_json.get("api_secret")
                        access_token = access_token or cred_json.get("access_token")
                        access_token_secret = access_token_secret or cred_json.get("access_token_secret")
                        bearer_token = bearer_token or cred_json.get("bearer_token")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Vault retrieval note: {e}")

    # 3. Fallback to Environment Variables
    api_key = api_key or os.getenv("X_API_KEY", "").strip() or None
    api_secret = api_secret or os.getenv("X_API_SECRET", "").strip() or None
    access_token = access_token or os.getenv("X_ACCESS_TOKEN", "").strip() or None
    access_token_secret = access_token_secret or os.getenv("X_ACCESS_TOKEN_SECRET", "").strip() or None
    bearer_token = bearer_token or os.getenv("X_BEARER_TOKEN", "").strip() or None

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": access_token,
        "access_token_secret": access_token_secret,
        "bearer_token": bearer_token,
    }


def initialize_tweepy_client(credentials: Dict[str, Optional[str]]):
    """Initializes and returns a Tweepy Client (v2 API)."""
    import tweepy

    return tweepy.Client(
        consumer_key=credentials.get("api_key"),
        consumer_secret=credentials.get("api_secret"),
        access_token=credentials.get("access_token"),
        access_token_secret=credentials.get("access_token_secret"),
        bearer_token=credentials.get("bearer_token"),
        wait_on_rate_limit=False,
    )


def verify_x_tweet(tweepy_client, tweet_id: str) -> Dict[str, Any]:
    """
    Verifies that a created tweet actually exists on X by retrieving it via the API.
    """
    try:
        clean_id = str(tweet_id).strip()
        response = tweepy_client.get_tweet(
            id=clean_id,
            tweet_fields=["id", "text", "created_at", "author_id"],
        )
        if response and response.data:
            tweet_data = response.data
            tweet_url = f"https://x.com/i/status/{tweet_data.id}"
            return {
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": str(tweet_data.id),
                "external_url": tweet_url,
                "text": tweet_data.text[:280] if tweet_data.text else "",
            }
        else:
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": "Tweet retrieved but response data was empty",
            }
    except Exception as e:
        clean_err = str(e)[:200]
        return {
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "error": f"Verification failed: {clean_err}",
        }


def persist_x_receipt(receipt: Dict[str, Any], db=None, user_id: str = "user_001"):
    """
    Persists the executed X/Twitter action receipt into the SQLite database.
    Reuses the ConnectorAction model via save_connector_action.
    """
    close_db_at_end = False
    if db is None:
        try:
            from database.models import SessionLocal
            db = SessionLocal()
            close_db_at_end = True
        except Exception:
            return

    try:
        from database.models import ConnectorAction, PhaseResult
        from database.operations import save_connector_action

        action_id = receipt.get("action_id")
        exec_id = receipt.get("execution_id", "")
        action_name = receipt.get("action_type", "create_post")
        status = receipt.get("status", "SUCCESS")
        error_msg = receipt.get("error")

        save_connector_action(
            db=db,
            user_id=user_id,
            execution_id=exec_id,
            connector_id="twitter",
            action=action_name,
            status=status,
            result=receipt,
            error=error_msg,
            action_id=action_id,
        )

        # Update PhaseResult distribution_plan if this execution_id exists
        if exec_id:
            phase_res = (
                db.query(PhaseResult)
                .filter(PhaseResult.execution_id == exec_id, PhaseResult.phase_number == 3)
                .first()
            )
            if phase_res and phase_res.distribution_plan:
                plan = dict(phase_res.distribution_plan)
                actions = list(plan.get("actions", []))
                updated = False
                for idx, act in enumerate(actions):
                    if act.get("action_id") == action_id or (act.get("platform") == "twitter" and act.get("action_type") == action_name):
                        actions[idx]["execution"] = {"status": status}
                        actions[idx]["receipt"] = receipt.get("receipt", {})
                        actions[idx]["executed_at"] = receipt.get("executed_at")
                        actions[idx]["error"] = error_msg
                        updated = True
                        break
                if updated:
                    plan["actions"] = actions
                    phase_res.distribution_plan = plan
                    db.commit()

    except Exception as e:
        logger.debug(f"Persistence note: {e}")
    finally:
        if close_db_at_end and db:
            db.close()


def execute_x_action(
    action: Dict[str, Any],
    user_id: str = "user_001",
    db=None,
    tweepy_client_override=None,
) -> Dict[str, Any]:
    """
    Executes a single proposed X/Twitter DistributionAction with full lifecycle verification.

    Parameters
    ----------
    action : dict
        The DistributionAction dictionary adhering to M3.1 contract.
    user_id : str
        The owning user ID.
    db : Session, optional
        Database session for credential lookup and receipt persistence.
    tweepy_client_override : optional
        Tweepy Client instance for testing/mocking.

    Returns
    -------
    dict
        Structured action receipt with execution status, verification, and external identifiers.
    """
    action_id = action.get("action_id", "")
    exec_id = action.get("execution_id", "")
    action_type = action.get("action_type", "")
    target = action.get("target") or {}
    content = action.get("content") or {}
    approval = action.get("approval") or {}
    now_iso = datetime.now(timezone.utc).isoformat()

    base_receipt = {
        "action_id": action_id,
        "execution_id": exec_id,
        "phase": 3,
        "worker": ActionWorker.SOCIAL,
        "platform": ActionPlatform.TWITTER,
        "action_type": action_type,
        "target": target,
        "content": content,
        "approval": approval,
        "execution": {"status": ExecutionStatus.NOT_STARTED},
        "receipt": {
            "verified": False,
            "verification_status": VerificationStatus.NOT_TESTED,
            "external_id": None,
            "external_url": None,
        },
        "created_at": action.get("created_at") or now_iso,
        "executed_at": None,
        "error": None,
        "status": ExecutionStatus.NOT_STARTED,
        "verified": False,
        "verification_status": VerificationStatus.NOT_TESTED,
        "external_id": None,
        "external_url": None,
    }

    # ---------------------------------------------------------------
    # 1. Validate Action Type
    # ---------------------------------------------------------------
    if action_type not in ("create_post",):
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Unsupported X action type: '{action_type}'. Only 'create_post' is supported."
        base_receipt["reason"] = "UNSUPPORTED_ACTION"
        return base_receipt

    # ---------------------------------------------------------------
    # 2. Approval Gate
    # ---------------------------------------------------------------
    approval_status = approval.get("status") if isinstance(approval, dict) else None
    approval_required = approval.get("required", True) if isinstance(approval, dict) else True

    if approval_required and approval_status != ApprovalStatus.APPROVED:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Approval required before execution. Current status: '{approval_status or 'PENDING_APPROVAL'}'."
        base_receipt["reason"] = "APPROVAL_REQUIRED"
        return base_receipt

    # ---------------------------------------------------------------
    # 3. Credential Resolution & Validation
    # ---------------------------------------------------------------
    credentials = resolve_x_credentials(user_id=user_id, db=db)
    has_creds = bool(
        credentials.get("api_key")
        and credentials.get("api_secret")
        and credentials.get("access_token")
        and credentials.get("access_token_secret")
    )

    if not has_creds and tweepy_client_override is None:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = "X/Twitter credentials missing or incomplete (requires api_key, api_secret, access_token, access_token_secret)."
        base_receipt["reason"] = "AUTH_REQUIRED"
        if exec_id:
            persist_x_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 4. Content Payload Validation
    # ---------------------------------------------------------------
    body = content.get("body") or content.get("text") or content.get("tweet") or ""

    if not body or not body.strip():
        base_receipt["execution"]["status"] = ExecutionStatus.FAILED
        base_receipt["status"] = ExecutionStatus.FAILED
        base_receipt["error"] = "Content 'body' (or 'text'/'tweet') is required and cannot be empty for create_post."
        if exec_id:
            persist_x_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # Enforce 280 character limit
    tweet_text = body.strip()[:280]

    # ---------------------------------------------------------------
    # 5. Initialize Client & Execute via Tweepy
    # ---------------------------------------------------------------
    try:
        client = tweepy_client_override or initialize_tweepy_client(credentials)
    except Exception as e:
        clean_err = str(e)[:200]
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Failed to initialize X/Twitter client: {clean_err}"
        base_receipt["reason"] = "AUTH_FAILED"
        return base_receipt

    executed_at_iso = datetime.now(timezone.utc).isoformat()
    base_receipt["executed_at"] = executed_at_iso

    try:
        response = client.create_tweet(text=tweet_text)

        if response and response.data:
            tweet_id = str(response.data["id"])
            tweet_url = f"https://x.com/i/status/{tweet_id}"

            # Step 6: Verify External Object
            verif = verify_x_tweet(client, tweet_id)
            if verif.get("verified"):
                base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
                base_receipt["status"] = ExecutionStatus.SUCCESS
                base_receipt["receipt"] = {
                    "verified": True,
                    "verification_status": VerificationStatus.PASS,
                    "external_id": tweet_id,
                    "external_url": tweet_url,
                }
                base_receipt["external_id"] = tweet_id
                base_receipt["external_url"] = tweet_url
                base_receipt["verified"] = True
                base_receipt["verification_status"] = VerificationStatus.PASS
            else:
                base_receipt["execution"]["status"] = ExecutionStatus.FAILED
                base_receipt["status"] = ExecutionStatus.FAILED
                base_receipt["error"] = f"Tweet posted but verification failed: {verif.get('error')}"
                base_receipt["receipt"] = {
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "external_id": tweet_id,
                    "external_url": tweet_url,
                }
                base_receipt["external_id"] = tweet_id
                base_receipt["external_url"] = tweet_url
        else:
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "X API returned empty response data after create_tweet."

    except Exception as exc:
        err_str = str(exc)
        clean_err = err_str[:300]
        # Sanitize any accidental secret exposure
        for sec in [credentials.get("api_secret"), credentials.get("access_token_secret")]:
            if sec and sec in clean_err:
                clean_err = clean_err.replace(sec, "[REDACTED]")

        status = ExecutionStatus.FAILED
        reason = "EXECUTION_ERROR"

        # Categorize common errors
        err_lower = clean_err.lower()
        if "401" in err_lower or "unauthorized" in err_lower or "invalid" in err_lower and "token" in err_lower:
            status = ExecutionStatus.BLOCKED
            reason = "AUTH_FAILED"
            clean_err = "X/Twitter authentication failed. Check credentials."
        elif "403" in err_lower or "forbidden" in err_lower or "suspended" in err_lower:
            reason = "PERMISSION_DENIED"
            clean_err = "X/Twitter permission denied or account suspended."
        elif "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            reason = "RATE_LIMITED"
            clean_err = "X/Twitter rate limit reached. Please wait before retrying."
        elif "timeout" in err_lower:
            reason = "TIMEOUT"
            clean_err = "X/Twitter API request timed out."
        elif "duplicate" in err_lower:
            reason = "DUPLICATE_CONTENT"
            clean_err = "X/Twitter rejected duplicate tweet content."

        base_receipt["execution"]["status"] = status
        base_receipt["status"] = status
        base_receipt["error"] = clean_err
        base_receipt["reason"] = reason

    # ---------------------------------------------------------------
    # 7. Persist Receipt
    # ---------------------------------------------------------------
    persist_x_receipt(base_receipt, db=db, user_id=user_id)

    return base_receipt
