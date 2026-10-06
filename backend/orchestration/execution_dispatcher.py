"""
Tetris — Workforce Engine: Execution Dispatcher Foundation (Stage 5A)
=====================================================================

Defines the safe execution dispatch foundation of the Tetris Workforce Engine:
1. DispatchStatus (READY, DISPATCHED, BLOCKED, INVALID, REJECTED)
2. ExecutionEnvelope (Structured execution specification package for worker handoff)
3. DispatchResult (Typed dispatch outcome and validation audit)
4. DispatchRegistry (In-memory tracking to guarantee idempotency and single dispatch)
5. ExecutionDispatcher (Deterministic dispatch compiler and safety validator)

Architectural Boundaries (Stage 5A):
- Pre-execution validation ONLY.
- Resolves workers, connector readiness, permissions, and DAG dependencies.
- Constructs strongly-typed ExecutionEnvelope for future worker handoff.
- ZERO worker execution: Does NOT call `BaseWorker.execute_task()` or external APIs.
- Defense-in-Depth: Rejects any dispatch containing raw unredacted secrets.
- Full Backward Compatibility: Does not alter existing execution routes or database models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from orchestration.project_context import FORBIDDEN_SECRET_KEYS, _sanitize_dict_secrets
from orchestration.task_assignment import CompiledTaskPlan, TaskReadiness
from orchestration.worker_contract import Task
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. DispatchStatus: Universal Dispatch Lifecycle States
# =============================================================================

class DispatchStatus(str, Enum):
    """
    Status of an execution dispatch request.
    """
    READY = "READY"             # Task validated and legally dispatchable
    DISPATCHED = "DISPATCHED"   # Envelope constructed and registered with DispatchRegistry
    BLOCKED = "BLOCKED"         # Missing connector, denied permission, pending approval, or unmet dependency
    INVALID = "INVALID"         # Missing identity fields, malformed task, or unregistered worker
    REJECTED = "REJECTED"       # Duplicate dispatch attempt or credential leakage detected


# =============================================================================
# 2. Defense-in-Depth Secret Scanner
# =============================================================================

# Common sensitive token prefixes / patterns to detect
_SUSPICIOUS_TOKEN_PATTERNS = [
    re.compile(r"sk_live_[0-9a-zA-Z]{12,}", re.IGNORECASE),
    re.compile(r"ghp_[0-9a-zA-Z]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[0-9a-zA-Z\._\-]{20,}", re.IGNORECASE),
    re.compile(r"reddit_session=[0-9a-zA-Z%_\-]+", re.IGNORECASE),
]


def detect_unredacted_secrets(obj: Any) -> bool:
    """
    Recursively inspects data structures for forbidden secret keys or raw token strings.
    Returns True if an unredacted secret is found.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = str(k).lower().strip()
            if k_lower in FORBIDDEN_SECRET_KEYS:
                # If key is forbidden and value is not the safe redaction marker or empty, flag it
                if v and v != "[REDACTED_SECRET]":
                    return True
            if detect_unredacted_secrets(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if detect_unredacted_secrets(item):
                return True
    elif isinstance(obj, str):
        for pattern in _SUSPICIOUS_TOKEN_PATTERNS:
            if pattern.search(obj):
                return True
    return False


# =============================================================================
# 3. ExecutionEnvelope: Structured Worker Handoff Contract
# =============================================================================

class ExecutionEnvelope(BaseModel):
    """
    Structured execution specification package prepared for worker handoff.
    Contains everything a Worker needs to prepare and execute work without
    exposing monolithic project context or sensitive credentials.
    """
    dispatch_id: str
    execution_id: str
    task_id: str
    project_id: str
    worker_id: str
    phase_id: str
    objective: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    expected_output: Dict[str, Any] = Field(default_factory=dict)
    permissions: List[str] = Field(default_factory=list)
    required_connectors: List[str] = Field(default_factory=list)
    approval_status: str = "NOT_REQUIRED"  # "APPROVED", "PENDING_APPROVAL", "NOT_REQUIRED"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionEnvelope:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 4. DispatchResult: Typed Dispatch Outcome & Validation Record
# =============================================================================

class DispatchResult(BaseModel):
    """
    Result of an execution dispatch evaluation.
    """
    status: str  # from DispatchStatus enum
    task_id: str
    worker_id: str
    execution_id: str
    dispatch_id: Optional[str] = None
    envelope: Optional[ExecutionEnvelope] = None
    reason: str = ""
    validation_errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    dispatched_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_dispatched(self) -> bool:
        return self.status == DispatchStatus.DISPATCHED.value and self.envelope is not None

    @property
    def is_blocked(self) -> bool:
        return self.status == DispatchStatus.BLOCKED.value

    @property
    def is_invalid(self) -> bool:
        return self.status == DispatchStatus.INVALID.value

    @property
    def is_rejected(self) -> bool:
        return self.status == DispatchStatus.REJECTED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DispatchResult:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 5. DispatchRegistry: In-Memory Tracking for Single Dispatch Guarantee
# =============================================================================

class DispatchRecord(BaseModel):
    """
    In-memory record of an active or completed dispatch.
    """
    dispatch_id: str
    task_id: str
    execution_id: str
    worker_id: str
    phase_id: str
    status: str = DispatchStatus.DISPATCHED.value
    envelope_metadata: Dict[str, Any] = Field(default_factory=dict)
    dispatched_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }


class DispatchRegistry:
    """
    In-memory registry tracking task dispatches to guarantee idempotency and prevent duplicate dispatches.
    """

    def __init__(self):
        self._records: Dict[str, DispatchRecord] = {}  # dispatch_id -> record
        self._task_to_dispatch: Dict[str, str] = {}    # task_id -> dispatch_id

    def register(self, envelope: ExecutionEnvelope) -> DispatchRecord:
        """
        Registers an execution envelope.
        Raises ValueError if task has already been dispatched.
        """
        if envelope.task_id in self._task_to_dispatch:
            existing_did = self._task_to_dispatch[envelope.task_id]
            raise ValueError(f"Task '{envelope.task_id}' has already been dispatched with ID '{existing_did}'.")

        rec = DispatchRecord(
            dispatch_id=envelope.dispatch_id,
            task_id=envelope.task_id,
            execution_id=envelope.execution_id,
            worker_id=envelope.worker_id,
            phase_id=envelope.phase_id,
            status=DispatchStatus.DISPATCHED.value,
            envelope_metadata=envelope.metadata,
            dispatched_at=_utc_now_iso(),
        )
        self._records[envelope.dispatch_id] = rec
        self._task_to_dispatch[envelope.task_id] = envelope.dispatch_id
        return rec

    def get(self, dispatch_id: str) -> Optional[DispatchRecord]:
        return self._records.get(dispatch_id.strip())

    def get_by_task(self, task_id: str) -> Optional[DispatchRecord]:
        did = self._task_to_dispatch.get(task_id.strip())
        return self._records.get(did) if did else None

    def has_dispatched(self, task_id: str) -> bool:
        return task_id.strip() in self._task_to_dispatch

    def clear(self) -> None:
        self._records.clear()
        self._task_to_dispatch.clear()

    def count(self) -> int:
        return len(self._records)


_GLOBAL_DISPATCH_REGISTRY: Optional[DispatchRegistry] = None


def get_default_dispatch_registry() -> DispatchRegistry:
    global _GLOBAL_DISPATCH_REGISTRY
    if _GLOBAL_DISPATCH_REGISTRY is None:
        _GLOBAL_DISPATCH_REGISTRY = DispatchRegistry()
    return _GLOBAL_DISPATCH_REGISTRY


# =============================================================================
# 6. ExecutionDispatcher: Pure Dispatch Validator & Envelope Builder
# =============================================================================

class ExecutionDispatcher:
    """
    Validates task readiness, resolves workers, audits permissions and connectors,
    and constructs ExecutionEnvelopes without executing work.
    """

    def __init__(
        self,
        registry: Optional[WorkerRegistry] = None,
        dispatch_registry: Optional[DispatchRegistry] = None,
    ):
        self.registry = registry or get_default_registry()
        self.dispatch_registry = dispatch_registry or get_default_dispatch_registry()

    # -------------------------------------------------------------------------
    # Public Dispatch Methods
    # -------------------------------------------------------------------------

    def dispatch_task(
        self,
        task: Task,
        compiled_task_plan: Optional[CompiledTaskPlan] = None,
        connected_connectors: Optional[Set[str] | List[str]] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        is_approved: bool = False,
        dry_run: bool = False,
    ) -> DispatchResult:
        """
        Validates a task and compiles an ExecutionEnvelope if legally dispatchable.
        """
        tid = task.task_id.strip() if task and task.task_id else "unknown_task"
        wid = task.worker_id.strip() if task and task.worker_id else "unknown_worker"
        eid = task.execution_id.strip() if task and task.execution_id else "unknown_exec"

        # 1. Defense-in-depth secret detection in task inputs/metadata
        if detect_unredacted_secrets(task.inputs) or detect_unredacted_secrets(task.metadata):
            return DispatchResult(
                status=DispatchStatus.REJECTED.value,
                task_id=tid,
                worker_id=wid,
                execution_id=eid,
                reason="Dispatch rejected: unredacted sensitive credentials detected in task payload.",
                validation_errors=["Security violation: Plaintext credential tokens detected."],
            )

        # 2. Structural identity validation
        validation_errors: List[str] = []
        if not task.task_id:
            validation_errors.append("Task is missing 'task_id'.")
        if not task.execution_id:
            validation_errors.append("Task is missing 'execution_id'.")
        if not task.project_id:
            validation_errors.append("Task is missing 'project_id'.")
        if not task.objective or not task.objective.strip():
            validation_errors.append("Task is missing 'objective'.")
        if not task.expected_output:
            validation_errors.append("Task is missing 'expected_output' contract.")

        phase_id = task.metadata.get("phase_id", "")
        if not phase_id:
            validation_errors.append("Task metadata is missing 'phase_id'.")

        if validation_errors:
            return DispatchResult(
                status=DispatchStatus.INVALID.value,
                task_id=tid,
                worker_id=wid,
                execution_id=eid,
                reason=f"Task schema validation failed: {'; '.join(validation_errors)}",
                validation_errors=validation_errors,
            )

        # 3. Duplicate dispatch check (idempotency guard)
        if not dry_run and self.dispatch_registry.has_dispatched(task.task_id):
            return DispatchResult(
                status=DispatchStatus.REJECTED.value,
                task_id=task.task_id,
                worker_id=wid,
                execution_id=task.execution_id,
                reason=f"Task '{task.task_id}' has already been dispatched.",
                validation_errors=["Duplicate dispatch rejected."],
            )

        # 4. Worker resolution in registry
        worker_desc = self.registry.get(task.worker_id)
        if not worker_desc:
            return DispatchResult(
                status=DispatchStatus.INVALID.value,
                task_id=task.task_id,
                worker_id=task.worker_id,
                execution_id=task.execution_id,
                reason=f"Worker '{task.worker_id}' is not registered in WorkerRegistry.",
                validation_errors=[f"Unregistered worker: {task.worker_id}"],
            )

        if worker_desc.availability_status != "AVAILABLE":
            return DispatchResult(
                status=DispatchStatus.BLOCKED.value,
                task_id=task.task_id,
                worker_id=worker_desc.worker_id,
                execution_id=task.execution_id,
                reason=f"Worker '{worker_desc.worker_id}' is currently unavailable ({worker_desc.availability_status}).",
                validation_errors=[f"Worker unavailable: {worker_desc.availability_status}"],
            )

        # 5. Dependency check via compiled_task_plan
        if compiled_task_plan:
            # Check if task is marked WAITING, BLOCKED, or INVALID in the plan
            if task.task_id in compiled_task_plan.waiting_tasks:
                return DispatchResult(
                    status=DispatchStatus.BLOCKED.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=f"Task '{task.task_id}' has unfulfilled prerequisite dependencies.",
                    validation_errors=[f"Unfulfilled dependencies: {task.dependencies}"],
                )
            if task.task_id in compiled_task_plan.blocked_tasks:
                return DispatchResult(
                    status=DispatchStatus.BLOCKED.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=task.metadata.get("blocked_reason", f"Task '{task.task_id}' is blocked."),
                    validation_errors=["Task is in BLOCKED state."],
                )
            if task.task_id in compiled_task_plan.invalid_tasks:
                return DispatchResult(
                    status=DispatchStatus.INVALID.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=f"Task '{task.task_id}' is marked INVALID in CompiledTaskPlan.",
                    validation_errors=["Task is in INVALID state."],
                )

        # 6. Connector validation
        task_connectors = task.metadata.get("required_connectors") or worker_desc.required_connectors
        if task_connectors:
            connected_set: Set[str] = {c.lower() for c in (connected_connectors or set())}
            missing_conns = [c for c in task_connectors if c.lower() not in connected_set]
            if missing_conns:
                return DispatchResult(
                    status=DispatchStatus.BLOCKED.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=f"Required connectors missing: {', '.join(missing_conns)}.",
                    validation_errors=[f"Missing connector: {c}" for c in missing_conns],
                )

        # 7. Permission validation
        task_permissions = task.permissions or worker_desc.permissions
        if task_permissions and authorized_permissions is not None:
            auth_set: Set[str] = {p.lower() for p in authorized_permissions}
            denied_perms = [p for p in task_permissions if p.lower() not in auth_set]
            if denied_perms:
                return DispatchResult(
                    status=DispatchStatus.BLOCKED.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=f"Permissions denied: {', '.join(denied_perms)}.",
                    validation_errors=[f"Denied permission: {p}" for p in denied_perms],
                )

        # 8. Approval boundary validation
        requires_approval = (
            any("approval_required" in p.lower() for p in task_permissions)
            or task.metadata.get("approval_required") is True
            or any("approval_required" in p.lower() for p in worker_desc.permissions)
        )
        approval_status = "NOT_REQUIRED"
        if requires_approval:
            if not is_approved:
                return DispatchResult(
                    status=DispatchStatus.BLOCKED.value,
                    task_id=task.task_id,
                    worker_id=worker_desc.worker_id,
                    execution_id=task.execution_id,
                    reason=f"Task '{task.task_id}' requires explicit approval before dispatch.",
                    validation_errors=["Pending approval authorization."],
                    metadata={"approval_required": True},
                )
            approval_status = "APPROVED"

        # 9. Build Deterministic Dispatch ID & ExecutionEnvelope
        dispatch_id = self._generate_dispatch_id(task.execution_id, task.task_id)

        envelope = ExecutionEnvelope(
            dispatch_id=dispatch_id,
            execution_id=task.execution_id,
            task_id=task.task_id,
            project_id=task.project_id or "",
            worker_id=worker_desc.worker_id,
            phase_id=phase_id,
            objective=task.objective,
            inputs=_sanitize_dict_secrets(task.inputs),
            expected_output=_sanitize_dict_secrets(task.expected_output),
            permissions=list(task_permissions),
            required_connectors=list(task_connectors),
            approval_status=approval_status,
            metadata=_sanitize_dict_secrets(task.metadata),
            created_at=_utc_now_iso(),
        )

        # 10. Register dispatch if not dry-run
        if not dry_run:
            self.dispatch_registry.register(envelope)
            task.metadata["dispatch_status"] = DispatchStatus.DISPATCHED.value
            task.metadata["dispatch_id"] = dispatch_id

        return DispatchResult(
            status=DispatchStatus.DISPATCHED.value,
            task_id=task.task_id,
            worker_id=worker_desc.worker_id,
            execution_id=task.execution_id,
            dispatch_id=dispatch_id,
            envelope=envelope,
            reason=f"Task successfully validated and dispatched to envelope {dispatch_id} (dry_run={dry_run}).",
            metadata={
                "dry_run": dry_run,
                "approval_status": approval_status,
                "worker_role": worker_desc.role,
            },
        )

    def dispatch_ready_tasks(
        self,
        compiled_task_plan: CompiledTaskPlan,
        connected_connectors: Optional[Set[str] | List[str]] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        approved_task_ids: Optional[Set[str] | List[str]] = None,
        dry_run: bool = False,
    ) -> List[DispatchResult]:
        """
        Dispatches all tasks marked READY in a CompiledTaskPlan independently and sequentially.
        """
        results: List[DispatchResult] = []
        approved_set: Set[str] = {t.strip() for t in (approved_task_ids or set())}

        ready_tasks = compiled_task_plan.get_ready_tasks()
        for task in ready_tasks:
            is_approved = task.task_id in approved_set
            res = self.dispatch_task(
                task=task,
                compiled_task_plan=compiled_task_plan,
                connected_connectors=connected_connectors,
                authorized_permissions=authorized_permissions,
                is_approved=is_approved,
                dry_run=dry_run,
            )
            results.append(res)

        return results

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _generate_dispatch_id(self, execution_id: str, task_id: str) -> str:
        """
        Constructs a deterministic dispatch identifier.
        """
        clean_eid = execution_id.replace("exec_", "").replace("-", "_").lower()
        clean_tid = task_id.replace("task_", "").replace("-", "_").lower()
        return f"dispatch_{clean_eid}_{clean_tid}"
