"""
Tetris — Workforce Engine: Task Assignment & Binding Engine (Stage 4B)
======================================================================

Translates TeamPlan phase worker assignments and ProjectContext into concrete,
strongly-typed Task specifications with explicit input/output bindings,
artifact dependencies, connector requirements, and readiness assessments:

1. TaskReadiness (READY, BLOCKED, WAITING, INVALID)
2. CompiledTaskPlan (Multi-phase task graph, dependencies, and readiness audit)
3. TaskAssignmentEngine (Deterministic compiler from ProjectContext + TeamPlan -> Task[])

Architectural Rules:
- Pure Compilation: Compiles Task specifications WITHOUT executing workers or external APIs.
- Controlled Context Slicing: Tasks receive ONLY authorized slices via `ProjectContext.get_slice()`.
- Zero Secrets: Never passes plaintext API keys, passwords, tokens, or session cookies to tasks.
- Deterministic: Identical inputs produce identical task IDs, dependencies, and bindings.
- Non-Breaking & Additive: Reuses existing `Task` and `TaskPlan` contracts from Stage 1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow, WorkerAssignment
from orchestration.project_context import ProjectContext, _sanitize_dict_secrets
from orchestration.worker_contract import Task
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry
from orchestration.team_manager import TeamPlan, PhaseTeamAssignment

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. TaskReadiness: Task Lifecycle Readiness States
# =============================================================================

class TaskReadiness(str, Enum):
    """
    Standard readiness states for individual tasks in a compiled task graph.
    """
    READY = "READY"       # All dependencies fulfilled, connectors connected, permissions granted
    WAITING = "WAITING"   # Waiting on prerequisite upstream tasks or phase activation
    BLOCKED = "BLOCKED"   # Missing required connector, denied permission, or blocked phase
    INVALID = "INVALID"   # Invalid configuration, unregistered worker, or circular dependency


# =============================================================================
# 2. Worker Context & Artifact Mapping Specifications
# =============================================================================

# Controlled context keys requested per worker specialization
DEFAULT_WORKER_CONTEXT_KEYS: Dict[str, List[str]] = {
    "worker_code": ["idea", "goal", "requirements", "constraints", "acceptance_criteria", "specifications"],
    "worker_ui": ["idea", "goal", "requirements", "acceptance_criteria", "specifications", "code_assets"],
    "worker_database": ["idea", "goal", "requirements", "specifications", "code_assets"],
    "worker_competitor_intel": ["idea", "goal", "target_users", "research"],
    "worker_research": ["idea", "goal", "target_users", "requirements"],
    "worker_pricing": ["idea", "target_users", "competitor_intelligence", "pricing"],
    "worker_qa_simulation": ["idea", "code_assets", "specifications", "acceptance_criteria", "simulation"],
    "worker_security": ["code_assets", "specifications", "requirements", "metadata"],
    "worker_campaign": ["idea", "target_users", "competitor_intelligence", "pricing", "simulation"],
    "worker_reddit": ["idea", "target_users", "distribution", "competitor_intelligence", "simulation"],
    "worker_x": ["idea", "target_users", "distribution", "simulation"],
    "worker_linkedin": ["idea", "target_users", "distribution", "pricing"],
    "worker_email": ["idea", "target_users", "distribution", "pricing"],
    "worker_deployment": ["idea", "code_assets", "specifications", "simulation", "acceptance_criteria"],
    "worker_launch_verification": ["idea", "deployment", "receipts", "simulation", "code_assets"],
    "worker_health": ["idea", "deployment", "receipts", "definition"],
}

# Artifact bindings (what artifact types a worker consumes and is expected to produce)
DEFAULT_WORKER_ARTIFACT_MAP: Dict[str, Dict[str, List[str]]] = {
    "worker_code": {
        "consumes": ["specification"],
        "produces": ["code_workspace", "backend_api"],
    },
    "worker_ui": {
        "consumes": ["specification", "code_workspace"],
        "produces": ["frontend_ui", "web_components"],
    },
    "worker_database": {
        "consumes": ["specification"],
        "produces": ["database_schema"],
    },
    "worker_competitor_intel": {
        "consumes": ["deep_research"],
        "produces": ["competitor_intelligence"],
    },
    "worker_research": {
        "consumes": [],
        "produces": ["domain_research_report"],
    },
    "worker_pricing": {
        "consumes": ["competitor_analysis"],
        "produces": ["pricing_model"],
    },
    "worker_qa_simulation": {
        "consumes": ["code_workspace", "specification"],
        "produces": ["simulation_result", "qa_report"],
    },
    "worker_security": {
        "consumes": ["code_workspace"],
        "produces": ["security_audit_report"],
    },
    "worker_campaign": {
        "consumes": ["competitor_analysis", "pricing_model", "simulation_result"],
        "produces": ["distribution_plan", "campaign_messaging"],
    },
    "worker_reddit": {
        "consumes": ["distribution_plan"],
        "produces": ["reddit_post_receipt"],
    },
    "worker_x": {
        "consumes": ["distribution_plan"],
        "produces": ["x_tweet_receipt"],
    },
    "worker_linkedin": {
        "consumes": ["distribution_plan"],
        "produces": ["linkedin_post_receipt"],
    },
    "worker_email": {
        "consumes": ["distribution_plan"],
        "produces": ["email_dispatch_receipt"],
    },
    "worker_deployment": {
        "consumes": ["code_workspace", "simulation_result"],
        "produces": ["deployment_bundle", "deployment_receipt"],
    },
    "worker_launch_verification": {
        "consumes": ["deployment_bundle", "deployment_receipt"],
        "produces": ["launch_verification", "launch_receipt"],
    },
    "worker_health": {
        "consumes": ["deployment_bundle", "live_service"],
        "produces": ["health_report", "uptime_metrics"],
    },
}


# =============================================================================
# 3. CompiledTaskPlan: Multi-Phase Task Graph & Execution Spec
# =============================================================================

class CompiledTaskPlan(BaseModel):
    """
    Comprehensive compilation of all tasks, dependencies, bindings, and readiness
    assessments across a ProjectWorkflow.
    """
    project_id: str
    execution_id: str
    tasks: List[Task] = Field(default_factory=list)
    task_dependencies: Dict[str, List[str]] = Field(default_factory=dict)
    ready_tasks: List[str] = Field(default_factory=list)
    blocked_tasks: List[str] = Field(default_factory=list)
    waiting_tasks: List[str] = Field(default_factory=list)
    invalid_tasks: List[str] = Field(default_factory=list)
    phase_task_map: Dict[str, List[str]] = Field(default_factory=dict)
    worker_task_map: Dict[str, List[str]] = Field(default_factory=dict)
    readiness: str = TaskReadiness.READY.value
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieves a task by task_id."""
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def get_tasks_for_phase(self, phase_id: str) -> List[Task]:
        """Retrieves all tasks belonging to a specific phase."""
        task_ids = set(self.phase_task_map.get(phase_id, []))
        return [t for t in self.tasks if t.task_id in task_ids]

    def get_tasks_for_worker(self, worker_id: str) -> List[Task]:
        """Retrieves all tasks assigned to a specific worker."""
        task_ids = set(self.worker_task_map.get(worker_id, []))
        return [t for t in self.tasks if t.task_id in task_ids]

    def get_ready_tasks(self) -> List[Task]:
        """Returns all tasks currently marked as READY."""
        ready_ids = set(self.ready_tasks)
        return [t for t in self.tasks if t.task_id in ready_ids]

    def is_executable(self) -> bool:
        """Determines if the task plan has ready executable tasks and no fatal errors."""
        return len(self.ready_tasks) > 0 and len(self.validation_errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Returns a sanitized JSON-safe dictionary representation."""
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CompiledTaskPlan:
        """Deserializes a CompiledTaskPlan from a dictionary."""
        return cls.model_validate(_sanitize_dict_secrets(data))


# Alias for backward/forward naming convenience
TaskAssignmentPlan = CompiledTaskPlan


# =============================================================================
# 4. TaskAssignmentEngine: Pure Task Compilation & Binding Engine
# =============================================================================

class TaskAssignmentEngine:
    """
    Compiles ProjectContext, ProjectWorkflow, and TeamPlan into concrete Task specifications.
    Guarantees deterministic task generation, controlled context slicing, and zero side effects.
    """

    def __init__(self, registry: Optional[WorkerRegistry] = None):
        self.registry = registry or get_default_registry()

    # -------------------------------------------------------------------------
    # Public Compilation API
    # -------------------------------------------------------------------------

    def assign_tasks(
        self,
        project_context: ProjectContext,
        workflow: ProjectWorkflow,
        team_plan: TeamPlan,
        connected_connectors: Optional[Set[str] | List[str]] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
    ) -> CompiledTaskPlan:
        """
        Compiles the entire project workflow and team plan into a deterministic CompiledTaskPlan.
        """
        connected_set: Set[str] = {c.lower() for c in (connected_connectors or set())}
        auth_perms_set: Optional[Set[str]] = {p.lower() for p in authorized_permissions} if authorized_permissions is not None else None

        compiled_tasks: List[Task] = []
        task_dependencies: Dict[str, List[str]] = {}
        phase_task_map: Dict[str, List[str]] = {}
        worker_task_map: Dict[str, List[str]] = {}
        ready_tasks: List[str] = []
        blocked_tasks: List[str] = []
        waiting_tasks: List[str] = []
        invalid_tasks: List[str] = []
        validation_errors: List[str] = []
        warnings: List[str] = []

        # Map to track generated task IDs by (phase_id, worker_id)
        phase_worker_task_lookup: Dict[str, Dict[str, str]] = {}

        # 1. Validation of inputs
        if not workflow.phases:
            validation_errors.append("ProjectWorkflow contains no phases.")
            return CompiledTaskPlan(
                project_id=project_context.project_id,
                execution_id=project_context.execution_id,
                readiness=TaskReadiness.INVALID.value,
                validation_errors=validation_errors,
            )

        # Check for workflow graph circularities
        graph_errors = workflow.validate_graph()
        if graph_errors:
            validation_errors.extend(graph_errors)
            return CompiledTaskPlan(
                project_id=project_context.project_id,
                execution_id=project_context.execution_id,
                readiness=TaskReadiness.INVALID.value,
                validation_errors=validation_errors,
            )

        # Determine phase execution order
        try:
            ordered_phase_ids = workflow.get_topological_order()
        except Exception as e:
            validation_errors.append(f"Failed to determine topological phase order: {str(e)}")
            return CompiledTaskPlan(
                project_id=project_context.project_id,
                execution_id=project_context.execution_id,
                readiness=TaskReadiness.INVALID.value,
                validation_errors=validation_errors,
            )

        # 2. First Pass: Generate concrete Task specifications for each worker in each phase
        for pid in ordered_phase_ids:
            phase = workflow.get_phase(pid)
            if not phase:
                continue

            phase_task_map[pid] = []
            phase_worker_task_lookup[pid] = {}

            # Retrieve and merge worker assignments from TeamPlan and phase.workers
            seen_canonical_wids: Set[str] = set()
            worker_assignments: List[WorkerAssignment] = []

            phase_assignment = team_plan.phase_assignments.get(pid)
            if phase_assignment and phase_assignment.worker_assignments:
                for wa in phase_assignment.worker_assignments:
                    w_desc = self.registry.get(wa.worker_id)
                    c_wid = w_desc.worker_id if w_desc else wa.worker_id
                    if c_wid not in seen_canonical_wids:
                        seen_canonical_wids.add(c_wid)
                        worker_assignments.append(wa)

            for wa in phase.workers:
                w_desc = self.registry.get(wa.worker_id)
                c_wid = w_desc.worker_id if w_desc else wa.worker_id
                if c_wid not in seen_canonical_wids:
                    seen_canonical_wids.add(c_wid)
                    worker_assignments.append(wa)

            if not worker_assignments:
                warnings.append(f"Phase '{pid}' has no assigned workers.")
                continue

            for w_idx, w_assign in enumerate(worker_assignments):
                wid = w_assign.worker_id

                # Validate worker in registry (supports aliases)
                worker_desc = self.registry.get(wid)
                if not worker_desc:
                    invalid_task_id = f"task_{pid}_{wid}"
                    invalid_tasks.append(invalid_task_id)
                    validation_errors.append(f"Worker '{wid}' in phase '{pid}' is not registered in WorkerRegistry.")
                    continue

                canonical_wid = worker_desc.worker_id

                # Deterministic Task ID
                task_id = self._generate_task_id(pid, canonical_wid)
                phase_worker_task_lookup[pid][wid] = task_id
                phase_worker_task_lookup[pid][canonical_wid] = task_id
                phase_task_map[pid].append(task_id)

                if canonical_wid not in worker_task_map:
                    worker_task_map[canonical_wid] = []
                worker_task_map[canonical_wid].append(task_id)

                # Context Slicing & Input Bindings
                task_inputs = self._derive_task_inputs(canonical_wid, phase, w_assign, project_context)

                # Objective Generation
                objective = self._generate_objective(canonical_wid, worker_desc, phase, project_context)

                # Artifact Bindings (Consumes & Produces)
                consumes_arts, produces_arts = self._derive_artifact_bindings(canonical_wid, w_assign)

                # Acceptance Criteria Bindings
                bound_criteria = self._bind_acceptance_criteria(canonical_wid, worker_desc, phase, project_context)

                # Permissions & Connectors
                required_connectors = list(set(worker_desc.required_connectors + w_assign.required_connectors))
                required_permissions = list(set(worker_desc.permissions + w_assign.permissions))

                # Expected Output Schema Contract
                expected_output = {
                    "expected_artifacts": produces_arts,
                    "target_phase": pid,
                    "target_worker": canonical_wid,
                    "status_contract": "SUCCESS",
                }

                task_metadata = {
                    "phase_id": pid,
                    "phase_name": phase.name,
                    "phase_number": phase.phase_number,
                    "worker_role": worker_desc.role,
                    "consumes_artifacts": consumes_arts,
                    "produces_artifacts": produces_arts,
                    "required_connectors": required_connectors,
                    "acceptance_criteria_bound": bound_criteria,
                    "assigned_at": w_assign.assigned_at,
                }

                # Construct Task object
                task = Task(
                    task_id=task_id,
                    execution_id=project_context.execution_id,
                    project_id=project_context.project_id,
                    worker_id=canonical_wid,
                    objective=objective,
                    inputs=task_inputs,
                    dependencies=[],  # Will be populated in Pass 2
                    permissions=required_permissions,
                    expected_output=expected_output,
                    metadata=task_metadata,
                )
                compiled_tasks.append(task)

        # 3. Second Pass: Build task-level dependency graph
        for task in compiled_tasks:
            pid = task.metadata.get("phase_id", "")
            wid = task.worker_id
            phase = workflow.get_phase(pid)

            t_deps: List[str] = []

            # A. Phase-level dependencies: depend on all tasks from prerequisite phases
            if phase and phase.dependencies:
                for prereq_pid in phase.dependencies:
                    prereq_task_ids = phase_task_map.get(prereq_pid, [])
                    for ptid in prereq_task_ids:
                        if ptid not in t_deps:
                            t_deps.append(ptid)

            # B. Intra-phase worker dependencies
            w_assign = phase.get_worker(wid) if phase else None
            if w_assign and w_assign.dependencies:
                for intra_dep_wid in w_assign.dependencies:
                    intra_tid = phase_worker_task_lookup.get(pid, {}).get(intra_dep_wid)
                    if intra_tid and intra_tid not in t_deps:
                        t_deps.append(intra_tid)

            task.dependencies = sorted(t_deps)
            task_dependencies[task.task_id] = list(task.dependencies)

        # 4. Third Pass: Evaluate Task Readiness
        completed_phase_ids = set(workflow.completed_phases)
        # Determine completed task IDs (from completed phases or context phase outcomes)
        completed_task_ids: Set[str] = set()
        for completed_pid in completed_phase_ids:
            for c_tid in phase_task_map.get(completed_pid, []):
                completed_task_ids.add(c_tid)

        for task in compiled_tasks:
            pid = task.metadata.get("phase_id", "")
            wid = task.worker_id
            worker_desc = self.registry.get(wid)
            phase = workflow.get_phase(pid)

            task_connectors = task.metadata.get("required_connectors", [])
            missing_conns = [c for c in task_connectors if c.lower() not in connected_set]

            task_perms = task.permissions
            denied_perms = []
            if auth_perms_set is not None:
                denied_perms = [p for p in task_perms if p.lower() not in auth_perms_set]

            # Check unfulfilled task dependencies
            unfulfilled_deps = [d for d in task.dependencies if d not in completed_task_ids]

            # Phase readiness check
            phase_is_ready_or_completed = (
                pid in completed_phase_ids
                or (phase and phase.status in (PhaseStatus.READY, PhaseStatus.RUNNING))
                or (phase and all(dep_p in completed_phase_ids for dep_p in phase.dependencies))
            )

            if missing_conns:
                task_readiness = TaskReadiness.BLOCKED.value
                task.metadata["blocked_reason"] = f"Missing required connectors: {', '.join(missing_conns)}"
                blocked_tasks.append(task.task_id)
            elif denied_perms:
                task_readiness = TaskReadiness.BLOCKED.value
                task.metadata["blocked_reason"] = f"Permissions denied: {', '.join(denied_perms)}"
                blocked_tasks.append(task.task_id)
            elif phase and phase.status == PhaseStatus.BLOCKED:
                task_readiness = TaskReadiness.BLOCKED.value
                task.metadata["blocked_reason"] = f"Parent phase '{pid}' is blocked"
                blocked_tasks.append(task.task_id)
            elif unfulfilled_deps or not phase_is_ready_or_completed:
                task_readiness = TaskReadiness.WAITING.value
                task.metadata["waiting_on"] = unfulfilled_deps
                waiting_tasks.append(task.task_id)
            else:
                task_readiness = TaskReadiness.READY.value
                ready_tasks.append(task.task_id)

            task.metadata["readiness_status"] = task_readiness

        # Overall task plan readiness
        if invalid_tasks or validation_errors:
            overall_readiness = TaskReadiness.INVALID.value
        elif blocked_tasks and not ready_tasks:
            overall_readiness = TaskReadiness.BLOCKED.value
        elif ready_tasks:
            overall_readiness = TaskReadiness.READY.value
        else:
            overall_readiness = TaskReadiness.WAITING.value

        return CompiledTaskPlan(
            project_id=project_context.project_id,
            execution_id=project_context.execution_id,
            tasks=compiled_tasks,
            task_dependencies=task_dependencies,
            ready_tasks=ready_tasks,
            blocked_tasks=blocked_tasks,
            waiting_tasks=waiting_tasks,
            invalid_tasks=invalid_tasks,
            phase_task_map=phase_task_map,
            worker_task_map=worker_task_map,
            readiness=overall_readiness,
            validation_errors=validation_errors,
            warnings=warnings,
            metadata={
                "total_tasks": len(compiled_tasks),
                "total_phases": len(ordered_phase_ids),
                "compiled_at": _utc_now_iso(),
            },
        )

    # -------------------------------------------------------------------------
    # Internal Deterministic Generation & Binding Helpers
    # -------------------------------------------------------------------------

    def _generate_task_id(self, phase_id: str, worker_id: str, index: int = 0) -> str:
        """
        Generates a deterministic task identifier.
        """
        clean_pid = phase_id.replace("phase_", "").replace(" ", "_").lower()
        clean_wid = worker_id.replace("worker_", "").replace(" ", "_").lower()
        if index == 0:
            return f"task_{clean_pid}_{clean_wid}"
        return f"task_{clean_pid}_{clean_wid}_{index}"

    def _derive_task_inputs(
        self,
        worker_id: str,
        phase: Phase,
        w_assign: WorkerAssignment,
        project_context: ProjectContext,
    ) -> Dict[str, Any]:
        """
        Retrieves a controlled, sanitized slice of ProjectContext according to the
        worker's required context keys.
        """
        # Determine required keys from worker defaults or explicit overrides
        req_keys = list(DEFAULT_WORKER_CONTEXT_KEYS.get(
            worker_id,
            ["idea", "goal", "requirements", "acceptance_criteria"],
        ))

        # Check for phase or assignment level context key overrides
        if phase.metadata and "context_keys" in phase.metadata:
            for k in phase.metadata["context_keys"]:
                if k not in req_keys:
                    req_keys.append(k)

        if w_assign.metadata and "context_keys" in w_assign.metadata:
            for k in w_assign.metadata["context_keys"]:
                if k not in req_keys:
                    req_keys.append(k)

        # Controlled retrieval via ProjectContext
        context_slice = project_context.get_slice(req_keys)
        return _sanitize_dict_secrets(context_slice)

    def _derive_artifact_bindings(
        self,
        worker_id: str,
        w_assign: WorkerAssignment,
    ) -> tuple[List[str], List[str]]:
        """
        Returns (consumes_artifacts, produces_artifacts) for the worker task.
        """
        defaults = DEFAULT_WORKER_ARTIFACT_MAP.get(
            worker_id,
            {"consumes": [], "produces": [f"{worker_id}_artifact"]},
        )
        consumes = list(defaults.get("consumes", []))
        produces = list(defaults.get("produces", []))

        # Override or supplement from assignment metadata if present
        if w_assign.metadata:
            if "consumes_artifacts" in w_assign.metadata:
                consumes = list(w_assign.metadata["consumes_artifacts"])
            if "produces_artifacts" in w_assign.metadata:
                produces = list(w_assign.metadata["produces_artifacts"])

        return consumes, produces

    def _generate_objective(
        self,
        worker_id: str,
        worker_desc: WorkerDescriptor,
        phase: Phase,
        project_context: ProjectContext,
    ) -> str:
        """
        Synthesizes a concrete, human-readable task objective for the worker.
        """
        idea = project_context.definition.idea
        role = worker_desc.role

        objective_templates = {
            "worker_code": f"Implement the core application backend, API routes, and business logic for '{idea}' according to the approved requirements.",
            "worker_ui": f"Implement the responsive frontend interface, UI components, and design styling for '{idea}' according to the approved requirements.",
            "worker_database": f"Model and construct the database schema, relational tables, and data models for '{idea}'.",
            "worker_competitor_intel": f"Discover and analyze top competitors, feature comparisons, and distribution channels for '{idea}'.",
            "worker_research": f"Conduct deep domain research, user pain point synthesis, and market trend reports for '{idea}'.",
            "worker_pricing": f"Design value-based SaaS pricing tiers, monetization strategy, and unit economics for '{idea}'.",
            "worker_qa_simulation": f"Execute behavioral simulation, runtime stress tests, and acceptance criteria verification for '{idea}'.",
            "worker_security": f"Perform security audit, credential isolation checks, and permission validation for '{idea}'.",
            "worker_campaign": f"Formulate multi-channel distribution strategy, launch messaging, and outreach sequence for '{idea}'.",
            "worker_reddit": f"Execute authorized community distribution and targeted discussions on Reddit for '{idea}' with verified receipts.",
            "worker_x": f"Publish product announcements and community launch threads on Twitter/X for '{idea}'.",
            "worker_linkedin": f"Publish professional B2B outreach and founder updates on LinkedIn for '{idea}'.",
            "worker_email": f"Execute targeted email outreach campaigns and beta invitations for '{idea}'.",
            "worker_deployment": f"Package production build bundle and deploy live hosting service for '{idea}'.",
            "worker_launch_verification": f"Verify live reachability and perform HTTP smoke checks on deployed service for '{idea}'.",
            "worker_health": f"Configure and verify operational health monitoring, uptime checks, and endpoint reliability for '{idea}'.",
        }

        if worker_id in objective_templates:
            return objective_templates[worker_id]

        # Dynamic fallback for custom/unregistered workers
        phase_purpose = phase.purpose or phase.description or phase.name
        return f"Execute {role} responsibilities in phase '{phase.name}' to fulfill: {phase_purpose} for '{idea}'."

    def _bind_acceptance_criteria(
        self,
        worker_id: str,
        worker_desc: WorkerDescriptor,
        phase: Phase,
        project_context: ProjectContext,
    ) -> List[str]:
        """
        Binds relevant project acceptance criteria to the specific worker task.
        """
        all_criteria = list(project_context.definition.acceptance_criteria)
        if not all_criteria:
            return []

        # QA, Simulation, and Build workers bind broadly to project acceptance criteria
        broad_eval_workers = {
            "worker_code",
            "worker_ui",
            "worker_database",
            "worker_qa_simulation",
            "worker_security",
        }

        if worker_id in broad_eval_workers:
            return all_criteria

        # Deployment and launch workers bind to criteria mentioning loading, live, dashboard, or alerts
        if worker_id in ("worker_deployment", "worker_launch_verification", "worker_health"):
            deploy_matches = [
                c for c in all_criteria
                if any(kw in c.lower() for kw in ["load", "deploy", "live", "dashboard", "alert", "trigger", "access"])
            ]
            return deploy_matches if deploy_matches else all_criteria

        # Distribution/Marketing workers bind to launch or general criteria
        return [c for c in all_criteria if any(kw in c.lower() for kw in ["track", "alert", "share", "community", "user"])] or all_criteria
