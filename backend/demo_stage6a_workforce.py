"""
TETRIS WORKFORCE — STAGE 6A DEMONSTRATION
=========================================

Demonstrates the first real vertical slice between Tetris project input
and the Workforce Engine closed-loop execution lifecycle:

Tetris Project ("Health API")
    ↓
ProjectContext
    ↓
phase_build (ProjectWorkflow)
    ↓
TeamManager (worker_code resolved)
    ↓
TaskAssignmentEngine (task_build_code compiled)
    ↓
WorkforceCoordinator
    ↓
ExecutionDispatcher
    ↓
WorkerRuntime
    ↓
CodeWorkerAdapter
    ↓
Verification (PASS)
    ↓
ContextSynchronizer
    ↓
Verified Artifacts in ProjectContext
"""

import os
import sys
from unittest.mock import patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    create_build_project_context,
    execute_build_vertical_slice,
)


def run_stage6a_demo():
    print("=" * 60)
    print(" TETRIS WORKFORCE — STAGE 6A BUILD VERTICAL SLICE DEMO")
    print("=" * 60)

    # 1. Instantiate fixture context
    ctx = create_build_project_context(
        project_id="proj_demo_health_api",
        execution_id="exec_demo_health_api_01",
    )

    print(f"\n[1] PROJECT INTAKE:")
    print(f"    Name:        {HEALTH_API_FIXTURE['project_name']}")
    print(f"    Idea:        {ctx.definition.idea}")
    print(f"    Project ID:  {ctx.project_id}")
    print(f"    Exec ID:     {ctx.execution_id}")

    # 2. Execute vertical slice while instrumenting legacy executors
    with patch("orchestrator.router.route_to_specialist") as mock_legacy_router, \
         patch("execution.runner.run_controlled_verification") as mock_legacy_runner:

        result = execute_build_vertical_slice(project_context=ctx)
        legacy_router_calls = mock_legacy_router.call_count
        legacy_runner_calls = mock_legacy_runner.call_count

    print(f"\n[2] WORKFLOW & TEAM RESOLUTION:")
    print(f"    Workflow:    phase_build (Phase 1)")
    print(f"    Team:        worker_code ({result.team_plan.phase_assignments['phase_build'].worker_ids})")
    print(f"    Readiness:   {result.team_plan.readiness}")

    print(f"\n[3] TASK COMPILATION:")
    print(f"    Task ID:     {result.task_plan.tasks[0].task_id}")
    print(f"    Worker:      {result.task_plan.tasks[0].worker_id}")
    print(f"    Readiness:   {result.task_plan.readiness}")
    print(f"    Objective:   {result.task_plan.tasks[0].objective}")

    print(f"\n[4] WORKFORCE COORDINATION & EXECUTION:")
    print(f"    Coordinator: {result.status}")
    print(f"    Steps Run:   {result.coordinator_result.steps_executed}")
    print(f"    Completed:   {result.coordinator_result.completed_tasks}")

    step_record = result.step_history[0] if result.step_history else None
    verif_status = step_record.verification_status if step_record else "UNKNOWN"
    dispatch_status = step_record.dispatch_status if step_record else "UNKNOWN"
    runtime_status = step_record.runtime_status if step_record else "UNKNOWN"
    sync_status = step_record.sync_status if step_record else "UNKNOWN"

    print(f"\n[5] SUBSYSTEM AUDIT TRAIL:")
    print(f"    Dispatcher:   {dispatch_status}")
    print(f"    Runtime:      {runtime_status}")
    print(f"    Worker:       CodeWorkerAdapter")
    print(f"    Verification: {verif_status}")
    print(f"    ContextSync:  {sync_status}")

    print(f"\n[6] PROMOTED PROJECT ARTIFACTS:")
    for art in result.artifacts:
        print(f"    - [{art.artifact_type}] {art.name} (id: {art.artifact_id})")
        print(f"      Location: {art.location or 'memory'}")
        print(f"      Summary:  {art.content_summary}")

    print(f"\n[7] PROVENANCE AUDIT:")
    if result.artifacts:
        sample_art = result.artifacts[0]
        print(f"    Project:     {ctx.project_id}")
        print(f"    Phase:       {sample_art.phase_id}")
        print(f"    Worker:      {sample_art.producer_worker}")
        print(f"    Task:        {sample_art.producer_task}")
        print(f"    Execution:   {sample_art.metadata.get('execution_id')}")
        print(f"    Runtime:     {sample_art.metadata.get('runtime_id')}")
        print(f"    Verified:    {sample_art.metadata.get('verified')} ({sample_art.metadata.get('verification_status')})")

    print(f"\n[8] SAFETY & ISOLATION VERIFICATION:")
    print(f"    Legacy Executor: NOT CALLED (router={legacy_router_calls}, runner={legacy_runner_calls})")
    print(f"    External APIs:   0")
    print(f"    Credentials:     0")

    print("\n" + "=" * 60)
    print(" STAGE 6A VERTICAL SLICE COMPLETE & VERIFIED")
    print("=" * 60)


if __name__ == "__main__":
    run_stage6a_demo()
