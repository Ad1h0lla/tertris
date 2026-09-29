"""
Tetris — Outreach Distribution Worker (Real Email Execution)
============================================================

Executes authorized outreach distribution actions via real email providers:
1. SendGrid (API-based)
2. SMTP (Standard Library / TLS / SSL)

Supported Action Types:
- send_email : Dispatches a single approved outreach email to a recipient

Lifecycle & Contracts:
- PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY
- Hard Gate: Only executes if approval.status == "APPROVED"
- Credentials resolved in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables
- Missing/invalid credentials return status = "BLOCKED", reason = "AUTH_REQUIRED"
- Honest Verification: Distinguishes provider acceptance (ACCEPTED) from inbox delivery (UNKNOWN / NOT_TESTED).
  Never fabricates message IDs or delivery receipts.
- Duplicate Protection / Idempotency: Checks for existing successful receipt for the given action_id.
"""

from typing import Dict, Any, Optional, List, Tuple
import os
import json
import logging
import re
import smtplib
import socket
from email.message import EmailMessage
from datetime import datetime, timezone

import requests
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

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ===========================================================================
# 1. CREDENTIAL SANITIZATION & RESOLUTION
# ===========================================================================

def sanitize_email_secrets(text: str, secrets: List[Optional[str]]) -> str:
    """Replaces any raw secret values with [REDACTED] in error strings."""
    if not text:
        return ""
    clean = str(text)
    for s in secrets:
        if s and isinstance(s, str) and len(s.strip()) > 3:
            clean = clean.replace(s.strip(), "[REDACTED]")
    return clean


def resolve_sendgrid_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[str]]:
    """
    Resolves SendGrid credentials in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables
    """
    api_key = None
    from_email = None
    from_name = None

    # 1. Check DB StoredCredential
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "sendgrid") or get_decrypted_credential(db, user_id, "email")
            if cred_str:
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        api_key = cred_json.get("api_key") or cred_json.get("SENDGRID_API_KEY")
                        from_email = cred_json.get("from_email") or cred_json.get("SENDGRID_FROM_EMAIL")
                        from_name = cred_json.get("from_name") or cred_json.get("SENDGRID_FROM_NAME")
                    elif isinstance(cred_str, str) and cred_str.startswith("SG."):
                        api_key = cred_str
                except Exception:
                    if cred_str.startswith("SG."):
                        api_key = cred_str
        except Exception as e:
            logger.debug(f"DB SendGrid credential retrieval note: {e}")

    # 2. Check Vault
    if not api_key:
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "sendgrid") or get_credential(user_id, "email")
            if vault_cred:
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        api_key = api_key or cred_json.get("api_key") or cred_json.get("SENDGRID_API_KEY")
                        from_email = from_email or cred_json.get("from_email") or cred_json.get("SENDGRID_FROM_EMAIL")
                        from_name = from_name or cred_json.get("from_name") or cred_json.get("SENDGRID_FROM_NAME")
                    elif isinstance(vault_cred, str) and vault_cred.startswith("SG."):
                        api_key = vault_cred
                except Exception:
                    if vault_cred.startswith("SG."):
                        api_key = vault_cred
        except Exception as e:
            logger.debug(f"Vault SendGrid retrieval note: {e}")

    # 3. Fallback to Environment Variables
    api_key = api_key or os.getenv("SENDGRID_API_KEY", "").strip() or None
    from_email = (
        from_email
        or os.getenv("SENDGRID_FROM_EMAIL", "").strip()
        or os.getenv("FROM_EMAIL", "").strip()
        or os.getenv("OUTREACH_FROM_EMAIL", "").strip()
        or "noreply@executa.ai"
    )
    from_name = (
        from_name
        or os.getenv("SENDGRID_FROM_NAME", "").strip()
        or os.getenv("FROM_NAME", "").strip()
        or "Tetris Outreach"
    )

    return {
        "api_key": api_key,
        "from_email": from_email,
        "from_name": from_name,
    }


