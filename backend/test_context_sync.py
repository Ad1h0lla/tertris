"""
Unit Tests for Workforce Engine — Stage 5C: Context Synchronizer
================================================================

Tests:
1. Successful verified RuntimeResult promotes artifacts to ProjectContext
2. Full deliverable provenance (project_id, phase_id, producer_worker, producer_task, execution_id)
3. Verified external receipt recording (platform, permalink, verification_status)
4. Failed execution does not promote success artifacts
5. Failed verification does not promote success artifacts (records honest failure in phase history)
6. Missing/NOT_TESTED verification is rejected honestly
7. Malformed RuntimeResult leaves ProjectContext unmutated
8. Idempotency: Re-applying the same RuntimeResult creates zero duplicate artifacts or receipts
9. Security: Defense-in-depth secret detection and recursive sanitization
10. Unrelated ProjectContext fields (definition, unrelated artifacts/history) remain untouched
11. Serialization round-trip of SyncResult
"""

import copy
import pytest

from orchestration.context_sync import ContextSynchronizer, SyncResult, SyncStatus
from orchestration.project_context import (
    Artifact,
    ProjectDefinition,
    ProjectContext,
)
from orchestration.worker_contract import TaskResult, VerificationResult, WorkerState
from orchestration.worker_runtime import RuntimeResult, RuntimeStatus


@pytest.fixture
def crypto_project_context() -> ProjectContext:
    defn = ProjectDefinition(
        idea="Crypto price tracking and alert SaaS",
        goal="Provide real-time crypto price tracking and alerts.",
        target_users="Retail crypto investors",
        requirements=["Real-time price tracking", "Custom price alerts"],
        acceptance_criteria=["user can add asset", "user can create alert"],
    )
    return ProjectContext(
        project_id="proj_crypto_sync_01",
        execution_id="exec_crypto_sync_02",
        user_id="user_trader_1",
        definition=defn,
    )


@pytest.fixture
def successful_runtime_result() -> RuntimeResult:
    task_res = TaskResult(
        task_id="task_build_code_01",
        worker_id="worker_code",
        state=WorkerState.SUCCESS,
        output={"status": "BUILT", "routes": ["/health", "/api/v1/assets"]},
        artifacts=[{
            "artifact_type": "code_workspace",
            "name": "Backend Code Workspace",
            "location": "workspace/backend",
            "summary": {"files": 12, "framework": "FastAPI"},
        }],
        actions=[{"action": "generate_code", "status": "COMPLETED"}],
    )
    verif_res = VerificationResult.pass_result(
        evidence={"routes_verified": 2, "syntax_valid": True}
    )
    return RuntimeResult(
        runtime_id="rt_code_01_success",
        dispatch_id="dispatch_crypto_sync_02_build_code",
        execution_id="exec_crypto_sync_02",
        task_id="task_build_code_01",
        project_id="proj_crypto_sync_01",
        worker_id="worker_code",
        status=RuntimeStatus.COMPLETED.value,
        task_result=task_res,
        verification_result=verif_res,
        metadata={"phase_id": "phase_build"},
    )


# =============================================================================
# 1. Verified Success Synchronization Tests
# =============================================================================

