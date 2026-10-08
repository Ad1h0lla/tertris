"""
Tetris — Workforce Engine: Project Context Foundation (Stage 4A)
================================================================

Defines the canonical, persistent, structured shared memory for Tetris projects:
1. Artifact (Structured artifact reference with provenance)
2. PhaseOutcomeReference (Orchestration view over phase outputs)
3. ReceiptReference (Verified external execution side effect reference without secrets)
4. Decision (Structured rationale log for auditability)
5. ProjectDefinition (Core idea, target users, requirements, constraints, acceptance criteria)
6. ProjectContext (Authoritative shared project memory with controlled slice retrieval)

Architectural Rules:
- Identity & Provenance: Every artifact, decision, and phase outcome is traceable to its source phase and worker.
- Controlled Access: Workers receive only the authorized/requested context slice via `get_slice()`.
- Security & Zero Secrets: ProjectContext NEVER stores plaintext passwords, API keys, session cookies, or tokens.
- Reference-Based: Stores file paths, database IDs, and URLs rather than copying massive file contents.
- Non-Breaking & Additive: Coexists seamlessly with existing SQLite `Execution` and `PhaseResult` tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Sensitive keys that must NEVER be stored or serialized in ProjectContext
FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "reddit_session",
    "session_cookies",
    "cookie",
    "cookies",
    "authorization",
    "auth_header",
    "bearer_token",
    "private_key",
}


def _sanitize_dict_secrets(obj: Any) -> Any:
    """
    Recursively scans and removes or masks any forbidden credential fields.
    """
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                clean[k] = "[REDACTED_SECRET]"
            else:
                clean[k] = _sanitize_dict_secrets(v)
        return clean
    elif isinstance(obj, list):
        return [_sanitize_dict_secrets(item) for item in obj]
    return obj


# =============================================================================
# 1. Artifact: Structured Artifact Reference with Provenance
# =============================================================================

class Artifact(BaseModel):
    """
    Represents a concrete deliverable, file tree, test result, or specification
    produced by a worker in a phase.
    """
    artifact_id: str = Field(default_factory=lambda: f"art_{uuid.uuid4().hex[:12]}")
    name: str
    artifact_type: str  # e.g., "code_workspace", "database_schema", "specification", "simulation_result", "distribution_plan", "deployment_bundle"
    phase_id: str
    producer_worker: str
    producer_task: Optional[str] = None
    status: str = "AVAILABLE"  # "AVAILABLE", "SUPERSEDED", "DEPRECATED", "DRAFT"
    location: str = ""  # File path, DB record key, or URI reference
    content_summary: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Artifact:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 2. PhaseOutcomeReference: Orchestration View of Phase Results
# =============================================================================

class PhaseOutcomeReference(BaseModel):
    """
    References a completed or in-progress phase result in the project history.
    """
    phase_id: str
    phase_name: str
    status: str  # e.g., "COMPLETED", "FAILED", "RUNNING"
    result_reference: Optional[str] = None  # Pointer to DB PhaseResult.id
    outcome_type: Optional[str] = None  # e.g., "code", "competitor_intel", "campaign"
    producer_worker: Optional[str] = None
    verification_status: Optional[str] = None  # "PASS", "FAIL", "NOT_TESTED"
    validation_score: Optional[float] = None
    summary: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    recorded_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PhaseOutcomeReference:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 3. ReceiptReference: Verified External Side Effect Reference
# =============================================================================

class ReceiptReference(BaseModel):
    """
    References a verified real-world external side effect (e.g. Reddit comment,
    email dispatch, live deployment) without storing secrets.
    """
    receipt_id: str = Field(default_factory=lambda: f"rcpt_{uuid.uuid4().hex[:12]}")
    platform: str  # "reddit", "twitter", "linkedin", "sendgrid", "vercel", etc.
    action_type: str  # "reply_to_post", "send_email", "deploy_vercel", etc.
    external_id: Optional[str] = None  # e.g. "t1_pe95jxd"
    permalink: Optional[str] = None  # e.g. "https://reddit.com/r/n8n/..."
    verified: bool = False
    verification_status: str = "NOT_TESTED"  # "PASS", "FAIL", "NOT_TESTED"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    phase_id: Optional[str] = None
    producer_worker: Optional[str] = None
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReceiptReference:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 4. Decision: Structured Rationale Log Entry
# =============================================================================

class Decision(BaseModel):
    """
    Preserves WHY an architectural, design, or distribution choice was made.
    """
    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:10]}")
    decision: str
    reason: str
    source: str  # e.g., "worker_campaign", "team_manager", "user_intake"
    phase_id: Optional[str] = None
    worker_id: Optional[str] = None
    timestamp: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Decision:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 5. ProjectDefinition: Problem, Goal, and Scope Definition
# =============================================================================

class ProjectDefinition(BaseModel):
    """
    Core project intent, target audience, requirements, constraints, and acceptance criteria.
    """
    idea: str
    goal: str
    target_users: str = ""
    requirements: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectDefinition:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 6. ProjectContext: Canonical Shared Project Memory
# =============================================================================

class ProjectContext(BaseModel):
    """
    Authoritative shared memory of the project across all phases and workers.
    Accumulates knowledge, preserves provenance, and provides controlled slices.
    """
    project_id: str = Field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:10]}")
    execution_id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:10]}")
    user_id: str = "user_001"
    definition: ProjectDefinition
    artifacts: Dict[str, Artifact] = Field(default_factory=dict)
    phase_history: Dict[str, PhaseOutcomeReference] = Field(default_factory=dict)
    receipts: List[ReceiptReference] = Field(default_factory=list)
    decisions: List[Decision] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    # -------------------------------------------------------------------------
    # Controlled Context Retrieval
    # -------------------------------------------------------------------------

    def get_slice(self, required_keys: List[str]) -> Dict[str, Any]:
        """
        Controlled read interface.
        Returns a dictionary containing ONLY the requested and authorized fields.
        Supports top-level keys ('idea', 'goal', 'requirements', 'target_users',
        'constraints', 'acceptance_criteria', 'receipts', 'decisions', 'phase_history')
        as well as artifact categories (e.g. 'code_assets', 'specifications',
        'research', 'competitor_intelligence', 'pricing', 'simulation', 'distribution',
        'deployment', 'health', or 'artifacts').
        """
        output: Dict[str, Any] = {}
        clean_keys = {k.strip().lower() for k in required_keys if k and k.strip()}

        # Definition keys
        if "idea" in clean_keys:
            output["idea"] = self.definition.idea
        if "goal" in clean_keys:
            output["goal"] = self.definition.goal
        if "target_users" in clean_keys or "target_audience" in clean_keys:
            output["target_users"] = self.definition.target_users
        if "requirements" in clean_keys:
            output["requirements"] = list(self.definition.requirements)
        if "constraints" in clean_keys:
            output["constraints"] = list(self.definition.constraints)
        if "acceptance_criteria" in clean_keys:
            output["acceptance_criteria"] = list(self.definition.acceptance_criteria)
        if "definition" in clean_keys:
            output["definition"] = self.definition.to_dict()

        # Core collections
        if "receipts" in clean_keys:
            output["receipts"] = [r.to_dict() for r in self.receipts]
        if "decisions" in clean_keys or "decision_log" in clean_keys:
            output["decisions"] = [d.to_dict() for d in self.decisions]
        if "phase_history" in clean_keys:
            output["phase_history"] = {pid: p.to_dict() for pid, p in self.phase_history.items()}
        if "metadata" in clean_keys:
            output["metadata"] = _sanitize_dict_secrets(self.metadata)

        # Artifact categories mapping
        artifact_category_aliases = {
            "specifications": {"specification", "spec", "specs", "schema"},
            "code_assets": {"code_workspace", "code", "backend", "frontend", "database_schema", "backend_api"},
            "research": {"deep_research", "market_trends", "domain_research"},
            "competitor_intelligence": {"competitor_analysis", "competitor_intel", "market_research"},
            "pricing": {"pricing_model", "pricing_strategy", "saas_tiers"},
            "simulation": {"simulation_result", "qa_test", "smoke_test"},
            "distribution": {"distribution_plan", "campaign_strategy", "outreach_sequence"},
            "deployment": {"deployment_bundle", "deployment_manifest", "live_service"},
            "health": {"health_config", "uptime_monitor", "health_check"},
        }

        # Full artifacts dictionary if explicitly requested
        if "artifacts" in clean_keys:
            output["artifacts"] = {aid: art.to_dict() for aid, art in self.artifacts.items()}

        # Filtered artifact category requests
        for req_key in clean_keys:
            if req_key in artifact_category_aliases:
                matched_types = artifact_category_aliases[req_key]
                category_artifacts = [
                    art.to_dict()
                    for art in self.artifacts.values()
                    if art.artifact_type in matched_types or req_key in art.artifact_type
                ]
                output[req_key] = category_artifacts
            elif req_key.startswith("artifacts."):
                sub_type = req_key.split(".", 1)[1]
                category_artifacts = [
                    art.to_dict()
                    for art in self.artifacts.values()
                    if art.artifact_type == sub_type or sub_type in art.artifact_type
                ]
                output[req_key] = category_artifacts

        return output

    # -------------------------------------------------------------------------
    # Controlled Context Update Methods
    # -------------------------------------------------------------------------

    def add_artifact(self, artifact: Artifact, allow_replace: bool = False) -> None:
        """
        Adds a structured artifact to the context.
        Raises ValueError if artifact_id already exists and allow_replace is False.
        """
        aid = artifact.artifact_id.strip()
        if not aid:
            raise ValueError("Artifact must have a non-empty artifact_id.")

        if aid in self.artifacts and not allow_replace:
            raise ValueError(f"Artifact with ID '{aid}' already exists. Set allow_replace=True to overwrite.")

        self.artifacts[aid] = artifact
        self.updated_at = _utc_now_iso()

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieves an Artifact by ID."""
        return self.artifacts.get(artifact_id.strip())

    def get_artifacts_by_type(self, artifact_type: str) -> List[Artifact]:
        """Retrieves all artifacts matching a given artifact_type."""
        t_clean = artifact_type.strip().lower()
        return [
            art for art in self.artifacts.values()
            if art.artifact_type.lower() == t_clean
        ]

    def get_artifacts_by_phase(self, phase_id: str) -> List[Artifact]:
        """Retrieves all artifacts produced in a given phase."""
        p_clean = phase_id.strip().lower()
        return [
            art for art in self.artifacts.values()
            if art.phase_id.lower() == p_clean
        ]

    def add_phase_outcome(self, outcome: PhaseOutcomeReference) -> None:
        """Records a phase outcome reference in phase_history."""
        self.phase_history[outcome.phase_id] = outcome
        self.updated_at = _utc_now_iso()

    def add_receipt(self, receipt: ReceiptReference) -> None:
        """Appends a verified external receipt reference."""
        self.receipts.append(receipt)
        self.updated_at = _utc_now_iso()

    def record_decision(
        self,
        decision: str,
        reason: str,
        source: str,
        phase_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        """
        Logs an architectural, design, or operational decision with full provenance.
        """
        entry = Decision(
            decision=decision.strip(),
            reason=reason.strip(),
            source=source.strip(),
            phase_id=phase_id,
            worker_id=worker_id,
            metadata=metadata or {},
        )
        self.decisions.append(entry)
        self.updated_at = _utc_now_iso()
        return entry

    def update_definition(
        self,
        target_users: Optional[str] = None,
        requirements: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        goal: Optional[str] = None,
    ) -> None:
        """Controlled update of project definition properties."""
        if target_users is not None:
            self.definition.target_users = str(target_users).strip()
        if requirements is not None:
            self.definition.requirements = list(requirements)
        if constraints is not None:
            self.definition.constraints = list(constraints)
        if acceptance_criteria is not None:
            self.definition.acceptance_criteria = list(acceptance_criteria)
        if goal is not None:
            self.definition.goal = str(goal).strip()
        self.updated_at = _utc_now_iso()

    def record_metadata(self, key: str, value: Any) -> None:
        """Sets a project-level metadata entry after secret sanitization."""
        self.metadata[key] = _sanitize_dict_secrets(value)
        self.updated_at = _utc_now_iso()

    # -------------------------------------------------------------------------
    # Serialization & Deserialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Returns a sanitized, secret-free JSON-safe dictionary."""
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectContext:
        """Deserializes a ProjectContext from a dictionary."""
        return cls.model_validate(_sanitize_dict_secrets(data))

    # -------------------------------------------------------------------------
    # Legacy / Current Database Projection Adapter
    # -------------------------------------------------------------------------

    @classmethod
    def from_existing_execution(
        cls,
        execution_id: str,
        db=None,
        user_id: str = "user_001",
    ) -> ProjectContext:
        """
        Projects an existing SQLite Execution + PhaseResults + ConnectorActions
        into a structured ProjectContext without altering authoritative database rows.
        """
        close_db = False
        if db is None:
            try:
                from database.models import SessionLocal
                db = SessionLocal()
                close_db = True
            except Exception:
                pass

        try:
            from database.models import Execution, PhaseResult, ConnectorAction

            exec_row = None
            if db is not None:
                exec_row = db.query(Execution).filter(Execution.id == execution_id).first()

            idea = exec_row.original_idea if exec_row and exec_row.original_idea else "Project Idea"
            goal = exec_row.understood_goal if exec_row and exec_row.understood_goal else idea

            defn = ProjectDefinition(
                idea=idea,
                goal=goal,
                target_users="",
                requirements=[],
                constraints=[],
                acceptance_criteria=[],
            )

            context = cls(
                project_id=f"proj_{execution_id[:12]}" if execution_id else f"proj_{uuid.uuid4().hex[:10]}",
                execution_id=execution_id,
                user_id=user_id,
                definition=defn,
            )

            if db is not None:
                # 1. Project PhaseResult outcomes
                phase_rows = db.query(PhaseResult).filter(PhaseResult.execution_id == execution_id).all()
                for pr in phase_rows:
                    pid = f"phase_{pr.phase_number}" if pr.phase_number else "phase_unknown"
                    p_name = pr.phase_name or f"Phase {pr.phase_number}"
                    context.add_phase_outcome(
                        PhaseOutcomeReference(
                            phase_id=pid,
                            phase_name=p_name,
                            status=pr.status or "COMPLETED",
                            result_reference=pr.id,
                            outcome_type=pr.outcome_type,
                            validation_score=pr.validation_score,
                            completed_at=pr.completed_at.isoformat() if pr.completed_at else None,
                        )
                    )

                    # Extract simulation artifact if present
                    if pr.simulation_result and isinstance(pr.simulation_result, dict):
                        context.add_artifact(
                            Artifact(
                                name=f"Simulation Result Phase {pr.phase_number}",
                                artifact_type="simulation_result",
                                phase_id=pid,
                                producer_worker="worker_qa_simulation",
                                content_summary=pr.simulation_result,
                                status="AVAILABLE",
                            ),
                            allow_replace=True,
                        )

                    # Extract distribution plan artifact if present
                    if pr.distribution_plan and isinstance(pr.distribution_plan, dict):
                        context.add_artifact(
                            Artifact(
                                name=f"Distribution Plan Phase {pr.phase_number}",
                                artifact_type="distribution_plan",
                                phase_id=pid,
                                producer_worker="worker_campaign",
                                content_summary=pr.distribution_plan,
                                status="AVAILABLE",
                            ),
                            allow_replace=True,
                        )

                # 2. Project ConnectorAction receipts
                action_rows = db.query(ConnectorAction).filter(ConnectorAction.execution_id == execution_id).all()
                for ca in action_rows:
                    res_dict = ca.result if isinstance(ca.result, dict) else {}
                    ext_id = res_dict.get("external_id")
                    permalink = res_dict.get("permalink") or res_dict.get("external_url")
                    is_verif = bool(res_dict.get("verified"))

                    context.add_receipt(
                        ReceiptReference(
                            receipt_id=ca.id,
                            platform=ca.connector_id,
                            action_type=ca.action,
                            external_id=ext_id,
                            permalink=permalink,
                            verified=is_verif,
                            verification_status="PASS" if is_verif else "FAIL",
                            evidence={"status": ca.status, "error": ca.error},
                            executed_at=ca.executed_at.isoformat() if ca.executed_at else _utc_now_iso(),
                        )
                    )

            return context

        finally:
            if close_db and db:
                db.close()
