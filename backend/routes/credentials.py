"""
M3.5-A — Credential Routes
===========================

Authoritative, Pydantic-validated credential endpoints.

Replaces the decompiled (broken) handlers registered by main_working.py
for:
    POST   /credentials/connect
    GET    /credentials/{user_id}
    DELETE /credentials/{user_id}/{app_name}

New routes:
    POST   /credentials/test/{app_name}
    GET    /credentials/readiness/{user_id}

Security:
  - Raw secrets are NEVER returned in API responses.
  - All credential values are serialised to JSON, then encrypted with Fernet
    before writing to SQLite (via credential_manager.py).
  - Error messages are sanitised through _mask_secrets().
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from database.models import get_db
from database.operations import list_credentials, delete_credential, get_credential as _db_get_raw
from integrations.credential_manager import (
    connect_app,
    disconnect_app,
    get_decrypted_credential,
    get_connected_apps,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials", tags=["credentials"])

# ---------------------------------------------------------------------------
# Supported connectors — metadata for structured credential forms.
# Each entry describes the fields the UI should render.
# ---------------------------------------------------------------------------

CONNECTOR_FIELD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "reddit": {
        "display_name": "Reddit",
        "connection_type": "api_credentials",
        "fields": [
            {"key": "client_id",     "label": "Client ID",     "secret": False, "required": True},
            {"key": "client_secret", "label": "Client Secret", "secret": True,  "required": True},
            {"key": "username",      "label": "Reddit Username","secret": False, "required": True},
            {"key": "password",      "label": "Reddit Password","secret": True,  "required": True},
            {"key": "user_agent",    "label": "User Agent",     "secret": False, "required": False,
             "placeholder": "TetrisBot/1.0 (by /u/yourname)"},
        ],
    },
    "twitter": {
        "display_name": "X / Twitter",
        "connection_type": "api_credentials",
        "fields": [
            {"key": "api_key",              "label": "API Key",              "secret": False, "required": True},
            {"key": "api_secret",           "label": "API Secret",           "secret": True,  "required": True},
            {"key": "access_token",         "label": "Access Token",         "secret": False, "required": True},
            {"key": "access_token_secret",  "label": "Access Token Secret",  "secret": True,  "required": True},
            {"key": "bearer_token",         "label": "Bearer Token",         "secret": True,  "required": False},
        ],
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "connection_type": "oauth_token",
        "fields": [
            {"key": "access_token", "label": "Access Token", "secret": True,  "required": True},
            {"key": "person_id",    "label": "Person ID / URN", "secret": False, "required": True,
             "placeholder": "urn:li:person:XXXXXXXX  or  just  XXXXXXXX"},
        ],
    },
    "sendgrid": {
        "display_name": "SendGrid",
        "connection_type": "api_key",
        "fields": [
            {"key": "api_key",    "label": "SendGrid API Key", "secret": True,  "required": True},
            {"key": "from_email", "label": "From Email",       "secret": False, "required": False,
             "placeholder": "noreply@yourdomain.com"},
            {"key": "from_name",  "label": "From Name",        "secret": False, "required": False,
             "placeholder": "Your Name"},
        ],
    },
    "smtp": {
        "display_name": "SMTP",
        "connection_type": "smtp",
        "fields": [
            {"key": "host",       "label": "SMTP Host",     "secret": False, "required": True,
             "placeholder": "smtp.gmail.com"},
            {"key": "port",       "label": "SMTP Port",     "secret": False, "required": False,
             "placeholder": "587"},
            {"key": "username",   "label": "Username",      "secret": False, "required": True},
            {"key": "password",   "label": "Password",      "secret": True,  "required": True},
            {"key": "from_email", "label": "From Email",    "secret": False, "required": False},
            {"key": "from_name",  "label": "From Name",     "secret": False, "required": False},
            {"key": "use_tls",    "label": "Use TLS",       "secret": False, "required": False,
             "placeholder": "true"},
        ],
    },
    "github": {
        "display_name": "GitHub",
        "connection_type": "api_key",
        "fields": [
            {"key": "token", "label": "Personal Access Token", "secret": True, "required": True},
        ],
    },
    "vercel": {
        "display_name": "Vercel",
        "connection_type": "api_key",
        "fields": [
            {"key": "token", "label": "Vercel API Token", "secret": True, "required": True},
        ],
    },
    "discord": {
        "display_name": "Discord",
        "connection_type": "bot_token",
        "fields": [
            {"key": "token",      "label": "Bot Token",  "secret": True,  "required": True},
            {"key": "channel_id", "label": "Channel ID", "secret": False, "required": False},
        ],
    },
}


# ---------------------------------------------------------------------------
# Secret sanitisation helpers
# ---------------------------------------------------------------------------

def _mask_secrets(text: str, secrets: list[str | None]) -> str:
    """Replace any raw secret that appears in an error string with [REDACTED]."""
    if not text:
        return ""
    clean = str(text)
    for s in secrets:
        if s and isinstance(s, str) and len(s.strip()) > 3:
            clean = clean.replace(s.strip(), "[REDACTED]")
    return clean


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class ConnectCredentialRequest(BaseModel):
    user_id: str = "user_001"
    app_name: str
    credentials: Dict[str, Any]          # structured key→value dict
    connection_type: Optional[str] = "api_key"
    display_name: Optional[str] = None

    @field_validator("app_name")
    @classmethod
    def normalise_app_name(cls, v: str) -> str:
        # Normalise "X" / "x" / "x/twitter" all to "twitter" for consistency
        v = v.strip().lower()
        if v in ("x", "x/twitter", "x / twitter"):
            return "twitter"
        return v

    @field_validator("credentials")
    @classmethod
    def credentials_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("credentials dict must not be empty")
        return v


class CredentialResponse(BaseModel):
    """Safe credential metadata — raw values are never included."""
    app_name: str
    connection_type: str
    display_name: Optional[str]
    connected_at: Optional[str]
    last_used: Optional[str]


class ConnectResponse(BaseModel):
    success: bool
    app_name: str
    message: str


class DisconnectResponse(BaseModel):
    success: bool
    message: str


class TestResponse(BaseModel):
    status: str          # "CONNECTED" | "AUTH_FAILED" | "UNSUPPORTED" | "BLOCKED"
    app_name: str
    verified: bool
    display_name: Optional[str] = None
    error: Optional[str] = None


class ReadinessConnector(BaseModel):
    connected: bool
    verified: bool


# ---------------------------------------------------------------------------
# GET /credentials/schemas
# Returns UI field definitions for supported connectors
# ---------------------------------------------------------------------------

@router.get("/schemas")
def get_connector_schemas():
    """Return UI form schemas for all supported connectors."""
    return {"schemas": CONNECTOR_FIELD_SCHEMAS}


# ---------------------------------------------------------------------------
# POST /credentials/connect
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=ConnectResponse)
def connect_credential(body: ConnectCredentialRequest, db=Depends(get_db)):
    """
    Encrypts and stores credentials for a given app.

    The `credentials` dict is serialised to JSON, then encrypted with Fernet
    before writing to the `stored_credentials` SQLite table.

    Never returns raw credential values.
    """
    # Serialise the structured credentials dict to a JSON string so it can be
    # stored as a single encrypted blob — matching what the workers expect.
    try:
        raw_credential_str = json.dumps(body.credentials, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid credentials format: {exc}")

    display = body.display_name or CONNECTOR_FIELD_SCHEMAS.get(
        body.app_name, {}
    ).get("display_name", body.app_name.capitalize())

    conn_type = body.connection_type or CONNECTOR_FIELD_SCHEMAS.get(
        body.app_name, {}
    ).get("connection_type", "api_key")

    result = connect_app(
        db=db,
        user_id=body.user_id,
        app_name=body.app_name,
        raw_credential=raw_credential_str,
        connection_type=conn_type,
        display_name=display,
    )

    return ConnectResponse(
        success=result.get("success", False),
        app_name=body.app_name,
        message=result.get("message", "Connected"),
    )


# ---------------------------------------------------------------------------
# GET /credentials/{user_id}
# ---------------------------------------------------------------------------

@router.get("/{user_id}")
def get_credentials(user_id: str, db=Depends(get_db)):
    """
    Lists all active credential entries for a user.
    Returns metadata only — no raw secrets.
    """
    credentials = get_connected_apps(db, user_id)
    return {
        "user_id": user_id,
        "connected_apps": credentials,
    }


# ---------------------------------------------------------------------------
# DELETE /credentials/{user_id}/{app_name}
# ---------------------------------------------------------------------------

@router.delete("/{user_id}/{app_name}", response_model=DisconnectResponse)
def remove_credential(user_id: str, app_name: str, db=Depends(get_db)):
    """Soft-deletes (deactivates) a stored credential."""
    # Normalise app_name alias
    app_name = app_name.strip().lower()
    if app_name in ("x", "x/twitter"):
        app_name = "twitter"

    result = disconnect_app(db=db, user_id=user_id, app_name=app_name)
    return DisconnectResponse(
        success=result.get("success", False),
        message=result.get("message", "Disconnected"),
    )


# ---------------------------------------------------------------------------
# POST /credentials/test/{app_name}
# ---------------------------------------------------------------------------

@router.post("/test/{app_name}", response_model=TestResponse)
def test_credential(app_name: str, user_id: str = "user_001", db=Depends(get_db)):
    """
    Verifies that the stored credentials for `app_name` are valid.

    IMPORTANT: This endpoint must NOT create posts, send emails, or perform
    any external write action. Identity/auth checks only.
    """
    app_name = app_name.strip().lower()
    if app_name in ("x", "x/twitter"):
        app_name = "twitter"

    # Retrieve and decrypt
    encrypted = _db_get_raw(db, user_id, app_name)
    if not encrypted:
        return TestResponse(
            status="BLOCKED",
            app_name=app_name,
            verified=False,
            error="No credentials stored. Please connect first.",
        )

    from integrations.credential_manager import decrypt_credential
    raw = decrypt_credential(encrypted)
    if not raw:
        return TestResponse(
            status="BLOCKED",
            app_name=app_name,
            verified=False,
            error="Failed to decrypt stored credentials.",
        )

    try:
        cred = json.loads(raw)
    except Exception:
        # Treat as flat string (legacy single-key formats)
        cred = {"token": raw, "api_key": raw}

    # ── per-platform identity checks ─────────────────────────────────────────
    if app_name == "reddit":
        return _test_reddit(app_name, cred)

    if app_name == "twitter":
        return _test_twitter(app_name, cred)

    if app_name == "linkedin":
        return _test_linkedin(app_name, cred)

    if app_name == "sendgrid":
        return _test_sendgrid(app_name, cred)

    if app_name == "smtp":
        return _test_smtp(app_name, cred)

    if app_name == "discord":
        return _test_discord_sync(app_name, cred)

    # Generic / unsupported — we can confirm credentials exist but can't verify
    return TestResponse(
        status="CONNECTED",
        app_name=app_name,
        verified=False,
        error=f"Live verification not yet supported for '{app_name}'. Credentials are stored.",
    )


def _test_reddit(app_name: str, cred: dict) -> TestResponse:
    secrets = [cred.get("client_secret"), cred.get("password")]
    try:
        import praw
        reddit = praw.Reddit(
            client_id=cred.get("client_id"),
            client_secret=cred.get("client_secret"),
            username=cred.get("username"),
            password=cred.get("password"),
            user_agent=cred.get("user_agent") or "TetrisCredentialTest/1.0",
        )
        me = reddit.user.me()
        if me:
            return TestResponse(
                status="CONNECTED",
                app_name=app_name,
                verified=True,
                display_name=str(me.name),
            )
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error="Reddit returned no identity.")
    except ImportError:
        return TestResponse(status="BLOCKED", app_name=app_name, verified=False,
                            error="praw not installed; cannot verify Reddit credentials.")
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


def _test_twitter(app_name: str, cred: dict) -> TestResponse:
    secrets = [cred.get("api_secret"), cred.get("access_token_secret"), cred.get("bearer_token")]
    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=cred.get("api_key"),
            consumer_secret=cred.get("api_secret"),
            access_token=cred.get("access_token"),
            access_token_secret=cred.get("access_token_secret"),
            bearer_token=cred.get("bearer_token"),
            wait_on_rate_limit=False,
        )
        me = client.get_me()
        if me and me.data:
            return TestResponse(
                status="CONNECTED",
                app_name=app_name,
                verified=True,
                display_name=f"@{me.data.username}",
            )
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error="X/Twitter returned no identity.")
    except ImportError:
        return TestResponse(status="BLOCKED", app_name=app_name, verified=False,
                            error="tweepy not installed; cannot verify X credentials.")
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


def _test_linkedin(app_name: str, cred: dict) -> TestResponse:
    secrets = [cred.get("access_token")]
    try:
        import requests as _req
        res = _req.get(
            "https://api.linkedin.com/v2/me",
            headers={
                "Authorization": f"Bearer {cred.get('access_token', '')}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=10,
        )
        if res.status_code == 200:
            data = res.json()
            first = data.get("localizedFirstName", "")
            last = data.get("localizedLastName", "")
            return TestResponse(
                status="CONNECTED",
                app_name=app_name,
                verified=True,
                display_name=f"{first} {last}".strip() or None,
            )
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(f"LinkedIn returned HTTP {res.status_code}", secrets))
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


def _test_sendgrid(app_name: str, cred: dict) -> TestResponse:
    """Verify SendGrid API key via /v3/user/account (read-only)."""
    secrets = [cred.get("api_key")]
    api_key = cred.get("api_key", "")
    if not api_key:
        return TestResponse(status="BLOCKED", app_name=app_name, verified=False,
                            error="No api_key in stored credentials.")
    try:
        import requests as _req
        res = _req.get(
            "https://api.sendgrid.com/v3/user/account",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if res.status_code == 200:
            data = res.json()
            return TestResponse(
                status="CONNECTED",
                app_name=app_name,
                verified=True,
                display_name=data.get("username"),
            )
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(f"SendGrid returned HTTP {res.status_code}", secrets))
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


def _test_smtp(app_name: str, cred: dict) -> TestResponse:
    """Verify SMTP credentials by opening a connection and authenticating (no email sent)."""
    secrets = [cred.get("password")]
    host = cred.get("host", "")
    port = int(cred.get("port") or 587)
    username = cred.get("username", "")
    password = cred.get("password", "")
    use_ssl = str(cred.get("use_ssl", "false")).lower() in ("true", "1", "yes") or port == 465

    if not host or not username or not password:
        return TestResponse(status="BLOCKED", app_name=app_name, verified=False,
                            error="Missing host, username, or password in stored credentials.")
    try:
        import smtplib
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        server.login(username, password)
        server.quit()
        return TestResponse(
            status="CONNECTED",
            app_name=app_name,
            verified=True,
            display_name=f"{username}@{host}",
        )
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


def _test_discord_sync(app_name: str, cred: dict) -> TestResponse:
    """Verify Discord bot token via /users/@me (synchronous wrapper)."""
    secrets = [cred.get("token")]
    token = cred.get("token", "")
    if not token:
        return TestResponse(status="BLOCKED", app_name=app_name, verified=False,
                            error="No token in stored Discord credentials.")
    try:
        import requests as _req
        res = _req.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=8,
        )
        if res.status_code == 200:
            data = res.json()
            return TestResponse(
                status="CONNECTED",
                app_name=app_name,
                verified=True,
                display_name=data.get("username"),
            )
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(f"Discord returned HTTP {res.status_code}", secrets))
    except Exception as exc:
        return TestResponse(status="AUTH_FAILED", app_name=app_name, verified=False,
                            error=_mask_secrets(str(exc), secrets))


# ---------------------------------------------------------------------------
# GET /credentials/readiness/{user_id}
# ---------------------------------------------------------------------------

@router.get("/readiness/{user_id}")
def get_readiness(user_id: str, db=Depends(get_db)):
    """
    Returns connected/verified status for all known distribution connectors.

    Used by the M3.5 Distribution Orchestrator to gate campaign execution:
    "Can this user execute this campaign?"

    Does NOT perform live API calls — returns stored credential existence only.
    For live verification use POST /credentials/test/{app_name}.
    """
    distribution_platforms = ["reddit", "twitter", "linkedin", "sendgrid", "smtp"]

    active_creds = get_connected_apps(db, user_id)
    connected_set = {c["app_name"] for c in active_creds}

    readiness: Dict[str, Dict[str, bool]] = {}
    for platform in distribution_platforms:
        readiness[platform] = {
            "connected": platform in connected_set,
            # verified = False here; use /test/{app_name} to set to True
            "verified": False,
        }

    return {
        "user_id": user_id,
        "connectors": readiness,
    }
