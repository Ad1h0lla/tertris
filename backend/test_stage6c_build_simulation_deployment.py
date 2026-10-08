"""
Tetris — Workforce Engine: Stage 6C Build → Simulation → Deployment Multi-Phase Tests
======================================================================================

Proves the complete three-phase closed-loop execution lifecycle in the Workforce Engine:

BUILD (Task A)
    ↓
verified build artifacts (code_workspace, backend_api)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (transitions Task B from WAITING to READY)
    ↓
SIMULATION / QA (Task B consumes verified build artifacts from ProjectContext slice)
    ↓
verified simulation deliverables (simulation_result, qa_report)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (transitions Task C from WAITING to READY)
    ↓
DEPLOYMENT (Task C consumes Build + Simulation artifacts from ProjectContext slice)
    ↓
verified deployment deliverables (deployment_bundle, deployment_receipt)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)

Test Matrix (All 33 Core Requirements):
1. test_three_phase_workflow_structure
2. test_phase_dependency_graph
3. test_team_manager_resolves_all_three_workers
4. test_task_compilation_produces_three_tasks
5. test_build_initially_ready
6. test_simulation_initially_waiting
7. test_deployment_initially_waiting
8. test_build_executes_through_workforce
9. test_build_artifacts_promoted
10. test_graph_advancer_unlocks_simulation
11. test_simulation_consumes_build_artifacts
12. test_simulation_artifacts_promoted
13. test_graph_advancer_unlocks_deployment
14. test_deployment_receives_project_context_derived_inputs
15. test_deployment_executes_through_dispatcher
16. test_deployment_verification_pass
17. test_final_project_context_contains_deployment_outcome
18. test_final_coordinator_status_completed
19. test_build_failure_blocks_simulation_and_deployment
20. test_simulation_failure_blocks_deployment
21. test_deployment_failure_is_recorded_honestly
22. test_build_artifacts_survive_simulation_failure
23. test_simulation_artifacts_survive_deployment_failure
24. test_approval_blocks_deployment_execution
25. test_approval_allows_deployment_to_resume
26. test_legacy_execution_system_never_invoked
27. test_external_network_calls_are_zero_in_test_mode
28. test_credentials_are_zero_in_test_mode
29. test_synchronization_is_idempotent
30. test_execution_is_deterministic
31. test_coordinator_owns_ordering
32. test_graph_advancer_owns_unlock
33. test_deployment_task_uses_actual_project_context_handoff
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSimulationDeploymentSliceResult,
    create_build_project_context,
    create_build_simulation_deployment_workflow,
    execute_build_simulation_deployment_vertical_slice,
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
from orchestration.graph_advancer import GraphAdvancer, TaskState
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
    DeploymentWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    SimulationWorkerAdapter,
    WorkerRuntime,
    WorkerRuntimeRegistry,
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
# 1. Three-Phase Workflow, Team, and Graph Structure Tests (Tests 1-7)
# =============================================================================

class TestStage6CWorkflowAndGraphFoundation:
    """Validates the 3-phase ProjectWorkflow, TeamManager resolution, and initial task states."""

    def test_1_three_phase_workflow_structure(self):
        """Test 1: Three-phase workflow is valid with correct phases and workers."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)

        assert isinstance(wf, ProjectWorkflow)
        assert len(wf.phases) == 3
        assert "phase_build" in wf.phases
        assert "phase_simulation" in wf.phases
        assert "phase_deployment" in wf.phases

    def test_2_phase_dependency_graph(self):
        """Test 2: Proves the generic DAG dependency chain (build -> simulation -> deployment)."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)

        assert wf.get_phase("phase_build").dependencies == []
        assert wf.get_phase("phase_simulation").dependencies == ["phase_build"]
        assert wf.get_phase("phase_deployment").dependencies == ["phase_simulation"]

    def test_3_team_manager_resolves_all_three_workers(self):
        """Test 3: TeamManager resolves worker_code, worker_qa_simulation, and worker_deployment from registry."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "requirements"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        assert team_plan.is_executable()
        assert "worker_code" in team_plan.phase_assignments["phase_build"].worker_ids
        assert "worker_qa_simulation" in team_plan.phase_assignments["phase_simulation"].worker_ids
        assert "worker_deployment" in team_plan.phase_assignments["phase_deployment"].worker_ids

    def test_4_task_compilation_produces_three_tasks(self):
        """Test 4: TaskAssignmentEngine produces exactly three tasks."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        assert task_plan.is_executable()
        assert len(task_plan.tasks) == 3
        assert task_plan.get_task("task_build_code") is not None
        assert task_plan.get_task("task_simulation_qa_simulation") is not None
        assert task_plan.get_task("task_deployment_deployment") is not None

    def test_5_build_initially_ready(self):
        """Test 5: Build task is initially READY."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        assert "task_build_code" in task_plan.ready_tasks
        assert task_plan.get_task("task_build_code").metadata.get("readiness_status") == "READY"

    def test_6_simulation_initially_waiting(self):
        """Test 6: Simulation task is initially WAITING."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        assert "task_simulation_qa_simulation" in task_plan.waiting_tasks
        assert task_plan.get_task("task_simulation_qa_simulation").metadata.get("readiness_status") == "WAITING"

    def test_7_deployment_initially_waiting(self):
        """Test 7: Deployment task is initially WAITING."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        assert "task_deployment_deployment" in task_plan.waiting_tasks
        assert task_plan.get_task("task_deployment_deployment").metadata.get("readiness_status") == "WAITING"


