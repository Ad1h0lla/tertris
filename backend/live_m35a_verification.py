"""
M3.5-A Live Verification Script
================================

Tests ONLY authentication/identity checks — no posts, no emails, no writes.

Uses credentials from:
  1. DB (stored_credentials via credential_manager)
  2. Fallback to .env

Run:
    cd backend
    .venv-rebuild\\Scripts\\python.exe live_m35a_verification.py
"""

import os
import sys
import json
import logging

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from dotenv import load_dotenv
load_dotenv()

from database.models import init_db, SessionLocal
init_db()
db = SessionLocal()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("live_m35a")

RESULTS = []

def report(app, status, detail=""):
    icon = {
        "CONNECTED":   "[OK]",
        "AUTH_FAILED": "[FAIL]",
        "BLOCKED":     "[BLOCKED]",
        "UNSUPPORTED": "[SKIP]",
    }.get(status, "[?]")
    line = f"  {icon}  {app:<12}  {status:<12}  {detail}"
    # Use ascii-safe print for Windows cp1252 terminals
    print(line.encode("ascii", errors="replace").decode("ascii"))
    RESULTS.append({"app": app, "status": status, "detail": detail})


print("\n" + "="*60)
print("  TETRIS M3.5-A — LIVE CONNECTION VERIFICATION")
print("  Read-only identity checks only. No writes.")
print("="*60 + "\n")


# ── Reddit ─────────────────────────────────────────────────────────────────────
print("[Reddit]")
try:
    from execution.reddit_executor import resolve_reddit_credentials
    creds = resolve_reddit_credentials("user_001", db=db)
    if not (creds.get("client_id") and creds.get("client_secret")):
        report("reddit", "BLOCKED", "No credentials stored or in .env")
    else:
        try:
            import praw
            r = praw.Reddit(
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
                username=creds.get("username"),
                password=creds.get("password"),
                user_agent=creds.get("user_agent") or "TetrisVerify/1.0",
            )
            me = r.user.me()
            report("reddit", "CONNECTED", f"u/{me.name}" if me else "identity: unknown")
        except ImportError:
            report("reddit", "BLOCKED", "praw not installed")
        except Exception as e:
            clean = str(e)[:120].replace(creds.get("client_secret","????"), "[REDACTED]").replace(creds.get("password","????"), "[REDACTED]")
            report("reddit", "AUTH_FAILED", clean)
except Exception as e:
    report("reddit", "BLOCKED", str(e)[:80])


# ── X/Twitter ──────────────────────────────────────────────────────────────────
print("\n[X / Twitter]")
try:
    from execution.x_executor import resolve_x_credentials
    creds = resolve_x_credentials("user_001", db=db)
    if not (creds.get("api_key") and creds.get("api_secret")):
        report("twitter", "BLOCKED", "No credentials stored or in .env")
    else:
        try:
            import tweepy
            client = tweepy.Client(
                consumer_key=creds["api_key"],
                consumer_secret=creds["api_secret"],
                access_token=creds.get("access_token"),
                access_token_secret=creds.get("access_token_secret"),
                bearer_token=creds.get("bearer_token"),
                wait_on_rate_limit=False,
            )
            me = client.get_me()
            if me and me.data:
                report("twitter", "CONNECTED", f"@{me.data.username}")
            else:
                report("twitter", "AUTH_FAILED", "No identity returned")
        except ImportError:
            report("twitter", "BLOCKED", "tweepy not installed")
        except Exception as e:
            secrets = [creds.get("api_secret",""), creds.get("access_token_secret",""), creds.get("bearer_token","")]
            clean = str(e)[:120]
            for s in secrets:
                if s: clean = clean.replace(s, "[REDACTED]")
            report("twitter", "AUTH_FAILED", clean)
except Exception as e:
    report("twitter", "BLOCKED", str(e)[:80])


