"""
Unit Tests for Workforce Engine — Stage 2: Phase ↔ Worker Architecture Foundation
================================================================================

Tests:
1. Phase creation
2. Phase lifecycle
3. Worker assignment
4. Multiple workers inside one phase
5. Same worker type assigned to multiple phases
6. Phase dependencies
7. Arbitrary N phases
8. Linear dependency (A -> B)
9. Branching dependency (A -> B + C)
10. Fan-in dependency (B + C -> D)
11. Serialization / Deserialization
12. Invalid dependency detection
13. Circular dependency detection
14. Backward compatibility with existing phase representation
"""

import json
import pytest

from orchestration.phase_contract import (
    PhaseStatus,
    WorkerAssignment,
    Phase,
    ProjectWorkflow,
    DependencyGraphError,
    validate_phase_dependencies,
    compute_topological_order,
    from_legacy_phase_map,
)


# =============================================================================
# 1. Phase Creation Tests
# =============================================================================

class TestPhaseCreation:
    def test_phase_initialization_with_defaults(self):
        phase = Phase(
            phase_id="phase_build",
            phase_number=1,
            name="Build / Coding",
            description="Core software synthesis",
            purpose="Generate executable code",
            entry_requirements=["specification"],
            exit_requirements=["executable_code"],
        )
        assert phase.phase_id == "phase_build"
        assert phase.phase_number == 1
        assert phase.name == "Build / Coding"
        assert phase.status == PhaseStatus.PLANNED
        assert phase.dependencies == []
        assert phase.workers == []
        assert phase.entry_requirements == ["specification"]
        assert phase.exit_requirements == ["executable_code"]
        assert phase.created_at is not None


# =============================================================================
# 2. Phase Lifecycle Tests
# =============================================================================

class TestPhaseLifecycle:
    def test_all_lifecycle_states_exist(self):
        expected_states = {
            "PLANNED",
            "READY",
            "RUNNING",
            "BLOCKED",
            "WAITING",
            "COMPLETED",
            "FAILED",
            "SKIPPED",
            "CANCELLED",
        }
        actual_states = {s.value for s in PhaseStatus}
        assert actual_states == expected_states

    def test_terminal_states(self):
        assert PhaseStatus.is_terminal(PhaseStatus.COMPLETED) is True
        assert PhaseStatus.is_terminal(PhaseStatus.FAILED) is True
        assert PhaseStatus.is_terminal(PhaseStatus.SKIPPED) is True
        assert PhaseStatus.is_terminal(PhaseStatus.CANCELLED) is True
        assert PhaseStatus.is_terminal(PhaseStatus.RUNNING) is False
        assert PhaseStatus.is_terminal(PhaseStatus.PLANNED) is False

    def test_valid_lifecycle_transitions(self):
        # Forward happy path: PLANNED -> READY -> RUNNING -> COMPLETED
        assert PhaseStatus.PLANNED.can_transition_to(PhaseStatus.READY) is True
        assert PhaseStatus.READY.can_transition_to(PhaseStatus.RUNNING) is True
        assert PhaseStatus.RUNNING.can_transition_to(PhaseStatus.COMPLETED) is True

        # Waiting / Blocked / Failure paths
        assert PhaseStatus.READY.can_transition_to(PhaseStatus.WAITING) is True
        assert PhaseStatus.RUNNING.can_transition_to(PhaseStatus.FAILED) is True
        assert PhaseStatus.RUNNING.can_transition_to(PhaseStatus.BLOCKED) is True

        # Retry from failed/blocked
        assert PhaseStatus.FAILED.can_transition_to(PhaseStatus.READY) is True
        assert PhaseStatus.BLOCKED.can_transition_to(PhaseStatus.READY) is True

    def test_invalid_lifecycle_transitions(self):
        # Cannot jump from PLANNED directly to COMPLETED
        assert PhaseStatus.PLANNED.can_transition_to(PhaseStatus.COMPLETED) is False

        # Cannot transition out of terminal COMPLETED
        assert PhaseStatus.COMPLETED.can_transition_to(PhaseStatus.RUNNING) is False

        # Cannot transition out of CANCELLED
        assert PhaseStatus.CANCELLED.can_transition_to(PhaseStatus.READY) is False