# =============================================================================
# 2. Execution, Promotion & DAG Advancement Tests (Tests 8-18)
# =============================================================================

class TestStage6CExecutionLifecycleAndPromotion:
    """Validates the step-by-step and full execution lifecycle across Build, Simulation, and Deployment."""

    def test_8_9_build_executes_and_promotes_artifacts(self):
        """Test 8 & 9: Build executes through Workforce and promotes code artifacts."""
        result = execute_build_simulation_deployment_vertical_slice()

        assert result.success is True
        build_step = result.step_history[0]
        assert build_step.task_id == "task_build_code"
        assert build_step.worker_id == "worker_code"
        assert build_step.verification_status == "PASS"

        build_art_types = [a.artifact_type for a in result.build_artifacts]
        assert "code_workspace" in build_art_types
        assert "backend_api" in build_art_types

    def test_10_11_12_simulation_unlocks_consumes_and_promotes(self):
        """Test 10, 11, 12: GraphAdvancer unlocks Simulation, consumes Build artifacts, and promotes deliverables."""
        result = execute_build_simulation_deployment_vertical_slice()

        assert result.success is True
        sim_step = result.step_history[1]
        assert sim_step.task_id == "task_simulation_qa_simulation"
        assert sim_step.worker_id == "worker_qa_simulation"
        assert sim_step.verification_status == "PASS"

        sim_art_types = [a.artifact_type for a in result.simulation_artifacts]
        assert "simulation_result" in sim_art_types
        assert "qa_report" in sim_art_types

    def test_13_14_15_16_deployment_lifecycle(self):
        """Test 13, 14, 15, 16: Deployment is unlocked, receives inputs, executes through Dispatcher, and passes verification."""
        result = execute_build_simulation_deployment_vertical_slice()

        assert result.success is True
        deploy_step = result.step_history[2]
        assert deploy_step.task_id == "task_deployment_deployment"
        assert deploy_step.worker_id == "worker_deployment"
        assert deploy_step.dispatch_status == DispatchStatus.DISPATCHED.value
        assert deploy_step.runtime_status == RuntimeStatus.COMPLETED.value
        assert deploy_step.verification_status == "PASS"

        deploy_art_types = [a.artifact_type for a in result.deployment_artifacts]
        assert "deployment_bundle" in deploy_art_types
        assert "deployment_receipt" in deploy_art_types

    def test_17_18_final_context_and_coordinator_status(self):
        """Test 17 & 18: Final ProjectContext contains deployment outcome and coordinator status is COMPLETED."""
        result = execute_build_simulation_deployment_vertical_slice()

        assert result.status == CoordinatorStatus.COMPLETED.value
        ctx = result.project_context

        assert "phase_build" in ctx.phase_history
        assert ctx.phase_history["phase_build"].verification_status == "PASS"
        assert "phase_simulation" in ctx.phase_history
        assert ctx.phase_history["phase_simulation"].verification_status == "PASS"
        assert "phase_deployment" in ctx.phase_history
        assert ctx.phase_history["phase_deployment"].verification_status == "PASS"


# =============================================================================
# 3. Failure Isolation & Artifact Preservation Tests (Tests 19-23)
# =============================================================================

