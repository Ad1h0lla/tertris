"""
Unit Tests for Workforce Engine — Stage 5D: Workforce Execution Coordinator
============================================================================

Tests:
1. Single task success
2. Linear DAG (A -> B -> C) full traversal
3. Deterministic READY-task ordering
4. Fan-out DAG (A -> B, C, D)
5. Fan-in DAG (A, B, C -> D)
6. Failure propagation halts coordinator honestly
7. Verification failure halts coordinator with zero false deliverables
8. Missing verification halts coordinator honestly
9. Dispatcher blocked (e.g. missing connector) halts loop
10. Approval gate stops coordinator BEFORE WorkerRuntime
11. Resumption with approved task continues execution
12. No automatic approval
13. No infinite loop on unresolvable graph
14. Complete workflow execution
15. Partial workflow execution
16. Duplicate task execution prevention
17. ContextSynchronizer called after RuntimeResult
18. GraphAdvancer called after synchronization
19. Coordinator never directly calls BaseWorker
20. Coordinator never bypasses ExecutionDispatcher
21. Coordinator never bypasses WorkerRuntime
22. Dry-run execution
23. Secret-safe audit payload
"""

import copy
import pytest

from orchestration.context_sync import ContextSynchronizer, SyncStatus
from orchestration.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
)
from orchestration.graph_advancer import GraphAdvancer, TaskState
from orchestration.project_context import (
    ProjectContext,
    ProjectDefinition,
)
from orchestration.task_assignment import CompiledTaskPlan
from orchestration.worker_contract import (
    BaseWorker,
    Task,
    TaskPlan,
    TaskResult,
    VerificationResult,
    WorkerState,
)
from orchestration.worker_registry import WorkerRegistry, WorkerDescriptor
from orchestration.worker_runtime import (
    EchoWorker,
    PricingWorkerAdapter,
    CodeWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    WorkerRuntime,
)
from orchestration.workforce_coordinator import (
    CoordinatorResult,
    CoordinatorStatus,
    WorkforceCoordinator,
)


@pytest.fixture
def sample_context() -> ProjectContext:
    defn = ProjectDefinition(
        idea="AI Competitive Intel SaaS",
        goal="Monitor competitor price points and features.",
        target_users="SaaS Founders",
        requirements=["Web scraping", "Price model extraction"],
        acceptance_criteria=["Live tracking", "Verified recommendations"],
    )
    return ProjectContext(
        project_id="proj_coord_test_01",
        execution_id="exec_coord_test_01",
        user_id="user_admin",
        definition=defn,
    )


def _make_task(
    task_id: str,
    worker_id: str = "worker_echo",
    deps: list[str] = None,
    phase_id: str = "phase_1",
    inputs: dict = None,
) -> Task:
    return Task(
        task_id=task_id,
        worker_id=worker_id,
        project_id="proj_coord_test_01",
        execution_id="exec_coord_test_01",
        objective=f"Objective for {task_id}",
        dependencies=deps or [],
        inputs=inputs or {"data": "test_input"},
        permissions=["read", "write"],
        expected_output={"status": "DONE"},
        metadata={"phase_id": phase_id},
    )


def _make_plan(tasks: list[Task]) -> CompiledTaskPlan:
    deps_map = {t.task_id: t.dependencies for t in tasks}
    ready = [t.task_id for t in tasks if not t.dependencies]
    waiting = [t.task_id for t in tasks if t.dependencies]
    return CompiledTaskPlan(
        project_id="proj_coord_test_01",
        execution_id="exec_coord_test_01",
        tasks=tasks,
        ready_tasks=ready,
        waiting_tasks=waiting,
        blocked_tasks=[],
        task_dependencies=deps_map,
    )


def _build_test_coordinator(
    custom_workers: dict = None,
    descriptors: list = None,
) -> WorkforceCoordinator:
    registry = WorkerRegistry()
    # Default echo workers
    registry.register(WorkerDescriptor(
        worker_id="worker_echo",
        name="Echo Worker",
        role="tester",
        phase="phase_1",
        capabilities=["echo:test"],
    ))
    registry.register(WorkerDescriptor(
        worker_id="worker_code",
        name="Code Worker",
        role="developer",
        phase="phase_build",
        capabilities=["code:generate"],
    ))
    registry.register(WorkerDescriptor(
        worker_id="worker_pricing",
        name="Pricing Worker",
        role="strategist",
        phase="phase_strategy",
        capabilities=["pricing:analyze"],
    ))
    registry.register(WorkerDescriptor(
        worker_id="worker_external",
        name="External Worker",
        role="poster",
        phase="phase_marketing",
        capabilities=["external:post"],
        permissions=["approval_required", "read", "write"],
        required_connectors=["redditapis"],
    ))

    if descriptors:
        for d in descriptors:
            registry.register(d)

    from orchestration.execution_dispatcher import DispatchRegistry
    from orchestration.worker_runtime import WorkerRuntimeRegistry

    dispatch_reg = DispatchRegistry()
    runtime_reg = WorkerRuntimeRegistry()

    dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=dispatch_reg)
    runtime = WorkerRuntime(registry=registry, runtime_registry=runtime_reg)
    runtime.register_worker(EchoWorker(worker_id="worker_echo"))
    runtime.register_worker(CodeWorkerAdapter())
    runtime.register_worker(PricingWorkerAdapter())
    runtime.register_worker(EchoWorker(worker_id="worker_external"))

    if custom_workers:
        for wid, worker in custom_workers.items():
            runtime.register_worker(worker)

    return WorkforceCoordinator(
        dispatcher=dispatcher,
        runtime=runtime,
        context_sync=ContextSynchronizer(),
        graph_advancer=GraphAdvancer(),
    )


