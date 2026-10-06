"""
Unit Tests for Workforce Engine — Stage 1: Worker Contract Foundation
====================================================================

Tests:
1. WorkerState lifecycle states and valid/invalid transitions
2. Terminal state identification
3. Task model serialization, deserialization, and schema validation
4. TaskPlan model, executable readiness, and approval requirements
5. TaskResult model and success property evaluation
6. VerificationResult model (pass/fail helpers, evidence, external IDs)
7. BaseWorker abstract interface contract and subclass execution
8. Backwards compatibility with existing execution/distribution models
"""

import json
import pytest
from pydantic import ValidationError

from orchestration.worker_contract import (
    WorkerState,
    Task,
    TaskPlan,
    TaskResult,
    VerificationResult,
    BaseWorker,
)
from execution.distribution_models import (
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
    create_distribution_action,
)


# =============================================================================
# 1. WorkerState Lifecycle & Transition Tests
# =============================================================================

class TestWorkerStateLifecycle:
    def test_all_lifecycle_states_exist(self):
        expected_states = {
            "PLANNED",
            "PREPARED",
            "APPROVAL_REQUIRED",
            "APPROVED",
            "RUNNING",
            "VERIFYING",
            "SUCCESS",
            "FAILED",
            "BLOCKED",
            "CANCELLED",
        }
        actual_states = {s.value for s in WorkerState}
        assert actual_states == expected_states

    def test_terminal_states(self):
        assert WorkerState.is_terminal(WorkerState.SUCCESS) is True
        assert WorkerState.is_terminal(WorkerState.FAILED) is True
        assert WorkerState.is_terminal(WorkerState.BLOCKED) is True
        assert WorkerState.is_terminal(WorkerState.CANCELLED) is True
        assert WorkerState.is_terminal(WorkerState.RUNNING) is False
        assert WorkerState.is_terminal(WorkerState.PLANNED) is False
        assert WorkerState.is_terminal("NON_EXISTENT") is False

    def test_valid_state_transitions(self):
        # Forward happy path
        assert WorkerState.PLANNED.can_transition_to(WorkerState.PREPARED) is True
        assert WorkerState.PREPARED.can_transition_to(WorkerState.APPROVAL_REQUIRED) is True
        assert WorkerState.APPROVAL_REQUIRED.can_transition_to(WorkerState.APPROVED) is True
        assert WorkerState.APPROVED.can_transition_to(WorkerState.RUNNING) is True
        assert WorkerState.RUNNING.can_transition_to(WorkerState.VERIFYING) is True
        assert WorkerState.VERIFYING.can_transition_to(WorkerState.SUCCESS) is True

        # Identity transition
        assert WorkerState.RUNNING.can_transition_to(WorkerState.RUNNING) is True

        # Blocking / failure paths
        assert WorkerState.PLANNED.can_transition_to(WorkerState.BLOCKED) is True
        assert WorkerState.RUNNING.can_transition_to(WorkerState.FAILED) is True
        assert WorkerState.VERIFYING.can_transition_to(WorkerState.FAILED) is True

        # Retry from failed/blocked
        assert WorkerState.FAILED.can_transition_to(WorkerState.PLANNED) is True
        assert WorkerState.BLOCKED.can_transition_to(WorkerState.PREPARED) is True

    def test_invalid_state_transitions(self):
        # Cannot jump from PLANNED directly to SUCCESS without executing
        assert WorkerState.PLANNED.can_transition_to(WorkerState.SUCCESS) is False

        # Cannot transition out of terminal SUCCESS
        assert WorkerState.SUCCESS.can_transition_to(WorkerState.RUNNING) is False
        assert WorkerState.SUCCESS.can_transition_to(WorkerState.PLANNED) is False

        # Cannot transition out of CANCELLED
        assert WorkerState.CANCELLED.can_transition_to(WorkerState.RUNNING) is False

        # Invalid state string
        assert WorkerState.PLANNED.can_transition_to("INVALID_STATE") is False


# =============================================================================
# 2. Task Model Tests
# =============================================================================