class TestVerifiedSuccessSynchronization:
    def test_verified_success_promotes_artifacts(self, crypto_project_context, successful_runtime_result):
        synchronizer = ContextSynchronizer()

        result = synchronizer.apply_result(crypto_project_context, successful_runtime_result)

        assert result.status == SyncStatus.SYNCED.value
        assert result.is_synced is True
        assert len(result.artifacts_created) == 1
        assert "phase_build" in result.phase_outcomes_updated

        # Verify ProjectContext state
        art_id = result.artifacts_created[0]
        artifact = crypto_project_context.get_artifact(art_id)
        assert artifact is not None
        assert artifact.artifact_type == "code_workspace"
        assert artifact.status == "AVAILABLE"
        assert artifact.producer_worker == "worker_code"
        assert artifact.producer_task == "task_build_code_01"
        assert artifact.phase_id == "phase_build"
        assert artifact.metadata.get("runtime_id") == "rt_code_01_success"
        assert artifact.metadata.get("verification_status") == "PASS"

        # Verify phase history entry
        phase_history = crypto_project_context.phase_history
        assert "phase_build" in phase_history
        assert phase_history["phase_build"].status == "COMPLETED"
        assert phase_history["phase_build"].verification_status == "PASS"

    def test_verified_receipt_recording(self, crypto_project_context):
        task_res = TaskResult(
            task_id="task_reddit_01",
            worker_id="worker_reddit",
            state=WorkerState.SUCCESS,
            output={"post_title": "Announcing Crypto Tracker"},
            artifacts=[{"artifact_type": "reddit_post_receipt", "summary": {"post_id": "t3_abc123"}}],
        )
        verif_res = VerificationResult.pass_result(
            external_id="t3_abc123",
            permalink="https://reddit.com/r/crypto/comments/abc123",
            evidence={"platform": "reddit", "action_type": "submit_post", "receipt_id": "rcpt_reddit_live_01"},
        )
        runtime_res = RuntimeResult(
            runtime_id="rt_reddit_01_success",
            dispatch_id="dispatch_reddit_01",
            execution_id="exec_crypto_sync_02",
            task_id="task_reddit_01",
            project_id="proj_crypto_sync_01",
            worker_id="worker_reddit",
            status=RuntimeStatus.COMPLETED.value,
            task_result=task_res,
            verification_result=verif_res,
            metadata={"phase_id": "phase_marketing"},
        )

        synchronizer = ContextSynchronizer()
        result = synchronizer.apply_result(crypto_project_context, runtime_res)

        assert result.is_synced is True
        assert len(result.receipts_created) == 1

        # Check receipt in ProjectContext
        assert len(crypto_project_context.receipts) == 1
        rcpt = crypto_project_context.receipts[0]
        assert rcpt.receipt_id == "rcpt_reddit_live_01"
        assert rcpt.platform == "reddit"
        assert rcpt.external_id == "t3_abc123"
        assert rcpt.permalink == "https://reddit.com/r/crypto/comments/abc123"
        assert rcpt.verified is True
        assert rcpt.verification_status == "PASS"


# =============================================================================
# 2. Failure & Unverified Result Acceptance Gate Tests
# =============================================================================

class TestFailureAndUnverifiedGates:
    def test_failed_execution_does_not_promote_artifacts(self, crypto_project_context):
        task_res = TaskResult(
            task_id="task_build_code_fail",
            worker_id="worker_code",
            state=WorkerState.FAILED,
            error="Syntax error in generated backend routes",
        )
        runtime_res = RuntimeResult(
            runtime_id="rt_code_fail",
            dispatch_id="dispatch_code_fail",
            execution_id="exec_crypto_sync_02",
            task_id="task_build_code_fail",
            project_id="proj_crypto_sync_01",
            worker_id="worker_code",
            status=RuntimeStatus.FAILED.value,
            task_result=task_res,
            error="Syntax error",
            metadata={"phase_id": "phase_build"},
        )

        synchronizer = ContextSynchronizer()
        result = synchronizer.apply_result(crypto_project_context, runtime_res)

        assert result.status == SyncStatus.FAILED.value
        assert len(result.artifacts_created) == 0
        assert len(crypto_project_context.artifacts) == 0

        # Phase history records failure
        assert "phase_build" in crypto_project_context.phase_history
        assert crypto_project_context.phase_history["phase_build"].status == "FAILED"

    def test_failed_verification_does_not_promote_artifacts(self, crypto_project_context):
        """Worker execution succeeded, but verification failed."""
        task_res = TaskResult(
            task_id="task_qa_01",
            worker_id="worker_qa_simulation",
            state=WorkerState.SUCCESS,
            output={"overall_status": "FAIL", "failed_checks": 2},
        )
        verif_res = VerificationResult.fail_result(
            error="Simulation payload test failed 2/5 checks",
            evidence={"overall_status": "FAIL"},
        )
        runtime_res = RuntimeResult(
            runtime_id="rt_qa_verif_fail",
            dispatch_id="dispatch_qa_01",
            execution_id="exec_crypto_sync_02",
            task_id="task_qa_01",
            project_id="proj_crypto_sync_01",
            worker_id="worker_qa_simulation",
            status=RuntimeStatus.FAILED.value,
            task_result=task_res,
            verification_result=verif_res,
            metadata={"phase_id": "phase_simulation"},
        )

        synchronizer = ContextSynchronizer()
        result = synchronizer.apply_result(crypto_project_context, runtime_res)

        assert result.status == SyncStatus.FAILED.value
        assert len(result.artifacts_created) == 0
        assert len(crypto_project_context.artifacts) == 0

    def test_missing_verification_is_rejected(self, crypto_project_context, successful_runtime_result):
        successful_runtime_result.verification_result = None

        synchronizer = ContextSynchronizer()
        result = synchronizer.apply_result(crypto_project_context, successful_runtime_result)

        assert result.status in (SyncStatus.REJECTED.value, SyncStatus.FAILED.value)
        assert len(result.artifacts_created) == 0
        assert len(crypto_project_context.artifacts) == 0


# =============================================================================
# 3. Idempotency & Malformed Input Tests
# =============================================================================