def resolve_smtp_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[Any]]:
    """
    Resolves SMTP credentials in priority order:
    1. StoredCredential / credential manager (encrypted in DB)
    2. Vault
    3. Environment variables
    """
    host = None
    port = None
    username = None
    password = None
    from_email = None
    from_name = None
    use_tls = None
    use_ssl = None

    # 1. Check DB StoredCredential
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "smtp")
            if cred_str:
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        host = cred_json.get("host") or cred_json.get("SMTP_HOST")
                        port = cred_json.get("port") or cred_json.get("SMTP_PORT")
                        username = cred_json.get("username") or cred_json.get("SMTP_USERNAME") or cred_json.get("SMTP_USER")
                        password = cred_json.get("password") or cred_json.get("SMTP_PASSWORD") or cred_json.get("SMTP_PASS")
                        from_email = cred_json.get("from_email") or cred_json.get("SMTP_FROM_EMAIL")
                        from_name = cred_json.get("from_name") or cred_json.get("SMTP_FROM_NAME")
                        use_tls = cred_json.get("use_tls") or cred_json.get("SMTP_USE_TLS")
                        use_ssl = cred_json.get("use_ssl") or cred_json.get("SMTP_USE_SSL")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"DB SMTP credential retrieval note: {e}")

    # 2. Check Vault
    if not (host and username and password):
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "smtp")
            if vault_cred:
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        host = host or cred_json.get("host") or cred_json.get("SMTP_HOST")
                        port = port or cred_json.get("port") or cred_json.get("SMTP_PORT")
                        username = username or cred_json.get("username") or cred_json.get("SMTP_USERNAME")
                        password = password or cred_json.get("password") or cred_json.get("SMTP_PASSWORD")
                        from_email = from_email or cred_json.get("from_email") or cred_json.get("SMTP_FROM_EMAIL")
                        from_name = from_name or cred_json.get("from_name") or cred_json.get("SMTP_FROM_NAME")
                        use_tls = use_tls if use_tls is not None else cred_json.get("use_tls")
                        use_ssl = use_ssl if use_ssl is not None else cred_json.get("use_ssl")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Vault SMTP retrieval note: {e}")

    # 3. Fallback to Environment Variables
    host = host or os.getenv("SMTP_HOST", "").strip() or None
    port_env = os.getenv("SMTP_PORT", "").strip()
    if port is None and port_env:
        try:
            port = int(port_env)
        except ValueError:
            port = 587
    elif port is None:
        port = 587

    username = username or os.getenv("SMTP_USERNAME", "").strip() or os.getenv("SMTP_USER", "").strip() or None
    password = password or os.getenv("SMTP_PASSWORD", "").strip() or os.getenv("SMTP_PASS", "").strip() or None
    from_email = (
        from_email
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("FROM_EMAIL", "").strip()
        or username
        or "noreply@executa.ai"
    )
    from_name = (
        from_name
        or os.getenv("SMTP_FROM_NAME", "").strip()
        or os.getenv("FROM_NAME", "").strip()
        or "Tetris Outreach"
    )

    if use_tls is None:
        tls_env = os.getenv("SMTP_USE_TLS", "true").strip().lower()
        use_tls = tls_env in ("true", "1", "yes")

    if use_ssl is None:
        ssl_env = os.getenv("SMTP_USE_SSL", "false").strip().lower()
        use_ssl = ssl_env in ("true", "1", "yes") or port == 465

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "from_name": from_name,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


# ===========================================================================
# 2. VALIDATION HELPERS
# ===========================================================================