# ── LinkedIn ───────────────────────────────────────────────────────────────────
print("\n[LinkedIn]")
try:
    from execution.linkedin_executor import resolve_linkedin_credentials
    creds = resolve_linkedin_credentials("user_001", db=db)
    if not creds.get("access_token"):
        report("linkedin", "BLOCKED", "No credentials stored or in .env")
    else:
        try:
            import requests
            res = requests.get(
                "https://api.linkedin.com/v2/me",
                headers={
                    "Authorization": f"Bearer {creds['access_token']}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                name = f"{data.get('localizedFirstName','')} {data.get('localizedLastName','')}".strip()
                report("linkedin", "CONNECTED", name or "identity: ok")
            else:
                report("linkedin", "AUTH_FAILED", f"HTTP {res.status_code}")
        except Exception as e:
            clean = str(e)[:120].replace(creds.get("access_token","????"), "[REDACTED]")
            report("linkedin", "AUTH_FAILED", clean)
except Exception as e:
    report("linkedin", "BLOCKED", str(e)[:80])


# ── SendGrid ───────────────────────────────────────────────────────────────────
print("\n[SendGrid]")
try:
    from execution.email_executor import resolve_sendgrid_credentials
    creds = resolve_sendgrid_credentials("user_001", db=db)
    if not creds.get("api_key"):
        report("sendgrid", "BLOCKED", "No credentials stored or in .env")
    else:
        try:
            import requests
            res = requests.get(
                "https://api.sendgrid.com/v3/user/account",
                headers={"Authorization": f"Bearer {creds['api_key']}"},
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                report("sendgrid", "CONNECTED", f"account: {data.get('username','unknown')}")
            else:
                report("sendgrid", "AUTH_FAILED", f"HTTP {res.status_code}")
        except Exception as e:
            clean = str(e)[:120].replace(creds.get("api_key","????"), "[REDACTED]")
            report("sendgrid", "AUTH_FAILED", clean)
except Exception as e:
    report("sendgrid", "BLOCKED", str(e)[:80])


# ── SMTP ───────────────────────────────────────────────────────────────────────
print("\n[SMTP]")
try:
    from execution.email_executor import resolve_smtp_credentials
    creds = resolve_smtp_credentials("user_001", db=db)
    if not (creds.get("host") and creds.get("username") and creds.get("password")):
        report("smtp", "BLOCKED", "No credentials stored or in .env")
    else:
        try:
            import smtplib
            host = creds["host"]
            port = int(creds.get("port") or 587)
            use_ssl = str(creds.get("use_ssl","false")).lower() in ("true","1") or port == 465
            if use_ssl:
                srv = smtplib.SMTP_SSL(host, port, timeout=10)
            else:
                srv = smtplib.SMTP(host, port, timeout=10)
                srv.starttls()
            srv.login(creds["username"], creds["password"])
            srv.quit()
            report("smtp", "CONNECTED", f"{creds['username']}@{host}")
        except Exception as e:
            clean = str(e)[:120].replace(creds.get("password","????"), "[REDACTED]")
            report("smtp", "AUTH_FAILED", clean)
except Exception as e:
    report("smtp", "BLOCKED", str(e)[:80])


# ── DB health ──────────────────────────────────────────────────────────────────
print("\n[DB / stored_credentials]")
try:
    from integrations.credential_manager import get_connected_apps
    apps = get_connected_apps(db, "user_001")
    report("db_health", "CONNECTED", f"{len(apps)} credential(s) stored for user_001")
except Exception as e:
    report("db_health", "BLOCKED", str(e)[:80])


db.close()

print("\n" + "-"*60)
connected = sum(1 for r in RESULTS if r["status"] == "CONNECTED")
blocked   = sum(1 for r in RESULTS if r["status"] == "BLOCKED")
failed    = sum(1 for r in RESULTS if r["status"] == "AUTH_FAILED")
print(f"  CONNECTED: {connected}  |  AUTH_FAILED: {failed}  |  BLOCKED (no creds): {blocked}")
print("  Note: BLOCKED means no credentials provided — not a code error.")
print("        AUTH_FAILED means credentials exist but were rejected by the provider.")
print("-"*60 + "\n")