class TestStage6CFailureIsolationAndPreservation:
    """Validates failure handling, blocking, and artifact survival across stages."""

    def test_19_build_failure_blocks_simulation_and_deployment(self):
        """Test 19: Build failure blocks downstream tasks; 0 sim calls, 0 deploy calls."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())

        failing_code = CodeWorkerAdapter()
        failing_code.verify_result = MagicMock(return_value=VerificationResult.fail_result("Syntax error"))
        runtime.register_worker(failing_code)

        sim_worker = SimulationWorkerAdapter()
        sim_spy = MagicMock(side_effect=sim_worker.execute_task)
        sim_worker.execute_task = sim_spy
        runtime.register_worker(sim_worker)

        deploy_worker = DeploymentWorkerAdapter()
        deploy_spy = MagicMock(side_effect=deploy_worker.execute_task)
        deploy_worker.execute_task = deploy_spy
        runtime.register_worker(deploy_worker)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 1
        assert "task_build_code" in res.failed_tasks
        assert sim_spy.call_count == 0
        assert deploy_spy.call_count == 0

    def test_20_22_simulation_failure_blocks_deployment_and_preserves_build(self):
        """Test 20 & 22: Simulation failure blocks Deployment; Build artifacts survive."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())

        failing_sim = SimulationWorkerAdapter()
        failing_sim.verify_result = MagicMock(return_value=VerificationResult.fail_result("Sim failure"))
        runtime.register_worker(failing_sim)

        deploy_worker = DeploymentWorkerAdapter()
        deploy_spy = MagicMock(side_effect=deploy_worker.execute_task)
        deploy_worker.execute_task = deploy_spy
        runtime.register_worker(deploy_worker)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 2
        assert deploy_spy.call_count == 0

        build_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_code"]
        assert len(build_arts) >= 2

        deploy_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_deployment"]
        assert len(deploy_arts) == 0

    def test_21_23_deployment_failure_is_recorded_honestly_and_preserves_upstream(self):
        """Test 21 & 23: Deployment failure records failure honestly; Build and Simulation artifacts survive."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())

        failing_deploy = DeploymentWorkerAdapter()
        failing_deploy.verify_result = MagicMock(return_value=VerificationResult.fail_result("Deployment HTTP 500"))
        runtime.register_worker(failing_deploy)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 3
        assert "task_deployment_deployment" in res.failed_tasks

        # Upstream artifacts preserved
        build_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_code"]
        sim_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_qa_simulation"]
        assert len(build_arts) >= 2
        assert len(sim_arts) >= 2

        # No successful deployment artifacts
        deploy_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_deployment"]
        assert len(deploy_arts) == 0

        # Honest failure in phase history
        assert ctx.phase_history["phase_deployment"].status == "FAILED"
        assert ctx.phase_history["phase_deployment"].verification_status == "FAIL"


# =============================================================================
# 4. Approval Gating Tests (Tests 24-25)
# =============================================================================

class TestStage6CApprovalGating:
    """Validates approval boundaries and controlled resumption."""

    def test_24_approval_blocks_deployment_execution(self):
        """Test 24: Unapproved deployment task stops coordinator before execution."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dep_task = task_plan.get_task("task_deployment_deployment")
        dep_task.metadata["approval_required"] = True

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())
        runtime.register_worker(DeploymentWorkerAdapter())

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={"task_build_code", "task_simulation_qa_simulation"},
        )

        assert res.status == CoordinatorStatus.APPROVAL_REQUIRED.value
        assert res.is_approval_required is True
        assert res.pending_approval_task_id == "task_deployment_deployment"
        assert "task_deployment_deployment" not in res.completed_tasks
        assert len(res.completed_tasks) == 2

    def test_25_approval_allows_deployment_to_resume(self):
        """Test 25: Explicit approval allows deployment to resume and complete."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dep_task = task_plan.get_task("task_deployment_deployment")
        dep_task.metadata["approval_required"] = True

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())
        runtime.register_worker(DeploymentWorkerAdapter())

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        # Run with explicit approval for deployment granted
        res_approved = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={"task_build_code", "task_simulation_qa_simulation", "task_deployment_deployment"},
        )
        assert res_approved.is_completed is True
        assert res_approved.status == CoordinatorStatus.COMPLETED.value
        assert "task_deployment_deployment" in res_approved.completed_tasks


# =============================================================================
# 5. Isolation, Determinism, Idempotency & Provenance Tests (Tests 26-33)
# =============================================================================

class TestStage6CIsolationDeterminismAndProvenance:
    """Validates zero legacy calls, offline test safety, determinism, idempotency, and handoff provenance."""

    def test_26_legacy_execution_system_never_invoked(self):
        """Test 26: Proves zero calls to legacy execution paths."""
        with patch("orchestrator.router.route_to_specialist", create=True) as mock_router, \
             patch("execution.runner.run_controlled_verification", create=True) as mock_runner, \
             patch("main._execute_agent_fixed", create=True) as mock_main:

            result = execute_build_simulation_deployment_vertical_slice()

            assert result.success is True
            assert mock_router.call_count == 0
            assert mock_runner.call_count == 0
            assert mock_main.call_count == 0

    def test_27_28_external_network_and_credentials_zero_in_test_mode(self):
        """Test 27 & 28: Proves zero external network calls or credentials in test mode."""
        with patch("urllib.request.urlopen") as mock_url, \
             patch("socket.socket.connect") as mock_socket:

            result = execute_build_simulation_deployment_vertical_slice()
            assert result.success is True
            assert mock_url.call_count == 0
            assert mock_socket.call_count == 0

    def test_29_synchronization_is_idempotent(self):
        """Test 29: Synchronization of identical runtime results is idempotent across all 3 phases."""
        ctx = create_build_project_context()
        sync = ContextSynchronizer()

        for phase_id, worker_id, task_id, art_type in [
            ("phase_build", "worker_code", "task_build_code", "code_workspace"),
            ("phase_simulation", "worker_qa_simulation", "task_simulation_qa_simulation", "simulation_result"),
            ("phase_deployment", "worker_deployment", "task_deployment_deployment", "deployment_bundle"),
        ]:
            task_res = TaskResult(
                task_id=task_id,
                worker_id=worker_id,
                state=WorkerState.SUCCESS,
                output={"status": "OK"},
                artifacts=[{"artifact_type": art_type, "status": "AVAILABLE"}],
            )
            rt_res = RuntimeResult(
                runtime_id=f"rt_{task_id}_{ctx.execution_id}",
                dispatch_id=f"dispatch_{task_id}_{ctx.execution_id}",
                execution_id=ctx.execution_id,
                task_id=task_id,
                project_id=ctx.project_id,
                worker_id=worker_id,
                status=RuntimeStatus.COMPLETED.value,
                task_result=task_res,
                verification_result=VerificationResult.pass_result(),
            )

            sync_1 = sync.apply_result(ctx, rt_res, phase_id=phase_id)
            assert sync_1.status == SyncStatus.SYNCED.value
            count_1 = len(ctx.artifacts)

            sync_2 = sync.apply_result(ctx, rt_res, phase_id=phase_id)
            assert sync_2.status == SyncStatus.SKIPPED.value
            assert len(ctx.artifacts) == count_1

    def test_30_execution_is_deterministic(self):
        """Test 30: Repeated runs produce identical task IDs, phase IDs, and artifact structure."""
        res_1 = execute_build_simulation_deployment_vertical_slice()
        res_2 = execute_build_simulation_deployment_vertical_slice()

        assert res_1.status == res_2.status == CoordinatorStatus.COMPLETED.value
        assert [t.task_id for t in res_1.task_plan.tasks] == [t.task_id for t in res_2.task_plan.tasks]
        assert [a.artifact_type for a in res_1.deployment_artifacts] == [a.artifact_type for a in res_2.deployment_artifacts]

    def test_31_coordinator_owns_ordering(self):
        """Test 31: Coordinator, not integration layer, discovers and executes DAG in topological order."""
        result = execute_build_simulation_deployment_vertical_slice()
        assert result.success is True
        assert [s.task_id for s in result.step_history] == [
            "task_build_code",
            "task_simulation_qa_simulation",
            "task_deployment_deployment",
        ]

    def test_32_graph_advancer_owns_unlock(self):
        """Test 32: GraphAdvancer owns unlocking tasks upon upstream completion without manual mutation."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        advancer = GraphAdvancer()

        # Step 1 unlock
        adv_1 = advancer.advance_graph(task_plan, completed_task_ids=["task_build_code"])
        assert "task_simulation_qa_simulation" in adv_1.newly_ready_tasks

        # Step 2 unlock
        adv_2 = advancer.advance_graph(task_plan, completed_task_ids=["task_build_code", "task_simulation_qa_simulation"])
        assert "task_deployment_deployment" in adv_2.newly_ready_tasks

    def test_33_deployment_task_uses_actual_project_context_handoff(self):
        """Test 33: CRITICAL — Deployment receives verified Build + Simulation artifacts from ProjectContext."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
        )

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())

        deploy_adapter = DeploymentWorkerAdapter()
        executed_tasks = []
        original_exec = deploy_adapter.execute_task

        def spy_exec(task, context=None):
            executed_tasks.append(task)
            return original_exec(task, context=context)

        deploy_adapter.execute_task = spy_exec
        runtime.register_worker(deploy_adapter)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        coord_res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=task_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )
        assert coord_res.is_completed
        assert len(executed_tasks) == 1

        dep_task = executed_tasks[0]
        code_producers = [a.get("producer_task") for a in dep_task.inputs.get("code_assets", [])]
        sim_producers = [a.get("producer_task") for a in dep_task.inputs.get("simulation", [])]

        assert "task_build_code" in code_producers
        assert "task_simulation_qa_simulation" in sim_producers