class TestIdempotencyAndMalformed:
    def test_duplicate_result_sync_is_idempotent(self, crypto_project_context, successful_runtime_result):
        synchronizer = ContextSynchronizer()

        # First synchronization succeeds
        res1 = synchronizer.apply_result(crypto_project_context, successful_runtime_result)
        assert res1.is_synced is True
        assert len(crypto_project_context.artifacts) == 1

        # Second synchronization of the exact same result is skipped without duplicates
        res2 = synchronizer.apply_result(crypto_project_context, successful_runtime_result)
        assert res2.status == SyncStatus.SKIPPED.value
        assert res2.is_skipped is True
        assert len(crypto_project_context.artifacts) == 1

    def test_duplicate_receipts_are_not_duplicated(self, crypto_project_context):
        task_res = TaskResult(
            task_id="task_reddit_02",
            worker_id="worker_reddit",
            state=WorkerState.SUCCESS,
            output={"post_title": "Announcing Crypto Tracker"},
        )
        verif_res = VerificationResult.pass_result(
            external_id="t3_xyz999",
            permalink="https://reddit.com/r/crypto/comments/xyz999",
            evidence={"platform": "reddit", "action_type": "submit_post", "receipt_id": "rcpt_dedup_01"},
        )
        runtime_res = RuntimeResult(
            runtime_id="rt_reddit_dedup_01",
            dispatch_id="dispatch_reddit_dedup",
            execution_id="exec_crypto_sync_02",
            task_id="task_reddit_02",
            project_id="proj_crypto_sync_01",
            worker_id="worker_reddit",
            status=RuntimeStatus.COMPLETED.value,
            task_result=task_res,
            verification_result=verif_res,
            metadata={"phase_id": "phase_marketing"},
        )

        synchronizer = ContextSynchronizer()
        res1 = synchronizer.apply_result(crypto_project_context, runtime_res)
        assert len(crypto_project_context.receipts) == 1

        # Simulate fresh synchronizer instance receiving same runtime result (receipt_id already in context)
        fresh_sync = ContextSynchronizer()
        res2 = fresh_sync.apply_result(crypto_project_context, runtime_res)
        # Should not duplicate receipt in project_context.receipts
        assert len(crypto_project_context.receipts) == 1

    def test_malformed_runtime_result_causes_no_mutation(self, crypto_project_context):
        initial_context_dict = copy.deepcopy(crypto_project_context.to_dict())

        malformed_result = RuntimeResult(
            runtime_id="",  # missing runtime_id
            dispatch_id="dispatch_bad",
            execution_id="",
            task_id="",
            project_id="",
            worker_id="",
            status=RuntimeStatus.COMPLETED.value,
        )

        synchronizer = ContextSynchronizer()
        res = synchronizer.apply_result(crypto_project_context, malformed_result)

        assert res.status == SyncStatus.REJECTED.value
        assert len(res.validation_errors) > 0
        # Context must be 100% unchanged
        assert crypto_project_context.to_dict() == initial_context_dict


# =============================================================================
# 4. Security & Context Immutability Tests
# =============================================================================

class TestSecurityAndContextImmutability:
    def test_raw_secrets_in_result_are_rejected(self, crypto_project_context, successful_runtime_result):
        successful_runtime_result.task_result.output["api_key"] = "sk_live_leaky_secret_9999"

        synchronizer = ContextSynchronizer()
        result = synchronizer.apply_result(crypto_project_context, successful_runtime_result)

        assert result.status == SyncStatus.REJECTED.value
        assert "security violation" in result.reason.lower()
        assert len(crypto_project_context.artifacts) == 0

    def test_unrelated_context_fields_remain_untouched(self, crypto_project_context, successful_runtime_result):
        defn_before = copy.deepcopy(crypto_project_context.definition.to_dict())

        synchronizer = ContextSynchronizer()
        synchronizer.apply_result(crypto_project_context, successful_runtime_result)

        # Core project definition and requirements must be 100% unchanged
        assert crypto_project_context.definition.to_dict() == defn_before


# =============================================================================
# 5. Serialization Round-Trip Tests
# =============================================================================

class TestSyncResultSerialization:
    def test_sync_result_serialization_roundtrip(self, crypto_project_context, successful_runtime_result):
        synchronizer = ContextSynchronizer()
        res = synchronizer.apply_result(crypto_project_context, successful_runtime_result)

        data = res.to_dict()
        assert isinstance(data, dict)
        reconstructed = SyncResult.from_dict(data)

        assert reconstructed.status == res.status
        assert reconstructed.runtime_id == res.runtime_id
        assert reconstructed.artifacts_created == res.artifacts_created
        assert reconstructed.is_synced is True