# =============================================================================
# 3. Worker Assignment Tests
# =============================================================================

class TestWorkerAssignment:
    def test_worker_assignment_creation(self):
        assignment = WorkerAssignment(
            worker_id="worker_reddit_01",
            phase_id="phase_marketing",
            role="reddit_specialist",
            capabilities=["reddit:search", "reddit:reply"],
            required_connectors=["redditapis"],
            permissions=["network:write"],
            task_ids=["task_001", "task_002"],
        )
        assert assignment.worker_id == "worker_reddit_01"
        assert assignment.phase_id == "phase_marketing"
        assert assignment.role == "reddit_specialist"
        assert "redditapis" in assignment.required_connectors
        assert "task_001" in assignment.task_ids


# =============================================================================
# 4. Multiple Workers Inside One Phase
# =============================================================================

class TestMultipleWorkersInsideOnePhase:
    def test_phase_holds_multiple_distinct_workers(self):
        phase = Phase(phase_id="phase_build", name="Build Phase")

        w1 = WorkerAssignment(worker_id="w_code", phase_id="phase_build", role="code_builder")
        w2 = WorkerAssignment(worker_id="w_ui", phase_id="phase_build", role="ui_developer")
        w3 = WorkerAssignment(worker_id="w_db", phase_id="phase_build", role="db_architect")

        phase.add_worker(w1)
        phase.add_worker(w2)
        phase.add_worker(w3)

        assert len(phase.workers) == 3
        assert phase.has_worker("w_code") is True
        assert phase.has_worker("w_ui") is True
        assert phase.has_worker("w_db") is True
        assert phase.get_worker("w_ui").role == "ui_developer"


# =============================================================================
# 5. Same Worker Type Assigned to Multiple Phases
# =============================================================================

class TestSameWorkerInMultiplePhases:
    def test_same_worker_type_assigned_across_phases(self):
        phase_sim = Phase(phase_id="phase_simulation", name="Simulation Phase")
        phase_ops = Phase(phase_id="phase_health", name="Health Operations Phase")

        # QA worker in simulation
        qa_sim = WorkerAssignment(
            worker_id="worker_qa_primary",
            phase_id="phase_simulation",
            role="payload_simulator",
            capabilities=["simulate:stress"],
        )
        # Same worker in operational health
        qa_ops = WorkerAssignment(
            worker_id="worker_qa_primary",
            phase_id="phase_health",
            role="runtime_health_monitor",
            capabilities=["monitor:synthetic"],
        )

        phase_sim.add_worker(qa_sim)
        phase_ops.add_worker(qa_ops)

        assert phase_sim.get_worker("worker_qa_primary").role == "payload_simulator"
        assert phase_ops.get_worker("worker_qa_primary").role == "runtime_health_monitor"
        assert phase_sim.get_worker("worker_qa_primary").phase_id == "phase_simulation"
        assert phase_ops.get_worker("worker_qa_primary").phase_id == "phase_health"


# =============================================================================
# 6. Phase Dependencies Representation
# =============================================================================

class TestPhaseDependencies:
    def test_phase_dependency_recording(self):
        wf = ProjectWorkflow(project_id="proj_test_01")
        p1 = Phase(phase_id="phase_1", name="Phase 1", dependencies=[])
        p2 = Phase(phase_id="phase_2", name="Phase 2", dependencies=["phase_1"])

        wf.add_phase(p1)
        wf.add_phase(p2)

        assert wf.dependencies["phase_2"] == ["phase_1"]
        assert wf.dependencies.get("phase_1") == []


