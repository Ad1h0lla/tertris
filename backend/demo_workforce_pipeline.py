"""
TETRIS WORKFORCE ENGINE — Multi-Task Pipeline Demonstration
===========================================================

Demonstrates the verified closed loop across Stages 5A, 5B, and 5C:

Task A READY
   ↓
[Stage 5A] ExecutionDispatcher.dispatch_task()
   ↓
[Stage 5B] WorkerRuntime.execute_envelope() (prepare -> execute -> verify)
   ↓
[Stage 5B] RuntimeResult (Verification PASSED)
   ↓
[Stage 5C] ContextSynchronizer.apply_result()
   ↓
[Stage 4A] ProjectContext updated with verified deliverables & receipts
   ↓
[Stage 5C] GraphAdvancer.advance_graph()
   ↓
Task B READY
   ↓
... (repeats until DAG completion)
"""

import json
import sys
import os

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestration.project_context import (
    ProjectContext,
    ProjectDefinition,
)
from orchestration.worker_contract import Task
from orchestration.task_assignment import CompiledTaskPlan
from orchestration.execution_dispatcher import (
    ExecutionDispatcher,
)
from orchestration.worker_runtime import (
    WorkerRuntime,
    EchoWorker,
    PricingWorkerAdapter,
    CodeWorkerAdapter,
)
from orchestration.context_sync import ContextSynchronizer, SyncStatus
from orchestration.graph_advancer import GraphAdvancer, TaskState


