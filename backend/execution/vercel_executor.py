"""
Tetris Vercel Deployment Executor
=================================

Real deployment engine for launching generated web applications to Vercel.

Architecture & Principles:
- Executes REAL cloud deployments via Vercel Deployments API (v13).
- Strict Simulation Gate: Refuses deployment if pre-launch simulation status is FAIL.
- Real Post-Deployment Smoke Check: Issues live HTTP request to verify deployed URL resolves.
- Credential Security: Never logs, leaks, or returns Vercel tokens.
- Controlled Subprocess / API handling: Enforced timeouts, robust error mapping, sanitized outputs.
- Structured Result Contract for persistence and future Health monitoring.
"""

import os
import sys
import time
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    import requests
except ImportError:
    requests = None


def get_vercel_token() -> Optional[str]:
    """
    Safely retrieves the Vercel API token from environment variables.
    Never logs or exposes the token value.
    """
    token = (
        os.environ.get("VERCEL_TOKEN")
        or os.environ.get("VERCEL_API_KEY")
        or os.environ.get("VERCEL_BEARER_TOKEN")
    )
    if token and token.strip():
        return token.strip()
    return None


def sanitize_project_name(name: str) -> str:
    """Sanitizes project name to conform to Vercel naming restrictions."""
    clean = re.sub(r"[^a-zA-Z0-9\-]", "-", (name or "project").lower()).strip("-")
    clean = re.sub(r"-+", "-", clean)
    if not clean or len(clean) < 3:
        clean = f"tetris-app-{clean or 'project'}"
    return clean[:50]


def check_simulation_gate(simulation_result: Optional[dict]) -> Tuple[bool, Optional[str]]:
    """
    Enforces the pre-launch simulation gate before deployment.
    Returns (allowed: bool, reason: Optional[str]).
    """
    if not simulation_result or not isinstance(simulation_result, dict):
        return True, None

    status = simulation_result.get("simulation_status", "PASS")
    if status == "FAIL":
        issues = simulation_result.get("issues", [])
        issue_msgs = [f"[{i.get('check', 'check')}]: {i.get('message', '')}" for i in issues]
        msg = "Pre-launch simulation failed. Issues must be resolved before deployment: " + "; ".join(issue_msgs[:3])
        return False, msg

    if status == "DEGRADED":
        return True, "Simulation completed with warnings (DEGRADED)."

    return True, None


def perform_live_smoke_check(url: str, timeout_seconds: int = 15) -> Dict[str, Any]:
    """
    Performs a real HTTP GET request against the deployed URL to verify live status.
    """
    if not requests:
        return {
            "status": "NOT_TESTED",
            "http_status": None,
            "content_length": 0,
            "url": url,
            "error": "requests library not installed",
        }

    target_url = url if url.startswith("http://") or url.startswith("https://") else f"https://{url}"

    try:
        response = requests.get(
            target_url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Tetris-Deployment-SmokeCheck/1.0"},
            allow_redirects=True,
        )

        is_success = (200 <= response.status_code < 400) and (len(response.content) > 0)

        return {
            "status": "PASS" if is_success else "FAIL",
            "http_status": response.status_code,
            "content_length": len(response.content),
            "url": target_url,
            "error": None if is_success else f"HTTP {response.status_code} received from deployment URL",
        }

    except Exception as exc:
        return {
            "status": "FAIL",
            "http_status": None,
            "content_length": 0,
            "url": target_url,
            "error": f"Smoke check connection error: {str(exc)}",
        }


