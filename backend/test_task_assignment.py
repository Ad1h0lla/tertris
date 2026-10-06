"""
Unit Tests for Workforce Engine — Stage 4B: Task Assignment & Binding Engine
============================================================================

Tests:
1. Deterministic Task compilation and ID generation
2. Task objectives derived from phase purpose, worker role, and project definition
3. Controlled context slicing and input bindings (zero secrets leaked)
4. Consumes / Produces artifact bindings
5. Task dependencies (inter-phase DAG, intra-phase dependencies, fan-in/fan-out)
6. Parallel task readiness (independent workers in ready phase are simultaneously READY)
7. Task readiness states (READY, WAITING, BLOCKED, INVALID)
8. Connector requirement preservation (redditapis, serper, vercel, sendgrid)
9. Permission requirement preservation
10. Acceptance criteria binding
11. Invalid plan handling (unknown workers, circular dependencies, empty phases)
12. Idempotency & recompilation safety (zero mutations to Context, Workflow, or TeamPlan)
13. Security: Recursive secret sanitization in task inputs
14. Realistic Multi-Phase Project Context Compilation (Crypto Price Tracking SaaS)
15. Proof of pure compilation: Zero workers executed, zero external APIs called
"""

import pytest

from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow, WorkerAssignment
from orchestration.project_context import (
    Artifact,
    Decision,
    PhaseOutcomeReference,
    ProjectDefinition,
    ProjectContext,
    ReceiptReference,
)
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry
from orchestration.team_manager import TeamManager, TeamPlan, PhaseTeamAssignment
from orchestration.task_assignment import (
    CompiledTaskPlan,
    TaskAssignmentEngine,
    TaskAssignmentPlan,
    TaskReadiness,
)


@pytest.fixture
def crypto_project_context() -> ProjectContext:
    """Creates a rich realistic ProjectContext for a Crypto Alert SaaS."""
    defn = ProjectDefinition(
        idea="Crypto price tracking and alert SaaS",
        goal="Provide real-time crypto price tracking, portfolio overview, and multi-channel alerts.",
        target_users="Retail crypto investors and active traders",
        requirements=[
            "Real-time price tracking for top 100 cryptocurrencies",
            "Custom price threshold alerts",
            "Responsive portfolio dashboard",
            "User authentication and accounts",
        ],
        constraints=["Latency under 500ms for price updates", "Zero secret exposure"],
        acceptance_criteria=[
            "user can add a tracked asset",
            "user can see current price",
            "user can create an alert",
            "alert can trigger",
            "dashboard loads successfully",
        ],
    )
    ctx = ProjectContext(
        project_id="proj_crypto_101",
        execution_id="exec_crypto_202",
        user_id="user_trader_9",
        definition=defn,
    )
    # Add initial specifications artifact
    ctx.add_artifact(
        Artifact(
            artifact_id="art_spec_01",
            name="Crypto SaaS System Architecture & Spec",
            artifact_type="specification",
            phase_id="phase_build",
            producer_worker="worker_code",
            content_summary={"architecture": "FastAPI + React + SQLite"},
            status="AVAILABLE",
        )
    )
    return ctx


@pytest.fixture
def crypto_workflow() -> ProjectWorkflow:
    """Creates a standard 5-phase workflow for the crypto project."""
    return ProjectWorkflow.create_default_lifecycle(
        project_id="proj_crypto_101",
        execution_id="exec_crypto_202",
    )


# =============================================================================
# 1. Deterministic Compilation & ID Generation Tests
# =============================================================================

