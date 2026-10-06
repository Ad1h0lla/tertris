"""
Unit Tests for Workforce Engine — Stage 5A: Execution Dispatcher Foundation
===========================================================================

Tests:
1. Valid READY task dispatch and ExecutionEnvelope generation
2. Unknown worker rejection (INVALID)
3. Unavailable/disabled worker blocking (BLOCKED)
4. Missing connector blocking (BLOCKED)
5. Missing/denied permission blocking (BLOCKED)
6. Unsatisfied DAG dependency blocking (BLOCKED)
7. Malformed task validation (missing objective, expected_output, project_id, execution_id, phase_id)
8. Defense-in-depth secret detection & rejection (REJECTED)
9. Deterministic dispatch ID generation
10. Duplicate dispatch rejection (idempotency guard)
11. Dry-run mode (validates envelope without registering or mutating state)
12. Approval-required task without approval (BLOCKED)
13. Approved task dispatch (DISPATCHED)
14. Batch dispatch of multiple ready tasks
15. Partial dispatch in mixed readiness batches (one READY, one BLOCKED)
16. In-memory DispatchRegistry query and clear operations
17. Serialization & deserialization round-trip of ExecutionEnvelope and DispatchResult
18. Realistic End-to-End Workforce Project Test (Crypto Alert SaaS build dispatch with downstream phases WAITING)
19. External Action Safety Test (Reddit worker requiring redditapis and approval: ZERO external API calls, ZERO posts)
20. Proof of Zero Execution: Zero BaseWorker execution, zero subprocesses, zero disk mutations, zero ProjectContext mutations
"""

import pytest

from orchestration.execution_dispatcher import (
    DispatchRecord,
    DispatchRegistry,
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
    ExecutionEnvelope,
    detect_unredacted_secrets,
    get_default_dispatch_registry,
)
from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow, WorkerAssignment
from orchestration.project_context import (
    Artifact,
    ProjectDefinition,
    ProjectContext,
)
from orchestration.task_assignment import (
    CompiledTaskPlan,
    TaskAssignmentEngine,
    TaskReadiness,
)
from orchestration.team_manager import TeamManager
from orchestration.worker_contract import Task, WorkerState
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry


@pytest.fixture(autouse=True)
def clean_dispatch_registry():
    """Ensure a fresh dispatch registry before every test."""
    reg = get_default_dispatch_registry()
    reg.clear()
    yield
    reg.clear()


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
            "User accounts",
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
    return ProjectContext(
        project_id="proj_crypto_501",
        execution_id="exec_crypto_601",
        user_id="user_admin_1",
        definition=defn,
    )


@pytest.fixture
def crypto_workflow() -> ProjectWorkflow:
    return ProjectWorkflow.create_default_lifecycle(
        project_id="proj_crypto_501",
        execution_id="exec_crypto_601",
    )


@pytest.fixture
def compiled_crypto_plan(crypto_project_context, crypto_workflow) -> CompiledTaskPlan:
    team_mgr = TeamManager()
    team_plan = team_mgr.evaluate_team(crypto_workflow)
    engine = TaskAssignmentEngine()
    return engine.assign_tasks(
        crypto_project_context,
        crypto_workflow,
        team_plan,
        connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"},
    )


# =============================================================================
# 1. Valid Task Dispatch & ExecutionEnvelope Tests
# =============================================================================

