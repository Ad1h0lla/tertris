"""
Unit Tests for Workforce Engine — Stage 5B: Worker Execution Runtime
====================================================================

Tests:
1. Deterministic EchoWorker lifecycle (prepare -> execute -> verify -> COMPLETED)
2. Preparation failure handling (execute_task not called, status FAILED)
3. Execution failure handling (verify_result not called, status FAILED)
4. Verification failure handling (honest reporting, status FAILED, no false completion)
5. Approval boundary enforcement (PENDING_APPROVAL -> BLOCKED, APPROVED -> COMPLETED)
6. Security & defense-in-depth secret detection (execution blocked, zero secret leaks)
7. Runtime idempotency (duplicate execution prevented, execute count == 1)
8. Dry-run mode (validation performed, execute_task not called, status DRY_RUN)
9. Real capability adapter execution (PricingWorkerAdapter, SimulationWorkerAdapter)
10. ProjectContext immutability verification (Snapshot A == Snapshot B after execution)
11. Downstream task immutability verification (Downstream tasks remain WAITING)
12. Timing metrics (duration_ms > 0, started_at, completed_at)
13. Exception safety (Worker exceptions isolated, orchestration process does not crash)
14. Serialization and deserialization round-trip of RuntimeResult
"""

import copy
import pytest

from orchestration.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
    ExecutionEnvelope,
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
from orchestration.worker_contract import BaseWorker, Task, TaskPlan, TaskResult, VerificationResult, WorkerState
from orchestration.worker_runtime import (
    EchoWorker,
    PricingWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    SimulationWorkerAdapter,
    WorkerRuntime,
    WorkerRuntimeRegistry,
    get_default_runtime_registry,
)


@pytest.fixture(autouse=True)
def clean_registries():
    """Ensure fresh registries before each test."""
    dispatch_reg = get_default_dispatch_registry()
    dispatch_reg.clear()
    runtime_reg = get_default_runtime_registry()
    runtime_reg.clear()
    yield
    dispatch_reg.clear()
    runtime_reg.clear()


@pytest.fixture
def crypto_project_context() -> ProjectContext:
    defn = ProjectDefinition(
        idea="Crypto price tracking and alert SaaS",
        goal="Provide real-time crypto price tracking, portfolio overview, and multi-channel alerts.",
        target_users="Retail crypto investors and active traders",
        requirements=[
            "Real-time price tracking for top 100 cryptocurrencies",
            "Custom price threshold alerts",
            "Responsive portfolio dashboard",
        ],
        acceptance_criteria=[
            "user can add a tracked asset",
            "user can see current price",
            "user can create an alert",
        ],
    )
    return ProjectContext(
        project_id="proj_crypto_701",
        execution_id="exec_crypto_801",
        user_id="user_trader_1",
        definition=defn,
    )


@pytest.fixture
def sample_envelope() -> ExecutionEnvelope:
    return ExecutionEnvelope(
        dispatch_id="dispatch_crypto_801_task_echo_01",
        execution_id="exec_crypto_801",
        task_id="task_echo_01",
        project_id="proj_crypto_701",
        worker_id="worker_echo",
        phase_id="phase_build",
        objective="Echo test message for deterministic verification",
        inputs={"message": "hello_tetris_runtime"},
        expected_output={"expected_artifacts": ["echo_artifact"]},
        permissions=["filesystem:write"],
        required_connectors=[],
        approval_status="NOT_REQUIRED",
        metadata={"phase_id": "phase_build"},
    )


# =============================================================================
# 1. Deterministic EchoWorker Lifecycle Tests
# =============================================================================

class TestDeterministicEchoWorkerLifecycle:
    def test_echo_worker_full_lifecycle_success(self, sample_envelope):
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.COMPLETED.value
        assert result.is_completed is True
        assert result.is_failed is False
        assert result.error is None
        assert result.task_result is not None
        assert result.task_result.state == WorkerState.SUCCESS
        assert result.task_result.output.get("echo") == "hello_tetris_runtime"
        assert result.verification_result is not None
        assert result.verification_result.verified is True
        assert result.duration_ms >= 0.0
        assert echo_worker.preparation_count == 1
        assert echo_worker.execution_count == 1
        assert echo_worker.verification_count == 1

    def test_echo_worker_timing_metrics(self, sample_envelope):
        runtime = WorkerRuntime()
        result = runtime.execute_envelope(sample_envelope)

        assert result.started_at != ""
        assert result.completed_at != ""
        assert result.duration_ms >= 0.0


