"""
Tetris — Workforce Engine: Stage 6D Build → Simulation → Deployment → Launch Verification Tests
=================================================================================================

Proves the complete four-phase closed-loop execution lifecycle in the Workforce Engine:

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
    ↓
GRAPH ADVANCER (transitions Task D from WAITING to READY)
    ↓
LAUNCH VERIFICATION (Task D consumes Deployment outputs from ProjectContext slice)
    ↓
verified live HTTP smoke verification deliverables (launch_verification, launch_receipt)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
Project State = LIVE

Test Matrix (All 37 Core Requirements):
1. test_four_phase_workflow_structure
2. test_phase_dependency_graph
3. test_team_manager_resolves_launch_verification_worker
4. test_four_tasks_compile_correctly
5. test_build_initially_ready
6. test_simulation_initially_waiting
7. test_deployment_initially_waiting
8. test_launch_verification_initially_waiting
9. test_build_executes
10. test_simulation_executes
11. test_deployment_executes
12. test_launch_verification_executes_through_worker_runtime
13. test_deployment_output_reaches_project_context
14. test_launch_verification_consumes_project_context_derived_deployment_data
15. test_url_is_resolved_from_deployment_result
16. test_http_verifier_is_called_with_resolved_url
17. test_successful_http_verification_produces_pass
18. test_launch_verification_artifact_is_promoted
19. test_project_becomes_live_only_after_verification
20. test_final_coordinator_status_completed
21. test_build_failure_blocks_all_downstream
22. test_simulation_failure_blocks_deployment_and_launch
23. test_deployment_failure_blocks_launch
24. test_launch_verification_failure_prevents_live
25. test_deployment_receipt_survives_launch_failure
26. test_no_false_live_state
27. test_no_false_successful_verification_artifact
28. test_no_manual_graph_mutation
29. test_graph_advancer_unlocks_launch
30. test_coordinator_owns_ordering
31. test_legacy_execution_path_never_invoked
32. test_external_network_is_zero_in_test_mode
33. test_credentials_are_zero
34. test_synchronization_is_idempotent
35. test_deterministic_execution
36. test_deployment_url_is_never_fabricated
37. test_missing_deployment_url_fails_honestly
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSimulationDeploymentLaunchSliceResult,
    create_build_project_context,
    create_build_simulation_deployment_launch_workflow,
    execute_build_simulation_deployment_launch_vertical_slice,
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
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry
from orchestration.worker_runtime import (
    CodeWorkerAdapter,
    DeploymentWorkerAdapter,
    LaunchVerificationWorkerAdapter,
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
# 1. Four-Phase Workflow & Task Graph Structure Foundation (Tests 1-8)
# =============================================================================

class TestStage6DWorkflowAndGraphFoundation:
    """
    Validates Requirements 1-8:
    1. Four-phase workflow structure
    2. Phase dependency graph (Build -> Simulation -> Deployment -> Launch Verification)
    3. TeamManager resolves all 4 workers
    4. Task compilation produces 4 tasks
    5. Build initially READY
    6. Simulation initially WAITING
    7. Deployment initially WAITING
    8. Launch Verification initially WAITING
    """

    def test_1_four_phase_workflow_structure(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)

        assert isinstance(wf, ProjectWorkflow)
        assert len(wf.phases) == 4
        assert "phase_build" in wf.phases
        assert "phase_simulation" in wf.phases
        assert "phase_deployment" in wf.phases
        assert "phase_launch_verification" in wf.phases

    def test_2_phase_dependency_graph(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)

        assert wf.get_phase("phase_build").dependencies == []
        assert wf.get_phase("phase_simulation").dependencies == ["phase_build"]
        assert wf.get_phase("phase_deployment").dependencies == ["phase_simulation"]
        assert wf.get_phase("phase_launch_verification").dependencies == ["phase_deployment"]

    def test_3_team_manager_resolves_all_four_workers(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        assert team_plan.is_executable()
        assert "worker_code" in team_plan.phase_assignments["phase_build"].worker_ids
        assert "worker_qa_simulation" in team_plan.phase_assignments["phase_simulation"].worker_ids
        assert "worker_deployment" in team_plan.phase_assignments["phase_deployment"].worker_ids
        assert "worker_launch_verification" in team_plan.phase_assignments["phase_launch_verification"].worker_ids

    def test_4_task_compilation_produces_four_tasks(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        assert task_plan.is_executable()
        assert len(task_plan.tasks) == 4
        assert task_plan.get_task("task_build_code") is not None
        assert task_plan.get_task("task_simulation_qa_simulation") is not None
        assert task_plan.get_task("task_deployment_deployment") is not None
        assert task_plan.get_task("task_launch_verification_launch_verification") is not None

    def test_5_6_7_8_initial_task_readiness_states(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        # 5. Build initially READY
        assert "task_build_code" in task_plan.ready_tasks
        assert task_plan.get_task("task_build_code").metadata.get("readiness_status") == "READY"
        # 6. Simulation initially WAITING
        assert "task_simulation_qa_simulation" in task_plan.waiting_tasks
        assert task_plan.get_task("task_simulation_qa_simulation").metadata.get("readiness_status") == "WAITING"
        # 7. Deployment initially WAITING
        assert "task_deployment_deployment" in task_plan.waiting_tasks
        assert task_plan.get_task("task_deployment_deployment").metadata.get("readiness_status") == "WAITING"
        # 8. Launch Verification initially WAITING
        assert "task_launch_verification_launch_verification" in task_plan.waiting_tasks
        assert task_plan.get_task("task_launch_verification_launch_verification").metadata.get("readiness_status") == "WAITING"


# =============================================================================
# 2. Execution Lifecycle, Live Reachability & Deliverable Promotion (Tests 9-20)
# =============================================================================

class TestStage6DExecutionLifecycleAndPromotion:
    """
    Validates Requirements 9-20:
    9. Build executes
    10. Simulation executes
    11. Deployment executes
    12. Launch Verification executes through WorkerRuntime
    13. Deployment output reaches ProjectContext
    14. Launch Verification consumes ProjectContext-derived deployment data
    15. URL is resolved from deployment result
    16. HTTP verifier is called with resolved URL
    17. Successful HTTP verification produces PASS
    18. Launch verification artifact is promoted
    19. Project becomes LIVE only after verification
    20. Final coordinator status COMPLETED
    """

    def test_9_10_11_12_full_pipeline_execution_through_runtime(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 128,
            "url": "https://health-tracker.vercel.app",
            "error": None,
        })

        result = execute_build_simulation_deployment_launch_vertical_slice(
            project_data=HEALTH_API_FIXTURE,
            http_verifier=mock_http,
        )

        assert result.success is True
        assert result.status == CoordinatorStatus.COMPLETED.value
        assert result.coordinator_result.is_completed is True
        assert result.coordinator_result.steps_executed == 4
        assert len(result.step_history) == 4

        # Step 1: Build
        assert result.step_history[0].task_id == "task_build_code"
        assert result.step_history[0].worker_id == "worker_code"
        assert result.step_history[0].runtime_status == RuntimeStatus.COMPLETED.value
        assert result.step_history[0].verification_status == "PASS"

        # Step 2: Simulation
        assert result.step_history[1].task_id == "task_simulation_qa_simulation"
        assert result.step_history[1].worker_id == "worker_qa_simulation"
        assert result.step_history[1].runtime_status == RuntimeStatus.COMPLETED.value
        assert result.step_history[1].verification_status == "PASS"

        # Step 3: Deployment
        assert result.step_history[2].task_id == "task_deployment_deployment"
        assert result.step_history[2].worker_id == "worker_deployment"
        assert result.step_history[2].runtime_status == RuntimeStatus.COMPLETED.value
        assert result.step_history[2].verification_status == "PASS"

        # Step 4: Launch Verification
        assert result.step_history[3].task_id == "task_launch_verification_launch_verification"
        assert result.step_history[3].worker_id == "worker_launch_verification"
        assert result.step_history[3].runtime_status == RuntimeStatus.COMPLETED.value
        assert result.step_history[3].verification_status == "PASS"

    def test_13_14_15_16_17_launch_verification_lifecycle(self):
        captured_urls = []

        def custom_verifier(target_url: str):
            captured_urls.append(target_url)
            return {
                "status": "PASS",
                "http_status": 200,
                "content_length": 256,
                "url": target_url,
                "error": None,
            }

        ctx = create_build_project_context()
        result = execute_build_simulation_deployment_launch_vertical_slice(
            project_context=ctx,
            http_verifier=custom_verifier,
        )

        # 13. Deployment output reaches ProjectContext
        dep_arts = ctx.get_artifacts_by_phase("phase_deployment")
        assert len(dep_arts) >= 1
        dep_url = dep_arts[0].content_summary.get("url")
        assert dep_url is not None
        assert dep_url.startswith("https://")

        # 14 & 15. Launch Verification consumes ProjectContext deployment data and resolves URL
        assert len(captured_urls) == 1
        assert captured_urls[0] == dep_url

        # 16 & 17. HTTP verifier was called with resolved URL and produced PASS
        launch_step = result.step_history[3]
        assert launch_step.runtime_status == RuntimeStatus.COMPLETED.value
        assert launch_step.verification_status == "PASS"

    def test_18_19_20_final_context_and_live_status(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 512,
            "url": "https://fastapi-health-tracker.vercel.app",
            "error": None,
        })

        ctx = create_build_project_context()
        # Before launch verification, project is NOT live
        assert ctx.is_live is False

        result = execute_build_simulation_deployment_launch_vertical_slice(
            project_context=ctx,
            http_verifier=mock_http,
        )

        # 18. Launch verification artifact is promoted
        launch_arts = [a for a in ctx.artifacts.values() if a.artifact_type in ("launch_verification", "launch_receipt")]
        assert len(launch_arts) >= 1
        for a in launch_arts:
            assert a.producer_worker == "worker_launch_verification"
            assert a.phase_id == "phase_launch_verification"
            assert a.status == "AVAILABLE"
            assert a.metadata.get("verification_status") == "PASS"

        # 19. Project becomes LIVE only after verification
        assert ctx.is_live is True
        assert result.is_live is True

        # 20. Final coordinator status COMPLETED
        assert result.coordinator_result.status == CoordinatorStatus.COMPLETED.value


# =============================================================================
# 3. Failure Isolation, Preservation & Negative Boundaries (Tests 21-27)
# =============================================================================

class TestStage6DFailureIsolationAndPreservation:
    """
    Validates Requirements 21-27:
    21. Build failure blocks all downstream (Simulation, Deployment, Launch)
    22. Simulation failure blocks Deployment and Launch
    23. Deployment failure blocks Launch
    24. Launch Verification failure prevents LIVE
    25. Deployment receipt survives Launch failure
    26. No false LIVE state
    27. No false successful verification artifact
    """

    def test_21_build_failure_blocks_all_downstream(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())

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

        launch_worker = LaunchVerificationWorkerAdapter()
        launch_spy = MagicMock(side_effect=launch_worker.execute_task)
        launch_worker.execute_task = launch_spy
        runtime.register_worker(launch_worker)

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
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 1
        assert "task_build_code" in res.failed_tasks
        assert sim_spy.call_count == 0
        assert deploy_spy.call_count == 0
        assert launch_spy.call_count == 0
        assert ctx.is_live is False

    def test_22_simulation_failure_blocks_deployment_and_launch(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())

        failing_sim = SimulationWorkerAdapter()
        failing_sim.verify_result = MagicMock(return_value=VerificationResult.fail_result("Sim failure"))
        runtime.register_worker(failing_sim)

        deploy_worker = DeploymentWorkerAdapter()
        deploy_spy = MagicMock(side_effect=deploy_worker.execute_task)
        deploy_worker.execute_task = deploy_spy
        runtime.register_worker(deploy_worker)

        launch_worker = LaunchVerificationWorkerAdapter()
        launch_spy = MagicMock(side_effect=launch_worker.execute_task)
        launch_worker.execute_task = launch_spy
        runtime.register_worker(launch_worker)

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
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 2
        assert deploy_spy.call_count == 0
        assert launch_spy.call_count == 0
        assert ctx.is_live is False

        build_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_code"]
        assert len(build_arts) >= 2

    def test_23_deployment_failure_blocks_launch(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        runtime = WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        runtime.register_worker(CodeWorkerAdapter())
        runtime.register_worker(SimulationWorkerAdapter())

        failing_deploy = DeploymentWorkerAdapter()
        failing_deploy.verify_result = MagicMock(return_value=VerificationResult.fail_result("Deployment HTTP 500"))
        runtime.register_worker(failing_deploy)

        launch_worker = LaunchVerificationWorkerAdapter()
        launch_spy = MagicMock(side_effect=launch_worker.execute_task)
        launch_worker.execute_task = launch_spy
        runtime.register_worker(launch_worker)

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
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
            approved_task_ids={t.task_id for t in task_plan.tasks},
        )

        assert res.is_failed
        assert res.steps_executed == 3
        assert launch_spy.call_count == 0
        assert ctx.is_live is False

        # Upstream artifacts preserved
        build_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_code"]
        sim_arts = [a for a in ctx.artifacts.values() if a.producer_worker == "worker_qa_simulation"]
        assert len(build_arts) >= 2
        assert len(sim_arts) >= 2

    def test_24_25_26_27_launch_verification_failure_prevents_live_and_preserves_upstream(self):
        failing_http = MagicMock(return_value={
            "status": "FAIL",
            "http_status": 503,
            "content_length": 0,
            "url": "https://health-tracker.vercel.app",
            "error": "Service Unavailable (503)",
        })

        ctx = create_build_project_context()
        result = execute_build_simulation_deployment_launch_vertical_slice(
            project_context=ctx,
            http_verifier=failing_http,
        )

        # 24. Launch Verification failure prevents LIVE
        assert result.success is False
        assert result.status == CoordinatorStatus.FAILED.value
        assert result.is_live is False
        assert ctx.is_live is False

        # 25. Build, Simulation, and Deployment artifacts survive Launch failure
        assert len(result.build_artifacts) > 0
        assert len(result.simulation_artifacts) > 0
        assert len(result.deployment_artifacts) > 0

        # 26. No false LIVE state
        assert ctx.metadata.get("is_live") is not True

        # 27. No false successful verification artifact
        launch_arts = [a for a in ctx.artifacts.values() if a.artifact_type in ("launch_verification", "launch_receipt")]
        assert len(launch_arts) == 0

        # 4 steps executed, last one failed
        assert len(result.step_history) == 4
        assert result.step_history[3].task_id == "task_launch_verification_launch_verification"
        assert result.step_history[3].runtime_status == RuntimeStatus.FAILED.value


# =============================================================================
# 4. Graph Advancement, Autonomy & No Manual Mutation (Tests 28-30)
# =============================================================================

class TestStage6DGraphAdvancementAndOrdering:
    """
    Validates Requirements 28-30:
    28. No manual graph mutation
    29. GraphAdvancer unlocks Launch
    30. Coordinator owns ordering
    """

    def test_28_29_no_manual_graph_mutation_graph_advancer_unlocks_launch(self):
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_workflow(ctx)
        reg = get_default_registry()

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )
        team_plan.apply_to_workflow(wf)

        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(
            project_context=ctx,
            workflow=wf,
            team_plan=team_plan,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"},
        )

        advancer = GraphAdvancer()

        # Step 0: Initial
        assert "task_launch_verification_launch_verification" in task_plan.waiting_tasks

        # Step 1: Complete Build
        adv_1 = advancer.advance_graph(task_plan, completed_task_ids=["task_build_code"])
        assert "task_simulation_qa_simulation" in adv_1.newly_ready_tasks
        assert "task_launch_verification_launch_verification" in task_plan.waiting_tasks

        # Step 2: Complete Simulation
        adv_2 = advancer.advance_graph(task_plan, completed_task_ids=["task_build_code", "task_simulation_qa_simulation"])
        assert "task_deployment_deployment" in adv_2.newly_ready_tasks
        assert "task_launch_verification_launch_verification" in task_plan.waiting_tasks

        # Step 3: Complete Deployment
        adv_3 = advancer.advance_graph(
            task_plan,
            completed_task_ids=["task_build_code", "task_simulation_qa_simulation", "task_deployment_deployment"]
        )
        # GraphAdvancer naturally unlocks Launch Verification
        assert "task_launch_verification_launch_verification" in adv_3.newly_ready_tasks
        assert "task_launch_verification_launch_verification" in task_plan.ready_tasks

    def test_30_coordinator_owns_ordering(self):
        execution_order = []

        class TrackingRuntime(WorkerRuntime):
            def execute_envelope(self, envelope, dry_run=False, max_execution_seconds=None):
                execution_order.append(envelope.task_id)
                return super().execute_envelope(envelope, dry_run=dry_run, max_execution_seconds=max_execution_seconds)

        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 64,
            "url": "https://health-tracker.vercel.app",
            "error": None,
        })

        rt = TrackingRuntime()
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=mock_http))

        result = execute_build_simulation_deployment_launch_vertical_slice(runtime=rt)

        assert result.success is True
        assert execution_order == [
            "task_build_code",
            "task_simulation_qa_simulation",
            "task_deployment_deployment",
            "task_launch_verification_launch_verification",
        ]


# =============================================================================
# 5. Isolation, Determinism, Safety & URL Integrity (Tests 31-37)
# =============================================================================

class TestStage6DIsolationDeterminismAndSafety:
    """
    Validates Requirements 31-37:
    31. Legacy execution system never invoked
    32. External network is zero in test mode
    33. Credentials are zero
    34. Synchronization idempotent
    35. Deterministic execution
    36. Deployment URL is never fabricated
    37. Missing deployment URL fails honestly
    """

    def test_31_legacy_execution_system_never_invoked(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 64,
            "url": "https://health-tracker.vercel.app",
            "error": None,
        })

        with patch("orchestrator.router.route_to_specialist", create=True) as mock_route, \
             patch("execution.runner.run_controlled_verification", create=True) as mock_runner, \
             patch("main._execute_agent_fixed", create=True) as mock_main:

            result = execute_build_simulation_deployment_launch_vertical_slice(
                http_verifier=mock_http,
            )

            assert result.success is True
            mock_route.assert_not_called()
            mock_runner.assert_not_called()
            mock_main.assert_not_called()

    def test_32_33_external_network_and_credentials_zero_in_test_mode(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 128,
            "url": "https://health-tracker.vercel.app",
            "error": None,
        })

        # Ensure no real urllib.request or requests network calls happen
        with patch("urllib.request.urlopen") as mock_url, \
             patch("requests.get") as mock_get:

            result = execute_build_simulation_deployment_launch_vertical_slice(
                http_verifier=mock_http,
            )

            assert result.success is True
            mock_url.assert_not_called()
            mock_get.assert_not_called()

        # Ensure no secret leakage in context
        ctx_dict = result.project_context.to_dict()
        for forbidden in ["api_key", "bearer ", "token", "client_secret"]:
            assert forbidden not in ctx_dict

    def test_34_synchronization_is_idempotent(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 64,
            "url": "https://test.vercel.app",
            "error": None,
        })

        ctx = create_build_project_context()
        sync = ContextSynchronizer()

        rt = WorkerRuntime()
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=mock_http))

        # Manually create task and execute
        task = Task(
            task_id="task_launch_test",
            worker_id="worker_launch_verification",
            objective="Verify launch",
            inputs={"deployment": [{"url": "https://test.vercel.app"}]},
        )
        plan = rt.resolve_worker("worker_launch_verification").prepare_task(task)
        res = rt.resolve_worker("worker_launch_verification").execute_task(task)
        verif = rt.resolve_worker("worker_launch_verification").verify_result(res)

        runtime_res = RuntimeResult(
            runtime_id="rt_launch_test_001",
            dispatch_id="disp_launch_test_001",
            task_id=task.task_id,
            execution_id=ctx.execution_id,
            project_id=ctx.project_id,
            worker_id="worker_launch_verification",
            status=RuntimeStatus.COMPLETED.value,
            task_result=res,
            verification_result=verif,
        )

        # First synchronization: SYNCED
        res1 = sync.apply_result(ctx, runtime_res, phase_id="phase_launch_verification")
        assert res1.status == SyncStatus.SYNCED.value
        initial_art_count = len(ctx.artifacts)

        # Second synchronization: SKIPPED (idempotent no-op)
        res2 = sync.apply_result(ctx, runtime_res, phase_id="phase_launch_verification")
        assert res2.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == initial_art_count

    def test_35_execution_is_deterministic(self):
        mock_http = MagicMock(return_value={
            "status": "PASS",
            "http_status": 200,
            "content_length": 64,
            "url": "https://health-tracker.vercel.app",
            "error": None,
        })

        res1 = execute_build_simulation_deployment_launch_vertical_slice(
            project_data=HEALTH_API_FIXTURE,
            http_verifier=mock_http,
        )
        res2 = execute_build_simulation_deployment_launch_vertical_slice(
            project_data=HEALTH_API_FIXTURE,
            http_verifier=mock_http,
        )

        assert res1.success == res2.success
        assert [s.task_id for s in res1.step_history] == [s.task_id for s in res2.step_history]
        assert [s.runtime_status for s in res1.step_history] == [s.runtime_status for s in res2.step_history]
        assert res1.is_live == res2.is_live is True

    def test_36_37_deployment_url_never_fabricated_and_missing_url_fails_honestly(self):
        worker = LaunchVerificationWorkerAdapter()

        # Case 1: Empty input with no deployment URL
        task_empty = Task(
            task_id="task_empty_launch",
            worker_id="worker_launch_verification",
            objective="Verify launch",
            inputs={},
        )
        res_empty = worker.execute_task(task_empty)
        assert res_empty.state == WorkerState.FAILED
        assert res_empty.output["status"] == "FAILED"
        assert res_empty.output["verification_status"] == "FAIL"
        assert "Missing or invalid deployment URL" in res_empty.output["error"]
        assert res_empty.output["deployment_url"] is None

        # Case 2: Malformed URL (not HTTP/HTTPS)
        task_malformed = Task(
            task_id="task_malformed_launch",
            worker_id="worker_launch_verification",
            objective="Verify launch",
            inputs={"deployment": [{"url": "ftp://bad-url"}]},
        )
        res_malformed = worker.execute_task(task_malformed)
        assert res_malformed.state == WorkerState.FAILED
        assert res_malformed.output["status"] == "FAILED"
        assert res_malformed.output["verification_status"] == "FAIL"

        # Verification result verification
        verif = worker.verify_result(res_empty)
        assert verif.verified is False
        assert verif.status == "FAIL"
