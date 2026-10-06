"""
Tetris — Workforce Engine: Workforce Execution Coordinator (Stage 5D)
======================================================================

Orchestrates the canonical closed-loop execution lifecycle across:
- Stage 5A: ExecutionDispatcher
- Stage 5B: WorkerRuntime
- Stage 5C: ContextSynchronizer
- Stage 5C: GraphAdvancer

Execution Cycle:
1. Find next READY task using deterministic ordering.
2. Validate readiness & permissions via ExecutionDispatcher.
3. Halt immediately if human/system approval is required (never auto-approve).
4. Hand ExecutionEnvelope to WorkerRuntime (prepare -> execute -> verify).
5. Synchronize verified deliverables into ProjectContext via ContextSynchronizer.
6. Advance DAG state via GraphAdvancer.
7. Repeat until DAG completion, failure, blocked state, or approval requirement.

Architectural Rules:
- Single-Task Stepping: Executes exactly ONE task at a time (zero uncoordinated concurrency).
- Deterministic Ordering: READY tasks are selected using a stable sort key.
- Strict Pipeline Integrity: Never bypasses ExecutionDispatcher, WorkerRuntime, ContextSync, or GraphAdvancer.
- Never directly invokes BaseWorker instances.
- Zero Automatic Approval: External side-effect actions MUST stop the coordinator until explicitly approved.
- Secret-Safe: Recursively sanitizes all diagnostic and audit payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from orchestration.context_sync import ContextSynchronizer, SyncResult, SyncStatus
from orchestration.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
    get_default_dispatch_registry,
)
from orchestration.graph_advancer import (
    GraphAdvancementResult,
    GraphAdvancer,
    TaskState,
)
from orchestration.project_context import (
    ProjectContext,
    _sanitize_dict_secrets,
)
from orchestration.task_assignment import CompiledTaskPlan
from orchestration.worker_contract import Task
from orchestration.worker_runtime import (
    RuntimeResult,
    RuntimeStatus,
    WorkerRuntime,
    get_default_registry,
    get_default_runtime_registry,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. CoordinatorStatus: Canonical Terminal & Active States
# =============================================================================

class CoordinatorStatus(str, Enum):
    """
    Status of the WorkforceCoordinator execution loop.
    """
    COMPLETED = "COMPLETED"                 # All tasks in the DAG completed and verified
    FAILED = "FAILED"                       # A task failed execution or verification
    BLOCKED = "BLOCKED"                     # DAG is blocked by unmet dependencies or missing connectors
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED" # External action requires human/system authorization
    MAX_STEPS_REACHED = "MAX_STEPS_REACHED" # Loop iteration limit reached
    INVALID = "INVALID"                     # Task configuration or DAG plan is malformed
    IDLE = "IDLE"                           # Coordinator initialized, not running


# =============================================================================
# 2. CoordinatorStepRecord: Audit Trail for Individual Steps
# =============================================================================

class CoordinatorStepRecord(BaseModel):
    """
    Detailed audit record for a single task execution step in the coordinator loop.
    """
    step_number: int
    task_id: str
    worker_id: str
    phase_id: str
    dispatch_status: str
    runtime_status: Optional[str] = None
    verification_status: Optional[str] = None
    sync_status: Optional[str] = None
    artifacts_produced: List[str] = Field(default_factory=list)
    receipts_produced: List[str] = Field(default_factory=list)
    newly_ready_tasks: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


# =============================================================================
# 3. CoordinatorResult: End-of-Run Outcome & Diagnostic Audit
# =============================================================================

class CoordinatorResult(BaseModel):
    """
    Comprehensive outcome and audit payload produced when the coordinator halts.
    """
    status: str  # from CoordinatorStatus
    project_id: str
    execution_id: str
    steps_executed: int = 0
    completed_tasks: List[str] = Field(default_factory=list)
    failed_tasks: List[str] = Field(default_factory=list)
    blocked_tasks: List[str] = Field(default_factory=list)
    pending_approval_task_id: Optional[str] = None
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    reason: str = ""
    errors: List[str] = Field(default_factory=list)
    started_at: str = Field(default_factory=_utc_now_iso)
    completed_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.status == CoordinatorStatus.COMPLETED.value

    @property
    def is_failed(self) -> bool:
        return self.status == CoordinatorStatus.FAILED.value

    @property
    def is_blocked(self) -> bool:
        return self.status == CoordinatorStatus.BLOCKED.value

    @property
    def is_approval_required(self) -> bool:
        return self.status == CoordinatorStatus.APPROVAL_REQUIRED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoordinatorResult:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 4. WorkforceCoordinator: Central Loop Runner Engine
# =============================================================================

class WorkforceCoordinator:
    """
    Executes and coordinates the closed-loop workforce execution pipeline:
    CompiledTaskPlan -> Dispatcher -> WorkerRuntime -> ContextSync -> GraphAdvancer -> Next Task.
    """

    def __init__(
        self,
        dispatcher: Optional[ExecutionDispatcher] = None,
        runtime: Optional[WorkerRuntime] = None,
        context_sync: Optional[ContextSynchronizer] = None,
        graph_advancer: Optional[GraphAdvancer] = None,
    ):
        self.dispatcher = dispatcher or ExecutionDispatcher()
        self.runtime = runtime or WorkerRuntime()
        self.context_sync = context_sync or ContextSynchronizer()
        self.graph_advancer = graph_advancer or GraphAdvancer()

    # -------------------------------------------------------------------------
    # Helper: Deterministic Ready Task Selection
    # -------------------------------------------------------------------------

    def select_next_ready_task(
        self,
        compiled_task_plan: CompiledTaskPlan,
        completed_task_ids: Set[str],
        failed_task_ids: Set[str],
    ) -> Optional[Task]:
        """
        Deterministically selects the next eligible READY task.
        Filters out already completed/failed tasks and sorts deterministically.
        """
        eligible_tids = [
            tid for tid in compiled_task_plan.ready_tasks
            if tid not in completed_task_ids and tid not in failed_task_ids
        ]

        if not eligible_tids:
            return None

        # Deterministic sorting: sort by task_id or original index in plan
        task_order_map = {t.task_id: idx for idx, t in enumerate(compiled_task_plan.tasks)}
        sorted_tids = sorted(eligible_tids, key=lambda tid: (task_order_map.get(tid, 999999), tid))

        target_tid = sorted_tids[0]
        return compiled_task_plan.get_task(target_tid)

    # -------------------------------------------------------------------------
    # Public Execution Loop API
    # -------------------------------------------------------------------------

    def run_workflow(
        self,
        project_context: ProjectContext,
        compiled_task_plan: CompiledTaskPlan,
        connected_connectors: Optional[Set[str] | List[str]] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        approved_task_ids: Optional[Set[str] | List[str]] = None,
        dry_run: bool = False,
        max_steps: Optional[int] = 100,
    ) -> CoordinatorResult:
        """
        Runs the workforce execution loop until DAG completion, failure, blocked graph,
        or approval requirement.
        """
        pid = project_context.project_id if project_context else "unknown_proj"
        eid = project_context.execution_id if project_context else "unknown_exec"
        started_at = _utc_now_iso()

        connectors = connected_connectors
        permissions = authorized_permissions
        approved_tasks = set(approved_task_ids or set())

        completed_task_ids: Set[str] = set()
        failed_task_ids: Set[str] = set()
        step_history: List[CoordinatorStepRecord] = []
        step_count = 0

        # Initial graph alignment (ensures root tasks without deps are marked READY)
        self.graph_advancer.advance_graph(
            compiled_task_plan,
            completed_task_ids=completed_task_ids,
            failed_task_ids=failed_task_ids,
        )

        while True:
            # Check maximum steps safety guard
            if max_steps is not None and step_count >= max_steps:
                return CoordinatorResult(
                    status=CoordinatorStatus.MAX_STEPS_REACHED.value,
                    project_id=pid,
                    execution_id=eid,
                    steps_executed=step_count,
                    completed_tasks=sorted(list(completed_task_ids)),
                    failed_tasks=sorted(list(failed_task_ids)),
                    blocked_tasks=compiled_task_plan.blocked_tasks,
                    step_history=step_history,
                    reason=f"Execution halted: Maximum step limit ({max_steps}) reached.",
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )

            # 1. Deterministically select the next READY task
            current_task = self.select_next_ready_task(
                compiled_task_plan,
                completed_task_ids,
                failed_task_ids,
            )

            # 2. If no READY task is found, evaluate termination state
            if current_task is None:
                # Check if all tasks in the plan are completed
                all_plan_tids = {t.task_id for t in compiled_task_plan.tasks}
                if all_plan_tids and completed_task_ids.issuperset(all_plan_tids):
                    return CoordinatorResult(
                        status=CoordinatorStatus.COMPLETED.value,
                        project_id=pid,
                        execution_id=eid,
                        steps_executed=step_count,
                        completed_tasks=sorted(list(completed_task_ids)),
                        failed_tasks=sorted(list(failed_task_ids)),
                        blocked_tasks=compiled_task_plan.blocked_tasks,
                        step_history=step_history,
                        reason="All tasks in the workflow successfully executed and verified.",
                        started_at=started_at,
                        completed_at=_utc_now_iso(),
                    )

                # Check if there are blocked tasks or unresolved failures
                if compiled_task_plan.blocked_tasks:
                    return CoordinatorResult(
                        status=CoordinatorStatus.BLOCKED.value,
                        project_id=pid,
                        execution_id=eid,
                        steps_executed=step_count,
                        completed_tasks=sorted(list(completed_task_ids)),
                        failed_tasks=sorted(list(failed_task_ids)),
                        blocked_tasks=compiled_task_plan.blocked_tasks,
                        step_history=step_history,
                        reason=f"Workflow halted: Tasks {compiled_task_plan.blocked_tasks} are BLOCKED.",
                        started_at=started_at,
                        completed_at=_utc_now_iso(),
                    )

                if compiled_task_plan.waiting_tasks:
                    return CoordinatorResult(
                        status=CoordinatorStatus.BLOCKED.value,
                        project_id=pid,
                        execution_id=eid,
                        steps_executed=step_count,
                        completed_tasks=sorted(list(completed_task_ids)),
                        failed_tasks=sorted(list(failed_task_ids)),
                        blocked_tasks=compiled_task_plan.blocked_tasks,
                        step_history=step_history,
                        reason=f"Workflow halted: Tasks {compiled_task_plan.waiting_tasks} remain WAITING with no executable READY tasks.",
                        started_at=started_at,
                        completed_at=_utc_now_iso(),
                    )

                # Empty or completed plan
                return CoordinatorResult(
                    status=CoordinatorStatus.COMPLETED.value,
                    project_id=pid,
                    execution_id=eid,
                    steps_executed=step_count,
                    completed_tasks=sorted(list(completed_task_ids)),
                    failed_tasks=sorted(list(failed_task_ids)),
                    blocked_tasks=compiled_task_plan.blocked_tasks,
                    step_history=step_history,
                    reason="Workflow completed with no remaining tasks.",
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )

            # 3. Process the selected READY task
            step_count += 1
            tid = current_task.task_id
            wid = current_task.worker_id
            phase_id = current_task.metadata.get("phase_id", "phase_default")
            is_task_approved = tid in approved_tasks

            # --- Stage 5A: Dispatch ---
            dispatch_res: DispatchResult = self.dispatcher.dispatch_task(
                task=current_task,
                compiled_task_plan=compiled_task_plan,
                connected_connectors=connectors,
                authorized_permissions=permissions,
                is_approved=is_task_approved,
                dry_run=dry_run,
            )

            # Check for Approval Required Gate
            if dispatch_res.status == DispatchStatus.BLOCKED.value and "approval" in dispatch_res.reason.lower():
                step_record = CoordinatorStepRecord(
                    step_number=step_count,
                    task_id=tid,
                    worker_id=wid,
                    phase_id=phase_id,
                    dispatch_status=dispatch_res.status,
                    error=dispatch_res.reason,
                )
                step_history.append(step_record)

                return CoordinatorResult(
                    status=CoordinatorStatus.APPROVAL_REQUIRED.value,
                    project_id=pid,
                    execution_id=eid,
                    steps_executed=step_count,
                    completed_tasks=sorted(list(completed_task_ids)),
                    failed_tasks=sorted(list(failed_task_ids)),
                    blocked_tasks=compiled_task_plan.blocked_tasks,
                    pending_approval_task_id=tid,
                    step_history=step_history,
                    reason=f"Task '{tid}' requires explicit authorization before execution.",
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )

            # Check if dispatch failed for other reasons (missing connectors, denied permissions, invalid schema)
            if not dispatch_res.is_dispatched or dispatch_res.envelope is None:
                failed_task_ids.add(tid)
                adv_res = self.graph_advancer.advance_graph(
                    compiled_task_plan,
                    completed_task_ids=completed_task_ids,
                    failed_task_ids=failed_task_ids,
                )
                step_record = CoordinatorStepRecord(
                    step_number=step_count,
                    task_id=tid,
                    worker_id=wid,
                    phase_id=phase_id,
                    dispatch_status=dispatch_res.status,
                    error=dispatch_res.reason,
                )
                step_history.append(step_record)

                return CoordinatorResult(
                    status=CoordinatorStatus.BLOCKED.value if dispatch_res.status == DispatchStatus.BLOCKED.value else CoordinatorStatus.FAILED.value,
                    project_id=pid,
                    execution_id=eid,
                    steps_executed=step_count,
                    completed_tasks=sorted(list(completed_task_ids)),
                    failed_tasks=sorted(list(failed_task_ids)),
                    blocked_tasks=compiled_task_plan.blocked_tasks,
                    step_history=step_history,
                    reason=f"Dispatch failed for task '{tid}': {dispatch_res.reason}",
                    errors=dispatch_res.validation_errors or [dispatch_res.reason],
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )

            # --- Stage 5B: Worker Runtime Execution ---
            envelope = dispatch_res.envelope
            runtime_res: RuntimeResult = self.runtime.execute_envelope(envelope, dry_run=dry_run)

            # --- Handle Dry-Run Mode ---
            if dry_run:
                is_step_successful = (
                    runtime_res.status == RuntimeStatus.DRY_RUN.value
                    or runtime_res.status == RuntimeStatus.COMPLETED.value
                )
                if is_step_successful:
                    completed_task_ids.add(tid)
                else:
                    failed_task_ids.add(tid)

                adv_res = self.graph_advancer.advance_graph(
                    compiled_task_plan,
                    completed_task_ids=completed_task_ids,
                    failed_task_ids=failed_task_ids,
                )
                step_record = CoordinatorStepRecord(
                    step_number=step_count,
                    task_id=tid,
                    worker_id=wid,
                    phase_id=phase_id,
                    dispatch_status=dispatch_res.status,
                    runtime_status=runtime_res.status,
                    verification_status="DRY_RUN",
                    sync_status="DRY_RUN",
                    newly_ready_tasks=adv_res.newly_ready_tasks,
                    error=runtime_res.error if not is_step_successful else None,
                )
                step_history.append(step_record)

                if not is_step_successful:
                    return CoordinatorResult(
                        status=CoordinatorStatus.FAILED.value,
                        project_id=pid,
                        execution_id=eid,
                        steps_executed=step_count,
                        completed_tasks=sorted(list(completed_task_ids)),
                        failed_tasks=sorted(list(failed_task_ids)),
                        blocked_tasks=compiled_task_plan.blocked_tasks,
                        step_history=step_history,
                        reason=f"Dry-run execution failed for task '{tid}': {runtime_res.error}",
                        errors=[runtime_res.error or "Dry-run failed"],
                        started_at=started_at,
                        completed_at=_utc_now_iso(),
                    )
                continue

            # --- Stage 5C: Context Synchronization ---
            sync_res: SyncResult = self.context_sync.apply_result(
                project_context=project_context,
                runtime_result=runtime_res,
                phase_id=phase_id,
            )

            # Evaluate execution outcome
            is_step_successful = (
                runtime_res.status == RuntimeStatus.COMPLETED.value
                and runtime_res.verification_result is not None
                and runtime_res.verification_result.verified is True
                and sync_res.status == SyncStatus.SYNCED.value
            )

            if is_step_successful:
                completed_task_ids.add(tid)
            else:
                failed_task_ids.add(tid)

            # --- Stage 5C: Graph Advancement ---
            adv_res = self.graph_advancer.advance_graph(
                compiled_task_plan,
                completed_task_ids=completed_task_ids,
                failed_task_ids=failed_task_ids,
            )

            # Record step in audit trail
            step_record = CoordinatorStepRecord(
                step_number=step_count,
                task_id=tid,
                worker_id=wid,
                phase_id=phase_id,
                dispatch_status=dispatch_res.status,
                runtime_status=runtime_res.status,
                verification_status=runtime_res.verification_result.status if runtime_res.verification_result else "NONE",
                sync_status=sync_res.status,
                artifacts_produced=sync_res.artifacts_created,
                receipts_produced=sync_res.receipts_created,
                newly_ready_tasks=adv_res.newly_ready_tasks,
                error=runtime_res.error or (sync_res.reason if not sync_res.is_synced else None),
            )
            step_history.append(step_record)

            # If task failed execution or verification, halt coordinator loop
            if not is_step_successful:
                return CoordinatorResult(
                    status=CoordinatorStatus.FAILED.value,
                    project_id=pid,
                    execution_id=eid,
                    steps_executed=step_count,
                    completed_tasks=sorted(list(completed_task_ids)),
                    failed_tasks=sorted(list(failed_task_ids)),
                    blocked_tasks=compiled_task_plan.blocked_tasks,
                    step_history=step_history,
                    reason=f"Task '{tid}' failed execution or verification: {runtime_res.error or sync_res.reason}",
                    errors=[runtime_res.error or sync_res.reason],
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )
