"""
Tetris — Workforce Engine: Phase ↔ Worker Architecture Foundation (Stage 2)
==========================================================================

Defines the canonical, strongly typed Phase and Workflow contracts:
1. PhaseStatus (Universal Phase Lifecycle States)
2. WorkerAssignment (A Worker's Membership & Role Inside a Phase)
3. Phase (Major Stage in Product Lifecycle with Arbitrary N Support)
4. ProjectWorkflow (Canonical Workflow DAG Container)
5. Graph Validation & Topological Sorting (Branching, Fan-In, Cycle Detection)
6. Backward Compatibility Adapters for Existing Phase Execution

Product Model:
PROJECT -> PHASES -> WORKERS -> TASKS -> ACTIONS -> EXECUTION -> VERIFICATION -> NEXT PHASE
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, Field, field_validator


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. PhaseStatus: Universal Phase Lifecycle States
# =============================================================================

class PhaseStatus(str, Enum):
    """
    Standard lifecycle states for a Phase in the Workforce Engine.
    """
    PLANNED = "PLANNED"       # Phase defined in workflow, awaiting prerequisites
    READY = "READY"           # All prerequisite phases completed, ready to start
    RUNNING = "RUNNING"       # Actively executing worker tasks
    BLOCKED = "BLOCKED"       # Blocked by missing entry requirement or prerequisite failure
    WAITING = "WAITING"       # Waiting for external dependency, gate, or event
    COMPLETED = "COMPLETED"   # All phase worker tasks and exit requirements passed
    FAILED = "FAILED"         # Phase failed (one or more required worker tasks failed)
    SKIPPED = "SKIPPED"       # Intentionally bypassed based on conditional rules
    CANCELLED = "CANCELLED"   # Aborted prior to completion

    @classmethod
    def terminal_states(cls) -> Set[PhaseStatus]:
        """Returns states from which no further normal progression occurs."""
        return {cls.COMPLETED, cls.FAILED, cls.SKIPPED, cls.CANCELLED}

    @classmethod
    def is_terminal(cls, status: PhaseStatus | str) -> bool:
        try:
            val = status if isinstance(status, cls) else cls(status.value if hasattr(status, "value") else str(status))
            return val in cls.terminal_states()
        except ValueError:
            return False

    def can_transition_to(self, target: PhaseStatus | str) -> bool:
        """Validates whether transitioning to target status is legally allowed."""
        try:
            target_enum = target if isinstance(target, PhaseStatus) else PhaseStatus(target.value if hasattr(target, "value") else str(target))
        except ValueError:
            return False

        if self == target_enum:
            return True

        valid_transitions: Dict[PhaseStatus, Set[PhaseStatus]] = {
            PhaseStatus.PLANNED: {
                PhaseStatus.READY,
                PhaseStatus.BLOCKED,
                PhaseStatus.SKIPPED,
                PhaseStatus.CANCELLED,
            },
            PhaseStatus.READY: {
                PhaseStatus.RUNNING,
                PhaseStatus.BLOCKED,
                PhaseStatus.WAITING,
                PhaseStatus.SKIPPED,
                PhaseStatus.CANCELLED,
            },
            PhaseStatus.RUNNING: {
                PhaseStatus.COMPLETED,
                PhaseStatus.FAILED,
                PhaseStatus.BLOCKED,
                PhaseStatus.WAITING,
                PhaseStatus.CANCELLED,
            },
            PhaseStatus.WAITING: {
                PhaseStatus.RUNNING,
                PhaseStatus.BLOCKED,
                PhaseStatus.CANCELLED,
            },
            PhaseStatus.BLOCKED: {
                PhaseStatus.READY,
                PhaseStatus.PLANNED,
                PhaseStatus.CANCELLED,
            },
            PhaseStatus.COMPLETED: set(),
            PhaseStatus.FAILED: {PhaseStatus.PLANNED, PhaseStatus.READY},  # Retry paths
            PhaseStatus.SKIPPED: set(),
            PhaseStatus.CANCELLED: set(),
        }

        return target_enum in valid_transitions.get(self, set())


# =============================================================================
# 2. WorkerAssignment: Membership of a Worker Inside a Phase
# =============================================================================

class WorkerAssignment(BaseModel):
    """
    Captures a worker's role, capabilities, and assignment INSIDE a specific Phase.
    The same worker type may be assigned to multiple phases with phase-specific tasks.
    """
    worker_id: str
    phase_id: str
    role: str
    capabilities: List[str] = Field(default_factory=list)
    required_connectors: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    task_ids: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)  # worker_ids or task_ids
    metadata: Dict[str, Any] = Field(default_factory=dict)
    assigned_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkerAssignment:
        return cls.model_validate(data)


# =============================================================================
# 3. Phase: Strongly Typed Phase Contract
# =============================================================================

class Phase(BaseModel):
    """
    Represents a major stage in the product lifecycle (e.g. Build, QA, Distribution, Deployment).
    Supports arbitrary N phases, custom requirements, and multi-worker membership.
    """
    phase_id: str
    phase_number: Optional[int] = None
    name: str
    description: str = ""
    purpose: str = ""
    status: PhaseStatus = PhaseStatus.PLANNED
    dependencies: List[str] = Field(default_factory=list)  # Prerequisite phase_ids
    workers: List[WorkerAssignment] = Field(default_factory=list)
    entry_requirements: List[str] = Field(default_factory=list)
    exit_requirements: List[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def add_worker(self, worker_assignment: WorkerAssignment) -> None:
        """Adds a worker assignment to this phase."""
        if worker_assignment.phase_id != self.phase_id:
            worker_assignment.phase_id = self.phase_id
        # Replace if worker_id already exists in this phase, else append
        for i, existing in enumerate(self.workers):
            if existing.worker_id == worker_assignment.worker_id:
                self.workers[i] = worker_assignment
                return
        self.workers.append(worker_assignment)

    def get_worker(self, worker_id: str) -> Optional[WorkerAssignment]:
        """Retrieves a worker assignment by worker_id."""
        for w in self.workers:
            if w.worker_id == worker_id:
                return w
        return None

    def has_worker(self, worker_id: str) -> bool:
        """Checks if a worker is assigned to this phase."""
        return any(w.worker_id == worker_id for w in self.workers)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Phase:
        return cls.model_validate(data)


# =============================================================================
# 4. Dependency Graph Engine (Topological Sorting & Cycle Detection)
# =============================================================================

class DependencyGraphError(Exception):
    """Raised when a phase dependency graph contains invalid or circular references."""
    pass


def validate_phase_dependencies(
    phases: Dict[str, Phase],
    dependencies: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """
    Validates a phase dependency graph.
    Returns a list of error strings if invalid or empty list if valid.
    Checks:
    1. All declared dependencies point to existing phase IDs.
    2. No self-dependencies (A -> A).
    3. No circular dependencies (A -> B -> A or A -> B -> C -> A).
    """
    errors: List[str] = []
    dep_map: Dict[str, List[str]] = {}

    # Build comprehensive dependency mapping from phase objects or explicit dict
    for pid, phase in phases.items():
        deps = list(phase.dependencies)
        if dependencies and pid in dependencies:
            for d in dependencies[pid]:
                if d not in deps:
                    deps.append(d)
        dep_map[pid] = deps

    # 1. Check for non-existent dependencies and self-dependencies
    for pid, deps in dep_map.items():
        for d in deps:
            if d == pid:
                errors.append(f"Phase '{pid}' cannot depend on itself.")
            elif d not in phases:
                errors.append(f"Phase '{pid}' depends on non-existent phase '{d}'.")

    if errors:
        return errors

    # 2. Cycle Detection using DFS / Graph Coloring
    # 0 = unvisited, 1 = visiting (in current recursion stack), 2 = visited
    visited: Dict[str, int] = {pid: 0 for pid in phases}

    def _has_cycle(node: str, path: List[str]) -> bool:
        visited[node] = 1
        path.append(node)
        for neighbor in dep_map.get(node, []):
            if neighbor not in visited:
                continue
            if visited[neighbor] == 1:
                cycle_str = " -> ".join(path[path.index(neighbor):] + [neighbor])
                errors.append(f"Circular dependency detected: {cycle_str}")
                return True
            elif visited[neighbor] == 0:
                if _has_cycle(neighbor, path):
                    return True
        path.pop()
        visited[node] = 2
        return False

    for pid in phases:
        if visited[pid] == 0:
            if _has_cycle(pid, []):
                break

    return errors


def compute_topological_order(
    phases: Dict[str, Phase],
    dependencies: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """
    Computes a valid topological execution order for phases using Kahn's Algorithm.
    Raises DependencyGraphError if cycles or invalid dependencies are detected.
    """
    errors = validate_phase_dependencies(phases, dependencies)
    if errors:
        raise DependencyGraphError(f"Cannot compute execution order: {'; '.join(errors)}")

    # Build in-degree map and adjacency list (parent -> children)
    adj: Dict[str, List[str]] = {pid: [] for pid in phases}
    in_degree: Dict[str, int] = {pid: 0 for pid in phases}

    for pid, phase in phases.items():
        deps = list(phase.dependencies)
        if dependencies and pid in dependencies:
            for d in dependencies[pid]:
                if d not in deps:
                    deps.append(d)
        for dep in deps:
            if dep in adj:
                adj[dep].append(pid)
                in_degree[pid] += 1

    # Queue of nodes with in_degree == 0 (no unfulfilled prerequisites)
    # Tie-break by phase_number or alphabetical phase_id for deterministic ordering
    zero_in = sorted(
        [pid for pid, deg in in_degree.items() if deg == 0],
        key=lambda x: (phases[x].phase_number if phases[x].phase_number is not None else 9999, x),
    )
    queue = deque(zero_in)
    order: List[str] = []

    while queue:
        curr = queue.popleft()
        order.append(curr)

        # For all phases that depend on `curr`, decrement in-degree
        for child in adj.get(curr, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(order) != len(phases):
        raise DependencyGraphError("Circular dependency detected in phase graph.")

    return order


# =============================================================================
# 5. ProjectWorkflow: Canonical Workflow Model
# =============================================================================

class ProjectWorkflow(BaseModel):
    """
    Canonical workflow contract representing arbitrary N phases, phase dependencies,
    worker assignments, and progress tracking for a Project.
    """
    project_id: str = Field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:10]}")
    execution_id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:10]}")
    phases: Dict[str, Phase] = Field(default_factory=dict)
    phase_order: List[str] = Field(default_factory=list)
    dependencies: Dict[str, List[str]] = Field(default_factory=dict)
    current_phase: Optional[str] = None
    completed_phases: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def add_phase(
        self,
        phase: Phase,
        dependencies: Optional[List[str]] = None,
    ) -> None:
        """
        Adds a phase to the workflow and records its dependencies.
        """
        self.phases[phase.phase_id] = phase
        if dependencies is not None:
            phase.dependencies = list(dependencies)
            self.dependencies[phase.phase_id] = list(dependencies)
        else:
            self.dependencies[phase.phase_id] = list(phase.dependencies)

        # Refresh topological phase order if valid
        try:
            self.phase_order = compute_topological_order(self.phases, self.dependencies)
        except DependencyGraphError:
            if phase.phase_id not in self.phase_order:
                self.phase_order.append(phase.phase_id)

    def get_phase(self, phase_id: str) -> Optional[Phase]:
        """Retrieves a Phase by phase_id."""
        return self.phases.get(phase_id)

    def get_ready_phases(self) -> List[Phase]:
        """
        Returns all phases whose prerequisite dependencies have been COMPLETED
        and are currently in PLANNED or READY status.
        """
        ready: List[Phase] = []
        completed_set = set(self.completed_phases)

        for pid, phase in self.phases.items():
            if pid in completed_set:
                continue
            if phase.status in (PhaseStatus.COMPLETED, PhaseStatus.SKIPPED, PhaseStatus.RUNNING):
                continue
            deps = self.dependencies.get(pid) if self.dependencies.get(pid) is not None else phase.dependencies
            if all(dep in completed_set for dep in deps):
                ready.append(phase)

        return ready

    def validate_graph(self) -> List[str]:
        """Validates the workflow graph for missing or circular dependencies."""
        return validate_phase_dependencies(self.phases, self.dependencies)

    def get_topological_order(self) -> List[str]:
        """Returns the valid topological execution order for all phases."""
        return compute_topological_order(self.phases, self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectWorkflow:
        return cls.model_validate(data)

    @classmethod
    def create_default_lifecycle(
        cls,
        project_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> ProjectWorkflow:
        """
        Factory creating the standard 5-phase product lifecycle:
        1. BUILD (Code Worker, UI Worker, Database Worker)
        2. SIMULATION (QA Worker, Security Worker)
        3. MARKETING (Reddit Worker, X Worker, Email Worker)
        4. DEPLOYMENT (Deployment Worker)
        5. HEALTH / OPERATE (Health Worker)

        Graph: BUILD -> SIMULATION -> MARKETING -> DEPLOYMENT -> HEALTH
        """
        wf = cls(
            project_id=project_id or f"proj_{uuid.uuid4().hex[:10]}",
            execution_id=execution_id or f"exec_{uuid.uuid4().hex[:10]}",
        )

        # 1. Build Phase
        p1 = Phase(
            phase_id="phase_build",
            phase_number=1,
            name="Build & Coding",
            description="Build core application, UI, and backend data models.",
            purpose="Generate functional software asset from specifications.",
            status=PhaseStatus.READY,
            dependencies=[],
            entry_requirements=["intake_specification"],
            exit_requirements=["executable_code", "file_manifest"],
        )
        p1.add_worker(WorkerAssignment(worker_id="worker_code", phase_id="phase_build", role="code_builder", capabilities=["code:generate"]))
        p1.add_worker(WorkerAssignment(worker_id="worker_ui", phase_id="phase_build", role="ui_developer", capabilities=["ui:generate"]))
        p1.add_worker(WorkerAssignment(worker_id="worker_db", phase_id="phase_build", role="database_architect", capabilities=["db:schema"]))
        wf.add_phase(p1)

        # 2. Simulation Phase (depends on Build)
        p2 = Phase(
            phase_id="phase_simulation",
            phase_number=2,
            name="Simulation & QA",
            description="Simulate real runtime behaviors, payloads, and edge cases.",
            purpose="Verify behavioral stability and security prior to distribution.",
            dependencies=["phase_build"],
            entry_requirements=["executable_code"],
            exit_requirements=["simulation_pass"],
        )
        p2.add_worker(WorkerAssignment(worker_id="worker_qa", phase_id="phase_simulation", role="qa_tester", capabilities=["simulate:payload"]))
        p2.add_worker(WorkerAssignment(worker_id="worker_sec", phase_id="phase_simulation", role="security_auditor", capabilities=["audit:security"]))
        wf.add_phase(p2)

        # 3. Marketing Phase (depends on Simulation)
        p3 = Phase(
            phase_id="phase_marketing",
            phase_number=3,
            name="Marketing & Distribution",
            description="Generate distribution campaigns and execute authorized community outreach.",
            purpose="Distribute validated product to target communities with verified receipts.",
            dependencies=["phase_simulation"],
            entry_requirements=["simulation_pass", "distribution_plan"],
            exit_requirements=["verified_distribution_receipts"],
        )
        p3.add_worker(WorkerAssignment(worker_id="worker_reddit", phase_id="phase_marketing", role="reddit_specialist", capabilities=["reddit:post", "reddit:reply"], required_connectors=["redditapis"]))
        p3.add_worker(WorkerAssignment(worker_id="worker_x", phase_id="phase_marketing", role="x_specialist", capabilities=["x:tweet"], required_connectors=["twitter"]))
        p3.add_worker(WorkerAssignment(worker_id="worker_email", phase_id="phase_marketing", role="email_specialist", capabilities=["email:send"], required_connectors=["sendgrid"]))
        wf.add_phase(p3)

        # 4. Deployment Phase (depends on Marketing)
        p4 = Phase(
            phase_id="phase_deployment",
            phase_number=4,
            name="Deployment & Hosting",
            description="Prepare production hosting bundles and deploy live services.",
            purpose="Host the live application on production infrastructure.",
            dependencies=["phase_marketing"],
            entry_requirements=["executable_code"],
            exit_requirements=["live_url"],
        )
        p4.add_worker(WorkerAssignment(worker_id="worker_deploy", phase_id="phase_deployment", role="deployment_engineer", capabilities=["deploy:vercel", "deploy:cloud"]))
        wf.add_phase(p4)

        # 5. Health & Operations Phase (depends on Deployment)
        p5 = Phase(
            phase_id="phase_health",
            phase_number=5,
            name="Health & Operate",
            description="Monitor live endpoints, error rates, and cron health status.",
            purpose="Maintain operational reliability post-launch.",
            dependencies=["phase_deployment"],
            entry_requirements=["live_url"],
            exit_requirements=["health_check_pass"],
        )
        p5.add_worker(WorkerAssignment(worker_id="worker_health", phase_id="phase_health", role="health_monitor", capabilities=["monitor:http", "health:check"]))
        wf.add_phase(p5)

        return wf


# =============================================================================
# 6. Backward Compatibility Adapters
# =============================================================================

def from_legacy_phase_map(
    intent_classification: str = "saas",
    execution_id: str = "",
    project_id: str = "",
) -> ProjectWorkflow:
    """
    Adapter converting legacy 4-phase definitions from orchestrator.phase_map
    into a canonical ProjectWorkflow model.
    """
    from orchestrator.phase_map import get_recommended_phases, PHASES, DEFAULT_PHASE_AGENTS

    rec_nums = get_recommended_phases(intent_classification)
    wf = ProjectWorkflow(
        project_id=project_id or f"proj_{uuid.uuid4().hex[:10]}",
        execution_id=execution_id or f"exec_{uuid.uuid4().hex[:10]}",
        metadata={"legacy_intent": intent_classification},
    )

    prev_pid: Optional[str] = None
    for p_num in sorted(rec_nums):
        meta = PHASES.get(p_num, {
            "name": f"Phase {p_num}",
            "description": f"Phase {p_num} execution",
        })
        pid = f"phase_{p_num}"
        deps = [prev_pid] if prev_pid else []

        phase = Phase(
            phase_id=pid,
            phase_number=p_num,
            name=meta.get("name", f"Phase {p_num}"),
            description=meta.get("description", ""),
            dependencies=deps,
            status=PhaseStatus.READY if not deps else PhaseStatus.PLANNED,
        )

        agent_info = DEFAULT_PHASE_AGENTS.get(p_num, {"type": "code", "name": "Specialist"})
        phase.add_worker(
            WorkerAssignment(
                worker_id=f"worker_{agent_info.get('type', 'general')}",
                phase_id=pid,
                role=agent_info.get("name", "Specialist"),
                capabilities=[f"{agent_info.get('type', 'general')}:execute"],
            )
        )

        wf.add_phase(phase)
        prev_pid = pid

    return wf
