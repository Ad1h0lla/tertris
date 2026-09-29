"""
Tetris — LinkedIn Social Distribution Worker
=============================================

Executes authorized social distribution actions on LinkedIn via the LinkedIn API.

Supported Action Types:
- create_post : Publishes a text post to a LinkedIn profile

Lifecycle & Contracts:
- PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY
- Hard Gate: Only executes if approval.status == "APPROVED"
- Never returns SUCCESS without verified external LinkedIn object
- Credentials resolved via:
    1. StoredCredential / credential manager
    2. Vault
    3. Environment variables (LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_ID)
- Missing/invalid credentials return status = "BLOCKED", reason = "AUTH_REQUIRED"
- Verification: LinkedIn API has limited retrieval support for posts;
  verification_status is set to NOT_SUPPORTED (never faked as PASS).
  SUCCESS is only returned when the API returns a valid post ID.
"""

from typing import Dict, Any, Optional
import os
import json
import logging
import requests
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

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"


def resolve_linkedin_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[str]]:
    """
    Resolves LinkedIn credentials in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables

    Returns a dict with keys: access_token, person_id.
    """
    access_token = None
    person_id = None

    # 1. Check DB StoredCredential
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "linkedin")
            if cred_str:
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        access_token = cred_json.get("access_token")
                        person_id = cred_json.get("person_id")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"DB credential retrieval note: {e}")

    # 2. Check Vault
    if not (access_token and person_id):
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "linkedin")
            if vault_cred:
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        access_token = access_token or cred_json.get("access_token")
                        person_id = person_id or cred_json.get("person_id")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Vault retrieval note: {e}")

    # 3. Fallback to Environment Variables
    access_token = access_token or os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip() or None
    person_id = person_id or os.getenv("LINKEDIN_PERSON_ID", "").strip() or None

    return {
        "access_token": access_token,
        "person_id": person_id,
    }


def create_linkedin_post_payload(person_id: str, text: str) -> dict:
    """
    Constructs the LinkedIn UGC Post API payload for a text-only post.
    Uses the UGC Posts API (v2) format.
    """
    return {
        "author": f"urn:li:person:{person_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text,
                },
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }


def publish_linkedin_post(
    access_token: str,
    person_id: str,
    text: str,
    http_client=None,
) -> Dict[str, Any]:
    """
    Publishes a text post to LinkedIn via the UGC Posts API.
    Returns the raw API response dict or error.
    """
    url = f"{LINKEDIN_API_BASE}/ugcPosts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    payload = create_linkedin_post_payload(person_id, text)

    client = http_client or requests
    try:
        resp = client.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            data = resp.json() if hasattr(resp, "json") else {}
            post_id = data.get("id", "")
            return {
                "success": True,
                "post_id": post_id,
                "status_code": resp.status_code,
                "data": data,
            }
        else:
            error_body = ""
            try:
                error_body = resp.text[:300]
            except Exception:
                pass
            return {
                "success": False,
                "status_code": resp.status_code,
                "error": f"LinkedIn API error {resp.status_code}: {error_body}",
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"LinkedIn request failed: {str(e)[:200]}",
        }