# =============================================================================
# 7. Arbitrary N Phases Support
# =============================================================================

class TestArbitraryNPhases:
    def test_workflow_supports_n_custom_phases(self):
        wf = ProjectWorkflow(project_id="proj_custom_n")
        custom_phase_names = [
            "research",
            "specification",
            "architecture",
            "build",
            "simulation",
            "compliance",
            "marketing",
            "deployment",
        ]

        prev_id = None
        for idx, name in enumerate(custom_phase_names):
            pid = f"phase_{name}"
            deps = [prev_id] if prev_id else []
            phase = Phase(
                phase_id=pid,
                phase_number=idx + 1,
                name=name.capitalize(),
                dependencies=deps,
            )
            wf.add_phase(phase)
            prev_id = pid

        assert len(wf.phases) == 8
        order = wf.get_topological_order()
        assert len(order) == 8
        assert order[0] == "phase_research"
        assert order[-1] == "phase_deployment"


# =============================================================================
# 8. Linear Dependency (A -> B)
# =============================================================================

class TestLinearDependency:
    def test_linear_a_to_b(self):
        wf = ProjectWorkflow(project_id="proj_linear")
        pA = Phase(phase_id="A", name="Phase A", dependencies=[])
        pB = Phase(phase_id="B", name="Phase B", dependencies=["A"])

        wf.add_phase(pA)
        wf.add_phase(pB)

        order = wf.get_topological_order()
        assert order == ["A", "B"]

        # Readiness tracking
        ready_initially = wf.get_ready_phases()
        assert [p.phase_id for p in ready_initially] == ["A"]

        # When A completes, B becomes ready
        wf.completed_phases.append("A")
        ready_after_a = wf.get_ready_phases()
        assert [p.phase_id for p in ready_after_a] == ["B"]


# =============================================================================
# 9. Branching Dependency (A -> B + C)
# =============================================================================

class TestBranchingDependency:
    def test_branching_a_to_b_and_c(self):
        wf = ProjectWorkflow(project_id="proj_branch")
        pA = Phase(phase_id="A", name="Phase A", dependencies=[])
        pB = Phase(phase_id="B", name="Phase B", dependencies=["A"])
        pC = Phase(phase_id="C", name="Phase C", dependencies=["A"])

        wf.add_phase(pA)
        wf.add_phase(pB)
        wf.add_phase(pC)

        order = wf.get_topological_order()
        assert order[0] == "A"
        assert set(order[1:]) == {"B", "C"}

        # Completing A unlocks both B and C
        wf.completed_phases.append("A")
        ready = wf.get_ready_phases()
        assert {p.phase_id for p in ready} == {"B", "C"}


# =============================================================================
# 10. Fan-in Dependency (B + C -> D)
# =============================================================================

class TestFanInDependency:
    def test_fan_in_b_and_c_to_d(self):
        wf = ProjectWorkflow(project_id="proj_fanin")
        pA = Phase(phase_id="A", name="Phase A", dependencies=[])
        pB = Phase(phase_id="B", name="Phase B", dependencies=["A"])
        pC = Phase(phase_id="C", name="Phase C", dependencies=["A"])
        pD = Phase(phase_id="D", name="Phase D", dependencies=["B", "C"])

        wf.add_phase(pA)
        wf.add_phase(pB)
        wf.add_phase(pC)
        wf.add_phase(pD)

        order = wf.get_topological_order()
        assert order[0] == "A"
        assert order[-1] == "D"
        assert set(order[1:3]) == {"B", "C"}

        # When only B is complete, D is NOT ready
        wf.completed_phases = ["A", "B"]
        ready = wf.get_ready_phases()
        assert [p.phase_id for p in ready] == ["C"]

        # When B and C are both complete, D is ready
        wf.completed_phases = ["A", "B", "C"]
        ready_final = wf.get_ready_phases()
        assert [p.phase_id for p in ready_final] == ["D"]


