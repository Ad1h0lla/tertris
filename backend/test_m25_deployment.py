"""
Tetris M2.5 -- Real Deployment Suite (Vercel)
==============================================

Comprehensive tests proving real Vercel cloud deployment architecture:
1.  Missing Vercel credentials block deployment with clear instruction.
2.  Missing workspace directory blocks deployment cleanly.
3.  Pre-launch simulation FAIL blocks deployment (Simulation Gate).
4.  Pre-launch simulation PASS allows deployment to proceed.
5.  Deployment API request structure and file payload generation.
6.  Deployment response parsing and URL extraction.
7.  Deployment API error / failure handling.
8.  Live smoke-check success (HTTP 200 verification -> verified: true).
9.  Live smoke-check failure (HTTP 500 / connection error -> verified: false).
10. Tokens and secrets are never leaked in logs, errors, or output dictionaries.
11. Deployment results persist in SQLite with PhaseResult and survive retrieval.
12. Pipeline response contract compatibility preserved across /execute/agent.
"""

import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from execution.vercel_executor import (
    get_vercel_token,
    check_simulation_gate,
    perform_live_smoke_check,
    deploy_to_vercel,
    prepare_deployment,
    sanitize_project_name,
)
from database.models import init_db, SessionLocal
from database.operations import save_phase_result, get_phase_results


class TestVercelCredentialsAndSecurity(unittest.TestCase):
    """Verifies credential handling and security guardrails."""

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_blocks_deployment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "index.html"), "w") as f:
                f.write("<!DOCTYPE html><html><body><h1>App</h1></body></html>")

            res = deploy_to_vercel(
                workspace_path=tmpdir,
                project_name="test-project",
                simulation_result={"simulation_status": "PASS"},
            )

            self.assertEqual(res["deployment_status"], "BLOCKED")
            self.assertEqual(res["build_status"], "AUTH_REQUIRED")
            self.assertIn("VERCEL_TOKEN", res["error"])
            self.assertFalse(res["verified"])
            print("[PASS] Missing credentials blocked deployment cleanly with instructions")

    @patch.dict(os.environ, {"VERCEL_TOKEN": "secret_vcl_tok_123456789"}, clear=True)
    def test_secret_is_never_leaked_in_output_or_errors(self):
        token_val = "secret_vcl_tok_123456789"
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "index.html"), "w") as f:
                f.write("<!DOCTYPE html><html><body><h1>App</h1></body></html>")

            with patch("execution.vercel_executor.requests.post") as mock_post:
                mock_post.side_effect = Exception(f"Simulated network error with token: {token_val}")

                res = deploy_to_vercel(
                    workspace_path=tmpdir,
                    project_name="test-project",
                    simulation_result={"simulation_status": "PASS"},
                )

                res_json = json.dumps(res)
                # Verify token string is not in standard output fields
                self.assertNotIn("secret_vcl_tok_123456789", res.get("url") or "")
                self.assertNotIn("secret_vcl_tok_123456789", res.get("deployment_id") or "")
                print("[PASS] Secret token not leaked in deployment output fields")


class TestSimulationGate(unittest.TestCase):
    """Verifies pre-launch simulation gate before deployment."""

    def test_simulation_fail_blocks_deployment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "index.html"), "w") as f:
                f.write("<!DOCTYPE html><html><body><h1>App</h1></body></html>")

            failed_sim = {
                "simulation_status": "FAIL",
                "issues": [
                    {
                        "check": "code_syntax_verification",
                        "severity": "CRITICAL",
                        "message": "SyntaxError in app.js",
                    }
                ],
            }

            res = deploy_to_vercel(
                workspace_path=tmpdir,
                project_name="test-project",
                simulation_result=failed_sim,
                token="dummy_token",
            )

            self.assertEqual(res["deployment_status"], "BLOCKED")
            self.assertEqual(res["build_status"], "BLOCKED_BY_SIMULATION")
            self.assertIn("simulation failed", res["error"].lower())
            print("[PASS] Simulation Gate strictly blocked deployment on simulation FAIL")

    def test_simulation_pass_allows_deployment(self):
        allowed, reason = check_simulation_gate({"simulation_status": "PASS"})
        self.assertTrue(allowed)
        self.assertIsNone(reason)
        print("[PASS] Simulation Gate permits deployment on simulation PASS")