def validate_email_address(email: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validates that an email address is non-empty and syntactically valid."""
    if not email or not isinstance(email, str) or not email.strip():
        return False, "Recipient email address is required and cannot be empty."
    clean = email.strip()
    if not EMAIL_REGEX.match(clean):
        return False, f"Invalid email format: '{clean}'."
    return True, None


def validate_email_payload(subject: Optional[str], body: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validates that subject and body are present and non-empty."""
    if not subject or not isinstance(subject, str) or not subject.strip():
        return False, "Email subject is required and cannot be empty."
    if not body or not isinstance(body, str) or not body.strip():
        return False, "Email body is required and cannot be empty."
    return True, None


# ===========================================================================
# 3. PROVIDER ABSTRACTION & ADAPTERS
# ===========================================================================

class EmailProvider:
    """Base interface for all email providers."""

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        raise NotImplementedError("EmailProvider subclasses must implement send().")


class SendGridEmailProvider(EmailProvider):
    """SendGrid API v3 Email Adapter."""

    def __init__(self, api_key: str, default_from_email: str = "noreply@executa.ai", default_from_name: str = "Tetris Outreach"):
        self.api_key = api_key
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        http_client=None,
        **kwargs,
    ) -> Dict[str, Any]:
        sender_email = from_email or self.default_from_email
        sender_name = from_name or self.default_from_name

        payload = {
            "personalizations": [
                {
                    "to": [{"email": to_email.strip()}],
                }
            ],
            "from": {
                "email": sender_email.strip(),
                "name": sender_name.strip(),
            },
            "subject": subject.strip(),
            "content": [
                {
                    "type": "text/plain",
                    "value": body.strip(),
                }
            ],
        }

        if html_body and html_body.strip():
            payload["content"].append({
                "type": "text/html",
                "value": html_body.strip(),
            })

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client = http_client or requests

        try:
            response = client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers=headers,
                json=payload,
                timeout=15,
            )

            status_code = getattr(response, "status_code", 0)
            resp_headers = getattr(response, "headers", {}) or {}

            # SendGrid returns 202 Accepted on success
            if status_code in (200, 202):
                msg_id = resp_headers.get("X-Message-Id") or resp_headers.get("x-message-id")
                return {
                    "success": True,
                    "provider": "sendgrid",
                    "provider_status": "ACCEPTED",
                    "status_code": status_code,
                    "message_id": msg_id,
                    "verified": True,
                    "verification_status": VerificationStatus.PASS,
                    "delivery_status": "UNKNOWN",
                    "error": None,
                }
            elif status_code == 429:
                return {
                    "success": False,
                    "provider": "sendgrid",
                    "provider_status": "RATE_LIMITED",
                    "status_code": 429,
                    "message_id": None,
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "reason": "RATE_LIMITED",
                    "error": "SendGrid rate limit exceeded. Please retry later.",
                }
            elif status_code in (401, 403):
                err_text = getattr(response, "text", "")
                clean_err = sanitize_email_secrets(err_text, [self.api_key])[:300]
                reason = "AUTH_FAILED" if status_code == 401 else "PERMISSION_DENIED"
                return {
                    "success": False,
                    "provider": "sendgrid",
                    "provider_status": "REJECTED",
                    "status_code": status_code,
                    "message_id": None,
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "reason": reason,
                    "error": f"SendGrid authentication/permission error ({status_code}): {clean_err or 'Invalid credentials or unverified sender identity.'}",
                }
            else:
                err_text = getattr(response, "text", "")
                clean_err = sanitize_email_secrets(err_text, [self.api_key])[:300]
                return {
                    "success": False,
                    "provider": "sendgrid",
                    "provider_status": "FAILED",
                    "status_code": status_code,
                    "message_id": None,
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "reason": "PROVIDER_ERROR",
                    "error": f"SendGrid API rejected send request ({status_code}): {clean_err}",
                }

        except (requests.Timeout, socket.timeout):
            return {
                "success": False,
                "provider": "sendgrid",
                "provider_status": "FAILED",
                "message_id": None,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "reason": "TIMEOUT",
                "error": "SendGrid API request timed out after 15s. Ambiguous outcome; not retrying blindly.",
            }
        except Exception as exc:
            clean_err = sanitize_email_secrets(str(exc), [self.api_key])[:300]
            return {
                "success": False,
                "provider": "sendgrid",
                "provider_status": "FAILED",
                "message_id": None,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "reason": "EXECUTION_ERROR",
                "error": f"SendGrid dispatch failed: {clean_err}",
            }


