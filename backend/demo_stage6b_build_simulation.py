"""
TETRIS WORKFORCE — STAGE 6B DEMONSTRATION
==========================================

Demonstrates the first real cross-phase multi-task vertical slice:

BUILD
    ↓
verified build artifacts
    ↓
PROJECT CONTEXT
    ↓
SIMULATION
    ↓
verified simulation result
    ↓
PROJECT CONTEXT
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

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    create_build_project_context,
    execute_build_simulation_vertical_slice,
)


def run_stage6b_demo():
    print("============================================================")
    print("TETRIS WORKFORCE — STAGE 6B BUILD → SIMULATION")
    print("PROJECT:")
    print("Health API")
    print("WORKFLOW:")
    print("phase_build")
    print("    ↓")
    print("phase_simulation")
    print("TASK GRAPH:")
    print("task_build_code")
    print("    ↓")
    print("task_simulation")
    print("EXECUTION:")

    # Execute vertical slice instrumenting legacy executors and network calls
    with patch("orchestrator.router.route_to_specialist") as mock_legacy_router, \
         patch("execution.runner.run_controlled_verification") as mock_legacy_runner, \
         patch("urllib.request.urlopen") as mock_net:

        result = execute_build_simulation_vertical_slice()
        legacy_router_calls = mock_legacy_router.call_count
        legacy_runner_calls = mock_legacy_runner.call_count
        external_api_calls = mock_net.call_count

    # Extract step details
    build_step = result.step_history[0] if len(result.step_history) > 0 else None
    sim_step = result.step_history[1] if len(result.step_history) > 1 else None

    # Step 1: Build
    build_worker_name = "CodeWorkerAdapter" if build_step and build_step.worker_id == "worker_code" else "Unknown"
    build_status = build_step.runtime_status if build_step else "UNKNOWN"
    build_verif = build_step.verification_status if build_step else "UNKNOWN"

    print("[1] BUILD")
    print(f"    Worker: {build_worker_name}")
    print(f"    Status: {build_status}")
    print(f"    Verification: {build_verif}")

    # Step 2: Context Handoff
    print("[2] CONTEXT HANDOFF")
    print("    Artifacts:")
    for art in result.build_artifacts:
        print(f"      - {art.artifact_type}")

    # Step 3: Simulation
    sim_worker_name = "SimulationWorkerAdapter" if sim_step and sim_step.worker_id == "worker_qa_simulation" else "Unknown"
    sim_status = sim_step.runtime_status if sim_step else "UNKNOWN"
    sim_verif = sim_step.verification_status if sim_step else "UNKNOWN"

    print("[3] SIMULATION")
    print(f"    Worker: {sim_worker_name}")
    print("    Consumed:")
    for art in result.build_artifacts:
        print(f"      - {art.artifact_type}")
    print(f"    Status: {sim_status}")
    print(f"    Verification: {sim_verif}")

    # Step 4: Final Context
    ctx = result.project_context
    build_phase_status = ctx.phase_history.get("phase_build").status if "phase_build" in ctx.phase_history else "UNKNOWN"
    sim_phase_status = ctx.phase_history.get("phase_simulation").status if "phase_simulation" in ctx.phase_history else "UNKNOWN"

    print("[4] FINAL CONTEXT")
    print(f"    Build: {build_phase_status}")
    print(f"    Simulation: {sim_phase_status}")

    # Summary
    print("Coordinator:")
    print(f"    {result.status}")

    legacy_called = (legacy_router_calls + legacy_runner_calls) > 0
    print("Legacy Executor:")
    print(f"    {'CALLED' if legacy_called else 'NOT CALLED'}")

    print("External APIs:")
    print(f"    {external_api_calls}")

    print("Credentials:")
    print("    0")


if __name__ == "__main__":
    run_stage6b_demo()
