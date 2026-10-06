"""
Tetris — Workforce Engine: Graph Advancer (Stage 5C)
====================================================

Re-evaluates DAG dependencies and task readiness states across a CompiledTaskPlan
upon task completion or failure:

1. TaskState (WAITING, READY, RUNNING, COMPLETED, FAILED, BLOCKED, INVALID)
2. GraphAdvancementResult (Detailed delta audit of newly ready, waiting, or blocked tasks)
3. GraphAdvancer (Pure topological state machine for DAG dependency resolution)

Architectural Rules:
- Pure State Machine: Evaluates dependency states ONLY. Does NOT execute or dispatch workers.
- Linear, Fan-In, and Fan-Out: Unlocks downstream tasks ONLY when ALL prerequisites succeed.
- Failure Propagation: Blocks downstream tasks if any required prerequisite fails.
- Idempotent & Deterministic: Running multiple advancement cycles with the same inputs produces identical state.
- Zero Side-Effects: Does not call WorkerRuntime, ExecutionDispatcher, or external APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from orchestration.project_context import _sanitize_dict_secrets
from orchestration.task_assignment import CompiledTaskPlan, TaskReadiness

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. TaskState: Canonical Task Graph State Classifications
# =============================================================================

class TaskState(str, Enum):
    """
    State of an individual task inside the CompiledTaskPlan graph.
    """
    WAITING = "WAITING"       # Waiting on unfulfilled upstream dependencies
    READY = "READY"           # All prerequisite dependencies successfully completed
    RUNNING = "RUNNING"       # Currently dispatched/executing in runtime
    COMPLETED = "COMPLETED"   # Execution completed and verification passed
    FAILED = "FAILED"         # Execution or verification failed
    BLOCKED = "BLOCKED"       # Blocked by an upstream dependency failure or missing prerequisites
    INVALID = "INVALID"       # Malformed or unresolvable task


# =============================================================================
# 2. GraphAdvancementResult: State Delta Audit Payload
# =============================================================================

class GraphAdvancementResult(BaseModel):
    """
    Detailed audit of newly unlocked, blocked, and active tasks following DAG re-evaluation.
    """
    newly_ready_tasks: List[str] = Field(default_factory=list)
    newly_blocked_tasks: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    failed_tasks: List[str] = Field(default_factory=list)
    waiting_tasks: List[str] = Field(default_factory=list)
    task_states: Dict[str, str] = Field(default_factory=dict)
    advanced_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GraphAdvancementResult:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 3. GraphAdvancer: Pure DAG Dependency Re-Evaluation Engine
# =============================================================================

class GraphAdvancer:
    """
    Re-evaluates task readiness and dependency completion states across a CompiledTaskPlan.
    """

    def __init__(self):
        pass

    def advance_graph(
        self,
        compiled_task_plan: CompiledTaskPlan,
        completed_task_ids: Optional[Set[str] | List[str]] = None,
        failed_task_ids: Optional[Set[str] | List[str]] = None,
        current_task_states: Optional[Dict[str, str]] = None,
    ) -> GraphAdvancementResult:
        """
        Re-evaluates the DAG dependencies in compiled_task_plan based on completed and failed tasks.
        Updates compiled_task_plan's ready_tasks, waiting_tasks, and blocked_tasks collections.
        """
        completed_set: Set[str] = {t.strip() for t in (completed_task_ids or set())}
        failed_set: Set[str] = {t.strip() for t in (failed_task_ids or set())}
        states: Dict[str, str] = dict(current_task_states or {})

        # 1. Initialize known states from inputs or existing task metadata
        for t in compiled_task_plan.tasks:
            tid = t.task_id
            if tid in completed_set:
                states[tid] = TaskState.COMPLETED.value
            elif tid in failed_set:
                states[tid] = TaskState.FAILED.value
            elif tid not in states:
                # Infer from compiled task plan collections or task metadata
                if tid in compiled_task_plan.ready_tasks:
                    states[tid] = TaskState.READY.value
                elif tid in compiled_task_plan.waiting_tasks:
                    states[tid] = TaskState.WAITING.value
                elif tid in compiled_task_plan.blocked_tasks:
                    states[tid] = TaskState.BLOCKED.value
                elif tid in compiled_task_plan.invalid_tasks:
                    states[tid] = TaskState.INVALID.value
                else:
                    states[tid] = t.metadata.get("readiness_status", TaskState.WAITING.value)

        newly_ready: List[str] = []
        newly_blocked: List[str] = []

        # 2. Re-evaluate dependencies for all non-terminal tasks
        # Iterate until state stabilizes (handling transitive multi-phase cascades)
        changed = True
        while changed:
            changed = False
            for t in compiled_task_plan.tasks:
                tid = t.task_id
                curr_state = states.get(tid, TaskState.WAITING.value)

                # Skip terminal states
                if curr_state in (TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.INVALID.value):
                    continue

                deps = compiled_task_plan.task_dependencies.get(tid, t.dependencies)

                # Check if ANY prerequisite dependency has FAILED or is BLOCKED
                blocked_or_failed_deps = [d for d in deps if states.get(d) in (TaskState.FAILED.value, TaskState.BLOCKED.value)]
                if blocked_or_failed_deps:
                    if curr_state != TaskState.BLOCKED.value:
                        states[tid] = TaskState.BLOCKED.value
                        t.metadata["readiness_status"] = TaskState.BLOCKED.value
                        t.metadata["blocked_reason"] = f"Prerequisite dependency '{blocked_or_failed_deps[0]}' is {states.get(blocked_or_failed_deps[0])}."
                        newly_blocked.append(tid)
                        changed = True
                    continue

                # Check if ALL prerequisite dependencies are COMPLETED
                if deps:
                    all_completed = all(states.get(d) == TaskState.COMPLETED.value for d in deps)
                    if all_completed:
                        if curr_state != TaskState.READY.value:
                            states[tid] = TaskState.READY.value
                            t.metadata["readiness_status"] = TaskState.READY.value
                            if "waiting_on" in t.metadata:
                                del t.metadata["waiting_on"]
                            newly_ready.append(tid)
                            changed = True
                    else:
                        # Still waiting on unfinished dependencies
                        unresolved = [d for d in deps if states.get(d) != TaskState.COMPLETED.value]
                        if curr_state != TaskState.WAITING.value and curr_state != TaskState.BLOCKED.value:
                            states[tid] = TaskState.WAITING.value
                            t.metadata["readiness_status"] = TaskState.WAITING.value
                            t.metadata["waiting_on"] = unresolved
                            changed = True
                else:
                    # Root tasks with no dependencies are READY (unless manually blocked)
                    if curr_state == TaskState.WAITING.value:
                        states[tid] = TaskState.READY.value
                        t.metadata["readiness_status"] = TaskState.READY.value
                        newly_ready.append(tid)
                        changed = True

        # 3. Synchronize CompiledTaskPlan collections
        active_ready = [t.task_id for t in compiled_task_plan.tasks if states.get(t.task_id) == TaskState.READY.value]
        active_waiting = [t.task_id for t in compiled_task_plan.tasks if states.get(t.task_id) == TaskState.WAITING.value]
        active_blocked = [t.task_id for t in compiled_task_plan.tasks if states.get(t.task_id) == TaskState.BLOCKED.value]
        all_completed = [t.task_id for t in compiled_task_plan.tasks if states.get(t.task_id) == TaskState.COMPLETED.value]
        all_failed = [t.task_id for t in compiled_task_plan.tasks if states.get(t.task_id) == TaskState.FAILED.value]

        compiled_task_plan.ready_tasks = active_ready
        compiled_task_plan.waiting_tasks = active_waiting
        compiled_task_plan.blocked_tasks = active_blocked

        return GraphAdvancementResult(
            newly_ready_tasks=newly_ready,
            newly_blocked_tasks=newly_blocked,
            completed_tasks=all_completed,
            failed_tasks=all_failed,
            waiting_tasks=active_waiting,
            task_states=states,
            advanced_at=_utc_now_iso(),
            metadata={
                "total_ready": len(active_ready),
                "total_waiting": len(active_waiting),
                "total_blocked": len(active_blocked),
                "total_completed": len(all_completed),
            },
        )