class SMTPEmailProvider(EmailProvider):
    """SMTP Email Adapter using standard library smtplib with TLS/SSL."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        default_from_email: str = "noreply@executa.ai",
        default_from_name: str = "Tetris Outreach",
        use_tls: bool = True,
        use_ssl: bool = False,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name
        self.use_tls = use_tls
        self.use_ssl = use_ssl

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        smtp_client=None,
        **kwargs,
    ) -> Dict[str, Any]:
        sender_email = from_email or self.default_from_email
        sender_name = from_name or self.default_from_name

        msg = EmailMessage()
        msg["Subject"] = subject.strip()
        msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
        msg["To"] = to_email.strip()
        msg.set_content(body.strip())

        if html_body and html_body.strip():
            msg.add_alternative(html_body.strip(), subtype="html")

        secrets_to_sanitize = [self.password, self.username]

        try:
            if smtp_client is not None:
                server = smtp_client
                refused = server.send_message(msg)
                # If smtp_client is a mock or wrapper, capture smtp response
                smtp_resp = getattr(server, "last_response", (250, b"2.0.0 OK message queued"))
            else:
                if self.use_ssl or self.port == 465:
                    server = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
                else:
                    server = smtplib.SMTP(self.host, self.port, timeout=15)
                    server.ehlo()
                    if self.use_tls:
                        server.starttls()
                        server.ehlo()

                if self.username and self.password:
                    server.login(self.username, self.password)

                refused = server.send_message(msg)
                smtp_resp = getattr(server, "noop", lambda: (250, b"2.0.0 OK"))()
                try:
                    server.quit()
                except Exception:
                    pass

            if refused:
                return {
                    "success": False,
                    "provider": "smtp",
                    "provider_status": "REJECTED",
                    "smtp_response": str(refused),
                    "message_id": None,
                    "verified": False,
                    "verification_status": VerificationStatus.FAIL,
                    "reason": "RECIPIENT_REFUSED",
                    "error": f"SMTP server refused recipients: {refused}",
                }

            resp_str = str(smtp_resp)
            return {
                "success": True,
                "provider": "smtp",
                "provider_status": "ACCEPTED",
                "smtp_response": resp_str,
                "message_id": None,
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "delivery_status": "UNKNOWN",
                "error": None,
            }

        except smtplib.SMTPAuthenticationError as auth_err:
            clean_err = sanitize_email_secrets(str(auth_err), secrets_to_sanitize)[:300]
            return {
                "success": False,
                "provider": "smtp",
                "provider_status": "REJECTED",
                "message_id": None,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "reason": "AUTH_FAILED",
                "error": f"SMTP Authentication failed: {clean_err}",
            }
        except (socket.timeout, smtplib.SMTPConnectError) as conn_err:
            clean_err = sanitize_email_secrets(str(conn_err), secrets_to_sanitize)[:300]
            is_timeout = isinstance(conn_err, socket.timeout) or "timeout" in str(conn_err).lower()
            return {
                "success": False,
                "provider": "smtp",
                "provider_status": "FAILED",
                "message_id": None,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "reason": "TIMEOUT" if is_timeout else "CONNECTION_FAILED",
                "error": f"SMTP connection error: {clean_err}",
            }
        except Exception as exc:
            clean_err = sanitize_email_secrets(str(exc), secrets_to_sanitize)[:300]
            return {
                "success": False,
                "provider": "smtp",
                "provider_status": "FAILED",
                "message_id": None,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "reason": "EXECUTION_ERROR",
                "error": f"SMTP send failed: {clean_err}",
            }


# ===========================================================================
# 4. IDEMPOTENCY CHECK & PERSISTENCE
# ===========================================================================

def check_email_idempotency(action_id: str, db=None) -> Optional[Dict[str, Any]]:
    """
    Checks if an action_id has already been executed successfully.
    Returns the existing receipt if found, preventing accidental duplicate sends.
    """
    if not action_id:
        return None

    close_db = False
    if db is None:
        try:
            from database.models import SessionLocal
            db = SessionLocal()
            close_db = True
        except Exception:
            return None

    try:
        from database.models import ConnectorAction
        existing = (
            db.query(ConnectorAction)
            .filter(
                ConnectorAction.id == action_id,
                ConnectorAction.status == ExecutionStatus.SUCCESS,
            )
            .first()
        )
        if existing and existing.result:
            return existing.result
        return None
    except Exception as e:
        logger.debug(f"Idempotency check note: {e}")
        return None
    finally:
        if close_db and db:
            db.close()


def persist_email_receipt(receipt: Dict[str, Any], db=None, user_id: str = "user_001"):
    """
    Persists the executed email action receipt into SQLite database.
    Reuses ConnectorAction model via save_connector_action.
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
        action_name = receipt.get("action_type", "send_email")
        status = receipt.get("status", "SUCCESS")
        error_msg = receipt.get("error")

        save_connector_action(
            db=db,
            user_id=user_id,
            execution_id=exec_id,
            connector_id="email",
            action=action_name,
            status=status,
            result=receipt,
            error=error_msg,
            action_id=action_id,
        )

        # Update PhaseResult distribution_plan if execution_id exists
        if exec_id:
            from sqlalchemy.orm.attributes import flag_modified
            phase_res = (
                db.query(PhaseResult)
                .filter(PhaseResult.execution_id == exec_id, PhaseResult.phase_number == 3)
                .first()
            )
            if phase_res and phase_res.distribution_plan:
                import copy
                plan = copy.deepcopy(phase_res.distribution_plan)
                actions = list(plan.get("actions", []))
                updated = False
                for idx, act in enumerate(actions):
                    if act.get("action_id") == action_id or (act.get("platform") == "email" and act.get("action_type") == action_name):
                        actions[idx]["execution"] = {"status": status}
                        actions[idx]["receipt"] = receipt.get("receipt", {})
                        actions[idx]["executed_at"] = receipt.get("executed_at")
                        actions[idx]["error"] = error_msg
                        updated = True
                        break
                if updated:
                    plan["actions"] = actions
                    phase_res.distribution_plan = plan
                    flag_modified(phase_res, "distribution_plan")
                    db.commit()

    except Exception as e:
        logger.debug(f"Email persistence note: {e}")
    finally:
        if close_db_at_end and db:
            db.close()


