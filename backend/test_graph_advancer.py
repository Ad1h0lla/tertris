"""
Unit Tests for Workforce Engine — Stage 5C: Graph Advancer
===========================================================

Tests:
1. Linear DAG advancement (A -> B -> C):
   - A succeeds -> B READY, C WAITING
   - B succeeds -> C READY
2. Fan-out DAG advancement (A -> B, C, D):
   - A succeeds -> B, C, D all become READY
3. Fan-in DAG advancement (A, B, C -> D):
   - A succeeds, B WAITING, C WAITING -> D remains WAITING
   - A, B succeed, C WAITING -> D remains WAITING
   - A, B, C all succeed -> D becomes READY
4. Failure propagation:
   - Upstream failure blocks direct dependents (WAITING -> BLOCKED)
   - Fan-in with one failure blocks downstream dependent (A ok, B ok, C failed -> D BLOCKED)
5. Idempotency & Determinism:
   - Advancing the graph repeatedly with identical inputs yields identical state
6. Pure State Machine isolation:
   - GraphAdvancer never dispatches or executes tasks
   - Newly ready tasks remain unexecuted (state change only)
7. Serialization round-trip of GraphAdvancementResult
"""

import pytest

from orchestration.graph_advancer import (
    GraphAdvancer,
    GraphAdvancementResult,
    TaskState,
)
from orchestration.task_assignment import CompiledTaskPlan
from orchestration.worker_contract import Task


def _make_task(task_id: str, deps: list[str] = None, phase_id: str = "phase_1") -> Task:
    return Task(
        task_id=task_id,
        worker_id=f"worker_{task_id}",
        phase_id=phase_id,
        objective=f"Objective for {task_id}",
        dependencies=deps or [],
        inputs={},
        permissions=["read", "write"],
    )


def _make_plan(tasks: list[Task]) -> CompiledTaskPlan:
    deps_map = {t.task_id: t.dependencies for t in tasks}
    # Initial readiness: tasks with no dependencies are READY, others WAITING
    ready = [t.task_id for t in tasks if not t.dependencies]
    waiting = [t.task_id for t in tasks if t.dependencies]
    return CompiledTaskPlan(
        project_id="proj_test_01",
        execution_id="exec_test_01",
        tasks=tasks,
        ready_tasks=ready,
        waiting_tasks=waiting,
        blocked_tasks=[],
        task_dependencies=deps_map,
    )


# =============================================================================
# 1. Linear DAG Advancement Tests (A -> B -> C)
# =============================================================================

