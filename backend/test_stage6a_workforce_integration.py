"""
Tetris — Workforce Engine: Stage 6A Build Vertical Slice Integration Tests
==========================================================================

Proves the complete end-to-end integration between Tetris project specifications
and the Workforce Engine closed-loop execution lifecycle:

Tetris Project
    ↓
ProjectContext
    ↓
Build Phase (phase_build)
    ↓
TeamManager
    ↓
TaskAssignmentEngine
    ↓
CompiledTaskPlan
    ↓
WorkforceCoordinator
    ↓
ExecutionDispatcher
    ↓
WorkerRuntime
    ↓
CodeWorkerAdapter
    ↓
Verification
    ↓
ContextSynchronizer
    ↓
Verified Build Artifact in ProjectContext

Test Matrix:
1. ProjectContext fixture is valid and complete.
2. Build workflow structure and worker_code assignment.
3. TeamManager resolves worker_code via WorkerRegistry.
4. TaskAssignmentEngine compiles valid Build task (task_build_code).
5. WorkforceCoordinator executes the task end-to-end.
6. ExecutionDispatcher is invoked and builds ExecutionEnvelope.
7. WorkerRuntime is invoked and processes the envelope.
8. CodeWorkerAdapter is actually invoked (prepare -> execute -> verify).
9. Verification PASS is required for successful completion.
10. Failed verification does not create a successful artifact.
11. Successful verification creates an authoritative ProjectContext artifact.
12. Artifact provenance is complete and auditable.
13. Final coordinator status is COMPLETED.
14. Legacy executor / router is NEVER invoked.
15. No external network calls occur.
16. No credentials are required.
17. Re-running the integration produces deterministic outputs.
18. Duplicate RuntimeResult does not duplicate ProjectContext artifacts.
19. Legacy project dict correctly adapts into ProjectContext.
20. ProjectContext slice retrieval reflects verified build artifacts.
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSliceResult,
    create_build_project_context,
    create_build_workflow,
    execute_build_vertical_slice,
    from_legacy_project_dict,
)
from orchestration.context_sync import ContextSynchronizer, SyncResult, SyncStatus
from orchestration.execution_dispatcher import (
    DispatchRecord,
    DispatchRegistry,
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
    get_default_dispatch_registry,
)
from orchestration.graph_advancer import GraphAdvancer
from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow
from orchestration.project_context import (
    Artifact,
    ProjectContext,
    ProjectDefinition,
)
from orchestration.task_assignment import (
    CompiledTaskPlan,
    TaskAssignmentEngine,
    TaskReadiness,
)
from orchestration.team_manager import TeamManager, TeamPlan, TeamReadiness
from orchestration.worker_contract import (
    Task,
    TaskResult,
    VerificationResult,
    WorkerState,
)
from orchestration.worker_registry import WorkerRegistry, get_default_registry
from orchestration.worker_runtime import (
    CodeWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    WorkerRuntime,
    get_default_runtime_registry,
)
from orchestration.workforce_coordinator import (
    CoordinatorResult,
    CoordinatorStatus,
    WorkforceCoordinator,
)


@pytest.fixture(autouse=True)
def clean_registries():
    """Ensure fresh registries before every test."""
    reg = get_default_dispatch_registry()
    reg.clear()
    rt_reg = get_default_runtime_registry()
    rt_reg.clear()


# =============================================================================
# 1. ProjectContext & Workflow Fixture Validation Tests
# =============================================================================

class TestStage6AFixtureAndWorkflow:
    """Validates the input fixtures and workflow construction contracts."""

    def test_project_context_fixture_valid(self):
        """Test 1: ProjectContext fixture is valid, typed, and complete."""
        ctx = create_build_project_context(
            project_id="proj_test_health_01",
            execution_id="exec_test_health_01",
        )
        assert ctx.project_id == "proj_test_health_01"
        assert ctx.execution_id == "exec_test_health_01"
        assert ctx.definition.idea == HEALTH_API_FIXTURE["idea"]
        assert len(ctx.definition.requirements) == 3
        assert len(ctx.definition.acceptance_criteria) == 3
        assert "FastAPI" in ctx.definition.requirements[0]
        assert len(ctx.artifacts) == 0

    def test_build_workflow_resolves_worker_code(self):
        """Test 2: Build workflow creates phase_build with worker_code assignment."""
        ctx = create_build_project_context()
        wf = create_build_workflow(ctx)

        assert isinstance(wf, ProjectWorkflow)
        assert "phase_build" in wf.phases
        build_phase = wf.get_phase("phase_build")
        assert build_phase is not None
        assert build_phase.phase_number == 1
        assert build_phase.status == PhaseStatus.READY
        assert build_phase.has_worker("worker_code")

        assignment = build_phase.get_worker("worker_code")
        assert assignment is not None
        assert assignment.role == "code_builder"
        assert "code_generation" in assignment.capabilities
        assert "backend" in assignment.capabilities
        assert "api_development" in assignment.capabilities

    def test_team_manager_resolves_worker_code(self):
        """Test 3: TeamManager resolves worker_code via WorkerRegistry."""
        ctx = create_build_project_context()
        wf = create_build_workflow(ctx)
        team_mgr = TeamManager()

        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "requirements"]),
        )

        assert isinstance(team_plan, TeamPlan)
        assert team_plan.is_executable()
        assert team_plan.readiness == TeamReadiness.READY.value
        assert "phase_build" in team_plan.phase_assignments
        phase_plan = team_plan.phase_assignments["phase_build"]
        assert "worker_code" in phase_plan.worker_ids
        assert len(phase_plan.capabilities_missing) == 0

    def test_task_assignment_engine_creates_build_task(self):
        """Test 4: TaskAssignmentEngine creates a valid Build task for worker_code."""
        ctx = create_build_project_context()
        wf = create_build_workflow(ctx)
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(wf, ctx.get_slice(["idea", "goal", "requirements"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine()
        task_plan = task_engine.assign_tasks(ctx, wf, team_plan)

        assert isinstance(task_plan, CompiledTaskPlan)
        assert task_plan.is_executable()
        assert task_plan.readiness == TaskReadiness.READY.value
        assert len(task_plan.tasks) == 1

        build_task = task_plan.tasks[0]
        assert build_task.task_id == "task_build_code"
        assert build_task.worker_id == "worker_code"
        assert build_task.project_id == ctx.project_id
        assert build_task.execution_id == ctx.execution_id
        assert "idea" in build_task.inputs
        assert "requirements" in build_task.inputs
        assert "code_workspace" in build_task.metadata.get("produces_artifacts", [])
        assert "backend_api" in build_task.metadata.get("produces_artifacts", [])


# =============================================================================
# 2. End-to-End Vertical Slice Execution & Subsystem Invocations
# =============================================================================

class TestStage6AExecutionAndPipeline:
    """Validates the execution lifecycle across Coordinator, Dispatcher, Runtime, Adapter, ContextSync."""

    def test_workforce_coordinator_executes_task_end_to_end(self):
        """Test 5: WorkforceCoordinator executes the task and completes successfully."""
        ctx = create_build_project_context(
            project_id="proj_slice_exec_01",
            execution_id="exec_slice_exec_01",
        )
        res = execute_build_vertical_slice(project_context=ctx)

        assert isinstance(res, BuildSliceResult)
        assert res.success is True
        assert res.status == CoordinatorStatus.COMPLETED.value
        assert res.coordinator_result.is_completed
        assert "task_build_code" in res.coordinator_result.completed_tasks
        assert len(res.coordinator_result.failed_tasks) == 0
        assert len(res.coordinator_result.blocked_tasks) == 0
        assert res.coordinator_result.steps_executed == 1

    def test_execution_dispatcher_is_invoked(self):
        """Test 6: ExecutionDispatcher is actually invoked to produce the ExecutionEnvelope."""
        ctx = create_build_project_context()
        wf = create_build_workflow(ctx)
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(wf, ctx.get_slice(["idea", "goal", "requirements"]))
        team_plan.apply_to_workflow(wf)
        task_engine = TaskAssignmentEngine()
        task_plan = task_engine.assign_tasks(ctx, wf, team_plan)

        dispatcher = ExecutionDispatcher()
        with patch.object(dispatcher, "dispatch_task", wraps=dispatcher.dispatch_task) as spy_dispatch:
            coordinator = WorkforceCoordinator(dispatcher=dispatcher)
            res = coordinator.run_workflow(ctx, task_plan)

            assert res.is_completed
            assert spy_dispatch.call_count == 1
            call_task = spy_dispatch.call_args[1]["task"]
            assert call_task.task_id == "task_build_code"
            assert call_task.worker_id == "worker_code"

    def test_worker_runtime_is_invoked(self):
        """Test 7: WorkerRuntime is actually invoked to execute the envelope."""
        ctx = create_build_project_context()
        wf = create_build_workflow(ctx)
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(wf, ctx.get_slice(["idea", "goal", "requirements"]))
        team_plan.apply_to_workflow(wf)
        task_engine = TaskAssignmentEngine()
        task_plan = task_engine.assign_tasks(ctx, wf, team_plan)

        runtime = WorkerRuntime()
        with patch.object(runtime, "execute_envelope", wraps=runtime.execute_envelope) as spy_exec:
            coordinator = WorkforceCoordinator(runtime=runtime)
            res = coordinator.run_workflow(ctx, task_plan)

            assert res.is_completed
            assert spy_exec.call_count == 1
            call_env = spy_exec.call_args[0][0]
            assert call_env.task_id == "task_build_code"
            assert call_env.worker_id == "worker_code"

    def test_code_worker_adapter_actually_invoked(self):
        """Test 8: CodeWorkerAdapter is resolved and its execute_task / verify_result are called."""
        ctx = create_build_project_context()
        code_worker = CodeWorkerAdapter()

        with patch.object(code_worker, "prepare_task", wraps=code_worker.prepare_task) as spy_prep, \
             patch.object(code_worker, "execute_task", wraps=code_worker.execute_task) as spy_exec, \
             patch.object(code_worker, "verify_result", wraps=code_worker.verify_result) as spy_verif:

            runtime = WorkerRuntime(custom_workers={"worker_code": code_worker})
            coordinator = WorkforceCoordinator(runtime=runtime)

            res = execute_build_vertical_slice(
                project_context=ctx,
                runtime=runtime,
                coordinator=coordinator,
            )

            assert res.success is True
            assert spy_prep.call_count == 1
            assert spy_exec.call_count == 1
            assert spy_verif.call_count == 1

            # Assert output contents from CodeWorkerAdapter
            task_result = spy_exec.spy_return if hasattr(spy_exec, "spy_return") else spy_exec.mock_calls[0]
            assert res.artifacts is not None
            assert len(res.artifacts) >= 2


# =============================================================================
# 3. Verification & Artifact Promotion Tests
# =============================================================================

class TestStage6AVerificationAndArtifacts:
    """Validates verification gating, artifact promotion, provenance, and idempotency."""

    def test_verification_pass_is_required(self):
        """Test 9: Verification PASS is verified in RuntimeResult and CoordinatorStepRecord."""
        ctx = create_build_project_context()
        res = execute_build_vertical_slice(project_context=ctx)

        assert res.success is True
        assert len(res.step_history) == 1
        step = res.step_history[0]
        assert step.task_id == "task_build_code"
        assert step.worker_id == "worker_code"
        assert step.dispatch_status == DispatchStatus.DISPATCHED.value
        assert step.runtime_status == RuntimeStatus.COMPLETED.value
        assert step.verification_status == "PASS"
        assert step.sync_status == SyncStatus.SYNCED.value

    def test_failed_verification_does_not_create_successful_artifact(self):
        """Test 10: If verification fails, coordinator halts and zero success artifacts are created."""
        ctx = create_build_project_context(
            project_id="proj_fail_test",
            execution_id="exec_fail_test",
        )
        failing_worker = CodeWorkerAdapter()

        # Monkeypatch verify_result to fail
        def failing_verify(task_result: TaskResult) -> VerificationResult:
            return VerificationResult.fail_result(error="Simulated route compilation failure.")

        failing_worker.verify_result = failing_verify

        runtime = WorkerRuntime(custom_workers={"worker_code": failing_worker})
        coordinator = WorkforceCoordinator(runtime=runtime)

        res = execute_build_vertical_slice(
            project_context=ctx,
            runtime=runtime,
            coordinator=coordinator,
        )

        assert res.success is False
        assert res.status == CoordinatorStatus.FAILED.value
        assert "task_build_code" in res.coordinator_result.failed_tasks

        # Zero success artifacts must be promoted to ProjectContext
        assert len(ctx.artifacts) == 0
        # Failure is recorded honestly in phase history
        assert "phase_build" in ctx.phase_history
        assert ctx.phase_history["phase_build"].status == "FAILED"
        assert ctx.phase_history["phase_build"].verification_status == "FAIL"

    def test_successful_verification_creates_project_context_artifact(self):
        """Test 11: Successful verification creates ProjectContext artifacts."""
        ctx = create_build_project_context(
            project_id="proj_art_test",
            execution_id="exec_art_test",
        )
        res = execute_build_vertical_slice(project_context=ctx)

        assert res.success is True
        assert len(ctx.artifacts) >= 2
        artifact_types = [a.artifact_type for a in ctx.artifacts.values()]
        assert "code_workspace" in artifact_types
        assert "backend_api" in artifact_types

    def test_artifact_provenance_is_correct(self):
        """Test 12: Artifact provenance contains complete traceable metadata."""
        ctx = create_build_project_context(
            project_id="proj_prov_001",
            execution_id="exec_prov_001",
        )
        res = execute_build_vertical_slice(project_context=ctx)

        assert res.success is True
        for art in ctx.artifacts.values():
            assert isinstance(art, Artifact)
            assert art.phase_id == "phase_build"
            assert art.producer_worker == "worker_code"
            assert art.producer_task == "task_build_code"
            assert art.status == "AVAILABLE"
            assert "runtime_id" in art.metadata
            assert art.metadata["verified"] is True
            assert art.metadata["verification_status"] == "PASS"

        # Check phase history reference
        assert "phase_build" in ctx.phase_history
        phase_hist = ctx.phase_history["phase_build"]
        assert phase_hist.status == "COMPLETED"
        assert phase_hist.producer_worker == "worker_code"
        assert phase_hist.verification_status == "PASS"

    def test_duplicate_runtime_result_does_not_duplicate_artifacts(self):
        """Test 18: Re-applying duplicate RuntimeResult to ContextSynchronizer is idempotent."""
        ctx = create_build_project_context()
        res = execute_build_vertical_slice(project_context=ctx)
        initial_art_count = len(ctx.artifacts)
        assert initial_art_count >= 2

        # Try to re-apply the same runtime result
        sync = ContextSynchronizer()
        # Find step record
        step = res.step_history[0]
        # Build synthetic runtime result with same runtime_id
        task_res = TaskResult(
            task_id="task_build_code",
            worker_id="worker_code",
            state=WorkerState.SUCCESS,
            output={"status": "BUILT", "routes": ["/health"]},
        )
        verif_res = VerificationResult.pass_result(evidence={"routes": 1})
        dup_rt_res = RuntimeResult(
            runtime_id=f"rt_task_build_code_{ctx.execution_id}",
            dispatch_id=f"dispatch_task_build_code_{ctx.execution_id}",
            task_id="task_build_code",
            execution_id=ctx.execution_id,
            project_id=ctx.project_id,
            worker_id="worker_code",
            status=RuntimeStatus.COMPLETED.value,
            task_result=task_res,
            verification_result=verif_res,
            verified=True,
        )

        sync_res1 = sync.apply_result(ctx, dup_rt_res, phase_id="phase_build")
        count_after_first = len(ctx.artifacts)
        # Second application with same synchronizer instance
        sync_res2 = sync.apply_result(ctx, dup_rt_res, phase_id="phase_build")

        assert sync_res2.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == count_after_first


# =============================================================================
# 4. Legacy Isolation & Zero Side Effects Tests
# =============================================================================

class TestStage6ALegacyIsolationAndGuards:
    """Validates that legacy routers/runners are never called and zero external network calls occur."""

    def test_legacy_executor_never_invoked(self):
        """Test 14: Legacy route_to_specialist and runner are NEVER called during Workforce build."""
        ctx = create_build_project_context()

        with patch("orchestrator.router.route_to_specialist") as mock_legacy_router, \
             patch("execution.runner.run_controlled_verification") as mock_legacy_runner:

            res = execute_build_vertical_slice(project_context=ctx)

            assert res.success is True
            assert mock_legacy_router.call_count == 0
            assert mock_legacy_runner.call_count == 0

    def test_no_external_network_calls_or_credentials_required(self):
        """Tests 15 & 16: Executes completely offline with zero credentials and zero API keys."""
        ctx = create_build_project_context()

        # Mock socket or urllib/requests if any were to be made
        with patch("urllib.request.urlopen") as mock_url:
            res = execute_build_vertical_slice(
                project_context=ctx,
                connected_connectors=[],
                authorized_permissions=["filesystem:write", "workspace:edit"],
            )

            assert res.success is True
            assert mock_url.call_count == 0

    def test_deterministic_rerun_produces_identical_outputs(self):
        """Test 17: Re-running with the same deterministic fixture produces identical structure."""
        ctx1 = create_build_project_context(project_id="proj_fixed", execution_id="exec_fixed_1")
        ctx2 = create_build_project_context(project_id="proj_fixed", execution_id="exec_fixed_2")

        res1 = execute_build_vertical_slice(project_context=ctx1)
        res2 = execute_build_vertical_slice(project_context=ctx2)

        assert res1.success is True and res2.success is True
        assert res1.status == res2.status
        assert [a.artifact_type for a in res1.artifacts] == [a.artifact_type for a in res2.artifacts]
        assert [a.location for a in res1.artifacts] == [a.location for a in res2.artifacts]

    def test_from_legacy_project_dict_adapter(self):
        """Test 19: Legacy project goal dictionary is seamlessly adapted to ProjectContext."""
        legacy_goal = {
            "understood_goal": "Build a small FastAPI backend exposing GET /health",
            "idea_type": "saas",
            "requirements": ["FastAPI", "GET /health"],
            "acceptance_criteria": ["Expose GET /health endpoint"],
            "execution_id": "exec_from_legacy_99",
            "project_id": "proj_from_legacy_99",
        }

        ctx = from_legacy_project_dict(legacy_goal)
        assert ctx.project_id == "proj_from_legacy_99"
        assert ctx.execution_id == "exec_from_legacy_99"
        assert "FastAPI" in ctx.definition.requirements[0]

        res = execute_build_vertical_slice(project_context=ctx)
        assert res.success is True
        assert len(res.artifacts) >= 2

    def test_context_slice_retrieval_reflects_build_artifacts(self):
        """Test 20: ProjectContext slice retrieval reflects code assets after successful build."""
        ctx = create_build_project_context()
        res = execute_build_vertical_slice(project_context=ctx)

        assert res.success is True
        slice_data = ctx.get_slice(["code_assets", "artifacts", "requirements", "phase_history"])
        assert "code_assets" in slice_data
        assert "artifacts" in slice_data
        assert "phase_history" in slice_data
        assert len(slice_data["artifacts"]) >= 2
        assert len(slice_data["code_assets"]) >= 1
        assert "phase_build" in slice_data["phase_history"]