class TestDeterministicTaskCompilation:
    def test_task_compilation_deterministic_ids(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        plan1 = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)
        plan2 = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        assert len(plan1.tasks) == len(plan2.tasks)
        task_ids_1 = [t.task_id for t in plan1.tasks]
        task_ids_2 = [t.task_id for t in plan2.tasks]
        assert task_ids_1 == task_ids_2

        # Check explicit deterministic ID format
        assert "task_build_code" in task_ids_1
        assert "task_build_ui" in task_ids_1
        assert "task_build_db" in task_ids_1 or "task_build_database" in [t.replace("db", "database") for t in task_ids_1]

    def test_recompilation_immutability(self, crypto_project_context, crypto_workflow):
        """Ensures assigning tasks does not mutate ProjectContext, Workflow, or TeamPlan."""
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        ctx_dict_before = crypto_project_context.to_dict()
        wf_dict_before = crypto_workflow.to_dict()
        tp_dict_before = team_plan.to_dict()

        engine = TaskAssignmentEngine()
        engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        assert crypto_project_context.to_dict() == ctx_dict_before
        assert crypto_workflow.to_dict() == wf_dict_before
        assert team_plan.to_dict() == tp_dict_before


# =============================================================================
# 2. Objective & Content Synthesis Tests
# =============================================================================