def deploy_to_vercel(
    workspace_path: str,
    project_name: str = "tetris-project",
    simulation_result: Optional[dict] = None,
    token: Optional[str] = None,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """
    Executes a real Vercel cloud deployment for the given workspace.

    Returns structured deployment result:
    {
      "deployment_status": "SUCCESS|FAILED|BLOCKED",
      "provider": "vercel",
      "deployment_id": str,
      "url": str,
      "verified": bool,
      "verification_status": "PASS|FAIL|NOT_TESTED",
      "build_status": str,
      "error": Optional[str],
      "smoke_check": dict,
      "deployed_at": str
    }
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_name = sanitize_project_name(project_name)

    # ── 1. Verify workspace exists and has files ─────────────────────────────
    if not os.path.exists(workspace_path):
        return {
            "deployment_status": "BLOCKED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "NOT_TESTED",
            "build_status": "NOT_STARTED",
            "error": f"Workspace directory not found: {workspace_path}",
            "deployed_at": now_iso,
        }

    # Collect workspace files
    files_payload = []
    for root, _, filenames in os.walk(workspace_path):
        for fn in filenames:
            fp = os.path.join(root, fn)
            rel_path = os.path.relpath(fp, workspace_path).replace("\\", "/")
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                files_payload.append({
                    "file": rel_path,
                    "data": content,
                })
            except Exception:
                pass

    if not files_payload:
        return {
            "deployment_status": "BLOCKED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "NOT_TESTED",
            "build_status": "NOT_STARTED",
            "error": "Zero deployable artifact files found in workspace.",
            "deployed_at": now_iso,
        }

    # ── 2. Check Simulation Gate ──────────────────────────────────────────────
    gate_ok, gate_reason = check_simulation_gate(simulation_result)
    if not gate_ok:
        return {
            "deployment_status": "BLOCKED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "NOT_TESTED",
            "build_status": "BLOCKED_BY_SIMULATION",
            "error": gate_reason,
            "deployed_at": now_iso,
        }

    # ── 3. Check Vercel Credentials ───────────────────────────────────────────
    auth_token = token or get_vercel_token()
    if not auth_token:
        return {
            "deployment_status": "BLOCKED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "NOT_TESTED",
            "build_status": "AUTH_REQUIRED",
            "error": (
                "Missing VERCEL_TOKEN environment variable. "
                "To enable real cloud deployments, add VERCEL_TOKEN to backend/.env."
            ),
            "deployed_at": now_iso,
        }

    # ── 4. Call Vercel Deployments API (v13) ───────────────────────────────────
    api_url = "https://api.vercel.com/v13/deployments"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }

    req_body = {
        "name": clean_name,
        "files": files_payload,
        "projectSettings": {
            "framework": None,
        },
        "target": "production",
    }

    try:
        resp = requests.post(api_url, headers=headers, json=req_body, timeout=30)

        if resp.status_code not in (200, 201):
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            err_msg = err_data.get("error", {}).get("message") or f"Vercel API returned HTTP {resp.status_code}"
            return {
                "deployment_status": "FAILED",
                "provider": "vercel",
                "deployment_id": None,
                "url": None,
                "verified": False,
                "verification_status": "FAIL",
                "build_status": "API_ERROR",
                "error": err_msg,
                "deployed_at": now_iso,
            }

        deploy_data = resp.json()
        deploy_id = deploy_data.get("id")
        raw_url = deploy_data.get("url") or ""
        if not raw_url and deploy_data.get("alias"):
            aliases = deploy_data.get("alias")
            raw_url = aliases[0] if isinstance(aliases, list) and aliases else str(aliases)
        ready_state = deploy_data.get("readyState", "BUILDING")

        live_url = f"https://{raw_url}" if raw_url and not raw_url.startswith("http") else raw_url

        # ── 5. Poll for Ready State if building ────────────────────────────────
        start_time = time.time()
        while ready_state in ("INITIALIZING", "BUILDING", "ANALYZING") and (time.time() - start_time < timeout_seconds):
            time.sleep(2)
            try:
                poll_resp = requests.get(
                    f"https://api.vercel.com/v13/deployments/{deploy_id}",
                    headers=headers,
                    timeout=15,
                )
                if poll_resp.status_code == 200:
                    poll_data = poll_resp.json()
                    ready_state = poll_data.get("readyState", ready_state)
                    if poll_data.get("url"):
                        raw_url = poll_data["url"]
                        live_url = f"https://{raw_url}"
            except Exception:
                pass

        if ready_state == "ERROR":
            return {
                "deployment_status": "FAILED",
                "provider": "vercel",
                "deployment_id": deploy_id,
                "url": live_url,
                "verified": False,
                "verification_status": "FAIL",
                "build_status": "ERROR",
                "error": "Vercel build failed during deployment processing.",
                "deployed_at": now_iso,
            }

        # ── 6. Live Smoke Verification Check ──────────────────────────────────
        smoke_result = perform_live_smoke_check(live_url)
        is_verified = (smoke_result.get("status") == "PASS")

        return {
            "deployment_status": "SUCCESS" if is_verified else "FAILED",
            "provider": "vercel",
            "deployment_id": deploy_id,
            "url": live_url,
            "verified": is_verified,
            "verification_status": smoke_result.get("status", "FAIL"),
            "build_status": ready_state,
            "error": smoke_result.get("error"),
            "smoke_check": smoke_result,
            "deployed_at": now_iso,
        }

    except requests.exceptions.Timeout:
        return {
            "deployment_status": "FAILED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "FAIL",
            "build_status": "TIMEOUT",
            "error": f"Vercel deployment request timed out after {timeout_seconds}s",
            "deployed_at": now_iso,
        }
    except Exception as exc:
        return {
            "deployment_status": "FAILED",
            "provider": "vercel",
            "deployment_id": None,
            "url": None,
            "verified": False,
            "verification_status": "FAIL",
            "build_status": "EXCEPTION",
            "error": f"Deployment executor error: {str(exc)}",
            "deployed_at": now_iso,
        }


def prepare_deployment(
    code_output: str = "",
    project_name: str = "project",
    outcome_type: str = "code",
    workspace_path: Optional[str] = None,
    simulation_result: Optional[dict] = None,
) -> dict:
    """
    Deployment preparation and execution entrypoint.
    Executes real Vercel cloud deployment if workspace is available.
    """
    if workspace_path and os.path.exists(workspace_path):
        return deploy_to_vercel(
            workspace_path=workspace_path,
            project_name=project_name,
            simulation_result=simulation_result,
        )

    # Fallback if no workspace provided
    return {
        "framework": "Static Web",
        "recommended_platform": "Vercel",
        "deployment_status": "BLOCKED",
        "provider": "vercel",
        "one_click_ready": False,
        "error": "Workspace directory required for deployment execution.",
    }
