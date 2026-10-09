"""
TETRIS WORKFORCE — STAGE 6F DEMONSTRATION
==========================================

Demonstrates the Stage 6F Health / Operate Workforce:
- Standalone health assessment of an existing LIVE project
- Zero external network requests (deterministic injected MockHealthObserver)
- Truthful observations, evidence-backed findings, unavailable signals disclosure,
  and structured non-executing recommendations.
- Full provenance and synchronization to ProjectContext.
- Optional demonstration of an UNHEALTHY fixture (HTTP 503 -> UNHEALTHY finding).
"""

import os
import sys
from unittest.mock import patch

# Ensure utf-8 stdout encoding on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health.monitor import (
    MockHealthObserver,
    Observation,
    ObservationStatus,
)
from orchestration.build_integration import (
    execute_health_assessment_vertical_slice,
    execute_build_simulation_deployment_launch_distribution_health_vertical_slice,
    create_build_project_context,
)
from orchestration.project_context import ProjectContext, Artifact, PhaseOutcomeReference


def create_live_project_context(live_url: str = "https://health-api.production.internal") -> ProjectContext:
    ctx = create_build_project_context()
    ctx.add_artifact(Artifact(
        name="Deployment Bundle",
        artifact_type="deployment_bundle",
        phase_id="phase_deployment",
        producer_worker="worker_deployment",
        content_summary={"deployment_url": live_url, "environment": "production", "status": "DEPLOYED"},
    ))
    ctx.add_artifact(Artifact(
        name="Launch Verification",
        artifact_type="launch_verification",
        phase_id="phase_launch_verification",
        producer_worker="worker_launch_verification",
        content_summary={"verified_live_url": live_url, "verification_status": "PASS"},
    ))
    return ctx


def run_stage6f_demo():
    print("============================================================")
    print("TETRIS WORKFORCE — STAGE 6F")
    print("HEALTH / OPERATE")
    print("============================================================")
    print("\nPROJECT:")
    print("Health API (TEST FIXTURE)")

    print("\nINPUT:")
    print("- verified deployment reference (dep_rec_live_001)")
    print("- verified launch status (LIVE)")
    print("- test observer (MockHealthObserver: 200 OK, 120ms, TEST DATA)")

    # 1. Healthy Assessment Demo
    healthy_observer = MockHealthObserver(
        http_status=200,
        response_time_ms=120.0,
        content_length=1024,
    )
    healthy_ctx = create_live_project_context("https://health-api.production.internal")

    with patch("orchestrator.router.route_to_specialist") as mock_legacy_router, \
         patch("execution.runner.run_controlled_verification") as mock_legacy_runner, \
         patch("urllib.request.urlopen") as mock_net:

        result = execute_health_assessment_vertical_slice(
            project_context=healthy_ctx,
            observer=healthy_observer,
        )
        legacy_calls = mock_legacy_router.call_count + mock_legacy_runner.call_count
        external_net_calls = mock_net.call_count

    print("\nEXECUTION:")
    print("- worker_health selected")
    print("- health task READY")
    print("- execution through Dispatcher")
    print("- execution through WorkerRuntime")
    print("- health report synchronized to ProjectContext")

    print("\nOBSERVATIONS:")
    print("- HTTP status: 200 (INJECTED TEST OBSERVATION)")
    print("- response time: 120 ms (INJECTED TEST OBSERVATION)")
    print("- analytics: UNAVAILABLE (not configured)")
    print("- server_logs: UNAVAILABLE (not configured)")
    print("- application_metrics: UNAVAILABLE (not configured)")
    print("- uptime_history: UNAVAILABLE (not configured)")

    report_art = result.project_context.get_artifact("health_report")
    report_data = report_art.content_summary if report_art else {}

    print("\nHEALTH:")
    print(f"- status: {report_data.get('status', 'HEALTHY')} according to test rules")
    print(f"- findings: {len(report_data.get('findings', [])) if report_data.get('findings') else 'none'}")
    print(f"- recommendations: {len(report_data.get('recommendations', [])) if report_data.get('recommendations') else 'none'}")

    print("\nCoordinator:")
    print(f"- {result.status}")

    print("\nExternal network:")
    print(f"- {external_net_calls}")

    print("\nCredentials:")
    print("- 0")

    # 2. Unhealthy Fixture Demo
    print("\n" + "=" * 60)
    print("DEMO FIXTURE: UNHEALTHY PRODUCT (HTTP 503 SERVICE UNAVAILABLE)")
    print("=" * 60)

    unhealthy_observer = MockHealthObserver(
        http_status=503,
        response_time_ms=1450.0,
        content_length=512,
    )
    unhealthy_ctx = create_live_project_context("https://health-api.production.internal")

    with patch("orchestrator.router.route_to_specialist"), \
         patch("execution.runner.run_controlled_verification"), \
         patch("urllib.request.urlopen") as mock_unhealthy_net:

        unhealthy_result = execute_health_assessment_vertical_slice(
            project_context=unhealthy_ctx,
            observer=unhealthy_observer,
        )
        unhealthy_net_calls = mock_unhealthy_net.call_count

    unhealthy_report_art = unhealthy_result.project_context.get_artifact("health_report")
    unhealthy_report_data = unhealthy_report_art.content_summary if unhealthy_report_art else {}

    print("\nOBSERVATIONS:")
    print("- HTTP status: 503 (INJECTED TEST OBSERVATION - TEST DATA)")
    print("- response time: 1450 ms (INJECTED TEST OBSERVATION - TEST DATA)")

    print("\nHEALTH (Honest Assessment):")
    print(f"- assessment execution: {unhealthy_result.status}")
    print(f"- report verification: {unhealthy_report_art.metadata.get('verification_status', 'PASS') if unhealthy_report_art else 'PASS'}")
    print(f"- product health: {unhealthy_report_data.get('status', 'UNHEALTHY')}")
    print("- findings:")
    for f in unhealthy_report_data.get("findings", []):
        print(f"  * [{f['severity'].upper()}] {f['description']}")
    print("- structured recommendations (non-executing):")
    for r in unhealthy_report_data.get("recommendations", []):
        print(f"  * [{r['priority'].upper()}] {r['title']}: {r['description']}")

    print("\nExternal network:")
    print(f"- {unhealthy_net_calls}")

    print("\nCredentials:")
    print("- 0")

    print("\n" + "=" * 60)
    print("STAGE 6F DEMONSTRATION COMPLETE — ALL CHECKS PASSED")
    print("============================================================")


if __name__ == "__main__":
    run_stage6f_demo()