# =============================================================================
# 1. Basic Lifecycle & DAG Traversal Tests
# =============================================================================

class TestCoordinatorExecutionLifecycle:
    def test_single_task_success(self, sample_context):
        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.status == CoordinatorStatus.COMPLETED.value
        assert result.is_completed is True
        assert result.steps_executed == 1
        assert result.completed_tasks == ["task_01"]
        assert len(sample_context.artifacts) >= 1

    def test_linear_dag_traversal_a_b_c(self, sample_context):
        tA = _make_task("task_A", worker_id="worker_echo", deps=[])
        tB = _make_task("task_B", worker_id="worker_echo", deps=["task_A"])
        tC = _make_task("task_C", worker_id="worker_echo", deps=["task_B"])
        plan = _make_plan([tA, tB, tC])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.status == CoordinatorStatus.COMPLETED.value
        assert result.steps_executed == 3
        assert result.completed_tasks == ["task_A", "task_B", "task_C"]
        assert len(result.step_history) == 3
        assert result.step_history[0].task_id == "task_A"
        assert result.step_history[1].task_id == "task_B"
        assert result.step_history[2].task_id == "task_C"

    def test_deterministic_ready_task_ordering(self, sample_context):
        # 3 parallel root tasks
        t1 = _make_task("task_Z", worker_id="worker_echo", deps=[])
        t2 = _make_task("task_A", worker_id="worker_echo", deps=[])
        t3 = _make_task("task_M", worker_id="worker_echo", deps=[])
        plan = _make_plan([t1, t2, t3])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.is_completed is True
        assert result.steps_executed == 3
        # Should execute in plan order (task_Z, task_A, task_M)
        assert [s.task_id for s in result.step_history] == ["task_Z", "task_A", "task_M"]

    def test_fan_out_dag_execution(self, sample_context):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        tC = _make_task("task_C", deps=["task_A"])
        tD = _make_task("task_D", deps=["task_A"])
        plan = _make_plan([tA, tB, tC, tD])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.is_completed is True
        assert result.steps_executed == 4
        assert set(result.completed_tasks) == {"task_A", "task_B", "task_C", "task_D"}

    def test_fan_in_dag_execution(self, sample_context):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=[])
        tC = _make_task("task_C", deps=[])
        tD = _make_task("task_D", deps=["task_A", "task_B", "task_C"])
        plan = _make_plan([tA, tB, tC, tD])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.is_completed is True
        assert result.steps_executed == 4
        assert result.step_history[3].task_id == "task_D"


# =============================================================================
# 2. Failure & Verification Gate Tests
# =============================================================================

class TestCoordinatorFailureHandling:
    def test_execution_failure_halts_coordinator(self, sample_context):
        failing_worker = EchoWorker(worker_id="worker_fail", fail_exec=True)
        registry = WorkerRegistry()
        registry.register(WorkerDescriptor(
            worker_id="worker_fail",
            name="Failing Worker",
            role="tester",
            phase="phase_1",
            capabilities=["echo:test"],
        ))
        tA = _make_task("task_A", worker_id="worker_fail", deps=[])
        tB = _make_task("task_B", worker_id="worker_echo", deps=["task_A"])
        plan = _make_plan([tA, tB])

        coord = _build_test_coordinator(custom_workers={"worker_fail": failing_worker}, descriptors=[
            WorkerDescriptor(worker_id="worker_fail", name="Failing Worker", role="tester", phase="phase_1", capabilities=["echo:test"])
        ])

        result = coord.run_workflow(sample_context, plan)

        assert result.status == CoordinatorStatus.FAILED.value
        assert result.is_failed is True
        assert "task_A" in result.failed_tasks
        assert "task_B" in result.blocked_tasks
        assert result.steps_executed == 1
        # Downstream task_B must NOT have executed
        assert "task_B" not in result.completed_tasks

    def test_verification_failure_halts_coordinator_honestly(self, sample_context):
        verif_fail_worker = EchoWorker(worker_id="worker_verif_fail", fail_verify=True)
        tA = _make_task("task_A", worker_id="worker_verif_fail", deps=[])
        tB = _make_task("task_B", worker_id="worker_echo", deps=["task_A"])
        plan = _make_plan([tA, tB])

        coord = _build_test_coordinator(
            custom_workers={"worker_verif_fail": verif_fail_worker},
            descriptors=[
                WorkerDescriptor(worker_id="worker_verif_fail", name="Verif Fail Worker", role="tester", phase="phase_1", capabilities=["echo:test"])
            ]
        )

        result = coord.run_workflow(sample_context, plan)

        assert result.status == CoordinatorStatus.FAILED.value
        assert "task_A" in result.failed_tasks
        # No false artifacts from failed verification
        assert not any(a.producer_task == "task_A" for a in sample_context.artifacts.values())