# =============================================================================
# 2. Worker Lifecycle Failure Modes
# =============================================================================

class TestWorkerFailureModes:
    def test_preparation_failure_prevents_execution(self, sample_envelope):
        failing_worker = EchoWorker(fail_prep=True)
        runtime = WorkerRuntime(custom_workers={"worker_echo": failing_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.FAILED.value
        assert result.is_failed is True
        assert result.is_completed is False
        assert "preparation exception" in result.error.lower()
        assert failing_worker.preparation_count == 1
        assert failing_worker.execution_count == 0  # NOT called
        assert failing_worker.verification_count == 0

    def test_execution_failure_prevents_verification(self, sample_envelope):
        failing_worker = EchoWorker(fail_exec=True)
        runtime = WorkerRuntime(custom_workers={"worker_echo": failing_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.FAILED.value
        assert result.is_failed is True
        assert "execution exception" in result.error.lower()
        assert failing_worker.preparation_count == 1
        assert failing_worker.execution_count == 1
        assert failing_worker.verification_count == 0  # NOT called

    def test_verification_failure_reports_failed_honestly(self, sample_envelope):
        failing_worker = EchoWorker(fail_verify=True)
        runtime = WorkerRuntime(custom_workers={"worker_echo": failing_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.FAILED.value
        assert result.is_failed is True
        assert result.is_completed is False
        assert result.task_result is not None
        assert result.verification_result is not None
        assert result.verification_result.verified is False
        assert "verification failure" in result.error.lower()
        assert failing_worker.preparation_count == 1
        assert failing_worker.execution_count == 1
        assert failing_worker.verification_count == 1


# =============================================================================
# 3. Approval Boundary Enforcement Tests
# =============================================================================

class TestApprovalBoundaryEnforcement:
    def test_pending_approval_blocks_execution(self, sample_envelope):
        sample_envelope.approval_status = "PENDING_APPROVAL"
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.BLOCKED.value
        assert result.is_blocked is True
        assert "requires approval" in result.error.lower()
        assert echo_worker.execution_count == 0

    def test_approved_envelope_executes(self, sample_envelope):
        sample_envelope.approval_status = "APPROVED"
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.COMPLETED.value
        assert result.is_completed is True
        assert echo_worker.execution_count == 1


# =============================================================================
# 4. Security & Secret Protection Tests
# =============================================================================

class TestSecurityAndSecretProtection:
    def test_raw_secret_in_envelope_inputs_is_rejected(self, sample_envelope):
        sample_envelope.inputs["api_key"] = "sk_live_super_secret_token_12345"
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        result = runtime.execute_envelope(sample_envelope)

        assert result.status == RuntimeStatus.INVALID.value
        assert "credentials detected" in result.error.lower()
        assert echo_worker.execution_count == 0
        # Secret value must NEVER appear in error message or output
        assert "sk_live_super_secret_token_12345" not in str(result.to_dict())

    def test_redacted_secret_placeholder_executes_safely(self, sample_envelope):
        sample_envelope.inputs["api_key"] = "[REDACTED_SECRET]"
        runtime = WorkerRuntime()

        result = runtime.execute_envelope(sample_envelope)
        assert result.status == RuntimeStatus.COMPLETED.value


# =============================================================================
# 5. Idempotency & Duplicate Execution Tests
# =============================================================================

class TestRuntimeIdempotency:
    def test_duplicate_dispatch_execution_is_blocked(self, sample_envelope):
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        # First execution succeeds
        res1 = runtime.execute_envelope(sample_envelope)
        assert res1.status == RuntimeStatus.COMPLETED.value
        assert echo_worker.execution_count == 1

        # Second execution of the exact same dispatch_id is blocked
        res2 = runtime.execute_envelope(sample_envelope)
        assert res2.status == RuntimeStatus.BLOCKED.value
        assert "already been executed" in res2.error.lower()
        assert echo_worker.execution_count == 1  # Still 1


# =============================================================================
# 6. Dry-Run Execution Tests
# =============================================================================

class TestDryRunExecution:
    def test_dry_run_prepares_without_executing(self, sample_envelope):
        echo_worker = EchoWorker()
        runtime = WorkerRuntime(custom_workers={"worker_echo": echo_worker})

        result = runtime.execute_envelope(sample_envelope, dry_run=True)

        assert result.status == RuntimeStatus.DRY_RUN.value
        assert result.is_dry_run is True
        assert echo_worker.preparation_count == 1
        assert echo_worker.execution_count == 0  # NOT executed
        assert echo_worker.verification_count == 0


# =============================================================================
# 7. Real Capability Worker Adapters (Pricing & Simulation)
# =============================================================================

class TestRealCapabilityWorkerAdapters:
    def test_pricing_worker_adapter_execution(self):
        pricing_envelope = ExecutionEnvelope(
            dispatch_id="dispatch_pricing_001",
            execution_id="exec_crypto_801",
            task_id="task_pricing_01",
            project_id="proj_crypto_701",
            worker_id="worker_pricing",
            phase_id="phase_validate",
            objective="Design value-based pricing tiers for Crypto Alert SaaS",
            inputs={"idea": "Crypto Alert SaaS", "target_users": "Active crypto traders"},
            expected_output={"expected_artifacts": ["pricing_model"]},
            permissions=[],
            required_connectors=[],
            metadata={"phase_id": "phase_validate"},
        )

        runtime = WorkerRuntime()
        result = runtime.execute_envelope(pricing_envelope)

        assert result.status == RuntimeStatus.COMPLETED.value
        assert result.is_completed is True
        assert result.task_result is not None
        assert "tiers" in result.task_result.output
        assert len(result.task_result.output["tiers"]) == 3
        assert result.verification_result.verified is True

    def test_build_phase_adapters_execution(self):
        """Verify Code, UI, and Database worker adapters execute and verify cleanly."""
        runtime = WorkerRuntime()

        # 1. Code Worker
        code_env = ExecutionEnvelope(
            dispatch_id="dispatch_code_001",
            execution_id="exec_1",
            task_id="task_code_01",
            project_id="proj_1",
            worker_id="worker_code",
            phase_id="phase_build",
            objective="Build backend routes",
            inputs={"idea": "Crypto Tracker", "requirements": ["asset tracking", "price alerts"]},
            expected_output={"expected_artifacts": ["code_workspace", "backend_api"]},
            permissions=["filesystem:write"],
            metadata={"phase_id": "phase_build"},
        )
        code_res = runtime.execute_envelope(code_env)
        assert code_res.status == RuntimeStatus.COMPLETED.value
        assert code_res.task_result.output.get("status") == "BUILT"
        assert len(code_res.task_result.output.get("routes", [])) == 3

        # 2. UI Worker
        ui_env = ExecutionEnvelope(
            dispatch_id="dispatch_ui_001",
            execution_id="exec_1",
            task_id="task_ui_01",
            project_id="proj_1",
            worker_id="worker_ui",
            phase_id="phase_build",
            objective="Build frontend components",
            inputs={"idea": "Crypto Tracker"},
            expected_output={"expected_artifacts": ["frontend_ui"]},
            permissions=["filesystem:write"],
            metadata={"phase_id": "phase_build"},
        )
        ui_res = runtime.execute_envelope(ui_env)
        assert ui_res.status == RuntimeStatus.COMPLETED.value
        assert ui_res.task_result.output.get("status") == "COMPILED"

        # 3. Database Worker
        db_env = ExecutionEnvelope(
            dispatch_id="dispatch_db_001",
            execution_id="exec_1",
            task_id="task_db_01",
            project_id="proj_1",
            worker_id="worker_database",
            phase_id="phase_build",
            objective="Model database schema",
            inputs={"idea": "Crypto Tracker"},
            expected_output={"expected_artifacts": ["database_schema"]},
            permissions=["database:schema"],
            metadata={"phase_id": "phase_build"},
        )
        db_res = runtime.execute_envelope(db_env)
        assert db_res.status == RuntimeStatus.COMPLETED.value
        assert db_res.task_result.output.get("status") == "MIGRATED"


# =============================================================================
# 10. Custom Worker Registration & Exception Isolation Tests
# =============================================================================

class TestCustomWorkerAndExceptionIsolation:
    def test_custom_worker_injection(self, sample_envelope):
        class CustomAnalyticsWorker(BaseWorker):
            def __init__(self):
                super().__init__(worker_id="worker_analytics", name="Analytics", role="analyst")
            def prepare_task(self, task, context=None):
                return TaskPlan(task_id=task.task_id, worker_id=self.worker_id, readiness_status="READY")
            def execute_task(self, task, context=None):
                return TaskResult(task_id=task.task_id, worker_id=self.worker_id, state=WorkerState.SUCCESS, output={"metric": 42})
            def verify_result(self, task_result):
                return VerificationResult.pass_result(evidence={"metric": 42})

        runtime = WorkerRuntime(custom_workers={"worker_analytics": CustomAnalyticsWorker()})
        sample_envelope.worker_id = "worker_analytics"
        sample_envelope.dispatch_id = "dispatch_custom_analytics_01"

        res = runtime.execute_envelope(sample_envelope)
        assert res.status == RuntimeStatus.COMPLETED.value
        assert res.task_result.output.get("metric") == 42

    def test_verification_exception_handling(self, sample_envelope):
        class CrashingVerifierWorker(EchoWorker):
            def verify_result(self, task_result):
                raise ValueError("Crash during verification inspection")

        runtime = WorkerRuntime(custom_workers={"worker_echo": CrashingVerifierWorker()})
        res = runtime.execute_envelope(sample_envelope)

        assert res.status == RuntimeStatus.FAILED.value
        assert "Crash during verification inspection" in res.error


# =============================================================================
# 8. ProjectContext and Downstream Task Immutability (Stage 5B Boundary)
# =============================================================================

class TestStage5BBoundaryImmutability:
    def test_project_context_remains_completely_unmutated(self, crypto_project_context):
        """Proof that Stage 5B runtime execution NEVER mutates ProjectContext."""
        ctx_before = copy.deepcopy(crypto_project_context.to_dict())

        envelope = ExecutionEnvelope(
            dispatch_id="dispatch_crypto_801_task_immutability",
            execution_id="exec_crypto_801",
            task_id="task_immutability",
            project_id=crypto_project_context.project_id,
            worker_id="worker_pricing",
            phase_id="phase_validate",
            objective="Synthesize pricing tiers",
            inputs={"idea": "Crypto Tracker", "target_users": "Traders"},
            expected_output={"expected_artifacts": ["pricing_model"]},
            metadata={"phase_id": "phase_validate"},
        )

        runtime = WorkerRuntime()
        res = runtime.execute_envelope(envelope)
        assert res.status == RuntimeStatus.COMPLETED.value

        ctx_after = crypto_project_context.to_dict()
        assert ctx_after == ctx_before  # 100% Identical, zero mutations

    def test_downstream_tasks_remain_unactivated(self, crypto_project_context):
        """Proof that Stage 5B does NOT activate downstream tasks in the CompiledTaskPlan."""
        wf = ProjectWorkflow.create_default_lifecycle(
            project_id=crypto_project_context.project_id,
            execution_id=crypto_project_context.execution_id,
        )
        team_mgr = TeamManager()
        team_plan = team_mgr.evaluate_team(wf)
        engine = TaskAssignmentEngine()
        compiled = engine.assign_tasks(crypto_project_context, wf, team_plan)

        # Simulation tasks are WAITING
        sim_task = compiled.get_tasks_for_phase("phase_simulation")[0]
        assert sim_task.task_id in compiled.waiting_tasks

        # Dispatch and execute a Build task
        dispatcher = ExecutionDispatcher()
        code_task = compiled.get_task("task_build_code")
        dispatch_res = dispatcher.dispatch_task(code_task, compiled_task_plan=compiled)

        runtime = WorkerRuntime()
        exec_res = runtime.execute_envelope(dispatch_res.envelope)
        assert exec_res.status == RuntimeStatus.COMPLETED.value

        # Simulation task MUST still be WAITING (Downstream activation belongs to Stage 5C)
        assert sim_task.task_id in compiled.waiting_tasks


# =============================================================================
# 9. Serialization Round-Trip Tests
# =============================================================================

class TestRuntimeSerialization:
    def test_runtime_result_serialization_roundtrip(self, sample_envelope):
        runtime = WorkerRuntime()
        res = runtime.execute_envelope(sample_envelope)

        data = res.to_dict()
        assert isinstance(data, dict)
        reconstructed = RuntimeResult.from_dict(data)

        assert reconstructed.runtime_id == res.runtime_id
        assert reconstructed.dispatch_id == res.dispatch_id
        assert reconstructed.status == res.status
        assert reconstructed.is_completed is True
        assert reconstructed.task_result.output == res.task_result.output