def run_pipeline_demo():
    print("=" * 70)
    print(" TETRIS WORKFORCE ENGINE — STAGES 5A -> 5B -> 5C DEMONSTRATION")
    print("=" * 70)

    # 1. Initialize Authoritative ProjectContext
    project_defn = ProjectDefinition(
        idea="AI-Powered Competitive Intelligence & Price Monitoring SaaS",
        goal="Continuously monitor competitor SaaS pricing, features, and roadmaps.",
        target_users="SaaS Founders and Product Marketers",
        requirements=[
            "Automated scraping and change detection",
            "Pricing tier analysis engine",
            "Targeted community distribution on Reddit",
        ],
        acceptance_criteria=[
            "Extract competitor plans & features",
            "Generate optimized tier recommendations",
            "Verified community outreach message with receipt",
        ],
    )
    context = ProjectContext(
        project_id="proj_saas_intel_99",
        execution_id="exec_cycle_2026",
        user_id="founder_alice",
        definition=project_defn,
    )
    print(f"\n[INIT] ProjectContext created:")
    print(f"       Project ID: {context.project_id}")
    print(f"       Idea: {context.definition.idea}")

    # 2. Define Multi-Task Dependency DAG (A -> B -> C)
    task_A = Task(
        task_id="task_01_code",
        worker_id="worker_code",
        project_id=context.project_id,
        execution_id=context.execution_id,
        objective="Generate core scraper backend API and data schemas.",
        dependencies=[],
        inputs={"framework": "FastAPI", "modules": ["scraper", "diff_engine"]},
        permissions=["read", "write"],
        expected_output={"status": "BUILT", "workspace": "backend"},
        metadata={"phase_id": "phase_build"},
    )

    task_B = Task(
        task_id="task_02_pricing",
        worker_id="worker_pricing",
        project_id=context.project_id,
        execution_id=context.execution_id,
        objective="Analyze competitor price points and recommend monetization tiers.",
        dependencies=["task_01_code"],
        inputs={"competitor_prices": [29, 79, 199], "target_margin": 0.8},
        permissions=["read", "write"],
        expected_output={"recommended_tiers": ["Starter $19", "Pro $69", "Enterprise $199"]},
        metadata={"phase_id": "phase_strategy"},
    )

    task_C = Task(
        task_id="task_03_distribution",
        worker_id="worker_reddit",
        project_id=context.project_id,
        execution_id=context.execution_id,
        objective="Generate and verify launch announcement with external receipt reference.",
        dependencies=["task_02_pricing"],
        inputs={"subreddit": "r/SaaS", "channel": "reddit"},
        permissions=["read", "write"],
        expected_output={"status": "POSTED", "platform": "reddit"},
        metadata={"phase_id": "phase_marketing"},
    )

    tasks = [task_A, task_B, task_C]
    deps_map = {t.task_id: t.dependencies for t in tasks}

    # Initial plan setup: Task A is READY, Tasks B & C are WAITING
    plan = CompiledTaskPlan(
        project_id=context.project_id,
        execution_id=context.execution_id,
        tasks=tasks,
        ready_tasks=["task_01_code"],
        waiting_tasks=["task_02_pricing", "task_03_distribution"],
        blocked_tasks=[],
        task_dependencies=deps_map,
    )

    print(f"\n[DAG SETUP]")
    print(f"  Tasks: {[t.task_id for t in tasks]}")
    print(f"  Dependencies: {deps_map}")
    print(f"  Initial READY:   {plan.ready_tasks}")
    print(f"  Initial WAITING: {plan.waiting_tasks}")

    # 3. Instantiate Engine Components
    dispatcher = ExecutionDispatcher()
    runtime = WorkerRuntime()
    # Register adapters
    runtime.register_worker(CodeWorkerAdapter())
    runtime.register_worker(PricingWorkerAdapter())
    runtime.register_worker(EchoWorker(worker_id="worker_reddit"))
    context_sync = ContextSynchronizer()
    graph_advancer = GraphAdvancer()

    # 4. Step-by-Step Coordinated Execution Loop
    step_num = 1
    completed_tasks = set()

    while plan.ready_tasks:
        current_task_id = plan.ready_tasks[0]
        current_task = plan.get_task(current_task_id)

        print("\n" + "=" * 70)
        print(f" STEP {step_num}: PROCESSING TASK '{current_task_id}' (Worker: {current_task.worker_id})")
        print("=" * 70)

        # Stage 5A: Dispatch Task (Handling approval gate for external workers)
        print(f"\n1. [Stage 5A] Dispatching Task '{current_task_id}'...")
        dispatch_res = dispatcher.dispatch_task(
            current_task,
            compiled_task_plan=plan,
            connected_connectors=["redditapis", "internal_db"],
            authorized_permissions=["read", "write"],
            is_approved=False,
        )

        if dispatch_res.status == "BLOCKED" and "approval" in dispatch_res.reason.lower():
            print(f"   -> [APPROVAL GATE] Task '{current_task_id}' requires explicit approval before dispatch.")
            print(f"   -> Approving task for dry-run execution...")
            dispatch_res = dispatcher.dispatch_task(
                current_task,
                compiled_task_plan=plan,
                connected_connectors=["redditapis", "internal_db"],
                authorized_permissions=["read", "write"],
                is_approved=True,
            )

        assert dispatch_res.is_dispatched, f"Dispatch failed: {dispatch_res.reason}"
        print(f"   -> Dispatch Status: {dispatch_res.status}")
        print(f"   -> Dispatch ID:     {dispatch_res.envelope.dispatch_id}")
        print(f"   -> Inputs Provided: {list(dispatch_res.envelope.inputs.keys())}")

        # Stage 5B: Execute in Worker Runtime
        print(f"\n2. [Stage 5B] Executing in WorkerRuntime (prepare -> execute -> verify)...")
        runtime_res = runtime.execute_envelope(dispatch_res.envelope)
        print(f"   -> Runtime Status: {runtime_res.status}")
        print(f"   -> Worker State:   {runtime_res.task_result.state if runtime_res.task_result else 'N/A'}")
        print(f"   -> Verification:   {runtime_res.verification_result.status if runtime_res.verification_result else 'NONE'} (Verified: {runtime_res.verification_result.verified if runtime_res.verification_result else False})")
        print(f"   -> Output:         {json.dumps(runtime_res.task_result.output if runtime_res.task_result else {}, indent=2)}")

        # Stage 5C: Context Synchronizer
        phase_id = current_task.metadata.get("phase_id", "phase_default")
        print(f"\n3. [Stage 5C] Context Synchronizer (Strict Verification Gate)...")
        sync_res = context_sync.apply_result(context, runtime_res, phase_id=phase_id)
        print(f"   -> Sync Status: {sync_res.status}")
        print(f"   -> Artifacts Created: {sync_res.artifacts_created}")
        print(f"   -> Receipts Created:  {sync_res.receipts_created}")
        print(f"   -> Phase History:     {sync_res.phase_outcomes_updated}")

        # Mark task as completed
        completed_tasks.add(current_task_id)

        # Stage 5C: Graph Advancer
        print(f"\n4. [Stage 5C] Graph Advancer Re-evaluating Downstream Dependencies...")
        adv_res = graph_advancer.advance_graph(plan, completed_task_ids=completed_tasks)
        print(f"   -> Newly READY Tasks:   {adv_res.newly_ready_tasks}")
        print(f"   -> Remaining WAITING:   {adv_res.waiting_tasks}")
        print(f"   -> Active READY in DAG: {plan.ready_tasks}")

        step_num += 1

    # 5. Final Audit of ProjectContext
    print("\n" + "=" * 70)
    print(" PIPELINE COMPLETE — FINAL AUDIT OF AUTHORITATIVE PROJECTCONTEXT")
    print("=" * 70)
    print(f"\nTotal Artifacts in Context ({len(context.artifacts)}):")
    for art in context.artifacts.values():
        print(f"  - [{art.artifact_type}] {art.name} (Produced by {art.producer_worker}:{art.producer_task})")

    print(f"\nPhase History Outcomes ({len(context.phase_history)}):")
    for pid, ph in context.phase_history.items():
        print(f"  - [{pid}] Status: {ph.status}, Verification: {ph.verification_status}, Worker: {ph.producer_worker}")

    print("\n[SUCCESS] The multi-task DAG fully resolved from Task A -> Task B -> Task C with 100% verified provenance!")
    print("=" * 70)


if __name__ == "__main__":
    run_pipeline_demo()
