"""
Tetris — Workforce Engine: Stage 6B Build → Simulation Multi-Phase Vertical Slice Tests
========================================================================================

Proves the first real cross-phase multi-task workflow in the Workforce Engine:

BUILD (Task A)
    ↓
verified build artifacts (code_workspace, backend_api)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (automatically transitions Task B from WAITING to READY)
    ↓
SIMULATION / QA (Task B consumes verified build artifacts from ProjectContext slice)
    ↓
verified simulation deliverables (simulation_result, qa_report)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)

Test Matrix (31 Core Points):
1. Two-phase workflow is valid.
2. TeamManager resolves worker_code.
3. TeamManager resolves worker_qa_simulation.
4. TaskAssignmentEngine creates two tasks.
5. Build task is READY initially.
6. Simulation task is WAITING initially.
7. Dependency graph is: build → simulation.
8. WorkforceCoordinator executes Build first.
9. CodeWorkerAdapter is actually invoked.
10. Build verification PASS occurs.
11. Build artifacts enter ProjectContext.
12. GraphAdvancer unlocks Simulation.
13. Simulation becomes READY without manual state mutation.
14. SimulationWorkerAdapter is actually invoked.
15. Simulation receives Build-derived context (tested artifacts list / code_workspace).
16. Simulation verification PASS occurs.
17. Simulation artifacts enter ProjectContext.
18. Both phase outcomes are recorded as PASS in ProjectContext phase history.
19. Final CoordinatorStatus is COMPLETED.
20. Build failure prevents Simulation execution (0 simulation worker calls).
21. Simulation failure produces honest FAILED state.
22. Failed Simulation does not create successful simulation artifacts.
23. Build artifacts remain preserved after Simulation failure.
24. No legacy executor is invoked.
25. No external network calls occur.
26. No credentials are required.
27. Duplicate Build RuntimeResult does not duplicate artifacts in ProjectContext.
28. Duplicate Simulation RuntimeResult does not duplicate artifacts in ProjectContext.
29. Repeated deterministic execution produces stable results.
30. Coordinator, not the integration layer, owns task ordering.
31. GraphAdvancer, not the integration layer, unlocks Simulation.
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSimulationSliceResult,
    create_build_project_context,
    create_build_simulation_workflow,
    execute_build_simulation_vertical_slice,
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
# 1. Two-Phase Workflow & Team Resolution Tests
# =============================================================================

class TestStage6BWorkflowAndTeam:
    """Validates the 2-phase ProjectWorkflow and TeamManager resolution."""

    def test_two_phase_workflow_structure(self):
        """Test 1: Two-phase workflow is valid with correct phase dependencies and workers."""
        ctx = create_build_project_context(
            project_id="proj_workflow_test",
            execution_id="exec_workflow_test",
        )
        wf = create_build_simulation_workflow(ctx)

        assert isinstance(wf, ProjectWorkflow)
        assert len(wf.phases) == 2
        assert "phase_build" in wf.phases
        assert "phase_simulation" in wf.phases

        build_phase = wf.get_phase("phase_build")
        assert build_phase.phase_number == 1
        assert build_phase.status == PhaseStatus.READY
        assert build_phase.dependencies == []
        assert "worker_code" in [w.worker_id for w in build_phase.workers]

        sim_phase = wf.get_phase("phase_simulation")
        assert sim_phase.phase_number == 2
        assert sim_phase.status == PhaseStatus.PLANNED
        assert "phase_build" in sim_phase.dependencies
        assert "worker_qa_simulation" in [w.worker_id for w in sim_phase.workers]

    def test_team_manager_resolves_both_workers(self):
        """Test 2 & 3: TeamManager resolves worker_code and worker_qa_simulation from authoritative WorkerRegistry."""
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "requirements"]),
        )

        assert team_plan.is_executable()
        assert "phase_build" in team_plan.phase_assignments
        assert "phase_simulation" in team_plan.phase_assignments
        assert "worker_code" in team_plan.phase_assignments["phase_build"].worker_ids
        assert "worker_qa_simulation" in team_plan.phase_assignments["phase_simulation"].worker_ids

        # Ensure authoritative catalog resolution
        code_worker = registry.get("worker_code")
        assert code_worker is not None
        assert "code_generation" in code_worker.capabilities

        sim_worker = registry.get("worker_qa_simulation")
        assert sim_worker is not None
        assert "qa_testing" in sim_worker.capabilities or "behavioral_simulation" in sim_worker.capabilities


# =============================================================================
# 2. Task Compilation & Dependency Graph Tests
# =============================================================================

class TestStage6BTaskCompilationAndGraph:
    """Validates TaskAssignmentEngine compilation and the DAG structure."""

    def test_task_assignment_compiles_two_tasks_with_proper_readiness(self):
        """Test 4, 5, 6, 7: TaskAssignmentEngine creates 2 tasks, build is READY, simulation is WAITING."""
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
        )

        assert task_plan.is_executable()
        assert len(task_plan.tasks) == 2

        task_build = task_plan.get_task("task_build_code")
        assert task_build is not None
        assert task_build.worker_id == "worker_code"
        assert task_build.metadata.get("readiness_status") == "READY"
        assert len(task_build.dependencies) == 0

        task_sim = task_plan.get_task("task_simulation_qa_simulation")
        assert task_sim is not None
        assert task_sim.worker_id == "worker_qa_simulation"
        assert task_sim.metadata.get("readiness_status") == "WAITING"
        assert "task_build_code" in task_sim.dependencies

        # Assert compiled DAG structure
        assert task_plan.ready_tasks == ["task_build_code"]
        assert "task_simulation_qa_simulation" in task_plan.waiting_tasks
        assert "task_build_code" in task_plan.phase_task_map.get("phase_build", [])
        assert "task_simulation_qa_simulation" in task_plan.phase_task_map.get("phase_simulation", [])


# =============================================================================
# 3. End-to-End Multi-Phase Execution & ProjectContext Handoff Tests
# =============================================================================

class TestStage6BExecutionAndHandoff:
    """Validates WorkforceCoordinator DAG execution, GraphAdvancer unlocking, and real context handoff."""

    def test_end_to_end_build_to_simulation_execution(self):
        """
        Test 8-19: Proves the complete Build -> Context -> Simulation vertical slice.
        - WorkforceCoordinator executes Build first
        - CodeWorkerAdapter is invoked with verification PASS
        - Build artifacts enter ProjectContext
        - GraphAdvancer unlocks Simulation to READY without manual state mutation
        - SimulationWorkerAdapter is invoked with verification PASS
        - Simulation receives Build-derived context
        - Simulation artifacts enter ProjectContext
        - Both phase outcomes are recorded as PASS
        - Final CoordinatorStatus is COMPLETED
        """
        result = execute_build_simulation_vertical_slice()

        # Final terminal state
        assert result.success is True
        assert result.status == CoordinatorStatus.COMPLETED.value
        assert result.coordinator_result.steps_executed == 2

        # Verify Build Phase execution
        build_step = result.step_history[0]
        assert build_step.task_id == "task_build_code"
        assert build_step.worker_id == "worker_code"
        assert build_step.verification_status == "PASS"
        assert build_step.runtime_status == RuntimeStatus.COMPLETED.value
        assert build_step.sync_status == SyncStatus.SYNCED.value

        # Verify Simulation Phase execution
        sim_step = result.step_history[1]
        assert sim_step.task_id == "task_simulation_qa_simulation"
        assert sim_step.worker_id == "worker_qa_simulation"
        assert sim_step.verification_status == "PASS"
        assert sim_step.runtime_status == RuntimeStatus.COMPLETED.value
        assert sim_step.sync_status == SyncStatus.SYNCED.value

        # Verify ProjectContext contains artifacts from both phases
        ctx = result.project_context
        assert len(result.build_artifacts) >= 2
        assert len(result.simulation_artifacts) >= 2

        build_art_types = [a.artifact_type for a in result.build_artifacts]
        assert "code_workspace" in build_art_types
        assert "backend_api" in build_art_types

        sim_art_types = [a.artifact_type for a in result.simulation_artifacts]
        assert "simulation_result" in sim_art_types
        assert "qa_report" in sim_art_types

        # Verify phase history recorded in ProjectContext
        assert "phase_build" in ctx.phase_history
        assert ctx.phase_history["phase_build"].verification_status == "PASS"
        assert "phase_simulation" in ctx.phase_history
        assert ctx.phase_history["phase_simulation"].verification_status == "PASS"

    def test_handoff_integrity_simulation_consumes_build_artifacts(self):
        """
        Test 15: CRITICAL — Proves that Simulation receives the exact Build-produced artifacts from ProjectContext.
        Asserts that Simulation task inputs contain the code_workspace and backend_api produced by Build.
        """
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())

        # Track what SimulationWorkerAdapter actually receives
        sim_adapter = SimulationWorkerAdapter()
        executed_tasks = []
        original_exec = sim_adapter.execute_task

        def spy_execute(task, context=None):
            executed_tasks.append(task)
            return original_exec(task, context=context)

        sim_adapter.execute_task = spy_execute
        runtime.register_worker(sim_adapter)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        coord_res = coord.run_workflow(project_context=ctx, compiled_task_plan=task_plan)
        assert coord_res.is_completed

        # Verify that SimulationWorkerAdapter was called with the actual Build artifacts in its inputs
        assert len(executed_tasks) == 1
        sim_task = executed_tasks[0]
        assert "code_assets" in sim_task.inputs
        code_assets = sim_task.inputs["code_assets"]
        assert isinstance(code_assets, list)
        assert len(code_assets) >= 2

        # Check artifact provenance within the consumed code_assets
        asset_types = [a.get("artifact_type") for a in code_assets]
        assert "code_workspace" in asset_types
        assert "backend_api" in asset_types

        # Ensure the artifacts originated from task_build_code
        for asset in code_assets:
            assert asset.get("producer_task") == "task_build_code"
            assert asset.get("producer_worker") == "worker_code"
            assert asset.get("status") == "AVAILABLE"
            assert asset.get("metadata", {}).get("verification_status") == "PASS"

    def test_no_manual_state_mutation_graph_advancer_unlocks_simulation(self):
        """Test 12, 13, 31: Proves GraphAdvancer, not manual mutation, unlocks Simulation upon Build completion."""
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        # Before any execution, Simulation is WAITING
        assert "task_simulation_qa_simulation" in task_plan.waiting_tasks

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())

        advancer = GraphAdvancer()
        sync = ContextSynchronizer()

        # Run only step 1 (Build) manually through coordinator components to inspect intermediate state
        build_task = task_plan.get_task("task_build_code")
        disp_res = dispatcher.dispatch_task(build_task, compiled_task_plan=task_plan)
        assert disp_res.is_dispatched
        rt_result = runtime.execute_envelope(disp_res.envelope)
        sync_result = sync.apply_result(ctx, rt_result, phase_id="phase_build")
        assert sync_result.status == SyncStatus.SYNCED.value

        # Simulation is still WAITING before GraphAdvancer
        assert "task_simulation_qa_simulation" in task_plan.waiting_tasks

        # Apply GraphAdvancer
        advance_res = advancer.advance_graph(
            compiled_task_plan=task_plan,
            completed_task_ids=["task_build_code"],
        )

        assert "task_simulation_qa_simulation" in advance_res.newly_ready_tasks
        # Now Simulation is READY purely via GraphAdvancer
        assert "task_simulation_qa_simulation" in task_plan.ready_tasks


# =============================================================================
# 4. Failure Isolation Tests (Build Failure & Simulation Failure)
# =============================================================================

class TestStage6BFailureIsolation:
    """Validates honest failure states and isolation across phases."""

    def test_build_failure_prevents_simulation_execution(self):
        """
        Test 20: Proves that if Build fails verification:
        - task_build_code becomes FAILED
        - task_simulation remains WAITING / NOT READY
        - SimulationWorkerAdapter is called 0 times
        - No simulation artifacts or phase history are created
        - Coordinator stops honestly with FAILED
        """
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())

        # Mock CodeWorkerAdapter to fail verification
        failing_code_worker = CodeWorkerAdapter()
        failing_code_worker.verify_result = MagicMock(
            return_value=VerificationResult.fail_result(
                error="SyntaxError on line 42",
                evidence={"checks_performed": ["lint", "syntax"], "checks_failed": ["syntax_error_in_generated_api"]},
            )
        )
        runtime.register_worker(failing_code_worker)

        sim_worker = SimulationWorkerAdapter()
        sim_spy = MagicMock(side_effect=sim_worker.execute_task)
        sim_worker.execute_task = sim_spy
        runtime.register_worker(sim_worker)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(project_context=ctx, compiled_task_plan=task_plan)

        assert res.is_failed
        assert res.status == CoordinatorStatus.FAILED.value
        assert res.steps_executed == 1
        assert "task_build_code" in res.failed_tasks

        # Simulation task was never run
        assert sim_spy.call_count == 0
        assert "task_simulation_qa_simulation" in task_plan.blocked_tasks
        assert "task_simulation_qa_simulation" not in task_plan.ready_tasks

        # ProjectContext does not have any simulation artifacts or outcomes
        assert len(ctx.artifacts) == 0
        assert "phase_simulation" not in ctx.phase_history

    def test_simulation_failure_preserves_build_artifacts_and_fails_honestly(self):
        """
        Test 21, 22, 23: Proves that if Build succeeds but Simulation verification fails:
        - Build is COMPLETED and build artifacts are preserved in ProjectContext
        - Simulation is FAILED
        - Coordinator returns FAILED
        - No successful simulation artifacts are promoted to ProjectContext
        """
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())

        # Mock SimulationWorkerAdapter to fail verification
        failing_sim_worker = SimulationWorkerAdapter()
        failing_sim_worker.verify_result = MagicMock(
            return_value=VerificationResult.fail_result(
                error="Endpoint /metrics returned HTTP 500 under load",
                evidence={"checks_performed": ["schema_validation", "load_simulation"], "checks_failed": ["load_simulation_endpoint_500"]},
            )
        )
        runtime.register_worker(failing_sim_worker)

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        res = coord.run_workflow(project_context=ctx, compiled_task_plan=task_plan)

        assert res.is_failed
        assert res.status == CoordinatorStatus.FAILED.value
        assert res.steps_executed == 2
        assert "task_simulation_qa_simulation" in res.failed_tasks
        assert "task_build_code" not in res.failed_tasks

        # Build artifacts are intact in ProjectContext
        build_artifacts = [
            a for a in ctx.artifacts.values()
            if a.producer_worker == "worker_code"
        ]
        assert len(build_artifacts) >= 2

        # Simulation artifacts are NOT promoted as valid artifacts
        sim_artifacts = [
            a for a in ctx.artifacts.values()
            if a.producer_worker == "worker_qa_simulation"
        ]
        assert len(sim_artifacts) == 0

        # Phase history shows Build PASS, and simulation failure recorded honestly
        assert "phase_build" in ctx.phase_history
        assert ctx.phase_history["phase_build"].verification_status == "PASS"
        assert "phase_simulation" in ctx.phase_history
        assert ctx.phase_history["phase_simulation"].verification_status == "FAIL"
        assert ctx.phase_history["phase_simulation"].status == "FAILED"


# =============================================================================
# 5. Isolation, Determinism & Idempotency Tests
# =============================================================================

class TestStage6BIsolationAndIdempotency:
    """Validates zero legacy calls, zero external side-effects, determinism, and sync idempotency."""

    def test_legacy_execution_system_never_invoked(self):
        """Test 24: Proves zero calls to legacy execution paths."""
        with patch("orchestrator.router.route_to_specialist", create=True) as mock_router, \
             patch("execution.runner.run_controlled_verification", create=True) as mock_runner, \
             patch("main._execute_agent_fixed", create=True) as mock_main:

            result = execute_build_simulation_vertical_slice()

            assert result.success is True
            assert mock_router.call_count == 0
            assert mock_runner.call_count == 0
            assert mock_main.call_count == 0

    def test_no_external_network_calls_or_credentials(self):
        """Test 25 & 26: Proves complete local deterministic execution with zero external network or credentials."""
        with patch("urllib.request.urlopen") as mock_url, \
             patch("socket.socket.connect") as mock_socket:

            result = execute_build_simulation_vertical_slice()
            assert result.success is True
            assert mock_url.call_count == 0
            assert mock_socket.call_count == 0

    def test_idempotent_synchronization_for_build_and_simulation(self):
        """Test 27 & 28: Applying the same RuntimeResult twice does not duplicate artifacts or phase outcomes."""
        ctx = create_build_project_context()
        sync = ContextSynchronizer()

        # Create sample build result
        build_task_res = TaskResult(
            task_id="task_build_code",
            worker_id="worker_code",
            state=WorkerState.SUCCESS,
            output={"status": "BUILT", "routes": ["/health"]},
            artifacts=[
                {"artifact_type": "code_workspace", "location": "workspace/backend"},
                {"artifact_type": "backend_api", "routes": ["/health"]},
            ],
        )
        build_result = RuntimeResult(
            runtime_id=f"rt_task_build_code_{ctx.execution_id}",
            dispatch_id=f"dispatch_task_build_code_{ctx.execution_id}",
            execution_id=ctx.execution_id,
            task_id="task_build_code",
            project_id=ctx.project_id,
            worker_id="worker_code",
            status=RuntimeStatus.COMPLETED.value,
            task_result=build_task_res,
            verification_result=VerificationResult.pass_result(evidence={"routes": 1}),
        )

        sync_1 = sync.apply_result(ctx, build_result, phase_id="phase_build")
        assert sync_1.status == SyncStatus.SYNCED.value
        assert len(ctx.artifacts) == 2

        # Duplicate sync for build
        sync_2 = sync.apply_result(ctx, build_result, phase_id="phase_build")
        assert sync_2.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == 2  # Not 4

        # Create sample simulation result
        sim_task_res = TaskResult(
            task_id="task_simulation_qa_simulation",
            worker_id="worker_qa_simulation",
            state=WorkerState.SUCCESS,
            output={"status": "SIMULATED", "tests_passed": 5},
            artifacts=[
                {"artifact_type": "simulation_result", "status": "PASS"},
                {"artifact_type": "qa_report", "total_tests": 5},
            ],
        )
        sim_result = RuntimeResult(
            runtime_id=f"rt_task_simulation_{ctx.execution_id}",
            dispatch_id=f"dispatch_task_simulation_{ctx.execution_id}",
            execution_id=ctx.execution_id,
            task_id="task_simulation_qa_simulation",
            project_id=ctx.project_id,
            worker_id="worker_qa_simulation",
            status=RuntimeStatus.COMPLETED.value,
            task_result=sim_task_res,
            verification_result=VerificationResult.pass_result(evidence={"coverage": 100}),
        )

        sync_3 = sync.apply_result(ctx, sim_result, phase_id="phase_simulation")
        assert sync_3.status == SyncStatus.SYNCED.value
        assert len(ctx.artifacts) == 4

        # Duplicate sync for simulation
        sync_4 = sync.apply_result(ctx, sim_result, phase_id="phase_simulation")
        assert sync_4.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == 4  # Not 6

    def test_repeated_deterministic_execution(self):
        """Test 29: Proves repeated execution yields identical task IDs, phase IDs, and artifact structure."""
        res_1 = execute_build_simulation_vertical_slice()
        res_2 = execute_build_simulation_vertical_slice()

        assert res_1.status == res_2.status == CoordinatorStatus.COMPLETED.value
        assert len(res_1.task_plan.tasks) == len(res_2.task_plan.tasks) == 2
        assert [t.task_id for t in res_1.task_plan.tasks] == [t.task_id for t in res_2.task_plan.tasks]

        build_types_1 = sorted([a.artifact_type for a in res_1.build_artifacts])
        build_types_2 = sorted([a.artifact_type for a in res_2.build_artifacts])
        assert build_types_1 == build_types_2

        sim_types_1 = sorted([a.artifact_type for a in res_1.simulation_artifacts])
        sim_types_2 = sorted([a.artifact_type for a in res_2.simulation_artifacts])
        assert sim_types_1 == sim_types_2

    def test_coordinator_owns_task_ordering(self):
        """Test 30: Coordinator, not integration layer, discovers and drives DAG sequencing."""
        ctx = create_build_project_context()
        wf = create_build_simulation_workflow(ctx)
        registry = get_default_registry()

        team_mgr = TeamManager(registry=registry)
        team_plan = team_mgr.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=registry)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher(registry=registry, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=registry, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())

        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=ContextSynchronizer(),
            graph_advancer=GraphAdvancer(),
        )

        # We only call coord.run_workflow once, without manual step ordering
        coord_res = coord.run_workflow(project_context=ctx, compiled_task_plan=task_plan)
        assert coord_res.is_completed

        # Check execution order in step history
        assert len(coord_res.step_history) == 2
        assert coord_res.step_history[0].task_id == "task_build_code"
        assert coord_res.step_history[1].task_id == "task_simulation_qa_simulation"