# =============================================================================
# 11. Serialization / Deserialization Tests
# =============================================================================

class TestSerializationDeserialization:
    def test_workflow_json_roundtrip(self):
        wf = ProjectWorkflow.create_default_lifecycle(
            project_id="proj_roundtrip_100",
            execution_id="exec_roundtrip_200",
        )

        d = wf.to_dict()
        assert d["project_id"] == "proj_roundtrip_100"
        assert "phase_build" in d["phases"]
        assert len(d["phases"]["phase_build"]["workers"]) == 3

        json_str = json.dumps(d)
        reloaded_dict = json.loads(json_str)
        reloaded_wf = ProjectWorkflow.from_dict(reloaded_dict)

        assert reloaded_wf.project_id == wf.project_id
        assert reloaded_wf.execution_id == wf.execution_id
        assert len(reloaded_wf.phases) == len(wf.phases)
        assert reloaded_wf.get_phase("phase_marketing").has_worker("worker_reddit") is True


# =============================================================================
# 12. Invalid Dependency Detection
# =============================================================================

class TestInvalidDependencyDetection:
    def test_missing_prerequisite_phase_detected(self):
        phases = {
            "A": Phase(phase_id="A", name="Phase A", dependencies=["NON_EXISTENT"]),
        }
        errors = validate_phase_dependencies(phases)
        assert len(errors) == 1
        assert "depends on non-existent phase 'NON_EXISTENT'" in errors[0]

    def test_self_dependency_detected(self):
        phases = {
            "A": Phase(phase_id="A", name="Phase A", dependencies=["A"]),
        }
        errors = validate_phase_dependencies(phases)
        assert len(errors) == 1
        assert "cannot depend on itself" in errors[0]


# =============================================================================
# 13. Circular Dependency Detection
# =============================================================================

class TestCircularDependencyDetection:
    def test_direct_two_node_cycle(self):
        phases = {
            "A": Phase(phase_id="A", name="Phase A", dependencies=["B"]),
            "B": Phase(phase_id="B", name="Phase B", dependencies=["A"]),
        }
        errors = validate_phase_dependencies(phases)
        assert any("Circular dependency detected" in e for e in errors)
        with pytest.raises(DependencyGraphError):
            compute_topological_order(phases)

    def test_three_node_cycle(self):
        phases = {
            "A": Phase(phase_id="A", name="Phase A", dependencies=["C"]),
            "B": Phase(phase_id="B", name="Phase B", dependencies=["A"]),
            "C": Phase(phase_id="C", name="Phase C", dependencies=["B"]),
        }
        errors = validate_phase_dependencies(phases)
        assert any("Circular dependency detected" in e for e in errors)
        with pytest.raises(DependencyGraphError):
            compute_topological_order(phases)


# =============================================================================
# 14. Backward Compatibility with Existing Phase Representation
# =============================================================================

class TestBackwardCompatibility:
    def test_convert_from_legacy_phase_map_saas(self):
        wf = from_legacy_phase_map(intent_classification="saas")
        assert len(wf.phases) == 4
        assert "phase_1" in wf.phases
        assert "phase_4" in wf.phases
        assert wf.phase_order == ["phase_1", "phase_2", "phase_3", "phase_4"]
        assert wf.get_phase("phase_1").status == PhaseStatus.READY
        assert wf.get_phase("phase_2").dependencies == ["phase_1"]

    def test_convert_from_legacy_phase_map_content(self):
        # Content intent recommends phases [1, 3, 4]
        wf = from_legacy_phase_map(intent_classification="content")
        assert len(wf.phases) == 3
        assert "phase_1" in wf.phases
        assert "phase_3" in wf.phases
        assert "phase_4" in wf.phases
        assert "phase_2" not in wf.phases
        assert wf.phase_order == ["phase_1", "phase_3", "phase_4"]