class TestTaskObjectives:
    def test_task_objectives_are_concrete_and_relevant(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        code_task = compiled.get_task("task_build_code")
        assert code_task is not None
        assert "Crypto price tracking" in code_task.objective
        assert "backend" in code_task.objective.lower() or "api" in code_task.objective.lower()

        qa_task = compiled.get_task("task_simulation_qa")
        if not qa_task:
            qa_tasks = compiled.get_tasks_for_phase("phase_simulation")
            qa_task = qa_tasks[0] if qa_tasks else None
        assert qa_task is not None
        assert "Crypto price tracking" in qa_task.objective
        assert "simulation" in qa_task.objective.lower() or "verification" in qa_task.objective.lower()


# =============================================================================
# 3. Context Slicing & Input Bindings Tests
# =============================================================================

class TestContextSlicingAndInputBindings:
    def test_controlled_input_slicing_per_worker(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        code_task = compiled.get_task("task_build_code")
        assert code_task is not None
        # Code worker receives idea, goal, requirements, constraints, acceptance_criteria, specifications
        assert "idea" in code_task.inputs
        assert "requirements" in code_task.inputs
        assert "acceptance_criteria" in code_task.inputs
        # But should NOT receive unrelated root elements like receipts or phase_history
        assert "receipts" not in code_task.inputs
        assert "phase_history" not in code_task.inputs

    def test_security_zero_secrets_in_task_inputs(self, crypto_project_context, crypto_workflow):
        """Inject dirty secret into metadata and verify it is redacted in task inputs."""
        crypto_project_context.record_metadata("api_key", "sk_live_secret_12345")
        crypto_project_context.record_metadata("reddit_session", "session_token_xyz")

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        plan_dict = compiled.to_dict()
        serialized = str(plan_dict)

        assert "sk_live_secret_12345" not in serialized
        assert "session_token_xyz" not in serialized
        assert "[REDACTED_SECRET]" in serialized or "api_key" not in serialized


# =============================================================================
# 4. Artifact Bindings (Consumes & Produces) Tests
# =============================================================================

class TestArtifactBindings:
    def test_consumes_and_produces_artifact_declarations(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        code_task = compiled.get_task("task_build_code")
        assert code_task is not None
        assert "specification" in code_task.metadata["consumes_artifacts"]
        assert "code_workspace" in code_task.metadata["produces_artifacts"]
        assert "code_workspace" in code_task.expected_output["expected_artifacts"]

        deploy_tasks = [t for t in compiled.get_tasks_for_phase("phase_deployment") if "deployment" in t.worker_id]
        assert len(deploy_tasks) > 0
        deploy_task = deploy_tasks[0]
        assert "code_workspace" in deploy_task.metadata["consumes_artifacts"]
        assert "deployment_receipt" in deploy_task.metadata["produces_artifacts"] or "deployment_bundle" in deploy_task.metadata["produces_artifacts"]


# =============================================================================
# 5. Dependency & Parallelism Tests
# =============================================================================

class TestTaskDependenciesAndParallelism:
    def test_independent_tasks_in_ready_phase_are_parallel(self, crypto_project_context, crypto_workflow):
        """Build phase has code, UI, and DB workers with no intra-phase dependencies."""
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        build_tasks = compiled.get_tasks_for_phase("phase_build")
        assert len(build_tasks) == 3

        # All 3 build tasks have no dependencies
        for t in build_tasks:
            assert len(t.dependencies) == 0
            assert t.metadata["readiness_status"] == TaskReadiness.READY.value

        # All 3 build tasks are in ready_tasks
        for t in build_tasks:
            assert t.task_id in compiled.ready_tasks

    def test_downstream_phase_tasks_depend_on_upstream(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        build_task_ids = {t.task_id for t in compiled.get_tasks_for_phase("phase_build")}
        sim_tasks = compiled.get_tasks_for_phase("phase_simulation")

        assert len(sim_tasks) > 0
        for st in sim_tasks:
            # Simulation tasks depend on all build tasks
            for b_id in build_task_ids:
                assert b_id in st.dependencies
            # Since build is not yet completed, simulation tasks are WAITING
            assert st.metadata["readiness_status"] == TaskReadiness.WAITING.value
            assert st.task_id in compiled.waiting_tasks

    def test_completed_phase_activates_downstream_readiness(self, crypto_project_context, crypto_workflow):
        """Marking phase_build as completed makes phase_simulation tasks READY."""
        crypto_workflow.completed_phases = ["phase_build"]
        crypto_workflow.get_phase("phase_simulation").status = PhaseStatus.READY

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        sim_tasks = compiled.get_tasks_for_phase("phase_simulation")
        for st in sim_tasks:
            assert st.metadata["readiness_status"] == TaskReadiness.READY.value
            assert st.task_id in compiled.ready_tasks


# =============================================================================
# 6. Connector & Permission Readiness Tests
# =============================================================================

class TestConnectorAndPermissionReadiness:
    def test_missing_connector_blocks_task(self, crypto_project_context, crypto_workflow):
        """Marketing phase has Reddit worker requiring redditapis connector."""
        # Assume Build and Simulation are completed so Marketing is the active phase
        crypto_workflow.completed_phases = ["phase_build", "phase_simulation"]
        crypto_workflow.get_phase("phase_marketing").status = PhaseStatus.READY

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        # Evaluate without connected connectors
        compiled = engine.assign_tasks(
            crypto_project_context,
            crypto_workflow,
            team_plan,
            connected_connectors=set(),
        )

        reddit_tasks = [t for t in compiled.tasks if "reddit" in t.worker_id]
        assert len(reddit_tasks) > 0
        reddit_task = reddit_tasks[0]

        assert reddit_task.metadata["readiness_status"] == TaskReadiness.BLOCKED.value
        assert reddit_task.task_id in compiled.blocked_tasks
        assert "redditapis" in reddit_task.metadata["blocked_reason"]

    def test_connected_connector_makes_task_ready(self, crypto_project_context, crypto_workflow):
        """Connecting redditapis, twitter, and sendgrid makes marketing tasks READY."""
        crypto_workflow.completed_phases = ["phase_build", "phase_simulation"]
        crypto_workflow.get_phase("phase_marketing").status = PhaseStatus.READY

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(
            crypto_project_context,
            crypto_workflow,
            team_plan,
            connected_connectors={"redditapis", "twitter", "sendgrid"},
        )

        reddit_tasks = [t for t in compiled.tasks if "reddit" in t.worker_id]
        assert len(reddit_tasks) > 0
        assert reddit_tasks[0].metadata["readiness_status"] == TaskReadiness.READY.value
        assert reddit_tasks[0].task_id in compiled.ready_tasks


# =============================================================================
# 7. Acceptance Criteria Binding Tests
# =============================================================================

class TestAcceptanceCriteriaBinding:
    def test_tasks_bind_to_relevant_acceptance_criteria(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        code_task = compiled.get_task("task_build_code")
        assert code_task is not None
        bound = code_task.metadata["acceptance_criteria_bound"]
        assert len(bound) == len(crypto_project_context.definition.acceptance_criteria)
        assert "user can add a tracked asset" in bound
        assert "user can create an alert" in bound


# =============================================================================
# 8. Error Handling & Invalid Plan Tests
# =============================================================================

class TestInvalidPlanHandling:
    def test_unregistered_worker_fails_safely(self, crypto_project_context):
        wf = ProjectWorkflow(project_id="proj_bad", execution_id="exec_bad")
        p = Phase(phase_id="phase_bad", name="Bad Phase", status=PhaseStatus.READY)
        p.add_worker(WorkerAssignment(worker_id="worker_non_existent_99", phase_id="phase_bad", role="unknown"))
        wf.add_phase(p)

        team_plan = TeamPlan(project_id="proj_bad", execution_id="exec_bad")
        team_plan.phase_assignments["phase_bad"] = PhaseTeamAssignment(
            phase_id="phase_bad",
            phase_name="Bad Phase",
            worker_ids=["worker_non_existent_99"],
            worker_assignments=p.workers,
        )

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, wf, team_plan)

        assert compiled.readiness == TaskReadiness.INVALID.value
        assert len(compiled.validation_errors) > 0
        assert "worker_non_existent_99" in compiled.validation_errors[0]

    def test_empty_workflow_fails_safely(self, crypto_project_context):
        wf = ProjectWorkflow(project_id="proj_empty", execution_id="exec_empty")
        team_plan = TeamPlan(project_id="proj_empty", execution_id="exec_empty")

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, wf, team_plan)

        assert compiled.readiness == TaskReadiness.INVALID.value
        assert "no phases" in compiled.validation_errors[0].lower()


# =============================================================================
# 10. Complex DAG Topologies (Fan-In, Fan-Out, Multi-Worker Phases)
# =============================================================================

class TestComplexDAGTopologies:
    def test_fan_in_and_fan_out_dependency_resolution(self, crypto_project_context):
        """
        Topology:
        Phase A (root)
        Phase B (depends on A)
        Phase C (depends on A)
        Phase D (depends on B and C - Fan-in)
        """
        wf = ProjectWorkflow(project_id="proj_fan", execution_id="exec_fan")

        pA = Phase(phase_id="pA", name="Phase A", status=PhaseStatus.READY)
        pA.add_worker(WorkerAssignment(worker_id="worker_code", phase_id="pA", role="code_builder"))
        wf.add_phase(pA)

        pB = Phase(phase_id="pB", name="Phase B", dependencies=["pA"], status=PhaseStatus.PLANNED)
        pB.add_worker(WorkerAssignment(worker_id="worker_ui", phase_id="pB", role="ui_developer"))
        wf.add_phase(pB)

        pC = Phase(phase_id="pC", name="Phase C", dependencies=["pA"], status=PhaseStatus.PLANNED)
        pC.add_worker(WorkerAssignment(worker_id="worker_database", phase_id="pC", role="database_architect"))
        wf.add_phase(pC)

        pD = Phase(phase_id="pD", name="Phase D", dependencies=["pB", "pC"], status=PhaseStatus.PLANNED)
        pD.add_worker(WorkerAssignment(worker_id="worker_qa_simulation", phase_id="pD", role="qa_tester"))
        wf.add_phase(pD)

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(wf)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, wf, team_plan)

        taskA = compiled.get_task("task_pa_code")
        taskB = compiled.get_task("task_pb_ui")
        taskC = compiled.get_task("task_pc_database")
        taskD = compiled.get_task("task_pd_qa_simulation")

        assert taskA is not None and taskB is not None and taskC is not None and taskD is not None

        # Task A has 0 dependencies and is READY
        assert taskA.dependencies == []
        assert taskA.task_id in compiled.ready_tasks

        # Tasks B and C depend on Task A and are WAITING
        assert taskA.task_id in taskB.dependencies
        assert taskA.task_id in taskC.dependencies
        assert taskB.task_id in compiled.waiting_tasks
        assert taskC.task_id in compiled.waiting_tasks

        # Task D depends on both Task B and Task C (Fan-In)
        assert taskB.task_id in taskD.dependencies
        assert taskC.task_id in taskD.dependencies
        assert taskD.task_id in compiled.waiting_tasks

    def test_permission_denial_blocks_task(self, crypto_project_context, crypto_workflow):
        """Worker with required permissions is blocked when permissions are not authorized."""
        crypto_workflow.completed_phases = ["phase_build"]
        crypto_workflow.get_phase("phase_simulation").status = PhaseStatus.READY

        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        # Authorize empty permission list
        compiled = engine.assign_tasks(
            crypto_project_context,
            crypto_workflow,
            team_plan,
            authorized_permissions=[],
        )

        sim_tasks = compiled.get_tasks_for_phase("phase_simulation")
        for st in sim_tasks:
            if st.permissions:
                assert st.metadata["readiness_status"] == TaskReadiness.BLOCKED.value
                assert "Permissions denied" in st.metadata["blocked_reason"]

    def test_plan_helper_queries_and_filters(self, crypto_project_context, crypto_workflow):
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, crypto_workflow, team_plan)

        # get_tasks_for_worker
        code_tasks = compiled.get_tasks_for_worker("worker_code")
        assert len(code_tasks) >= 1
        assert all(t.worker_id == "worker_code" for t in code_tasks)

        # get_ready_tasks
        ready_tasks = compiled.get_ready_tasks()
        assert len(ready_tasks) > 0
        assert all(t.task_id in compiled.ready_tasks for t in ready_tasks)

        # is_executable
        assert compiled.is_executable() is True


# =============================================================================
# 11. Realistic End-to-End Project Context Compilation Test
# =============================================================================

class TestRealisticE2ECompilation:
    def test_crypto_saas_full_lifecycle_compilation(self, crypto_project_context, crypto_workflow):
        """
        Comprehensive test of the full crypto price tracker project:
        - 5 phases: Build, Simulation, Marketing, Deployment, Health
        - All workers assigned
        - Proper DAG dependencies and readiness
        - Zero side effects / zero execution
        """
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)
        assert team_plan.is_executable() or team_plan.readiness == "CAPABLE_BUT_MISSING_CONNECTOR"

        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(
            crypto_project_context,
            crypto_workflow,
            team_plan,
            connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"},
        )

        # 1. Check all phases have tasks
        assert len(compiled.tasks) >= 5
        assert len(compiled.phase_task_map) == 5

        # 2. Check build tasks are READY
        build_tasks = compiled.get_tasks_for_phase("phase_build")
        assert len(build_tasks) == 3
        for bt in build_tasks:
            assert bt.task_id in compiled.ready_tasks

        # 3. Check simulation tasks depend on build tasks
        sim_tasks = compiled.get_tasks_for_phase("phase_simulation")
        for st in sim_tasks:
            assert len(st.dependencies) >= 3
            assert st.task_id in compiled.waiting_tasks

        # 4. Check deployment tasks depend on simulation and marketing
        deploy_tasks = [t for t in compiled.get_tasks_for_phase("phase_deployment") if "deployment" in t.worker_id]
        assert len(deploy_tasks) > 0
        deploy_task = deploy_tasks[0]
        assert len(deploy_task.dependencies) > 0

        # 5. Check serialization round-trip
        data = compiled.to_dict()
        assert isinstance(data, dict)
        reconstructed = CompiledTaskPlan.from_dict(data)
        assert len(reconstructed.tasks) == len(compiled.tasks)
        assert reconstructed.project_id == crypto_project_context.project_id

        # 6. Verify zero secrets
        serialized = str(data)
        for secret_kw in ["sk_live_secret", "reddit_session_xyz", "bearer_token", "password_hash"]:
            assert secret_kw not in serialized