class TestTaskModel:
    def test_task_creation_with_defaults(self):
        task = Task(
            worker_id="worker_reddit_01",
            objective="Post product announcement to Reddit",
        )
        assert task.task_id.startswith("task_")
        assert task.worker_id == "worker_reddit_01"
        assert task.objective == "Post product announcement to Reddit"
        assert task.inputs == {}
        assert task.dependencies == []
        assert task.permissions == []
        assert task.created_at is not None

    def test_task_serialization_roundtrip(self):
        original = Task(
            task_id="task_12345",
            execution_id="exec_abcde",
            project_id="proj_999",
            worker_id="worker_code_01",
            objective="Generate FastAPI node server",
            inputs={"framework": "fastapi", "port": 8000},
            dependencies=["task_spec_01"],
            permissions=["filesystem:write", "network:listen"],
            expected_output={"schema": "zip"},
            metadata={"priority": "high"},
        )

        d = original.to_dict()
        assert d["task_id"] == "task_12345"
        assert d["inputs"]["framework"] == "fastapi"
        assert "task_spec_01" in d["dependencies"]

        # JSON serialize and deserialize
        json_str = json.dumps(d)
        reloaded_dict = json.loads(json_str)
        reloaded_task = Task.from_dict(reloaded_dict)

        assert reloaded_task.task_id == original.task_id
        assert reloaded_task.execution_id == original.execution_id
        assert reloaded_task.permissions == original.permissions
        assert reloaded_task.expected_output == original.expected_output


# =============================================================================
# 3. TaskPlan Model Tests
# =============================================================================

class TestTaskPlanModel:
    def test_task_plan_ready_executable(self):
        plan = TaskPlan(
            task_id="task_01",
            worker_id="worker_01",
            planned_actions=[{"action": "search", "query": "n8n"}],
            required_connectors=["redditapis"],
            required_capabilities=["reddit:read"],
            approval_requirement=False,
            readiness_status="READY",
            validation_errors=[],
        )
        assert plan.is_executable is True

    def test_task_plan_blocked_by_approval_requirement(self):
        plan = TaskPlan(
            task_id="task_01",
            worker_id="worker_01",
            planned_actions=[{"action": "submit_comment"}],
            required_connectors=["redditapis"],
            approval_requirement=True,
            approval_status=ApprovalStatus.PENDING_APPROVAL,
            readiness_status="READY",
        )
        assert plan.is_executable is False

        # Once approved, becomes executable
        plan.approval_status = ApprovalStatus.APPROVED
        assert plan.is_executable is True

    def test_task_plan_blocked_by_validation_errors(self):
        plan = TaskPlan(
            task_id="task_01",
            worker_id="worker_01",
            readiness_status="READY",
            validation_errors=["Missing target subreddit"],
        )
        assert plan.is_executable is False


# =============================================================================
# 4. VerificationResult Tests
# =============================================================================

class TestVerificationResultModel:
    def test_pass_result_helper(self):
        verif = VerificationResult.pass_result(
            external_id="t1_pe95jxd",
            permalink="https://www.reddit.com/r/n8n/comments/1wxsr8b/comment/pe95jxd/",
            evidence={"status_code": 200, "title": "n8n post"},
        )
        assert verif.verified is True
        assert verif.status == VerificationStatus.PASS
        assert verif.external_id == "t1_pe95jxd"
        assert "reddit.com" in verif.permalink
        assert verif.error is None
        assert verif.evidence["status_code"] == 200

    def test_fail_result_helper(self):
        verif = VerificationResult.fail_result(
            error="HTTP 500: reddit session invalid",
            evidence={"attempt_count": 1},
        )
        assert verif.verified is False
        assert verif.status == VerificationStatus.FAIL
        assert verif.external_id is None
        assert verif.permalink is None
        assert "reddit session invalid" in verif.error
        assert verif.evidence["attempt_count"] == 1


# =============================================================================
# 5. TaskResult Tests
# =============================================================================

class TestTaskResultModel:
    def test_task_result_success(self):
        verif = VerificationResult.pass_result(external_id="t1_123")
        res = TaskResult(
            task_id="task_01",
            worker_id="worker_reddit",
            state=WorkerState.SUCCESS,
            output={"comment_text": "Great tool"},
            actions=[{"platform": "reddit", "id": "t1_123"}],
            verification=verif,
        )
        assert res.is_success is True
        assert res.error is None
        assert len(res.actions) == 1

    def test_task_result_failure_when_verification_fails(self):
        verif = VerificationResult.fail_result(error="Could not verify comment on Reddit")
        res = TaskResult(
            task_id="task_01",
            worker_id="worker_reddit",
            state=WorkerState.SUCCESS,  # Even if state was marked success, verification fail invalidates it
            verification=verif,
        )
        assert res.is_success is False