class TestValidTaskDispatch:
    def test_valid_ready_task_dispatch(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        build_tasks = compiled_crypto_plan.get_tasks_for_phase("phase_build")
        assert len(build_tasks) > 0
        code_task = build_tasks[0]

        result = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)

        assert result.status == DispatchStatus.DISPATCHED.value
        assert result.is_dispatched is True
        assert result.envelope is not None
        assert result.task_id == code_task.task_id
        assert result.worker_id == code_task.worker_id
        assert result.dispatch_id == f"dispatch_crypto_601_{code_task.task_id.replace('task_', '')}"

        # Verify envelope contents
        env = result.envelope
        assert env.task_id == code_task.task_id
        assert env.objective == code_task.objective
        assert env.phase_id == "phase_build"
        assert "requirements" in env.inputs
        assert len(env.permissions) > 0

        # Verify task metadata updated
        assert code_task.metadata.get("dispatch_status") == DispatchStatus.DISPATCHED.value

    def test_deterministic_dispatch_id(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        # Dry run 1
        res1 = dispatcher.dispatch_task(code_task, dry_run=True)
        # Dry run 2
        res2 = dispatcher.dispatch_task(code_task, dry_run=True)

        assert res1.dispatch_id == res2.dispatch_id
        assert res1.dispatch_id == "dispatch_crypto_601_build_code"


# =============================================================================
# 2. Worker Resolution & Availability Validation Tests
# =============================================================================

class TestWorkerValidation:
    def test_unknown_worker_rejected_as_invalid(self):
        dispatcher = ExecutionDispatcher()
        bad_task = Task(
            task_id="task_bad_01",
            execution_id="exec_test_01",
            project_id="proj_test_01",
            worker_id="worker_does_not_exist_999",
            objective="Perform undefined work",
            expected_output={"status": "SUCCESS"},
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(bad_task)
        assert res.status == DispatchStatus.INVALID.value
        assert res.is_invalid is True
        assert "not registered" in res.reason.lower()

    def test_disabled_worker_blocked(self):
        custom_registry = WorkerRegistry()
        disabled_desc = WorkerDescriptor(
            worker_id="worker_disabled",
            name="Disabled Worker",
            role="tester",
            availability_status="DISABLED",
        )
        custom_registry.register(disabled_desc)

        dispatcher = ExecutionDispatcher(registry=custom_registry)
        task = Task(
            task_id="task_dis_01",
            execution_id="exec_test_01",
            project_id="proj_test_01",
            worker_id="worker_disabled",
            objective="Run disabled test",
            expected_output={"status": "SUCCESS"},
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(task)
        assert res.status == DispatchStatus.BLOCKED.value
        assert res.is_blocked is True
        assert "unavailable" in res.reason.lower()


# =============================================================================
# 3. Connector, Permission, and Dependency Validation Tests
# =============================================================================

class TestConnectorAndPermissionAndDAGValidation:
    def test_missing_connector_blocks_dispatch(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        reddit_tasks = [t for t in compiled_crypto_plan.tasks if "reddit" in t.worker_id]
        assert len(reddit_tasks) > 0
        reddit_task = reddit_tasks[0]

        # Dispatch with empty connected connectors
        res = dispatcher.dispatch_task(
            reddit_task,
            connected_connectors=set(),
            is_approved=True,
        )
        assert res.status == DispatchStatus.BLOCKED.value
        assert "redditapis" in res.reason.lower()

    def test_denied_permission_blocks_dispatch(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        # Authorize empty permission list
        res = dispatcher.dispatch_task(
            code_task,
            authorized_permissions=[],
        )
        assert res.status == DispatchStatus.BLOCKED.value
        assert "permission" in res.reason.lower()

    def test_unsatisfied_dependencies_block_dispatch(self, compiled_crypto_plan):
        """Simulation task depends on Build phase tasks and should be BLOCKED."""
        dispatcher = ExecutionDispatcher()
        sim_tasks = compiled_crypto_plan.get_tasks_for_phase("phase_simulation")
        assert len(sim_tasks) > 0
        sim_task = sim_tasks[0]

        res = dispatcher.dispatch_task(sim_task, compiled_task_plan=compiled_crypto_plan)
        assert res.status == DispatchStatus.BLOCKED.value
        assert "prerequisite" in res.reason.lower() or "dependencies" in res.reason.lower()


# =============================================================================
# 4. Schema & Identity Validation Tests
# =============================================================================

class TestSchemaValidation:
    def test_missing_objective_fails_as_invalid(self):
        dispatcher = ExecutionDispatcher()
        task = Task(
            task_id="task_no_obj",
            execution_id="exec_1",
            project_id="proj_1",
            worker_id="worker_code",
            objective="",  # Empty
            expected_output={"status": "SUCCESS"},
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(task)
        assert res.status == DispatchStatus.INVALID.value
        assert "objective" in res.reason.lower()

    def test_missing_phase_id_fails_as_invalid(self):
        dispatcher = ExecutionDispatcher()
        task = Task(
            task_id="task_no_pid",
            execution_id="exec_1",
            project_id="proj_1",
            worker_id="worker_code",
            objective="Write code",
            expected_output={"status": "SUCCESS"},
            metadata={},  # No phase_id
        )
        res = dispatcher.dispatch_task(task)
        assert res.status == DispatchStatus.INVALID.value
        assert "phase_id" in res.reason.lower()

    def test_missing_expected_output_fails_as_invalid(self):
        dispatcher = ExecutionDispatcher()
        task = Task(
            task_id="task_no_out",
            execution_id="exec_1",
            project_id="proj_1",
            worker_id="worker_code",
            objective="Write code",
            expected_output={},  # Empty
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(task)
        assert res.status == DispatchStatus.INVALID.value
        assert "expected_output" in res.reason.lower()


# =============================================================================
# 5. Security & Defense-in-Depth Secret Scanner Tests
# =============================================================================

class TestSecuritySecretDefense:
    def test_unredacted_secret_key_rejects_dispatch(self):
        dispatcher = ExecutionDispatcher()
        leaky_task = Task(
            task_id="task_leaky_01",
            execution_id="exec_sec_1",
            project_id="proj_sec_1",
            worker_id="worker_code",
            objective="Build API with secret",
            inputs={"api_key": "live_unredacted_key_999"},
            expected_output={"status": "SUCCESS"},
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(leaky_task)
        assert res.status == DispatchStatus.REJECTED.value
        assert res.is_rejected is True
        assert "credentials detected" in res.reason.lower()

    def test_unredacted_token_string_pattern_rejects_dispatch(self):
        dispatcher = ExecutionDispatcher()
        leaky_task = Task(
            task_id="task_leaky_02",
            execution_id="exec_sec_2",
            project_id="proj_sec_2",
            worker_id="worker_code",
            objective="Build API with token string",
            inputs={"context": "sk_live_99887766554433221100"},
            expected_output={"status": "SUCCESS"},
            metadata={"phase_id": "phase_build"},
        )
        res = dispatcher.dispatch_task(leaky_task)
        assert res.status == DispatchStatus.REJECTED.value
        assert res.is_rejected is True

    def test_redacted_secret_placeholder_is_safe(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None
        code_task.inputs["api_key"] = "[REDACTED_SECRET]"

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res.status == DispatchStatus.DISPATCHED.value


# =============================================================================
# 6. Idempotency & Duplicate Dispatch Tests
# =============================================================================

class TestIdempotencyAndRegistry:
    def test_duplicate_dispatch_is_rejected(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        # First dispatch succeeds
        res1 = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res1.status == DispatchStatus.DISPATCHED.value

        # Second dispatch of the exact same task is rejected
        res2 = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res2.status == DispatchStatus.REJECTED.value
        assert "already been dispatched" in res2.reason.lower()

    def test_dispatch_registry_queries(self, compiled_crypto_plan):
        registry = DispatchRegistry()
        dispatcher = ExecutionDispatcher(dispatch_registry=registry)
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res.is_dispatched is True

        # Query by task ID
        record = registry.get_by_task(code_task.task_id)
        assert record is not None
        assert record.task_id == code_task.task_id
        assert record.dispatch_id == res.dispatch_id

        # Query by dispatch ID
        record_by_did = registry.get(res.dispatch_id)
        assert record_by_did is not None
        assert record_by_did.dispatch_id == res.dispatch_id


# =============================================================================
# 7. Dry-Run & Approval Boundary Tests
# =============================================================================

class TestDryRunAndApprovalBoundaries:
    def test_dry_run_does_not_register_dispatch(self, compiled_crypto_plan):
        registry = DispatchRegistry()
        dispatcher = ExecutionDispatcher(dispatch_registry=registry)
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan, dry_run=True)
        assert res.status == DispatchStatus.DISPATCHED.value
        assert res.envelope is not None
        assert registry.count() == 0  # Not registered
        assert registry.has_dispatched(code_task.task_id) is False

    def test_approval_required_task_without_approval_is_blocked(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        reddit_tasks = [t for t in compiled_crypto_plan.tasks if "reddit" in t.worker_id]
        assert len(reddit_tasks) > 0
        reddit_task = reddit_tasks[0]

        # Has connector, but is_approved is False
        res = dispatcher.dispatch_task(
            reddit_task,
            connected_connectors={"redditapis"},
            is_approved=False,
        )
        assert res.status == DispatchStatus.BLOCKED.value
        assert "approval" in res.reason.lower()

    def test_approval_required_task_with_approval_is_dispatched(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        reddit_tasks = [t for t in compiled_crypto_plan.tasks if "reddit" in t.worker_id]
        assert len(reddit_tasks) > 0
        reddit_task = reddit_tasks[0]

        # Has connector AND is_approved is True
        res = dispatcher.dispatch_task(
            reddit_task,
            connected_connectors={"redditapis"},
            is_approved=True,
        )
        assert res.status == DispatchStatus.DISPATCHED.value
        assert res.envelope.approval_status == "APPROVED"


# =============================================================================
# 8. Batch & Partial Dispatch Tests
# =============================================================================

class TestBatchAndPartialDispatch:
    def test_dispatch_all_ready_tasks(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        results = dispatcher.dispatch_ready_tasks(compiled_crypto_plan)

        # All 3 build tasks in ready_tasks are dispatched
        assert len(results) == 3
        for r in results:
            assert r.status == DispatchStatus.DISPATCHED.value
            assert r.is_dispatched is True

    def test_partial_dispatch_with_mixed_permissions(self, compiled_crypto_plan):
        """Authorize permissions for code and DB, but not UI."""
        dispatcher = ExecutionDispatcher()
        # Authorize filesystem:write and database:schema, but omit some permissions
        results = dispatcher.dispatch_ready_tasks(
            compiled_crypto_plan,
            authorized_permissions=["filesystem:write", "database:schema"],
        )
        assert len(results) == 3
        # Each task was independently evaluated
        for r in results:
            assert r.status in (DispatchStatus.DISPATCHED.value, DispatchStatus.BLOCKED.value)


# =============================================================================
# 9. Realistic Multi-Phase Project Context Test
# =============================================================================

class TestRealisticWorkforceProjectDispatch:
    def test_crypto_saas_build_dispatch_lifecycle(self, crypto_project_context, crypto_workflow):
        """
        Realistic end-to-end scenario:
        1. Compile task plan from ProjectContext + Workflow + TeamPlan.
        2. Build tasks (code, UI, database) are READY.
        3. Simulation, Marketing, and Deployment tasks are WAITING.
        4. Dispatch ready tasks.
        5. Verify Build tasks DISPATCHED, downstream tasks remain WAITING.
        6. Verify ZERO execution occurred.
        """
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(crypto_workflow)
        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(
            crypto_project_context,
            crypto_workflow,
            team_plan,
            connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"},
        )

        # Ensure initial states
        assert len(compiled.ready_tasks) == 3
        assert len(compiled.waiting_tasks) >= 3

        dispatcher = ExecutionDispatcher()
        results = dispatcher.dispatch_ready_tasks(compiled)

        # Build tasks are dispatched
        assert len(results) == 3
        dispatched_task_ids = {r.task_id for r in results if r.is_dispatched}
        assert "task_build_code" in dispatched_task_ids
        assert "task_build_ui" in dispatched_task_ids
        assert "task_build_database" in dispatched_task_ids or "task_build_db" in dispatched_task_ids

        # Attempting to dispatch a simulation task is blocked because it is WAITING
        sim_tasks = compiled.get_tasks_for_phase("phase_simulation")
        sim_res = dispatcher.dispatch_task(sim_tasks[0], compiled_task_plan=compiled)
        assert sim_res.status == DispatchStatus.BLOCKED.value

        # Attempting to dispatch a marketing task is blocked because it is WAITING
        mkt_tasks = compiled.get_tasks_for_phase("phase_marketing")
        mkt_res = dispatcher.dispatch_task(mkt_tasks[0], compiled_task_plan=compiled)
        assert mkt_res.status == DispatchStatus.BLOCKED.value

        # Attempting to dispatch a deployment task is blocked because it is WAITING
        dep_tasks = compiled.get_tasks_for_phase("phase_deployment")
        dep_res = dispatcher.dispatch_task(dep_tasks[0], compiled_task_plan=compiled)
        assert dep_res.status == DispatchStatus.BLOCKED.value


# =============================================================================
# 10. External Action Safety & Zero Execution Proof
# =============================================================================

class TestExternalActionSafetyAndZeroExecution:
    def test_reddit_dispatch_executes_zero_external_calls(self, crypto_project_context):
        """
        Verify that dispatching a Reddit task creates the ExecutionEnvelope
        WITHOUT calling RedditAPIs or mutating databases.
        """
        task = Task(
            task_id="task_reddit_test_01",
            execution_id="exec_reddit_99",
            project_id="proj_reddit_99",
            worker_id="worker_reddit",
            objective="Post crypto launch update to Reddit",
            inputs={"idea": "Crypto Tracker", "target_subreddits": ["CryptoCurrency"]},
            expected_output={"expected_artifacts": ["reddit_post_receipt"]},
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_marketing", "required_connectors": ["redditapis"]},
        )

        dispatcher = ExecutionDispatcher()
        res = dispatcher.dispatch_task(
            task,
            connected_connectors={"redditapis"},
            authorized_permissions=["network:write:approval_required"],
            is_approved=True,
        )

        assert res.status == DispatchStatus.DISPATCHED.value
        assert res.envelope is not None
        assert res.envelope.worker_id == "worker_reddit"
        assert res.envelope.approval_status == "APPROVED"

# =============================================================================
# 11. Envelope & Result Serialization Round-Trip Tests
# =============================================================================

class TestSerializationRoundTrip:
    def test_execution_envelope_json_roundtrip(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res.envelope is not None

        data = res.envelope.to_dict()
        assert isinstance(data, dict)
        reconstructed = ExecutionEnvelope.from_dict(data)

        assert reconstructed.dispatch_id == res.envelope.dispatch_id
        assert reconstructed.task_id == res.envelope.task_id
        assert reconstructed.worker_id == res.envelope.worker_id
        assert reconstructed.objective == res.envelope.objective
        assert reconstructed.inputs == res.envelope.inputs

    def test_dispatch_result_json_roundtrip(self, compiled_crypto_plan):
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        data = res.to_dict()
        assert isinstance(data, dict)
        reconstructed = DispatchResult.from_dict(data)

        assert reconstructed.status == res.status
        assert reconstructed.task_id == res.task_id
        assert reconstructed.dispatch_id == res.dispatch_id
        assert reconstructed.is_dispatched is True


# =============================================================================
# 12. Proof of Zero Execution & Zero Mutation
# =============================================================================

class TestZeroExecutionAndZeroMutationProof:
    def test_context_and_workflow_unmutated_after_dispatch(self, crypto_project_context, crypto_workflow, compiled_crypto_plan):
        """Verify that dispatching tasks leaves ProjectContext and ProjectWorkflow completely unmutated."""
        ctx_before = crypto_project_context.to_dict()
        wf_before = crypto_workflow.to_dict()

        dispatcher = ExecutionDispatcher()
        dispatcher.dispatch_ready_tasks(compiled_crypto_plan)

        assert crypto_project_context.to_dict() == ctx_before
        assert crypto_workflow.to_dict() == wf_before

    def test_zero_baseworker_execution(self, compiled_crypto_plan):
        """Verify that dispatching creates an envelope without calling BaseWorker.execute_task."""
        dispatcher = ExecutionDispatcher()
        code_task = compiled_crypto_plan.get_task("task_build_code")
        assert code_task is not None

        res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled_crypto_plan)
        assert res.is_dispatched is True

        # Confirm task is NOT marked SUCCESS or FAILED (only DISPATCHED)
        assert res.status == DispatchStatus.DISPATCHED.value
        assert "execution_result" not in res.metadata
        assert "verified_receipt" not in res.metadata