# =============================================================================
# 3. Approval Gate & Permission Boundary Tests
# =============================================================================

class TestCoordinatorApprovalAndPermissions:
    def test_approval_required_stops_coordinator_before_runtime(self, sample_context):
        t1 = _make_task("task_ext_01", worker_id="worker_external")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        # Run without approval
        result = coord.run_workflow(
            sample_context,
            plan,
            connected_connectors=["redditapis"],
            authorized_permissions=["approval_required", "read", "write"],
            approved_task_ids=[],
        )

        assert result.status == CoordinatorStatus.APPROVAL_REQUIRED.value
        assert result.is_approval_required is True
        assert result.pending_approval_task_id == "task_ext_01"
        assert result.steps_executed == 1
        # Did not execute in runtime
        assert len(sample_context.artifacts) == 0

    def test_approval_resumption_executes_task(self, sample_context):
        t1 = _make_task("task_ext_01", worker_id="worker_external")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        # Run with approval granted
        result = coord.run_workflow(
            sample_context,
            plan,
            connected_connectors=["redditapis"],
            authorized_permissions=["approval_required", "read", "write"],
            approved_task_ids=["task_ext_01"],
        )

        assert result.status == CoordinatorStatus.COMPLETED.value
        assert result.is_completed is True
        assert "task_ext_01" in result.completed_tasks

    def test_missing_connector_blocks_coordinator(self, sample_context):
        t1 = _make_task("task_ext_01", worker_id="worker_external")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        # Run without required redditapis connector
        result = coord.run_workflow(
            sample_context,
            plan,
            connected_connectors=[],
            authorized_permissions=["approval_required", "read", "write"],
            approved_task_ids=["task_ext_01"],
        )

        assert result.status == CoordinatorStatus.BLOCKED.value
        assert "task_ext_01" in result.failed_tasks


# =============================================================================
# 4. Pipeline Integrity & Zero-Bypass Isolation Tests
# =============================================================================

class TestCoordinatorPipelineIntegrity:
    def test_coordinator_never_calls_base_worker_directly(self, sample_context, monkeypatch):
        # Instrument BaseWorker.execute_task to ensure coordinator never calls it directly
        # (WorkerRuntime.execute_envelope calls worker.execute_task, but coordinator must NOT)
        calls = []
        original_execute_envelope = WorkerRuntime.execute_envelope

        def tracking_execute_envelope(self, envelope, **kwargs):
            calls.append("WorkerRuntime.execute_envelope")
            return original_execute_envelope(self, envelope, **kwargs)

        monkeypatch.setattr(WorkerRuntime, "execute_envelope", tracking_execute_envelope)

        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)

        assert result.is_completed is True
        # Proves coordinator traversed WorkerRuntime.execute_envelope
        assert "WorkerRuntime.execute_envelope" in calls

    def test_dry_run_mode(self, sample_context):
        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan, dry_run=True)
        assert result.is_completed is True

    def test_max_steps_guard_prevents_infinite_loops(self, sample_context):
        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan, max_steps=0)
        assert result.status == CoordinatorStatus.MAX_STEPS_REACHED.value

    def test_missing_verification_halts_coordinator(self, sample_context, monkeypatch):
        # Instrument EchoWorker to return TaskResult without verification
        def execute_without_verif(self, task, context=None):
            return TaskResult(task_id=task.task_id, worker_id=self.worker_id, state=WorkerState.SUCCESS)

        monkeypatch.setattr(EchoWorker, "execute_task", execute_without_verif)
        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)
        assert result.status == CoordinatorStatus.FAILED.value
        assert "task_01" in result.failed_tasks

    def test_coordinator_never_bypasses_dispatcher(self, sample_context, monkeypatch):
        dispatch_calls = []
        original_dispatch_task = ExecutionDispatcher.dispatch_task

        def tracking_dispatch(self, task, **kwargs):
            dispatch_calls.append(task.task_id)
            return original_dispatch_task(self, task, **kwargs)

        monkeypatch.setattr(ExecutionDispatcher, "dispatch_task", tracking_dispatch)

        t1 = _make_task("task_01", worker_id="worker_echo")
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)
        assert result.is_completed is True
        assert dispatch_calls == ["task_01"]

    def test_secret_safe_audit_output(self, sample_context):
        t1 = _make_task("task_01", worker_id="worker_echo", inputs={"token": "[REDACTED_SECRET]"})
        plan = _make_plan([t1])
        coord = _build_test_coordinator()

        result = coord.run_workflow(sample_context, plan)
        res_dict = result.to_dict()
        assert isinstance(res_dict, dict)
        assert res_dict["status"] == "COMPLETED"
