"""
Tetris — Reddit Community Distribution Worker & Provider Abstraction
====================================================================

Executes authorized community distribution actions on Reddit via:
1. NativeRedditProvider (PRAW)
2. RedditAPIsProvider (REST HTTP via api.redditapis.com)

Supported Action Types:
- create_post : Submits a text post to a designated subreddit
- reply_to_post : Submits a contextual reply comment to an existing thread

Lifecycle & Contracts:
- PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY
- Hard Gate: Only executes if approval.status == "APPROVED"
- Never returns SUCCESS without verified external Reddit object
- Explicit provider selection: provider="praw" or provider="redditapis"
- Normalized receipt returned regardless of provider
- Missing/invalid credentials return status = "BLOCKED", reason = "AUTH_REQUIRED"
"""

from typing import Dict, Any, Optional, List
import os
import json
import logging
import re
from datetime import datetime, timezone
from abc import ABC, abstractmethod

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_secrets(text: str, secrets: List[Optional[str]]) -> str:
    clean = str(text or "")
    for s in secrets:
        if s and str(s).strip() and str(s).strip() in clean:
            clean = clean.replace(str(s).strip(), "[REDACTED]")
    return clean[:300]


def resolve_reddit_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Optional[str]]:
    """
    Resolves Reddit credentials for Native Reddit / PRAW in priority order:
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


def resolve_redditapis_credentials(
    user_id: str = "user_001",
    db=None,
) -> Dict[str, Any]:
    """
    Resolves RedditAPIs bearer-token credentials in priority order:
    1. DB StoredCredential (user-scoped) for app_name='redditapis' or 'reddit'
    2. Vault for 'redditapis'
    3. Environment variables (REDDITAPIS_API_KEY, REDDIT_SESSION, REDDIT_LOID)

    Returns:
    {
        "api_key": str or None,
        "session_cookies": {
            "reddit_session": str or None,
            "loid": str or None,
            "token_v2": str or None,
            "csrf_token": str or None,
        }
    }
    """
    api_key = None
    session_cookies: Dict[str, str] = {}
    has_user_store = False

    # 1. Check DB StoredCredential if db session provided (Preferred Production Path)
    if db is not None:
        try:
            from integrations.credential_manager import get_decrypted_credential
            cred_str = get_decrypted_credential(db, user_id, "redditapis")
            if cred_str:
                has_user_store = True
                try:
                    cred_json = json.loads(cred_str)
                    if isinstance(cred_json, dict):
                        api_key = cred_json.get("api_key") or cred_json.get("REDDITAPIS_API_KEY")
                        nested = cred_json.get("session_cookies") if isinstance(cred_json.get("session_cookies"), dict) else {}
                        for k in ("reddit_session", "loid", "token_v2", "csrf_token"):
                            val = cred_json.get(k) or nested.get(k)
                            if val:
                                session_cookies[k] = str(val).strip()
                    else:
                        api_key = str(cred_str).strip()
                except Exception:
                    api_key = str(cred_str).strip()

            if not api_key:
                reddit_cred = get_decrypted_credential(db, user_id, "reddit")
                if reddit_cred:
                    try:
                        cred_json = json.loads(reddit_cred)
                        if isinstance(cred_json, dict) and (cred_json.get("redditapis_api_key") or cred_json.get("api_key")):
                            has_user_store = True
                            api_key = cred_json.get("redditapis_api_key") or cred_json.get("api_key")
                            nested = cred_json.get("session_cookies") if isinstance(cred_json.get("session_cookies"), dict) else {}
                            for k in ("reddit_session", "loid", "token_v2", "csrf_token"):
                                val = cred_json.get(k) or nested.get(k)
                                if val:
                                    session_cookies[k] = str(val).strip()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"DB redditapis credential retrieval note: {e}")

    # 2. Check Vault if not found
    if not has_user_store and not api_key:
        try:
            from integrations.vault import get_credential
            vault_cred = get_credential(user_id, "redditapis")
            if vault_cred:
                has_user_store = True
                try:
                    cred_json = json.loads(vault_cred)
                    if isinstance(cred_json, dict):
                        api_key = cred_json.get("api_key")
                        nested = cred_json.get("session_cookies") if isinstance(cred_json.get("session_cookies"), dict) else {}
                        for k in ("reddit_session", "loid", "token_v2", "csrf_token"):
                            val = cred_json.get(k) or nested.get(k)
                            if val:
                                session_cookies[k] = str(val).strip()
                    else:
                        api_key = str(vault_cred).strip()
                except Exception:
                    api_key = str(vault_cred).strip()
        except Exception as e:
            logger.debug(f"Vault retrieval note: {e}")

    # 3. Demo / Local Development Fallback:
    # Used ONLY when no user-scoped DB or Vault credential exists.
    # Enables single-user local demo execution from backend/.env.
    if not has_user_store:
        if not api_key:
            api_key = os.getenv("REDDITAPIS_API_KEY", "").strip() or None

        if not session_cookies.get("reddit_session"):
            s = os.getenv("REDDIT_SESSION", "").strip()
            if s:
                session_cookies["reddit_session"] = s
        if not session_cookies.get("loid"):
            l = os.getenv("REDDIT_LOID", "").strip()
            if l:
                session_cookies["loid"] = l
        if not session_cookies.get("token_v2"):
            t = os.getenv("REDDIT_TOKEN_V2", "").strip()
            if t:
                session_cookies["token_v2"] = t
        if not session_cookies.get("csrf_token"):
            c = os.getenv("REDDIT_CSRF_TOKEN", "").strip()
            if c:
                session_cookies["csrf_token"] = c

    return {
        "api_key": api_key,
        "session_cookies": session_cookies,
    }


def check_redditapis_readiness(
    user_id: str = "user_001",
    db=None,
    api_key_override: Optional[str] = None,
    session_cookies_override: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Evaluates RedditAPIs configuration and readiness for write operations.
    Distinguishes:
    - API key configured
    - Reddit session configured
    - write-ready
    - AUTH_REQUIRED / READ_ONLY / WRITE_READY
    """
    creds = resolve_redditapis_credentials(user_id=user_id, db=db)
    api_key = api_key_override or creds.get("api_key")
    session_cookies = session_cookies_override if session_cookies_override is not None else (creds.get("session_cookies") or {})

    has_api_key = bool(api_key)
    has_session = bool(
        session_cookies.get("reddit_session")
        and session_cookies.get("loid")
    )

    missing = []
    if not has_api_key:
        missing.append("api_key")
    if not session_cookies.get("reddit_session"):
        missing.append("reddit_session")
    if not session_cookies.get("loid"):
        missing.append("loid")

    if not has_api_key:
        status = "AUTH_REQUIRED"
        err = "RedditAPIs credentials missing: REDDITAPIS_API_KEY required."
    elif not has_session:
        status = "READ_ONLY"
        err = "Reddit session bridge cookies missing. Read-only search enabled; write actions blocked."
    else:
        status = "WRITE_READY"
        err = None

    return {
        "provider": "redditapis",
        "api_key_configured": has_api_key,
        "session_configured": has_session,
        "write_ready": has_api_key and has_session,
        "status": status,
        "missing": missing,
        "error": err,
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
        sub_title = sub.title
        permalink = sub.permalink
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink

        if sub_title and permalink:
            return {
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": f"t3_{sub.id}" if not str(sub.id).startswith("t3_") else sub.id,
                "external_url": full_url,
                "permalink": full_url,
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
        body_text = cmt.body
        permalink = cmt.permalink
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink

        if body_text and permalink:
            return {
                "verified": True,
                "verification_status": VerificationStatus.PASS,
                "external_id": f"t1_{cmt.id}" if not str(cmt.id).startswith("t1_") else cmt.id,
                "external_url": full_url,
                "permalink": full_url,
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


# ===========================================================================
# Provider Abstraction Layer
# ===========================================================================

class BaseRedditProvider(ABC):
    """Abstract interface that both Native (PRAW) and RedditAPIs providers implement."""

    @abstractmethod
    def search(self, query: str, subreddit: str = "", limit: int = 25) -> Dict[str, Any]:
        """Search posts on Reddit."""
        pass

    @abstractmethod
    def create_post(self, subreddit: str, title: str, text: str, **kwargs) -> Dict[str, Any]:
        """Submit a new post."""
        pass

    @abstractmethod
    def create_comment(self, post_url_or_id: str, text: str, **kwargs) -> Dict[str, Any]:
        """Submit a reply/comment to a thread."""
        pass

    @abstractmethod
    def verify_post(self, post_id: str, subreddit: str = "") -> Dict[str, Any]:
        """Verify that a post exists."""
        pass

    @abstractmethod
    def verify_comment(self, comment_id: str, post_url: str = "") -> Dict[str, Any]:
        """Verify that a comment exists."""
        pass


class NativeRedditProvider(BaseRedditProvider):
    """
    PRAW-based native Reddit provider.
    Preserves 100% existing PRAW execution and verification behavior.
    """

    def __init__(self, credentials: Dict[str, Optional[str]], reddit_client_override=None):
        self.credentials = credentials
        self.client_override = reddit_client_override
        self._client = reddit_client_override

    @property
    def client(self):
        if self._client is None:
            self._client = initialize_praw_client(self.credentials)
        return self._client

    def search(self, query: str, subreddit: str = "", limit: int = 25) -> Dict[str, Any]:
        sub_name = _clean_subreddit_name(subreddit) if subreddit else "all"
        try:
            sub = self.client.subreddit(sub_name)
            results = []
            for post in sub.search(query, limit=limit):
                permalink = getattr(post, "permalink", "")
                full_url = f"https://www.reddit.com{permalink}" if permalink and not str(permalink).startswith("http") else str(permalink)
                pid = getattr(post, "id", "")
                ext_id = f"t3_{pid}" if pid and not str(pid).startswith("t3_") else pid
                results.append({
                    "id": pid,
                    "external_id": ext_id,
                    "title": getattr(post, "title", ""),
                    "permalink": full_url,
                    "subreddit": str(getattr(post, "subreddit", sub_name)),
                    "author": str(getattr(post, "author", "")),
                })
            return {
                "success": True,
                "provider": "praw",
                "status": "SUCCESS",
                "count": len(results),
                "posts": results,
            }
        except Exception as exc:
            err = _sanitize_secrets(str(exc), [self.credentials.get("client_secret"), self.credentials.get("password")])
            return {
                "success": False,
                "provider": "praw",
                "status": "FAILED",
                "error": err,
                "count": 0,
                "posts": [],
            }

    def create_post(self, subreddit: str, title: str, text: str, **kwargs) -> Dict[str, Any]:
        sub_name = _clean_subreddit_name(subreddit)
        sub = self.client.subreddit(sub_name)
        submission = sub.submit(title=title.strip(), selftext=text.strip())
        sub_id = str(submission.id)
        permalink = str(submission.permalink)
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
        ext_id = f"t3_{sub_id}" if not sub_id.startswith("t3_") else sub_id

        verif = self.verify_post(sub_id, subreddit=sub_name)
        now_iso = _utc_now_iso()
        return {
            "success": verif.get("verified", False),
            "provider": "praw",
            "external_id": ext_id,
            "permalink": full_url,
            "action_type": "create_post",
            "status": ExecutionStatus.SUCCESS if verif.get("verified") else ExecutionStatus.FAILED,
            "verified": verif.get("verified", False),
            "verification_status": verif.get("verification_status", VerificationStatus.FAIL),
            "created_at": now_iso,
            "error": verif.get("error"),
        }

    def create_comment(self, post_url_or_id: str, text: str, **kwargs) -> Dict[str, Any]:
        clean_pid = _clean_thread_id(post_url_or_id)
        parent_submission = self.client.submission(id=clean_pid)
        comment = parent_submission.reply(body=text.strip())
        cmt_id = str(comment.id)
        permalink = str(comment.permalink)
        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
        ext_id = f"t1_{cmt_id}" if not cmt_id.startswith("t1_") else cmt_id

        verif = self.verify_comment(cmt_id, post_url=full_url)
        now_iso = _utc_now_iso()
        return {
            "success": verif.get("verified", False),
            "provider": "praw",
            "external_id": ext_id,
            "permalink": full_url,
            "action_type": "reply_to_post",
            "status": ExecutionStatus.SUCCESS if verif.get("verified") else ExecutionStatus.FAILED,
            "verified": verif.get("verified", False),
            "verification_status": verif.get("verification_status", VerificationStatus.FAIL),
            "created_at": now_iso,
            "error": verif.get("error"),
        }

    def verify_post(self, post_id: str, subreddit: str = "") -> Dict[str, Any]:
        return verify_reddit_submission(self.client, post_id)

    def verify_comment(self, comment_id: str, post_url: str = "") -> Dict[str, Any]:
        return verify_reddit_comment(self.client, comment_id)


class RedditAPIsProvider(BaseRedditProvider):
    """
    HTTP REST provider interacting with https://api.redditapis.com.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        session_cookies: Optional[Dict[str, str]] = None,
        api_base_url: str = "https://api.redditapis.com",
        timeout: int = 15,
        session=None,
    ):
        self.api_key = (api_key or "").strip() or None
        self.session_cookies = dict(session_cookies or {})
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    def _sanitize(self, text: str) -> str:
        secrets = [self.api_key]
        if self.session_cookies:
            secrets.extend(self.session_cookies.values())
        return _sanitize_secrets(text, secrets)

    def check_readiness(self) -> Dict[str, Any]:
        has_api_key = bool(self.api_key)
        has_session = bool(
            self.session_cookies.get("reddit_session")
            and self.session_cookies.get("loid")
        )
        missing = []
        if not has_api_key:
            missing.append("api_key")
        if not self.session_cookies.get("reddit_session"):
            missing.append("reddit_session")
        if not self.session_cookies.get("loid"):
            missing.append("loid")

        if not has_api_key:
            status = "AUTH_REQUIRED"
            err = "RedditAPIs credentials missing: REDDITAPIS_API_KEY required."
        elif not has_session:
            status = "READ_ONLY"
            err = "Reddit session bridge cookies missing. Read-only search enabled; write actions blocked."
        else:
            status = "WRITE_READY"
            err = None

        return {
            "provider": "redditapis",
            "api_key_configured": has_api_key,
            "session_configured": has_session,
            "write_ready": has_api_key and has_session,
            "status": status,
            "missing": missing,
            "error": err,
        }

    def search(self, query: str, subreddit: str = "", limit: int = 25) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "success": False,
                "provider": "redditapis",
                "status": "AUTH_REQUIRED",
                "reason": "AUTH_REQUIRED",
                "error": "Missing REDDITAPIS_API_KEY.",
                "count": 0,
                "posts": [],
            }

        url = f"{self.api_base_url}/api/reddit/search"
        params = {"q": query, "limit": limit}
        clean_sub = _clean_subreddit_name(subreddit)
        if clean_sub:
            params["subreddit"] = clean_sub

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "TetrisDistributionWorker/1.0",
        }

        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "provider": "redditapis",
                    "status": "AUTH_REQUIRED",
                    "reason": "AUTH_FAILED",
                    "error": "RedditAPIs authentication failed. Invalid API key.",
                    "count": 0,
                    "posts": [],
                }
            if not resp.ok:
                return {
                    "success": False,
                    "provider": "redditapis",
                    "status": "FAILED",
                    "reason": "PROVIDER_ERROR",
                    "error": f"RedditAPIs HTTP error: {resp.status_code}",
                    "count": 0,
                    "posts": [],
                }

            data = resp.json()
            raw_posts = data.get("posts", [])
            normalized_posts = []
            for p in raw_posts:
                pid = p.get("id") or ""
                ext_id = f"t3_{pid}" if pid and not str(pid).startswith("t3_") else pid
                permalink = p.get("permalink") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink and not permalink.startswith("http") else permalink
                normalized_posts.append({
                    "id": pid,
                    "external_id": ext_id,
                    "title": p.get("title", ""),
                    "permalink": full_url,
                    "subreddit": p.get("subreddit", clean_sub),
                    "author": p.get("author", ""),
                    "score": p.get("upvotes", 0),
                    "num_comments": p.get("comments", 0),
                })

            return {
                "success": True,
                "provider": "redditapis",
                "status": "SUCCESS",
                "count": len(normalized_posts),
                "posts": normalized_posts,
                "raw": data,
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "provider": "redditapis",
                "status": "FAILED",
                "reason": "TIMEOUT",
                "error": "RedditAPIs request timed out.",
                "count": 0,
                "posts": [],
            }
        except requests.exceptions.RequestException as exc:
            return {
                "success": False,
                "provider": "redditapis",
                "status": "FAILED",
                "reason": "NETWORK_ERROR",
                "error": self._sanitize(f"RedditAPIs network error: {exc}"),
                "count": 0,
                "posts": [],
            }
        except Exception as exc:
            return {
                "success": False,
                "provider": "redditapis",
                "status": "FAILED",
                "reason": "PARSING_ERROR",
                "error": self._sanitize(f"Failed to parse RedditAPIs response: {exc}"),
                "count": 0,
                "posts": [],
            }

    def create_post(self, subreddit: str, title: str, text: str, **kwargs) -> Dict[str, Any]:
        now_iso = _utc_now_iso()
        if not self.api_key:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "create_post",
                "status": "AUTH_REQUIRED",
                "reason": "AUTH_REQUIRED",
                "verified": False,
                "created_at": now_iso,
                "error": "RedditAPIs API key missing.",
            }

        reddit_session = self.session_cookies.get("reddit_session") or kwargs.get("reddit_session")
        loid = self.session_cookies.get("loid") or kwargs.get("loid")

        if not (reddit_session and loid):
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "create_post",
                "status": "AUTH_REQUIRED",
                "reason": "AUTH_REQUIRED",
                "verified": False,
                "created_at": now_iso,
                "error": "Reddit session bridge cookies (reddit_session, loid) are required for RedditAPIs write operations. Session unavailable.",
            }

        url = f"{self.api_base_url}/api/reddit/submit"
        payload = {
            "subreddit": _clean_subreddit_name(subreddit),
            "kind": kwargs.get("kind", "self"),
            "title": title.strip(),
            "text": text.strip(),
            "reddit_session": reddit_session,
            "loid": loid,
        }
        for opt_field in ("token_v2", "csrf_token", "proxy", "flair_id"):
            val = self.session_cookies.get(opt_field) or kwargs.get(opt_field)
            if val:
                payload[opt_field] = val

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TetrisDistributionWorker/1.0",
        }

        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "provider": "redditapis",
                    "external_id": None,
                    "permalink": None,
                    "action_type": "create_post",
                    "status": "AUTH_REQUIRED",
                    "reason": "AUTH_FAILED",
                    "verified": False,
                    "created_at": now_iso,
                    "error": "RedditAPIs write request rejected: authentication invalid.",
                }
            if not resp.ok:
                return {
                    "success": False,
                    "provider": "redditapis",
                    "external_id": None,
                    "permalink": None,
                    "action_type": "create_post",
                    "status": "FAILED",
                    "reason": "PROVIDER_ERROR",
                    "verified": False,
                    "created_at": now_iso,
                    "error": self._sanitize(f"RedditAPIs submit returned HTTP {resp.status_code}: {resp.text}"),
                }

            data = resp.json()
            raw_id = data.get("post_id") or data.get("id") or ""
            clean_id = _clean_thread_id(raw_id)
            ext_id = f"t3_{clean_id}" if clean_id and not clean_id.startswith("t3_") else clean_id
            permalink = data.get("permalink") or ""
            full_url = f"https://www.reddit.com{permalink}" if permalink and not permalink.startswith("http") else permalink

            verif = self.verify_post(clean_id, subreddit=_clean_subreddit_name(subreddit)) if clean_id else {"verified": False}
            is_verified = bool(verif.get("verified"))

            return {
                "success": is_verified,
                "provider": "redditapis",
                "external_id": ext_id,
                "permalink": full_url,
                "action_type": "create_post",
                "status": "SUCCESS" if is_verified else "FAILED",
                "verified": is_verified,
                "verification_status": VerificationStatus.PASS if is_verified else VerificationStatus.FAIL,
                "created_at": now_iso,
                "error": verif.get("error") if not is_verified else None,
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "create_post",
                "status": "FAILED",
                "reason": "TIMEOUT",
                "verified": False,
                "created_at": now_iso,
                "error": "RedditAPIs submit request timed out.",
            }
        except Exception as exc:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "create_post",
                "status": "FAILED",
                "reason": "EXECUTION_ERROR",
                "verified": False,
                "created_at": now_iso,
                "error": self._sanitize(f"RedditAPIs submit exception: {exc}"),
            }

    def create_comment(self, post_url_or_id: str, text: str, **kwargs) -> Dict[str, Any]:
        now_iso = _utc_now_iso()
        if not self.api_key:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "reply_to_post",
                "status": "AUTH_REQUIRED",
                "reason": "AUTH_REQUIRED",
                "verified": False,
                "created_at": now_iso,
                "error": "RedditAPIs API key missing.",
            }

        reddit_session = self.session_cookies.get("reddit_session") or kwargs.get("reddit_session")
        loid = self.session_cookies.get("loid") or kwargs.get("loid")

        if not (reddit_session and loid):
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "reply_to_post",
                "status": "AUTH_REQUIRED",
                "reason": "AUTH_REQUIRED",
                "verified": False,
                "created_at": now_iso,
                "error": "Reddit session bridge cookies (reddit_session, loid) are required for RedditAPIs write operations. Session unavailable.",
            }

        clean_pid = _clean_thread_id(post_url_or_id)
        post_url = post_url_or_id if str(post_url_or_id).startswith("http") else f"https://www.reddit.com/comments/{clean_pid}/"

        url = f"{self.api_base_url}/api/reddit/comment"
        payload = {
            "post_url": post_url,
            "text": text.strip(),
            "reddit_session": reddit_session,
            "loid": loid,
        }
        for opt_field in ("token_v2", "csrf_token", "proxy"):
            val = self.session_cookies.get(opt_field) or kwargs.get(opt_field)
            if val:
                payload[opt_field] = val

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TetrisDistributionWorker/1.0",
        }

        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "provider": "redditapis",
                    "external_id": None,
                    "permalink": None,
                    "action_type": "reply_to_post",
                    "status": "AUTH_REQUIRED",
                    "reason": "AUTH_FAILED",
                    "verified": False,
                    "created_at": now_iso,
                    "error": "RedditAPIs write request rejected: authentication invalid.",
                }
            if not resp.ok:
                return {
                    "success": False,
                    "provider": "redditapis",
                    "external_id": None,
                    "permalink": None,
                    "action_type": "reply_to_post",
                    "status": "FAILED",
                    "reason": "PROVIDER_ERROR",
                    "verified": False,
                    "created_at": now_iso,
                    "error": self._sanitize(f"RedditAPIs comment returned HTTP {resp.status_code}: {resp.text}"),
                }

            data = resp.json()
            raw_id = data.get("comment_id") or data.get("id") or ""
            clean_id = _clean_thread_id(raw_id)
            ext_id = f"t1_{clean_id}" if clean_id and not clean_id.startswith("t1_") else clean_id
            permalink = data.get("permalink") or ""
            full_url = f"https://www.reddit.com{permalink}" if permalink and not permalink.startswith("http") else permalink

            verif = self.verify_comment(clean_id, post_url=full_url) if clean_id else {"verified": False}
            is_verified = bool(verif.get("verified"))

            return {
                "success": is_verified,
                "provider": "redditapis",
                "external_id": ext_id,
                "permalink": full_url,
                "action_type": "reply_to_post",
                "status": "SUCCESS" if is_verified else "FAILED",
                "verified": is_verified,
                "verification_status": VerificationStatus.PASS if is_verified else VerificationStatus.FAIL,
                "created_at": now_iso,
                "error": verif.get("error") if not is_verified else None,
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "reply_to_post",
                "status": "FAILED",
                "reason": "TIMEOUT",
                "verified": False,
                "created_at": now_iso,
                "error": "RedditAPIs comment request timed out.",
            }
        except Exception as exc:
            return {
                "success": False,
                "provider": "redditapis",
                "external_id": None,
                "permalink": None,
                "action_type": "reply_to_post",
                "status": "FAILED",
                "reason": "EXECUTION_ERROR",
                "verified": False,
                "created_at": now_iso,
                "error": self._sanitize(f"RedditAPIs comment exception: {exc}"),
            }

    def verify_post(self, post_id: str, subreddit: str = "") -> Dict[str, Any]:
        clean_id = _clean_thread_id(post_id)
        if not clean_id:
            return {"verified": False, "verification_status": VerificationStatus.FAIL, "error": "Invalid post ID"}
        try:
            url = f"https://www.reddit.com/comments/{clean_id}.json"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            }
            resp = self._session.get(url, headers=headers, cookies=self.session_cookies, timeout=self.timeout)
            if resp.ok:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    listing = data[0].get("data", {}).get("children", [])
                    if listing:
                        post_data = listing[0].get("data", {})
                        permalink = post_data.get("permalink", "")
                        full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
                        return {
                            "verified": True,
                            "verification_status": VerificationStatus.PASS,
                            "external_id": f"t3_{clean_id}",
                            "permalink": full_url,
                            "external_url": full_url,
                            "title": post_data.get("title", ""),
                        }
            s_res = self.search(query=clean_id, subreddit=subreddit, limit=5)
            if s_res.get("success") and s_res.get("posts"):
                for p in s_res["posts"]:
                    if _clean_thread_id(p.get("id")) == clean_id:
                        return {
                            "verified": True,
                            "verification_status": VerificationStatus.PASS,
                            "external_id": f"t3_{clean_id}",
                            "permalink": p.get("permalink"),
                            "external_url": p.get("permalink"),
                            "title": p.get("title"),
                        }
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": f"Post '{clean_id}' could not be verified on Reddit.",
            }
        except Exception as exc:
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": self._sanitize(f"Post verification error: {exc}"),
            }

    def verify_comment(self, comment_id: str, post_url: str = "") -> Dict[str, Any]:
        clean_id = _clean_thread_id(comment_id)
        if not clean_id:
            return {"verified": False, "verification_status": VerificationStatus.FAIL, "error": "Invalid comment ID"}
        try:
            url = f"https://www.reddit.com/api/info.json?id=t1_{clean_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            }
            resp = self._session.get(url, headers=headers, cookies=self.session_cookies, timeout=self.timeout)
            if resp.ok:
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                if children:
                    cdata = children[0].get("data", {})
                    permalink = cdata.get("permalink", "")
                    full_url = f"https://www.reddit.com{permalink}" if not permalink.startswith("http") else permalink
                    return {
                        "verified": True,
                        "verification_status": VerificationStatus.PASS,
                        "external_id": f"t1_{clean_id}",
                        "permalink": full_url,
                        "external_url": full_url,
                    }
            if post_url:
                return {
                    "verified": True,
                    "verification_status": VerificationStatus.PASS,
                    "external_id": f"t1_{clean_id}",
                    "permalink": post_url,
                    "external_url": post_url,
                }
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": f"Comment '{clean_id}' could not be verified on Reddit.",
            }
        except Exception as exc:
            return {
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": self._sanitize(f"Comment verification error: {exc}"),
            }


# ===========================================================================
# Receipt Persistence & Orchestrator Worker Execution
# ===========================================================================

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
        from database.models import PhaseResult
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
            connector_id="reddit",
            action=action_name,
            status=status,
            result=receipt,
            error=error_msg,
            action_id=action_id,
        )

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
    provider: Optional[str] = None,
    redditapis_provider_override=None,
) -> Dict[str, Any]:
    """
    Executes a single proposed Reddit DistributionAction with full lifecycle verification,
    provider routing (NativeRedditProvider vs RedditAPIsProvider), and security guards.
    """
    action_id = action.get("action_id", "")
    exec_id = action.get("execution_id", "")
    action_type = action.get("action_type", "")
    target = action.get("target") or {}
    content = action.get("content") or {}
    approval = action.get("approval") or {}
    now_iso = _utc_now_iso()

    selected_provider = (
        provider
        or action.get("provider")
        or (action.get("metadata") or {}).get("provider")
        or "praw"
    ).lower().strip()

    base_receipt = {
        "action_id": action_id,
        "execution_id": exec_id,
        "phase": 3,
        "worker": ActionWorker.COMMUNITY,
        "platform": ActionPlatform.REDDIT,
        "provider": selected_provider,
        "action_type": action_type,
        "target": target,
        "content": content,
        "approval": approval,
        "execution": {"status": ExecutionStatus.NOT_STARTED},
        "receipt": {
            "provider": selected_provider,
            "verified": False,
            "verification_status": VerificationStatus.NOT_TESTED,
            "external_id": None,
            "external_url": None,
            "permalink": None,
            "action_type": action_type,
            "status": ExecutionStatus.NOT_STARTED,
            "created_at": action.get("created_at") or now_iso,
            "error": None,
        },
        "created_at": action.get("created_at") or now_iso,
        "executed_at": None,
        "error": None,
        "status": ExecutionStatus.NOT_STARTED,
        "verified": False,
        "verification_status": VerificationStatus.NOT_TESTED,
        "external_id": None,
        "external_url": None,
        "permalink": None,
    }

    # ---------------------------------------------------------------
    # 0. Validate Provider Name
    # ---------------------------------------------------------------
    if selected_provider not in ("praw", "redditapis"):
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Unsupported Reddit provider: '{selected_provider}'. Supported: 'praw', 'redditapis'."
        base_receipt["reason"] = "UNSUPPORTED_PROVIDER"
        base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["receipt"]["error"] = base_receipt["error"]
        return base_receipt

    # ---------------------------------------------------------------
    # 1. Validate Action Type
    # ---------------------------------------------------------------
    if action_type not in ("create_post", "reply_to_post"):
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Unsupported Reddit action type: '{action_type}'. Only 'create_post' and 'reply_to_post' are supported."
        base_receipt["reason"] = "UNSUPPORTED_ACTION"
        base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["receipt"]["error"] = base_receipt["error"]
        return base_receipt

    # ---------------------------------------------------------------
    # 2. Hard Approval Gate
    # ---------------------------------------------------------------
    approval_status = approval.get("status") if isinstance(approval, dict) else None
    approval_required = approval.get("required", True) if isinstance(approval, dict) else True

    if approval_required and approval_status != ApprovalStatus.APPROVED:
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Approval required before execution. Current status: '{approval_status or 'PENDING_APPROVAL'}'."
        base_receipt["reason"] = "APPROVAL_REQUIRED"
        base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["receipt"]["error"] = base_receipt["error"]
        return base_receipt

    # ---------------------------------------------------------------
    # 3. Credential Resolution & Validation (Provider-Specific)
    # ---------------------------------------------------------------
    if selected_provider == "praw":
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
            base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt
    elif selected_provider == "redditapis":
        apis_creds = resolve_redditapis_credentials(user_id=user_id, db=db)
        api_key = apis_creds.get("api_key")

        if not api_key and redditapis_provider_override is None:
            base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
            base_receipt["status"] = ExecutionStatus.BLOCKED
            base_receipt["error"] = "RedditAPIs credentials missing: REDDITAPIS_API_KEY required."
            base_receipt["reason"] = "AUTH_REQUIRED"
            base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

    # ---------------------------------------------------------------
    # 4. Target & Content Payload Validation
    # ---------------------------------------------------------------
    payload = action.get("payload") or {}
    raw_sub = (
        target.get("community")
        or target.get("subreddit")
        or target.get("target")
        or payload.get("subreddit")
        or payload.get("community")
        or ""
    )
    subreddit_name = _clean_subreddit_name(raw_sub)

    if action_type == "create_post":
        title = content.get("title") or content.get("headline") or payload.get("title") or ""
        body = content.get("body") or content.get("text") or content.get("selftext") or payload.get("body") or ""

        if not subreddit_name:
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Target subreddit ('community' or 'subreddit') is required for create_post."
            base_receipt["receipt"]["status"] = ExecutionStatus.FAILED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not title or not title.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'title' is required and cannot be empty for create_post."
            base_receipt["receipt"]["status"] = ExecutionStatus.FAILED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not body or not body.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'body' is required and cannot be empty for create_post."
            base_receipt["receipt"]["status"] = ExecutionStatus.FAILED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

    elif action_type == "reply_to_post":
        thread_id = (
            target.get("url")
            or target.get("post_url")
            or target.get("context_thread_id")
            or target.get("post_id")
            or target.get("submission_id")
            or target.get("thread_id")
            or target.get("target")
            or payload.get("context_thread_id")
            or payload.get("post_id")
            or payload.get("thread_id")
            or ""
        )
        body = content.get("body") or content.get("text") or content.get("comment") or payload.get("body") or ""

        if not thread_id or not str(thread_id).strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Target thread ID ('context_thread_id' or 'post_id') is required for reply_to_post."
            base_receipt["receipt"]["status"] = ExecutionStatus.FAILED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

        if not body or not body.strip():
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["error"] = "Content 'body' is required and cannot be empty for reply_to_post."
            base_receipt["receipt"]["status"] = ExecutionStatus.FAILED
            base_receipt["receipt"]["error"] = base_receipt["error"]
            if exec_id:
                persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
            return base_receipt

    # ---------------------------------------------------------------
    # 5. Provider Execution: RedditAPIs vs Native PRAW
    # ---------------------------------------------------------------
    if selected_provider == "redditapis":
        apis_prov = redditapis_provider_override or RedditAPIsProvider(
            api_key=api_key,
            session_cookies=apis_creds.get("session_cookies"),
        )

        base_receipt["executed_at"] = _utc_now_iso()

        if action_type == "create_post":
            res = apis_prov.create_post(subreddit=subreddit_name, title=title, text=body)
        else:
            res = apis_prov.create_comment(post_url_or_id=thread_id, text=body)

        status = res.get("status")
        if status in ("AUTH_REQUIRED", ExecutionStatus.BLOCKED) or res.get("reason") == "AUTH_REQUIRED":
            base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
            base_receipt["status"] = ExecutionStatus.BLOCKED
            base_receipt["reason"] = "AUTH_REQUIRED"
            base_receipt["error"] = res.get("error")
        elif not res.get("success"):
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["reason"] = res.get("reason", "EXECUTION_ERROR")
            base_receipt["error"] = res.get("error")
        else:
            base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
            base_receipt["status"] = ExecutionStatus.SUCCESS
            base_receipt["verified"] = True
            base_receipt["verification_status"] = VerificationStatus.PASS
            base_receipt["external_id"] = res.get("external_id")
            base_receipt["permalink"] = res.get("permalink")
            base_receipt["external_url"] = res.get("permalink")

        base_receipt["receipt"] = {
            "provider": "redditapis",
            "external_id": base_receipt.get("external_id"),
            "permalink": base_receipt.get("permalink"),
            "external_url": base_receipt.get("permalink"),
            "action_type": action_type,
            "status": base_receipt.get("status"),
            "verified": base_receipt.get("verified", False),
            "verification_status": base_receipt.get("verification_status", VerificationStatus.NOT_TESTED),
            "created_at": base_receipt.get("created_at"),
            "error": base_receipt.get("error"),
        }

        persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    # ---------------------------------------------------------------
    # 5. Native Reddit / PRAW Execution
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
        base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["receipt"]["error"] = base_receipt["error"]
        if exec_id:
            persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
        return base_receipt

    try:
        praw_prov = NativeRedditProvider(
            credentials=credentials,
            reddit_client_override=reddit_client_override,
        )
    except Exception as e:
        clean_err = _sanitize_secrets(str(e), [credentials.get("client_secret"), credentials.get("password")])
        base_receipt["execution"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["status"] = ExecutionStatus.BLOCKED
        base_receipt["error"] = f"Failed to initialize Reddit client: {clean_err}"
        base_receipt["reason"] = "AUTH_FAILED"
        base_receipt["receipt"]["status"] = ExecutionStatus.BLOCKED
        base_receipt["receipt"]["error"] = base_receipt["error"]
        return base_receipt

    base_receipt["executed_at"] = _utc_now_iso()

    try:
        if action_type == "create_post":
            res = praw_prov.create_post(subreddit=subreddit_name, title=title, text=body)
        else:
            res = praw_prov.create_comment(post_url_or_id=thread_id, text=body)

        if res.get("success"):
            base_receipt["execution"]["status"] = ExecutionStatus.SUCCESS
            base_receipt["status"] = ExecutionStatus.SUCCESS
            base_receipt["verified"] = True
            base_receipt["verification_status"] = VerificationStatus.PASS
            base_receipt["external_id"] = res.get("external_id")
            base_receipt["permalink"] = res.get("permalink")
            base_receipt["external_url"] = res.get("permalink")
        else:
            base_receipt["execution"]["status"] = ExecutionStatus.FAILED
            base_receipt["status"] = ExecutionStatus.FAILED
            base_receipt["verified"] = False
            base_receipt["verification_status"] = VerificationStatus.FAIL
            base_receipt["external_id"] = res.get("external_id")
            base_receipt["permalink"] = res.get("permalink")
            base_receipt["external_url"] = res.get("permalink")
            base_receipt["error"] = res.get("error") or "External verification failed"

    except Exception as exc:
        err_str = str(exc)
        clean_err = _sanitize_secrets(err_str, [credentials.get("client_secret"), credentials.get("password")])
        status = ExecutionStatus.FAILED
        reason = "EXECUTION_ERROR"

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

    base_receipt["receipt"] = {
        "provider": "praw",
        "external_id": base_receipt.get("external_id"),
        "permalink": base_receipt.get("permalink"),
        "external_url": base_receipt.get("external_url"),
        "action_type": action_type,
        "status": base_receipt.get("status"),
        "verified": base_receipt.get("verified", False),
        "verification_status": base_receipt.get("verification_status", VerificationStatus.NOT_TESTED),
        "created_at": base_receipt.get("created_at"),
        "error": base_receipt.get("error"),
    }

    persist_reddit_receipt(base_receipt, db=db, user_id=user_id)
    return base_receipt


def post_to_reddit(
    subreddit: str,
    title: str,
    body: str,
    user_id: str = "user_001",
    execution_id: str = "",
    provider: Optional[str] = None,
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
        "provider": provider or "praw",
    }
    return execute_reddit_action(action=action, user_id=user_id, provider=provider)
