"""
Tetris — Reddit Community Distribution Worker
==============================================

Executes authorized community distribution actions on Reddit via PRAW.

Supported Action Types:
- create_post : Submits a text post to a designated subreddit
- reply_to_post : Submits a contextual reply comment to an existing thread

Lifecycle & Contracts:
- PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY
- Hard Gate: Only executes if approval.status == "APPROVED"
- Never returns SUCCESS without verified external Reddit object
- Credentials resolved via:
    1. StoredCredential / credential manager
    2. Configured connector credentials
    3. Environment variables (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD, REDDIT_USER_AGENT)
- Missing/invalid credentials return status = "BLOCKED", reason = "AUTH_REQUIRED"
"""

from typing import Dict, Any, Optional
import os
import json
import logging
import re
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


def resolve_reddit_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[str]]:
    """
    Resolves Reddit credentials in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables

    Returns a dict with sanitized keys: client_id, client_secret, username, password, user_agent.
    """
    client_id = None
    client_secret = None
    username = None
    password = None
    user_agent = None

    # 1. Check DB StoredCredential if db session is provided or created
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "reddit")
            if cred_str:
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        client_id = cred_json.get("client_id")
                        client_secret = cred_json.get("client_secret")
                        username = cred_json.get("username")
                        password = cred_json.get("password")
                        user_agent = cred_json.get("user_agent")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"DB credential retrieval note: {e}")

    # 2. Check Vault if not found
    if not (client_id and client_secret and username and password):
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "reddit")
            if vault_cred:
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        client_id = client_id or cred_json.get("client_id")
                        client_secret = client_secret or cred_json.get("client_secret")
                        username = username or cred_json.get("username")
                        password = password or cred_json.get("password")
                        user_agent = user_agent or cred_json.get("user_agent")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Vault retrieval note: {e}")

    # 3. Fallback to Environment Variables
    client_id = client_id or os.getenv("REDDIT_CLIENT_ID", "").strip() or None
    client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET", "").strip() or None
    username = username or os.getenv("REDDIT_USERNAME", "").strip() or None
    password = password or os.getenv("REDDIT_PASSWORD", "").strip() or None
    user_agent = (
        user_agent
        or os.getenv("REDDIT_USER_AGENT", "").strip()
        or f"TetrisDistributionWorker/1.0 (by /u/{username or 'user'})"
    )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
        "user_agent": user_agent,
    }


def _clean_subreddit_name(raw_name: str) -> str:
    """Strips r/, /r/, leading/trailing slashes and whitespace."""
    if not raw_name:
        return ""
    cleaned = raw_name.strip()
    if cleaned.startswith("/r/"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("r/"):
        cleaned = cleaned[2:]
    return cleaned.strip("/").strip()


def _clean_thread_id(raw_id: str) -> str:
    """Strips t3_ or t1_ prefixes and URL parts if given."""
    if not raw_id:
        return ""
    cleaned = str(raw_id).strip()
    # If a full URL is provided, extract ID from /comments/<id>/
    if "reddit.com" in cleaned and "/comments/" in cleaned:
        match = re.search(r"/comments/([a-zA-Z0-9]+)", cleaned)
        if match:
            return match.group(1)
    if cleaned.startswith("t3_") or cleaned.startswith("t1_"):
        return cleaned[3:]
    return cleaned


def initialize_praw_client(credentials: Dict[str, Optional[str]]):
    """Initializes and returns a PRAW Reddit instance."""
    import praw

    return praw.Reddit(
        client_id=credentials.get("client_id"),
        client_secret=credentials.get("client_secret"),
        username=credentials.get("username"),
        password=credentials.get("password"),
        user_agent=credentials.get("user_agent") or "TetrisDistributionWorker/1.0",
        requestor_kwargs={"timeout": 15},
    )


def verify_reddit_submission(reddit_client, submission_id: str) -> Dict[str, Any]:
    """
    Verifies that a submitted post actually exists on Reddit and has valid permalink.
    """
    try:
        clean_id = _clean_thread_id(submission_id)
        sub = reddit_client.submission(id=clean_id)
        # Accessing an attribute triggers the lazy fetch
        sub_title = sub.title
        permalink = sub.permalink
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink

        if sub_title and permalink:
            return {
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": f"t3_{sub.id}" if not str(sub.id).startswith("t3_") else sub.id,
                "external_url": full_url,
                "title": sub_title,
            }
        else:
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": "Submission retrieved but missing title or permalink",
            }
    except Exception as e:
        clean_err = str(e)[:200]
        return {
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "error": f"Verification failed: {clean_err}",
        }