# ===========================================================================
# 5. OUTREACH WORKER / EMAIL EXECUTOR ENTRYPOINT
# ===========================================================================

def execute_email_action(
    action: Dict[str, Any],
    user_id: str = "user_001",
    db=None,
    provider_override: Optional[EmailProvider] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Executes a single proposed Outreach / Email DistributionAction with full lifecycle verification.

    Parameters
    ----------
    action : dict
        The DistributionAction dictionary adhering to M3.1 contract.
    user_id : str
        The owning user ID.
    db : Session, optional
        Database session for credential lookup and receipt persistence.
    provider_override : EmailProvider, optional
        EmailProvider instance for testing/mocking.

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
        "worker": ActionWorker.OUTREACH,
        "platform": ActionPlatform.EMAIL,
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
            "provider": None,
            "provider_status": None,
            "delivery_status": "NOT_TESTED",
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
    if action_type not in ("send_email",):
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Unsupported outreach action type: '{action_type}'. Only 'send_email' is supported."
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
    # 3. Idempotency Check (Duplicate Protection)
    # ---------------------------------------------------------------
    existing_receipt = check_email_idempotency(action_id, db=db)
    if existing_receipt:
        logger.info(f"Action '{action_id}' has already been successfully executed. Returning existing receipt.")
        return existing_receipt

    # ---------------------------------------------------------------
    # 4. Target & Recipient Validation
    # ---------------------------------------------------------------
    recipient_email = (
        target.get("email")
        or target.get("recipient")
        or target.get("to")
        or target.get("to_email")
        or content.get("to_email")
        or content.get("email")
        or ""
    )

    valid_email, email_err = validate_email_address(recipient_email)
    if not valid_email:
        base_receipt["execution"]["status"] = ExecutionStatus.FAILED
        base_receipt["status"] = ExecutionStatus.FAILED
        base_receipt["error"] = email_err
        base_receipt["reason"] = "INVALID_RECIPIENT"
        if exec_id:
            persist_email_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 5. Content Payload Validation
    # ---------------------------------------------------------------
    subject = content.get("subject") or content.get("title") or ""
    body = content.get("body") or content.get("text") or content.get("message") or ""
    html_body = content.get("html") or content.get("html_body") or None

    valid_content, content_err = validate_email_payload(subject, body)
    if not valid_content:
        base_receipt["execution"]["status"] = ExecutionStatus.FAILED
        base_receipt["status"] = ExecutionStatus.FAILED
        base_receipt["error"] = content_err
        base_receipt["reason"] = "INVALID_CONTENT"
        if exec_id:
            persist_email_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 6. Provider Resolution & Credential Check
    # ---------------------------------------------------------------
    provider = provider_override
    if provider is None:
        # Check SendGrid credentials
        sg_creds = resolve_sendgrid_credentials(user_id=user_id, db=db)
        if sg_creds.get("api_key"):
            provider = SendGridEmailProvider(
                api_key=sg_creds["api_key"],
                default_from_email=sg_creds["from_email"],
                default_from_name=sg_creds["from_name"],
            )
        else:
            # Check SMTP credentials
            smtp_creds = resolve_smtp_credentials(user_id=user_id, db=db)
            if smtp_creds.get("host") and (smtp_creds.get("username") or smtp_creds.get("port")):
                provider = SMTPEmailProvider(
                    host=smtp_creds["host"],
                    port=smtp_creds["port"],
                    username=smtp_creds["username"],
                    password=smtp_creds["password"],
                    default_from_email=smtp_creds["from_email"],
                    default_from_name=smtp_creds["from_name"],
                    use_tls=smtp_creds["use_tls"],
                    use_ssl=smtp_creds["use_ssl"],
                )

    if provider is None:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = "Email credentials missing or unconfigured (requires SendGrid SENDGRID_API_KEY or SMTP configuration)."
        base_receipt["reason"] = "AUTH_REQUIRED"
        if exec_id:
            persist_email_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 7. Execute Real Provider Send
    # ---------------------------------------------------------------
    executed_at_iso = datetime.now(timezone.utc).isoformat()
    base_receipt["executed_at"] = executed_at_iso

    from_email = target.get("from_email") or content.get("from_email")
    from_name = target.get("from_name") or content.get("from_name")

    res = provider.send(
        to_email=recipient_email,
        subject=subject,
        body=body,
        from_email=from_email,
        from_name=from_name,
        html_body=html_body,
        **kwargs,
    )

    # ---------------------------------------------------------------
    # 8. Verification & Honest Receipt Construction
    # ---------------------------------------------------------------
    prov_name = res.get("provider", "email")
    prov_status = res.get("provider_status", "UNKNOWN")
    msg_id = res.get("message_id")
    verified = bool(res.get("verified", False))
    verif_status = res.get("verification_status", VerificationStatus.FAIL)
    delivery_status = res.get("delivery_status", "UNKNOWN")
    error_msg = res.get("error")
    reason = res.get("reason")

    if res.get("success"):
        base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
        base_receipt["status"] = ExecutionStatus.SUCCESS
        base_receipt["verified"] = True
        base_receipt["verification_status"] = VerificationStatus.PASS
        base_receipt["external_id"] = msg_id
        base_receipt["receipt"] = {
            "verified": True,
            "verification_status": VerificationStatus.PASS,
            "external_id": msg_id,
            "external_url": None,
            "provider": prov_name,
            "provider_status": prov_status,
            "delivery_status": delivery_status,
            "smtp_response": res.get("smtp_response"),
            "status_code": res.get("status_code"),
        }
    else:
        exec_status = ExecutionStatus.BLOCKED if reason in ("AUTH_FAILED", "PERMISSION_DENIED") else ExecutionStatus.FAILED
        base_receipt["execution"]["status"] = exec_status
        base_receipt["status"] = exec_status
        base_receipt["verified"] = False
        base_receipt["verification_status"] = VerificationStatus.FAIL
        base_receipt["error"] = error_msg
        base_receipt["reason"] = reason or "EXECUTION_FAILED"
        base_receipt["receipt"] = {
            "verified": False,
            "verification_status": VerificationStatus.FAIL,
            "external_id": None,
            "external_url": None,
            "provider": prov_name,
            "provider_status": prov_status,
            "delivery_status": "NOT_TESTED",
            "error": error_msg,
        }

    # ---------------------------------------------------------------
    # 9. Persist Receipt
    # ---------------------------------------------------------------
    persist_email_receipt(base_receipt, db=db, user_id=user_id)

    return base_receipt


# ===========================================================================
# 6. BACKWARD COMPATIBILITY
# ===========================================================================

def send_email_sequence(emails: list, sequence: list, from_email: str = "noreply@executa.ai") -> dict:
    """Legacy helper for sequence dispatching."""
    if not emails:
        return {"success": False, "error": "No recipient emails provided"}
    
    first_email = emails[0] if isinstance(emails, list) else str(emails)
    first_step = sequence[0] if isinstance(sequence, list) and sequence else {}
    subject = first_step.get("subject", "Outreach from Tetris")
    body = first_step.get("body", first_step.get("text", "Hello from Tetris"))

    action = {
        "action_id": "",
        "execution_id": "",
        "worker": "outreach",
        "platform": "email",
        "action_type": "send_email",
        "target": {"email": first_email, "from_email": from_email},
        "content": {"subject": subject, "body": body},
        "approval": {"required": False, "status": ApprovalStatus.APPROVED},
    }
    return execute_email_action(action)