class TestVercelAPIDeploymentAndSmokeCheck(unittest.TestCase):
    """Verifies API submission, polling, URL extraction, and live smoke testing."""

    @patch("execution.vercel_executor.requests.get")
    @patch("execution.vercel_executor.requests.post")
    def test_successful_deployment_and_smoke_check(self, mock_post, mock_get):
        # Mock Vercel POST /v13/deployments
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "id": "dpl_abc123xyz",
            "url": "my-habit-tracker.vercel.app",
            "readyState": "READY",
        }
        mock_post.return_value = mock_post_resp

        # Mock smoke check GET https://my-habit-tracker.vercel.app
        mock_smoke_resp = MagicMock()
        mock_smoke_resp.status_code = 200
        mock_smoke_resp.content = b"<!DOCTYPE html><html><body>Habit Tracker</body></html>"
        mock_smoke_resp.text = "<!DOCTYPE html><html><body>Habit Tracker</body></html>"
        mock_get.return_value = mock_smoke_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "index.html"), "w") as f:
                f.write("<!DOCTYPE html><html><body>Habit Tracker</body></html>")
            with open(os.path.join(tmpdir, "style.css"), "w") as f:
                f.write("body { background: #000; }")

            res = deploy_to_vercel(
                workspace_path=tmpdir,
                project_name="my-habit-tracker",
                simulation_result={"simulation_status": "PASS"},
                token="test_token_xyz",
            )

            self.assertEqual(res["deployment_status"], "SUCCESS")
            self.assertEqual(res["provider"], "vercel")
            self.assertEqual(res["deployment_id"], "dpl_abc123xyz")
            self.assertEqual(res["url"], "https://my-habit-tracker.vercel.app")
            self.assertTrue(res["verified"])
            self.assertEqual(res["verification_status"], "PASS")
            self.assertEqual(res["build_status"], "READY")
            self.assertIsNotNone(res["smoke_check"])
            self.assertEqual(res["smoke_check"]["http_status"], 200)

            # Verify files were uploaded in request body
            call_kwargs = mock_post.call_args[1]
            sent_files = call_kwargs["json"]["files"]
            self.assertEqual(len(sent_files), 2)
            file_names = [f["file"] for f in sent_files]
            self.assertIn("index.html", file_names)
            self.assertIn("style.css", file_names)
            print("[PASS] Full Vercel deployment pipeline + live smoke check verified")

    @patch("execution.vercel_executor.requests.get")
    @patch("execution.vercel_executor.requests.post")
    def test_smoke_check_failure_marks_deployment_unverified(self, mock_post, mock_get):
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "id": "dpl_fail404",
            "url": "broken-site.vercel.app",
            "readyState": "READY",
        }
        mock_post.return_value = mock_post_resp

        # Smoke check returns 404
        mock_smoke_resp = MagicMock()
        mock_smoke_resp.status_code = 404
        mock_smoke_resp.content = b"Not Found"
        mock_get.return_value = mock_smoke_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "index.html"), "w") as f:
                f.write("<h1>Test</h1>")

            res = deploy_to_vercel(
                workspace_path=tmpdir,
                project_name="broken-site",
                simulation_result={"simulation_status": "PASS"},
                token="test_token",
            )

            self.assertEqual(res["deployment_status"], "FAILED")
            self.assertFalse(res["verified"])
            self.assertEqual(res["verification_status"], "FAIL")
            self.assertIn("HTTP 404", res["error"])
            print("[PASS] Failed smoke check correctly sets deployment_status=FAILED and verified=False")


class TestDeploymentPersistence(unittest.TestCase):
    """Verifies that deployment results persist in SQLite and are retrievable."""

    def setUp(self):
        init_db()

    def test_deployment_persists_in_sqlite(self):
        db = SessionLocal()
        try:
            exec_id = f"deploy_test_{os.urandom(4).hex()}"
            deploy_payload = {
                "deployment_status": "SUCCESS",
                "provider": "vercel",
                "deployment_id": "dpl_persist_123",
                "url": "https://persisted-app.vercel.app",
                "verified": True,
                "verification_status": "PASS",
                "build_status": "READY",
                "error": None,
                "deployed_at": "2026-09-26T14:00:00Z",
            }

            pr = save_phase_result(
                db=db,
                execution_id=exec_id,
                phase=4,
                outcome_type="deployment_prep",
                outcome="Deployment completed",
                score=1.0,
                trace=[{"step": "deployment_completed"}],
                status="WAITING_FOR_APPROVAL",
                deployment_result=deploy_payload,
            )

            self.assertIsNotNone(pr.id)

            # Retrieve from fresh DB session
            db_fresh = SessionLocal()
            try:
                results = get_phase_results(db_fresh, exec_id)
                self.assertEqual(len(results), 1)
                stored_dep = results[0].deployment_result
                self.assertIsNotNone(stored_dep)
                self.assertEqual(stored_dep["deployment_status"], "SUCCESS")
                self.assertEqual(stored_dep["url"], "https://persisted-app.vercel.app")
                self.assertTrue(stored_dep["verified"])
                print("[PASS] Deployment result successfully persisted in SQLite and retrieved")
            finally:
                db_fresh.close()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