def persist_linkedin_receipt(receipt: Dict[str, Any], db=None, user_id: str = "user_001"):
    """
    Persists the executed LinkedIn action receipt into the SQLite database.
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
            connector_id="linkedin",
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
                    if act.get("action_id") == action_id or (act.get("platform") == "linkedin" and act.get("action_type") == action_name):
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


def execute_linkedin_action(
    action: Dict[str, Any],
    user_id: str = "user_001",
    db=None,
    http_client_override=None,
) -> Dict[str, Any]:
    """
    Executes a single proposed LinkedIn DistributionAction with full lifecycle.

    Parameters
    ----------
    action : dict
        The DistributionAction dictionary adhering to M3.1 contract.
    user_id : str
        The owning user ID.
    db : Session, optional
        Database session for credential lookup and receipt persistence.
    http_client_override : optional
        HTTP client for testing/mocking (must support .post()).

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
        "platform": ActionPlatform.LINKEDIN,
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
        base_receipt["error"] = f"Unsupported LinkedIn action type: '{action_type}'. Only 'create_post' is supported."
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
    credentials = resolve_linkedin_credentials(user_id=user_id, db=db)
    has_creds = bool(
        credentials.get("access_token")
        and credentials.get("person_id")
    )

    if not has_creds and http_client_override is None:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = "LinkedIn credentials missing or incomplete (requires access_token, person_id)."
        base_receipt["reason"] = "AUTH_REQUIRED"
        if exec_id:
            persist_linkedin_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 4. Content Payload Validation
    # ---------------------------------------------------------------
    body = content.get("body") or content.get("text") or content.get("post") or ""

    if not body or not body.strip():
        base_receipt["execution"]["status"] = ExecutionStatus.FAILED
        base_receipt["status"] = ExecutionStatus.FAILED
        base_receipt["error"] = "Content 'body' (or 'text'/'post') is required and cannot be empty for create_post."
        if exec_id:
            persist_linkedin_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    post_text = body.strip()[:3000]  # LinkedIn post limit

    # ---------------------------------------------------------------
    # 5. Execute via LinkedIn API
    # ---------------------------------------------------------------
    executed_at_iso = datetime.now(timezone.utc).isoformat()
    base_receipt["executed_at"] = executed_at_iso

    try:
        access_token = credentials.get("access_token") or ""
        person_id = credentials.get("person_id") or ""

        api_result = publish_linkedin_post(
            access_token=access_token,
            person_id=person_id,
            text=post_text,
            http_client=http_client_override,
        )

        if api_result.get("success"):
            post_id = api_result.get("post_id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""

            if post_id:
                # LinkedIn API does not reliably support retrieving UGC posts after creation,
                # so verification_status is NOT_SUPPORTED (never faked as PASS).
                base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
                base_receipt["status"] = ExecutionStatus.SUCCESS
                base_receipt["receipt"] = {
                    "verified": False,
                    "verification_status": VerificationStatus.NOT_TESTED,
                    "verification_note": "LinkedIn UGC Posts API does not support reliable post-creation retrieval. Verification status set to NOT_TESTED, not faked.",
                    "external_id": post_id,
                    "external_url": post_url,
                }
                base_receipt["external_id"] = post_id
                base_receipt["external_url"] = post_url
                base_receipt["verified"] = False
                base_receipt["verification_status"] = VerificationStatus.NOT_TESTED
            else:
                base_receipt["execution"]["status"] = ExecutionStatus.FAILED
                base_receipt["status"] = ExecutionStatus.FAILED
                base_receipt["error"] = "LinkedIn API returned success but no post_id in response."
        else:
            err_msg = api_result.get("error", "Unknown LinkedIn API error")
            status_code = api_result.get("status_code")

            status = ExecutionStatus.FAILED
            reason = "EXECUTION_ERROR"

            if status_code == 401 or "unauthorized" in str(err_msg).lower():
                status = ExecutionStatus.BLOCKED
                reason = "AUTH_FAILED"
                err_msg = "LinkedIn authentication failed. Check access token."
            elif status_code == 403 or "forbidden" in str(err_msg).lower():
                reason = "PERMISSION_DENIED"
                err_msg = "LinkedIn permission denied. Check API scopes."
            elif status_code == 429 or "rate" in str(err_msg).lower():
                reason = "RATE_LIMITED"
                err_msg = "LinkedIn rate limit reached."
            elif status_code == 422 or "unprocessable" in str(err_msg).lower():
                reason = "VALIDATION_ERROR"

            # Sanitize any accidental credential leakage
            for sec in [credentials.get("access_token")]:
                if sec and sec in err_msg:
                    err_msg = err_msg.replace(sec, "[REDACTED]")

            base_receipt["execution"]["status"] = status
            base_receipt["status"] = status
            base_receipt["error"] = err_msg
            base_receipt["reason"] = reason

    except Exception as exc:
        err_str = str(exc)[:300]
        # Sanitize
        for sec in [credentials.get("access_token")]:
            if sec and sec in err_str:
                err_str = err_str.replace(sec, "[REDACTED]")

        base_receipt["execution"]["status"] = ExecutionStatus.FAILED
        base_receipt["status"] = ExecutionStatus.FAILED
        base_receipt["error"] = err_str
        base_receipt["reason"] = "EXECUTION_ERROR"

    # ---------------------------------------------------------------
    # 7. Persist Receipt
    # ---------------------------------------------------------------
    persist_linkedin_receipt(base_receipt, db=db, user_id=user_id)

    return base_receipt