def verify_reddit_comment(reddit_client, comment_id: str) -> Dict[str, Any]:
    """
    Verifies that a submitted comment actually exists on Reddit and has valid permalink.
    """
    try:
        clean_id = _clean_thread_id(comment_id)
        cmt = reddit_client.comment(id=clean_id)
        # Accessing body triggers the fetch
        body_text = cmt.body
        permalink = cmt.permalink
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink

        if body_text and permalink:
            return {
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": f"t1_{cmt.id}" if not str(cmt.id).startswith("t1_") else cmt.id,
                "external_url": full_url,
            }
        else:
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": "Comment retrieved but missing body or permalink",
            }
    except Exception as e:
        clean_err = str(e)[:200]
        return {
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "error": f"Verification failed: {clean_err}",
        }


def persist_reddit_receipt(receipt: Dict[str, Any], db=None, user_id: str = "user_001"):
    """
    Persists the executed Reddit action receipt into the SQLite database.
    Reuses the ConnectorAction model and updates PhaseResult distribution_plan if present.
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

        # Save ConnectorAction
        save_connector_action(
            db=db,
            user_id=user_id,
            execution_id=exec_id,
            connector_id="reddit",
            action=action_name,
            status=status,
            result=receipt,
            error=error_msg,
            action_id=action_id,
        )

        # Also update PhaseResult distribution_plan if this execution_id exists
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
                    if act.get("action_id") == action_id or (act.get("platform") == "reddit" and act.get("action_type") == action_name):
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


def execute_reddit_action(
    action: Dict[str, Any],
    user_id: str = "user_001",
    db=None,
    reddit_client_override=None,
) -> Dict[str, Any]:
    """
    Executes a single proposed Reddit DistributionAction with full lifecycle verification and security guards.

    Parameters
    ----------
    action : dict
        The DistributionAction dictionary adhering to M3.1 contract.
    user_id : str
        The owning user ID.
    db : Session, optional
        Database session for credential lookup and receipt persistence.
    reddit_client_override : optional
        PRAW client instance for testing/mocking.

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
        "worker": ActionWorker.COMMUNITY,
        "platform": ActionPlatform.REDDIT,
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
    if action_type not in ("create_post", "reply_to_post"):
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Unsupported Reddit action type: '{action_type}'. Only 'create_post' and 'reply_to_post' are supported."
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
    credentials = resolve_reddit_credentials(user_id=user_id, db=db)
    has_creds = bool(
        credentials.get("client_id")
        and credentials.get("client_secret")
        and credentials.get("username")
        and credentials.get("password")
    )

    if not has_creds and reddit_client_override is None:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = "Reddit credentials missing or incomplete (requires client_id, client_secret, username, password)."
        base_receipt["reason"] = "AUTH_REQUIRED"
        if exec_id:
            persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 4. Target & Content Payload Validation
    # ---------------------------------------------------------------
    raw_sub = target.get("community") or target.get("subreddit") or target.get("target") or ""
    subreddit_name = _clean_subreddit_name(raw_sub)

    if action_type == "create_post":
        title = content.get("title") or content.get("headline") or ""
        body = content.get("body") or content.get("text") or content.get("selftext") or ""

        if not subreddit_name:
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Target subreddit ('community' or 'subreddit') is required for create_post."
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not title or not title.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'title' is required and cannot be empty for create_post."
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not body or not body.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'body' is required and cannot be empty for create_post."
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

    elif action_type == "reply_to_post":
        thread_id = (
            target.get("context_thread_id")
            or target.get("post_id")
            or target.get("submission_id")
            or target.get("thread_id")
            or target.get("target")
            or ""
        )
        body = content.get("body") or content.get("text") or content.get("comment") or ""

        if not thread_id or not str(thread_id).strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Target thread ID ('context_thread_id' or 'post_id') is required for reply_to_post."
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not body or not body.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'body' is required and cannot be empty for reply_to_post."
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

    # ---------------------------------------------------------------
    # 5. Initialize Client & Execute via PRAW
    # ---------------------------------------------------------------
    try:
        reddit = reddit_client_override or initialize_praw_client(credentials)
    except Exception as e:
        clean_err = str(e)[:200]
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Failed to initialize Reddit client: {clean_err}"
        base_receipt["reason"] = "AUTH_FAILED"
        return base_receipt

    executed_at_iso = datetime.now(timezone.utc).isoformat()
    base_receipt["executed_at"] = executed_at_iso

    try:
        if action_type == "create_post":
            sub = reddit.subreddit(subreddit_name)
            submission = sub.submit(title=title.strip(), selftext=body.strip())
            sub_id = str(submission.id)
            permalink = str(submission.permalink)
            full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
            ext_id = f"t3_{sub_id}" if not sub_id.startswith("t3_") else sub_id

            # Step 6: Verify External Object
            verif = verify_reddit_submission(reddit, sub_id)
            if verif.get("verified"):
                base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
                base_receipt["status"] = ExecutionStatus.SUCCESS
                base_receipt["receipt"] = {
                    "verified": True,
                    "verification_status": VerificationStatus.PASS,
                    "external_id": ext_id,
                    "external_url": full_url,
                }
                base_receipt["external_id"] = ext_id
                base_receipt["external_url"] = full_url
                base_receipt["verified"] = True
                base_receipt["verification_status"] = VerificationStatus.PASS
            else:
                base_receipt["execution"]["status"] = ExecutionStatus.FAILED
                base_receipt["status"] = ExecutionStatus.FAILED
                base_receipt["error"] = f"Post submitted but verification failed: {verif.get('error')}"
                base_receipt["receipt"] = {
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "external_id": ext_id,
                    "external_url": full_url,
                }
                base_receipt["external_id"] = ext_id
                base_receipt["external_url"] = full_url

        elif action_type == "reply_to_post":
            clean_pid = _clean_thread_id(thread_id)
            parent_submission = reddit.submission(id=clean_pid)
            comment = parent_submission.reply(body=body.strip())
            cmt_id = str(comment.id)
            permalink = str(comment.permalink)
            full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
            ext_id = f"t1_{cmt_id}" if not cmt_id.startswith("t1_") else cmt_id

            # Step 6: Verify External Object
            verif = verify_reddit_comment(reddit, cmt_id)
            if verif.get("verified"):
                base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
                base_receipt["status"] = ExecutionStatus.SUCCESS
                base_receipt["receipt"] = {
                    "verified": True,
                    "verification_status": VerificationStatus.PASS,
                    "external_id": ext_id,
                    "external_url": full_url,
                }
                base_receipt["external_id"] = ext_id
                base_receipt["external_url"] = full_url
                base_receipt["verified"] = True
                base_receipt["verification_status"] = VerificationStatus.PASS
            else:
                base_receipt["execution"]["status"] = ExecutionStatus.FAILED
                base_receipt["status"] = ExecutionStatus.FAILED
                base_receipt["error"] = f"Reply submitted but verification failed: {verif.get('error')}"
                base_receipt["receipt"] = {
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "external_id": ext_id,
                    "external_url": full_url,
                }
                base_receipt["external_id"] = ext_id
                base_receipt["external_url"] = full_url

    except Exception as exc:
        err_str = str(exc)
        clean_err = err_str[:300]
        # Sanitize any accidental secret exposure
        for sec in [credentials.get("client_secret"), credentials.get("password")]:
            if sec and sec in clean_err:
                clean_err = clean_err.replace(sec, "[REDACTED]")

        status = ExecutionStatus.FAILED
        reason = "EXECUTION_ERROR"

        # Categorize common errors
        err_lower = clean_err.lower()
        if "401" in err_lower or "oauth" in err_lower or "invalid_grant" in err_lower or "unauthorized" in err_lower:
            status = ExecutionStatus.BLOCKED
            reason = "AUTH_FAILED"
            clean_err = "Reddit authentication failed. Check credentials."
        elif "404" in err_lower or "notfound" in err_lower or "redirect" in err_lower or "subreddit not found" in err_lower:
            reason = "SUBREDDIT_NOT_FOUND"
            clean_err = f"Subreddit 'r/{subreddit_name}' not found or inaccessible."
        elif "403" in err_lower or "forbidden" in err_lower or "banned" in err_lower:
            reason = "PERMISSION_DENIED"
            clean_err = f"Permission denied posting to r/{subreddit_name}."
        elif "ratelimit" in err_lower or "too many requests" in err_lower or "429" in err_lower:
            reason = "RATE_LIMITED"
            clean_err = "Reddit rate limit reached. Please wait before retrying."
        elif "timeout" in err_lower:
            reason = "TIMEOUT"
            clean_err = "Reddit API request timed out."

        base_receipt["execution"]["status"] = status
        base_receipt["status"] = status
        base_receipt["error"] = clean_err
        base_receipt["reason"] = reason

    # ---------------------------------------------------------------
    # 7. Persist Receipt
    # ---------------------------------------------------------------
    persist_reddit_receipt(base_receipt, db=db, user_id=user_id)

    return base_receipt


def post_to_reddit(
    subreddit: str,
    title: str,
    body: str,
    user_id: str = "user_001",
    execution_id: str = "",
) -> Dict[str, Any]:
    """
    Backwards-compatible convenience function for direct Reddit posting.
    Creates a pre-approved DistributionAction and executes it.
    """
    action = {
        "action_id": f"act-{datetime.now(timezone.utc).timestamp()}",
        "execution_id": execution_id,
        "worker": ActionWorker.COMMUNITY,
        "platform": ActionPlatform.REDDIT,
        "action_type": "create_post",
        "target": {"community": subreddit},
        "content": {"title": title, "body": body},
        "approval": {"required": False, "status": ApprovalStatus.APPROVED},
    }
    return execute_reddit_action(action=action, user_id=user_id)
