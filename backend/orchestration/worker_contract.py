"""
Tetris — Workforce Engine: Worker Contract Foundation (Stage 1)
==============================================================

Defines strongly typed, production-quality contracts for the Tetris Workforce Engine:
1. WorkerState (Lifecycle Enum & Transition Rules)
2. Task (Unit of Work Specification)
3. TaskPlan (Pre-execution Plan & Readiness Assessment)
4. TaskResult (Execution Outcome & Artifacts)
5. VerificationResult (Independent Proof of Outcome)
6. BaseWorker (Abstract Base Class for all AI Workers)

Architectural Compliance:
- Fully additive and backward compatible with existing Phase 3 models.
- Does not modify or replace existing executors (e.g. reddit_executor.py).
- Reuses existing VerificationStatus / ApprovalStatus conventions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, Field, field_validator

from execution.distribution_models import (
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. WorkerState: Universal Lifecycle States & Transitions
# =============================================================================

class WorkerState(str, Enum):
    """
    Standard lifecycle states for tasks and workers in the Workforce Engine.
    """
    PLANNED = "PLANNED"                     # Task defined, queued for preparation
    PREPARED = "PREPARED"                   # Plan generated, capabilities & connectors resolved
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED" # Awaiting human/system approval before side effects
    APPROVED = "APPROVED"                   # Approved and authorized for execution
    RUNNING = "RUNNING"                     # Actively executing work or external actions
    VERIFYING = "VERIFYING"                 # Execution finished, verifying outcomes/side effects
    SUCCESS = "SUCCESS"                     # Work and verification successfully completed
    FAILED = "FAILED"                       # Execution or verification failed (never fabricated)
    BLOCKED = "BLOCKED"                     # Missing prerequisites, credentials, or dependencies
    CANCELLED = "CANCELLED"                 # Cancelled prior to completion

    @classmethod
    def terminal_states(cls) -> Set[WorkerState]:
        """Returns states from which no further normal transitions occur."""
        return {cls.SUCCESS, cls.FAILED, cls.BLOCKED, cls.CANCELLED}

    @classmethod
    def is_terminal(cls, state: WorkerState | str) -> bool:
        """Checks if a given state is terminal."""
        try:
            val = state if isinstance(state, cls) else cls(state.value if hasattr(state, "value") else str(state))
            return val in cls.terminal_states()
        except ValueError:
            return False

    def can_transition_to(self, target: WorkerState | str) -> bool:
        """
        Validates whether transitioning from self to target is legally allowed.
        """
        try:
            target_enum = target if isinstance(target, WorkerState) else WorkerState(target.value if hasattr(target, "value") else str(target))
        except ValueError:
            return False

        # Identity transition (no-op)
        if self == target_enum:
            return True

        valid_transitions: Dict[WorkerState, Set[WorkerState]] = {
            WorkerState.PLANNED: {
                WorkerState.PREPARED,
                WorkerState.APPROVAL_REQUIRED,
                WorkerState.BLOCKED,
                WorkerState.CANCELLED,
                WorkerState.RUNNING,
            },
            WorkerState.PREPARED: {
                WorkerState.APPROVAL_REQUIRED,
                WorkerState.APPROVED,
                WorkerState.RUNNING,
                WorkerState.BLOCKED,
                WorkerState.CANCELLED,
            },
            WorkerState.APPROVAL_REQUIRED: {
                WorkerState.APPROVED,
                WorkerState.BLOCKED,
                WorkerState.CANCELLED,
                WorkerState.FAILED,
            },
            WorkerState.APPROVED: {
                WorkerState.RUNNING,
                WorkerState.CANCELLED,
                WorkerState.BLOCKED,
            },
            WorkerState.RUNNING: {
                WorkerState.VERIFYING,
                WorkerState.SUCCESS,
                WorkerState.FAILED,
                WorkerState.BLOCKED,
                WorkerState.CANCELLED,
            },
            WorkerState.VERIFYING: {
                WorkerState.SUCCESS,
                WorkerState.FAILED,
                WorkerState.BLOCKED,
            },
            WorkerState.SUCCESS: set(),
            WorkerState.FAILED: {WorkerState.PLANNED, WorkerState.PREPARED, WorkerState.RUNNING},  # Retry paths
            WorkerState.BLOCKED: {WorkerState.PLANNED, WorkerState.PREPARED, WorkerState.RUNNING, WorkerState.CANCELLED},
            WorkerState.CANCELLED: set(),
        }

        return target_enum in valid_transitions.get(self, set())


# =============================================================================
# 2. Task: Standard Unit of Work Specification
# =============================================================================

class Task(BaseModel):
    """
    Strongly-typed unit of work dispatched to a Worker.
    """
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    execution_id: str = Field(default="")
    project_id: Optional[str] = None
    worker_id: str
    objective: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    expected_output: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
        "populate_by_name": True,
    }

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        return cls.model_validate(data)


# =============================================================================
# 3. TaskPlan: Pre-execution Plan & Readiness Assessment
# =============================================================================

class TaskPlan(BaseModel):
    """
    Represents the planned actions, required capabilities, and readiness
    assessment before a Task executes.
    """
    task_id: str
    worker_id: str
    planned_actions: List[Dict[str, Any]] = Field(default_factory=list)
    required_connectors: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    approval_requirement: bool = False
    approval_status: str = ApprovalStatus.PENDING_APPROVAL
    readiness_status: str = "READY"  # e.g., "READY", "NOT_READY", "BLOCKED"
    validation_errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_executable(self) -> bool:
        """Determines if the plan is ready for immediate dispatch."""
        return (
            self.readiness_status == "READY"
            and len(self.validation_errors) == 0
            and (not self.approval_requirement or self.approval_status == ApprovalStatus.APPROVED)
        )


# =============================================================================
# 4. VerificationResult: Independent Proof of Outcome
# =============================================================================

class VerificationResult(BaseModel):
    """
    Independent verification of synthesized output or external side effects.
    Preserves existing verification conventions (PASS/FAIL/NOT_TESTED).
    """
    verified: bool = False
    status: str = VerificationStatus.NOT_TESTED  # PASS, FAIL, NOT_TESTED
    external_id: Optional[str] = None
    permalink: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    verified_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @classmethod
    def pass_result(
        cls,
        external_id: Optional[str] = None,
        permalink: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        return cls(
            verified=True,
            status=VerificationStatus.PASS,
            external_id=external_id,
            permalink=permalink,
            evidence=evidence or {},
            error=None,
        )

    @classmethod
    def fail_result(
        cls,
        error: str,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        return cls(
            verified=False,
            status=VerificationStatus.FAIL,
            external_id=None,
            permalink=None,
            evidence=evidence or {},
            error=str(error),
        )


# =============================================================================
# 5. TaskResult: Execution Outcome & Artifacts
# =============================================================================

class TaskResult(BaseModel):
    """
    Complete result payload produced after worker task execution.
    """
    task_id: str
    worker_id: str
    state: WorkerState = WorkerState.SUCCESS
    output: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_success(self) -> bool:
        return self.state == WorkerState.SUCCESS and (
            self.verification is None or self.verification.verified is True
        )


# =============================================================================
# 6. BaseWorker: Abstract Universal Worker Contract
# =============================================================================

class BaseWorker(ABC):
    """
    Universal Abstract Base Class for all Tetris AI Workers.

    Subclasses must implement:
    1. prepare_task(task, context) -> TaskPlan
    2. execute_task(task, context) -> TaskResult
    3. verify_result(task_result) -> VerificationResult
    """

    def __init__(
        self,
        worker_id: str,
        name: str,
        role: str,
        description: str = "",
        capabilities: Optional[List[str]] = None,
        required_connectors: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
    ):
        self.worker_id = worker_id
        self.name = name
        self.role = role
        self.description = description
        self.capabilities = list(capabilities or [])
        self.required_connectors = list(required_connectors or [])
        self.permissions = list(permissions or [])

    @abstractmethod
    def prepare_task(
        self,
        task: Task,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskPlan:
        """
        Evaluates task requirements, connector readiness, and produces a TaskPlan.
        """
        pass

    @abstractmethod
    def execute_task(
        self,
        task: Task,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """
        Executes authorized work or dispatches external actions.
        """
        pass

    @abstractmethod
    def verify_result(
        self,
        task_result: TaskResult,
    ) -> VerificationResult:
        """
        Independently verifies output or external side effects.
        """
        pass

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id='{self.worker_id}' name='{self.name}' "
            f"role='{self.role}'>"
        )