class TestLinearDagAdvancement:
    def test_linear_dag_progression(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        tC = _make_task("task_C", deps=["task_B"])
        plan = _make_plan([tA, tB, tC])

        advancer = GraphAdvancer()

        # Step 1: Initial state
        assert plan.ready_tasks == ["task_A"]
        assert set(plan.waiting_tasks) == {"task_B", "task_C"}

        # Step 2: Task A succeeds
        res1 = advancer.advance_graph(plan, completed_task_ids=["task_A"])
        assert "task_B" in res1.newly_ready_tasks
        assert "task_B" in plan.ready_tasks
        assert "task_C" in plan.waiting_tasks
        assert "task_A" not in plan.ready_tasks  # A is completed

        # Step 3: Task B succeeds
        res2 = advancer.advance_graph(plan, completed_task_ids=["task_A", "task_B"])
        assert "task_C" in res2.newly_ready_tasks
        assert "task_C" in plan.ready_tasks
        assert len(plan.waiting_tasks) == 0


# =============================================================================
# 2. Fan-Out DAG Advancement Tests (A -> B, C, D)
# =============================================================================

class TestFanOutDagAdvancement:
    def test_fan_out_all_children_become_ready(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        tC = _make_task("task_C", deps=["task_A"])
        tD = _make_task("task_D", deps=["task_A"])
        plan = _make_plan([tA, tB, tC, tD])

        advancer = GraphAdvancer()

        # A completes successfully
        res = advancer.advance_graph(plan, completed_task_ids=["task_A"])

        assert set(res.newly_ready_tasks) == {"task_B", "task_C", "task_D"}
        assert set(plan.ready_tasks) == {"task_B", "task_C", "task_D"}
        assert len(plan.waiting_tasks) == 0
        assert len(plan.blocked_tasks) == 0


# =============================================================================
# 3. Fan-In DAG Advancement Tests (A, B, C -> D)
# =============================================================================

class TestFanInDagAdvancement:
    def test_fan_in_waits_for_every_dependency(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=[])
        tC = _make_task("task_C", deps=[])
        tD = _make_task("task_D", deps=["task_A", "task_B", "task_C"])
        plan = _make_plan([tA, tB, tC, tD])

        advancer = GraphAdvancer()

        # Initial: A, B, C READY; D WAITING
        assert set(plan.ready_tasks) == {"task_A", "task_B", "task_C"}
        assert plan.waiting_tasks == ["task_D"]

        # Only A completes
        res1 = advancer.advance_graph(plan, completed_task_ids=["task_A"])
        assert "task_D" not in res1.newly_ready_tasks
        assert "task_D" in plan.waiting_tasks

        # A and B complete, C still pending
        res2 = advancer.advance_graph(plan, completed_task_ids=["task_A", "task_B"])
        assert "task_D" not in res2.newly_ready_tasks
        assert "task_D" in plan.waiting_tasks

        # All A, B, C complete -> D finally unlocks
        res3 = advancer.advance_graph(plan, completed_task_ids=["task_A", "task_B", "task_C"])
        assert "task_D" in res3.newly_ready_tasks
        assert plan.ready_tasks == ["task_D"]
        assert len(plan.waiting_tasks) == 0


# =============================================================================
# 4. Failure Propagation Tests
# =============================================================================

class TestFailurePropagation:
    def test_linear_failure_blocks_downstream(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        tC = _make_task("task_C", deps=["task_B"])
        plan = _make_plan([tA, tB, tC])

        advancer = GraphAdvancer()

        # Task A fails
        res = advancer.advance_graph(plan, failed_task_ids=["task_A"])

        assert "task_B" in res.newly_blocked_tasks
        assert "task_B" in plan.blocked_tasks
        assert "task_B" not in plan.ready_tasks
        # C also cascades to blocked
        assert "task_C" in plan.blocked_tasks
        assert len(plan.ready_tasks) == 0

    def test_fan_in_single_failure_blocks_downstream(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=[])
        tC = _make_task("task_C", deps=[])
        tD = _make_task("task_D", deps=["task_A", "task_B", "task_C"])
        plan = _make_plan([tA, tB, tC, tD])

        advancer = GraphAdvancer()

        # A and B succeeded, but C failed
        res = advancer.advance_graph(
            plan,
            completed_task_ids=["task_A", "task_B"],
            failed_task_ids=["task_C"],
        )

        assert "task_D" in res.newly_blocked_tasks
        assert "task_D" in plan.blocked_tasks
        assert "task_D" not in plan.ready_tasks
        assert len(plan.waiting_tasks) == 0


# =============================================================================
# 5. Determinism & Idempotency Tests
# =============================================================================

class TestDeterminismAndIdempotency:
    def test_repeated_advancement_is_idempotent(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        plan = _make_plan([tA, tB])

        advancer = GraphAdvancer()

        res1 = advancer.advance_graph(plan, completed_task_ids=["task_A"])
        assert "task_B" in res1.newly_ready_tasks
        assert plan.ready_tasks == ["task_B"]

        # Run again with same inputs
        res2 = advancer.advance_graph(plan, completed_task_ids=["task_A"])
        assert plan.ready_tasks == ["task_B"]
        assert len(plan.waiting_tasks) == 0
        assert len(plan.blocked_tasks) == 0


# =============================================================================
# 6. Zero Execution Isolation & Round-Trip Tests
# =============================================================================

class TestGraphAdvancerIsolationAndSerialization:
    def test_ready_tasks_are_not_executed(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        plan = _make_plan([tA, tB])

        advancer = GraphAdvancer()
        res = advancer.advance_graph(plan, completed_task_ids=["task_A"])

        # GraphAdvancer only altered state metadata; it did not execute task_B
        assert "task_B" in res.newly_ready_tasks
        assert plan.ready_tasks == ["task_B"]
        # task_B remains in READY state, never dispatched by GraphAdvancer
        assert res.task_states["task_B"] == TaskState.READY.value

    def test_graph_advancer_never_invokes_runtime_or_dispatcher(self, monkeypatch):
        # Ensure any attempt to call WorkerRuntime or ExecutionDispatcher raises error
        import orchestration.worker_runtime as wr
        import orchestration.execution_dispatcher as ed

        def forbidden_runtime_call(*args, **kwargs):
            raise AssertionError("WorkerRuntime was invoked by GraphAdvancer!")

        def forbidden_dispatcher_call(*args, **kwargs):
            raise AssertionError("ExecutionDispatcher was invoked by GraphAdvancer!")

        monkeypatch.setattr(wr.WorkerRuntime, "execute_envelope", forbidden_runtime_call)
        monkeypatch.setattr(ed.ExecutionDispatcher, "dispatch_task", forbidden_dispatcher_call)

        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        plan = _make_plan([tA, tB])

        advancer = GraphAdvancer()
        res = advancer.advance_graph(plan, completed_task_ids=["task_A"])
        assert "task_B" in res.newly_ready_tasks

    def test_advancement_result_serialization_roundtrip(self):
        tA = _make_task("task_A", deps=[])
        tB = _make_task("task_B", deps=["task_A"])
        plan = _make_plan([tA, tB])

        advancer = GraphAdvancer()
        res = advancer.advance_graph(plan, completed_task_ids=["task_A"])

        data = res.to_dict()
        assert isinstance(data, dict)
        reconstructed = GraphAdvancementResult.from_dict(data)

        assert reconstructed.newly_ready_tasks == res.newly_ready_tasks
        assert reconstructed.completed_tasks == res.completed_tasks
        assert reconstructed.task_states == res.task_states
