"""
Tetris — Workforce Engine: Dynamic Team Manager (Stage 3)
=========================================================

Evaluates project workflows, phase requirements, and available worker capabilities
to dynamically assemble and validate AI teams:
1. TeamReadiness (READY, CAPABLE_BUT_MISSING_CONNECTOR, NO_CAPABLE_WORKER, BLOCKED_BY_PERMISSION)
2. PhaseTeamAssignment (Workers selected and capabilities satisfied per phase)
3. TeamPlan (Comprehensive multi-phase team assignment and readiness audit)
4. TeamManager (Deterministic capability matching & team assembly engine)

Architectural Rules:
- Dynamic & non-hardcoded: Selects workers based on declared capabilities matching phase requirements.
- Distinguishes between worker capability and connector connection status.
- Additive and non-invasive: Does NOT execute workers or alter existing runtime execution paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from orchestration.phase_contract import Phase, ProjectWorkflow, WorkerAssignment
from orchestration.worker_registry import (
    WorkerDescriptor,
    WorkerRegistry,
    get_default_registry,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. TeamReadiness: Standard Readiness Classification
# =============================================================================

class TeamReadiness(str, Enum):
    """
    Standard readiness classifications for phase and workflow team plans.
    """
    READY = "READY"
    CAPABLE_BUT_MISSING_CONNECTOR = "CAPABLE_BUT_MISSING_CONNECTOR"
    NO_CAPABLE_WORKER = "NO_CAPABLE_WORKER"
    BLOCKED_BY_PERMISSION = "BLOCKED_BY_PERMISSION"


# =============================================================================
# 2. PhaseTeamAssignment & TeamPlan Models
# =============================================================================

class PhaseTeamAssignment(BaseModel):
    """
    Represents the workers selected, capabilities satisfied, and readiness for a single phase.
    """
    phase_id: str
    phase_name: str
    worker_ids: List[str] = Field(default_factory=list)
    worker_assignments: List[WorkerAssignment] = Field(default_factory=list)
    capabilities_required: List[str] = Field(default_factory=list)
    capabilities_satisfied: List[str] = Field(default_factory=list)
    capabilities_missing: List[str] = Field(default_factory=list)
    connector_requirements: List[str] = Field(default_factory=list)
    missing_connectors: List[str] = Field(default_factory=list)
    permission_requirements: List[str] = Field(default_factory=list)
    denied_permissions: List[str] = Field(default_factory=list)
    readiness: str = TeamReadiness.READY.value
    rationale: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PhaseTeamAssignment:
        return cls.model_validate(data)


class TeamPlan(BaseModel):
    """
    Comprehensive team assignment plan across all phases of a ProjectWorkflow.
    """
    project_id: str
    execution_id: str
    phase_assignments: Dict[str, PhaseTeamAssignment] = Field(default_factory=dict)
    workers: List[WorkerDescriptor] = Field(default_factory=list)
    readiness: str = TeamReadiness.READY.value
    rationale: Dict[str, str] = Field(default_factory=dict)
    unresolved_requirements: List[str] = Field(default_factory=list)
    missing_connectors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def is_executable(self) -> bool:
        """Returns True if the entire team plan is completely ready to execute."""
        return self.readiness == TeamReadiness.READY.value

    def apply_to_workflow(self, workflow: ProjectWorkflow) -> ProjectWorkflow:
        """
        Populates the Phase.workers on the given workflow with the WorkerAssignments
        generated in this TeamPlan.
        """
        for pid, phase_plan in self.phase_assignments.items():
            phase = workflow.get_phase(pid)
            if phase:
                phase.workers = list(phase_plan.worker_assignments)
        return workflow

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TeamPlan:
        return cls.model_validate(data)


# =============================================================================
# 3. TeamManager: Deterministic Capability Matching & Assembly Engine
# =============================================================================

class TeamManager:
    """
    Evaluates project requirements against the WorkerRegistry to assemble minimal,
    capable, and verified teams per phase.
    """

    def __init__(self, registry: Optional[WorkerRegistry] = None):
        self.registry = registry or get_default_registry()

    def infer_phase_capabilities(
        self,
        phase: Phase,
        project_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Extracts required capabilities for a phase by inspecting explicit metadata,
        entry/exit requirements, or phase keywords.
        """
        caps: Set[str] = set()

        # 1. Explicitly declared capabilities in phase metadata
        if phase.metadata and "required_capabilities" in phase.metadata:
            for c in phase.metadata["required_capabilities"]:
                caps.add(str(c).strip().lower())

        # 2. Context-provided phase overrides
        if project_context and "phase_requirements" in project_context:
            p_reqs = project_context["phase_requirements"].get(phase.phase_id, [])
            for c in p_reqs:
                caps.add(str(c).strip().lower())

        # 3. If no explicit capabilities are declared, infer from requirements or name/purpose keywords
        if not caps:
            text_corpus = f"{phase.name} {phase.description} {phase.purpose} {' '.join(phase.entry_requirements)} {' '.join(phase.exit_requirements)}".lower()

            keyword_map = {
                "backend": "backend",
                "api": "api_development",
                "code": "code_generation",
                "python": "python",
                "fastapi": "backend",
                "frontend": "frontend",
                "ui": "ui_design",
                "react": "react",
                "database": "database",
                "sql": "sql",
                "postgres": "postgresql",
                "sqlite": "sqlite",
                "competitor": "competitor_analysis",
                "research": "deep_research",
                "pricing": "pricing_strategy",
                "economics": "unit_economics",
                "simulation": "behavioral_simulation",
                "qa": "qa_testing",
                "security": "security_audit",
                "campaign": "campaign_strategy",
                "marketing": "campaign_strategy",
                "reddit": "reddit_distribution",
                "twitter": "x_distribution",
                "x_distribution": "x_distribution",
                "linkedin": "linkedin_distribution",
                "email": "email_outreach",
                "deploy": "deployment_preparation",
                "vercel": "vercel_deployment",
                "health": "health_monitoring",
            }

            for kw, cap in keyword_map.items():
                if kw in text_corpus:
                    caps.add(cap)

        # Fallback default if still empty
        if not caps:
            caps.add(f"{phase.name.lower().replace(' ', '_')}_task")

        return sorted(list(caps))

    def evaluate_team(
        self,
        workflow: ProjectWorkflow,
        project_context: Optional[Dict[str, Any]] = None,
        connected_connectors: Optional[Set[str] | List[str]] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
    ) -> TeamPlan:
        """
        Evaluates required capabilities across all phases in a workflow and produces
        a comprehensive, strongly typed TeamPlan.
        """
        connected_set: Set[str] = {c.lower() for c in (connected_connectors or set())}
        auth_perms_set: Optional[Set[str]] = {p.lower() for p in authorized_permissions} if authorized_permissions is not None else None

        phase_assignments: Dict[str, PhaseTeamAssignment] = {}
        all_selected_workers: Dict[str, WorkerDescriptor] = {}
        all_unresolved: Set[str] = set()
        all_missing_connectors: Set[str] = set()
        all_warnings: List[str] = []
        overall_readiness_ranks = {
            TeamReadiness.READY.value: 0,
            TeamReadiness.CAPABLE_BUT_MISSING_CONNECTOR.value: 1,
            TeamReadiness.BLOCKED_BY_PERMISSION.value: 2,
            TeamReadiness.NO_CAPABLE_WORKER.value: 3,
        }
        highest_rank = 0

        for pid in workflow.phase_order or list(workflow.phases.keys()):
            phase = workflow.get_phase(pid)
            if not phase:
                continue

            required_caps = self.infer_phase_capabilities(phase, project_context)
            unsatisfied_caps = set(required_caps)
            selected_workers_for_phase: List[WorkerDescriptor] = []
            satisfied_caps: Set[str] = set()

            # Greedy minimal worker selection: select workers that cover the most remaining unsatisfied capabilities
            available_workers = self.registry.list_all(available_only=True)

            while unsatisfied_caps:
                best_worker: Optional[WorkerDescriptor] = None
                best_overlap: Set[str] = set()

                for w in available_workers:
                    if w.worker_id in [sw.worker_id for sw in selected_workers_for_phase]:
                        continue
                    overlap = set(w.matches_capabilities(list(unsatisfied_caps)))
                    if len(overlap) > len(best_overlap):
                        best_worker = w
                        best_overlap = overlap
                    elif len(overlap) == len(best_overlap) and len(overlap) > 0:
                        # Tie-break by phase affinity
                        p_affinity = {a.lower() for a in w.phase_affinity}
                        if pid.lower() in p_affinity or phase.name.lower() in p_affinity:
                            best_worker = w
                            best_overlap = overlap

                if not best_worker or not best_overlap:
                    # No registered worker can satisfy remaining capabilities
                    break

                selected_workers_for_phase.append(best_worker)
                all_selected_workers[best_worker.worker_id] = best_worker
                satisfied_caps.update(best_overlap)
                unsatisfied_caps.difference_update(best_overlap)

            missing_caps = sorted(list(unsatisfied_caps))
            all_unresolved.update(missing_caps)

            # Evaluate connectors and permissions for this phase
            phase_connectors: Set[str] = set()
            for w in selected_workers_for_phase:
                phase_connectors.update(w.required_connectors)

            missing_phase_connectors = [c for c in sorted(list(phase_connectors)) if c.lower() not in connected_set]
            all_missing_connectors.update(missing_phase_connectors)

            phase_permissions: Set[str] = set()
            for w in selected_workers_for_phase:
                phase_permissions.update(w.permissions)

            denied_perms: List[str] = []
            if auth_perms_set is not None:
                denied_perms = [p for p in sorted(list(phase_permissions)) if p.lower() not in auth_perms_set]

            # Determine phase readiness
            if missing_caps:
                phase_readiness = TeamReadiness.NO_CAPABLE_WORKER.value
                rationale = f"Missing capable workers for requirements: {', '.join(missing_caps)}."
            elif missing_phase_connectors:
                phase_readiness = TeamReadiness.CAPABLE_BUT_MISSING_CONNECTOR.value
                rationale = f"All {len(required_caps)} capabilities satisfied by {len(selected_workers_for_phase)} workers, but connectors missing: {', '.join(missing_phase_connectors)}."
            elif denied_perms:
                phase_readiness = TeamReadiness.BLOCKED_BY_PERMISSION.value
                rationale = f"Permissions denied: {', '.join(denied_perms)}."
            else:
                phase_readiness = TeamReadiness.READY.value
                rationale = f"Ready. {len(selected_workers_for_phase)} workers satisfy all {len(required_caps)} capabilities."

            highest_rank = max(highest_rank, overall_readiness_ranks.get(phase_readiness, 0))

            # Build WorkerAssignment objects
            worker_assignments = []
            for w in selected_workers_for_phase:
                existing_wa = phase.get_worker(w.worker_id)
                deps = list(existing_wa.dependencies) if (existing_wa and existing_wa.dependencies) else []
                # If this is phase_distribution and wid is a channel worker and worker_campaign is present, ensure dependency
                if (pid == "phase_distribution" or "distribution" in pid.lower()) and w.worker_id in [
                    "worker_reddit", "worker_x", "worker_linkedin", "worker_email"
                ]:
                    if any(sw.worker_id == "worker_campaign" for sw in selected_workers_for_phase):
                        if "worker_campaign" not in deps:
                            deps.append("worker_campaign")

                wa_meta = {"selected_reason": "capability_match"}
                if existing_wa and existing_wa.metadata:
                    wa_meta.update(existing_wa.metadata)

                worker_assignments.append(
                    WorkerAssignment(
                        worker_id=w.worker_id,
                        phase_id=pid,
                        role=w.role,
                        capabilities=w.capabilities,
                        required_connectors=w.required_connectors,
                        permissions=w.permissions,
                        dependencies=deps,
                        metadata=wa_meta,
                    )
                )

            phase_assignments[pid] = PhaseTeamAssignment(
                phase_id=pid,
                phase_name=phase.name,
                worker_ids=[w.worker_id for w in selected_workers_for_phase],
                worker_assignments=worker_assignments,
                capabilities_required=required_caps,
                capabilities_satisfied=sorted(list(satisfied_caps)),
                capabilities_missing=missing_caps,
                connector_requirements=sorted(list(phase_connectors)),
                missing_connectors=missing_phase_connectors,
                permission_requirements=sorted(list(phase_permissions)),
                denied_permissions=denied_perms,
                readiness=phase_readiness,
                rationale=rationale,
            )

        # Aggregate overall workflow team readiness
        inv_ranks = {v: k for k, v in overall_readiness_ranks.items()}
        overall_readiness = inv_ranks.get(highest_rank, TeamReadiness.READY.value)

        # Global rationale
        global_rationale = {
            pid: pa.rationale for pid, pa in phase_assignments.items()
        }

        return TeamPlan(
            project_id=workflow.project_id,
            execution_id=workflow.execution_id,
            phase_assignments=phase_assignments,
            workers=list(all_selected_workers.values()),
            readiness=overall_readiness,
            rationale=global_rationale,
            unresolved_requirements=sorted(list(all_unresolved)),
            missing_connectors=sorted(list(all_missing_connectors)),
            warnings=all_warnings,
        )