# =============================================================================
# 6. BaseWorker Interface & Concrete Implementation Tests
# =============================================================================

class MockCommunityWorker(BaseWorker):
    """Concrete test worker implementing BaseWorker."""

    def prepare_task(self, task: Task, context=None) -> TaskPlan:
        return TaskPlan(
            task_id=task.task_id,
            worker_id=self.worker_id,
            planned_actions=[{"type": "reply_to_post", "target": task.inputs.get("target")}],
            required_connectors=self.required_connectors,
            required_capabilities=self.capabilities,
            approval_requirement="network:write" in self.permissions,
            approval_status=ApprovalStatus.PENDING_APPROVAL,
            readiness_status="READY",
        )

    def execute_task(self, task: Task, context=None) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            worker_id=self.worker_id,
            state=WorkerState.SUCCESS,
            output={"status": "dispatched"},
            actions=[{"platform": "reddit", "action": "reply"}],
        )

    def verify_result(self, task_result: TaskResult) -> VerificationResult:
        return VerificationResult.pass_result(
            external_id="t1_mock_id",
            permalink="https://reddit.com/r/test/comments/123/comment/mock_id",
        )


class TestBaseWorkerInterface:
    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseWorker(
                worker_id="w_base",
                name="Base",
                role="test",
            )

    def test_concrete_worker_lifecycle(self):
        worker = MockCommunityWorker(
            worker_id="worker_reddit_01",
            name="Reddit Community Specialist",
            role="community",
            description="Engages relevant developer communities",
            capabilities=["reddit:search", "reddit:reply"],
            required_connectors=["redditapis"],
            permissions=["network:write"],
        )

        assert repr(worker) == "<MockCommunityWorker id='worker_reddit_01' name='Reddit Community Specialist' role='community'>"
        assert worker.capabilities == ["reddit:search", "reddit:reply"]
        assert worker.required_connectors == ["redditapis"]

        task = Task(
            worker_id=worker.worker_id,
            objective="Reply to thread",
            inputs={"target": "https://reddit.com/r/n8n/comments/1wxsr8b/"},
        )

        # 1. Prepare
        plan = worker.prepare_task(task)
        assert plan.task_id == task.task_id
        assert plan.approval_requirement is True
        assert plan.is_executable is False

        # Simulate approval
        plan.approval_status = ApprovalStatus.APPROVED
        assert plan.is_executable is True

        # 2. Execute
        result = worker.execute_task(task)
        assert result.state == WorkerState.SUCCESS
        assert len(result.actions) == 1

        # 3. Verify
        verif = worker.verify_result(result)
        result.verification = verif
        assert result.is_success is True
        assert verif.external_id == "t1_mock_id"


# =============================================================================
# 7. Backwards Compatibility with Existing Modules
# =============================================================================

class TestBackwardsCompatibility:
    def test_compatible_with_existing_distribution_action_model(self):
        dist_action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="reply_to_post",
            target={"post_id": "1wxsr8b"},
            content={"body": "Test comment text"},
            execution_id="exec_compat_123",
        )

        # Map to Task
        task = Task(
            task_id=dist_action["action_id"],
            execution_id=dist_action["execution_id"],
            worker_id=dist_action["worker"],
            objective=f"{dist_action['action_type']} on {dist_action['platform']}",
            inputs={"target": dist_action["target"], "content": dist_action["content"]},
            permissions=["network:write"],
            metadata={"legacy_phase": dist_action["phase"]},
        )

        assert task.task_id == dist_action["action_id"]
        assert task.execution_id == "exec_compat_123"
        assert task.inputs["target"]["post_id"] == "1wxsr8b"

        # VerificationStatus interoperability
        assert VerificationStatus.PASS in ("PASS", "FAIL", "NOT_TESTED")
        assert ApprovalStatus.APPROVED in ("APPROVED", "PENDING_APPROVAL", "REJECTED")
        assert ExecutionStatus.SUCCESS in ("SUCCESS", "FAILED", "BLOCKED", "RUNNING", "NOT_STARTED")
