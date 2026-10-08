"""
Tetris — Workforce Engine: Worker Registry (Stage 3)
===================================================

Provides canonical discovery, capability indexing, and metadata for all Tetris AI Workers:
1. WorkerDescriptor (Strongly-typed metadata and capability specification)
2. WorkerRegistry (Central index for capability, task-type, and phase-affinity discovery)
3. Default Pre-Registered Catalog (All 15 real Tetris worker specializations)

Architectural Rules:
- Discovery-first: Metadata inspection without unnecessary worker instantiation.
- Distinct separation between Capability (what a worker can do) and Connector Readiness (whether external credentials are connected).
- Additive and non-breaking: Preserves existing execution abstractions and BaseWorker contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. WorkerDescriptor: Metadata & Capability Manifest
# =============================================================================

class WorkerDescriptor(BaseModel):
    """
    Defines the capabilities, connector requirements, permissions, and metadata
    for an AI worker.
    """
    worker_id: str
    name: str
    role: str
    description: str = ""
    capabilities: List[str] = Field(default_factory=list)
    required_connectors: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    supported_task_types: List[str] = Field(default_factory=list)
    phase_affinity: List[str] = Field(default_factory=list)
    availability_status: str = "AVAILABLE"  # "AVAILABLE", "DISABLED", "MAINTENANCE"
    worker_class_path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def has_capability(self, capability: str) -> bool:
        """Checks if the worker possesses a specific capability (case-insensitive)."""
        cap_clean = str(capability).strip().lower()
        return any(c.lower() == cap_clean for c in self.capabilities)

    def matches_capabilities(self, required_capabilities: List[str]) -> List[str]:
        """Returns the list of required capabilities satisfied by this worker."""
        worker_caps = {c.lower() for c in self.capabilities}
        return [r for r in required_capabilities if r.strip().lower() in worker_caps]

    def has_connector(self, connector_name: str) -> bool:
        """Checks if the worker requires a specific connector."""
        conn_clean = str(connector_name).strip().lower()
        return any(c.lower() == conn_clean for c in self.required_connectors)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkerDescriptor:
        return cls.model_validate(data)


# =============================================================================
# 2. WorkerRegistry: Central Capability & Discovery Index
# =============================================================================

WORKER_ALIASES: Dict[str, str] = {
    "worker_db": "worker_database",
    "worker_qa": "worker_qa_simulation",
    "worker_sec": "worker_security",
    "worker_deploy": "worker_deployment",
    "worker_launch": "worker_launch_verification",
    "worker_launch_verify": "worker_launch_verification",
}


class WorkerRegistry:
    """
    Registry indexing worker descriptors for fast lookup by ID, capability,
    task type, or phase affinity.
    """

    def __init__(self):
        self._workers: Dict[str, WorkerDescriptor] = {}

    def register(
        self,
        descriptor: WorkerDescriptor,
        allow_override: bool = False,
    ) -> None:
        """
        Registers a worker descriptor.
        Raises ValueError if worker_id is already registered and allow_override is False.
        """
        wid = descriptor.worker_id.strip()
        if not wid:
            raise ValueError("WorkerDescriptor must have a non-empty worker_id.")

        if wid in self._workers and not allow_override:
            raise ValueError(f"Worker with ID '{wid}' is already registered. Set allow_override=True to update.")

        self._workers[wid] = descriptor

    def unregister(self, worker_id: str) -> bool:
        """Removes a worker from the registry. Returns True if found and removed."""
        wid = worker_id.strip()
        if wid in self._workers:
            del self._workers[wid]
            return True
        return False

    def get(self, worker_id: str) -> Optional[WorkerDescriptor]:
        """Retrieves a WorkerDescriptor by worker_id."""
        wid = worker_id.strip()
        if wid in self._workers:
            return self._workers[wid]
        alias = WORKER_ALIASES.get(wid)
        if alias and alias in self._workers:
            return self._workers[alias]
        return None

    def has_worker(self, worker_id: str) -> bool:
        """Checks if a worker ID is registered."""
        wid = worker_id.strip()
        return wid in self._workers or WORKER_ALIASES.get(wid) in self._workers

    def list_all(self, available_only: bool = False) -> List[WorkerDescriptor]:
        """Returns all registered worker descriptors."""
        if available_only:
            return [w for w in self._workers.values() if w.availability_status == "AVAILABLE"]
        return list(self._workers.values())

    def find_by_capability(self, capability: str) -> List[WorkerDescriptor]:
        """Finds all workers possessing a given capability."""
        cap_clean = str(capability).strip().lower()
        return [
            w for w in self._workers.values()
            if w.availability_status == "AVAILABLE" and any(c.lower() == cap_clean for c in w.capabilities)
        ]

    def find_for_capabilities(
        self,
        capabilities: List[str],
        match_all: bool = False,
    ) -> List[WorkerDescriptor]:
        """
        Finds workers matching required capabilities.
        If match_all is True, only workers satisfying ALL capabilities are returned.
        If match_all is False, workers satisfying ANY capability are returned.
        """
        req_clean = [c.strip().lower() for c in capabilities if c.strip()]
        if not req_clean:
            return []

        results = []
        for w in self._workers.values():
            if w.availability_status != "AVAILABLE":
                continue
            worker_caps = {c.lower() for c in w.capabilities}
            if match_all:
                if all(r in worker_caps for r in req_clean):
                    results.append(w)
            else:
                if any(r in worker_caps for r in req_clean):
                    results.append(w)
        return results

    def find_by_task_type(self, task_type: str) -> List[WorkerDescriptor]:
        """Finds all workers supporting a specific task type."""
        t_clean = str(task_type).strip().lower()
        return [
            w for w in self._workers.values()
            if w.availability_status == "AVAILABLE" and any(t.lower() == t_clean for t in w.supported_task_types)
        ]

    def find_by_phase_affinity(self, phase_name_or_id: str) -> List[WorkerDescriptor]:
        """Finds all workers with declared affinity for a specific phase."""
        p_clean = str(phase_name_or_id).strip().lower()
        return [
            w for w in self._workers.values()
            if w.availability_status == "AVAILABLE" and any(p.lower() == p_clean for p in w.phase_affinity)
        ]

    def count(self) -> int:
        return len(self._workers)


# =============================================================================
# 3. Default Pre-Registered Catalog (All 15 Tetris Real Worker Specializations)
# =============================================================================

def build_default_worker_descriptors() -> List[WorkerDescriptor]:
    """
    Constructs descriptors for all 15 real Tetris worker roles and capabilities.
    """
    return [
        # --- BUILD & CORE ASSET SYNTHESIS ---
        WorkerDescriptor(
            worker_id="worker_code",
            name="Code Builder & Backend Specialist",
            role="code_builder",
            description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
            capabilities=["code_generation", "backend", "fullstack", "api_development", "python", "node"],
            required_connectors=[],
            permissions=["filesystem:write", "workspace:edit"],
            supported_task_types=["write_code", "generate_api", "scaffold_backend"],
            phase_affinity=["build", "phase_build", "phase_1"],
            worker_class_path="agents.specialist.code_agent",
        ),
        WorkerDescriptor(
            worker_id="worker_ui",
            name="UI & Frontend Developer",
            role="ui_developer",
            description="Generates rich web interfaces, React/Vite components, and modern CSS design systems.",
            capabilities=["frontend", "ui_design", "react", "html_css", "web_components"],
            required_connectors=[],
            permissions=["filesystem:write"],
            supported_task_types=["build_ui", "generate_components", "style_page"],
            phase_affinity=["build", "phase_build", "phase_1"],
            worker_class_path="agents.specialist.code_agent",
        ),
        WorkerDescriptor(
            worker_id="worker_database",
            name="Database & Data Architect",
            role="database_architect",
            description="Models relational schemas, SQLite/PostgreSQL tables, migrations, and ORM entities.",
            capabilities=["database", "sql", "postgresql", "sqlite", "data_modeling", "schema_design"],
            required_connectors=[],
            permissions=["database:schema", "filesystem:write"],
            supported_task_types=["create_schema", "database_migration", "model_tables"],
            phase_affinity=["build", "phase_build", "phase_1"],
            worker_class_path="agents.specialist.code_agent",
        ),

        # --- VALIDATION, INTELLIGENCE & RESEARCH ---
        WorkerDescriptor(
            worker_id="worker_competitor_intel",
            name="Competitor Intelligence Specialist",
            role="competitor_analyst",
            description="Discovers live market competitors, feature gaps, and audience channels via Serper search.",
            capabilities=["competitor_analysis", "market_research", "serper_search", "distribution_intelligence"],
            required_connectors=["serper"],
            permissions=["network:read"],
            supported_task_types=["search_competitors", "analyze_market", "find_channels"],
            phase_affinity=["validate", "research", "phase_2", "phase_simulation"],
            worker_class_path="agents.specialist.competitor_intel_agent",
        ),
        WorkerDescriptor(
            worker_id="worker_research",
            name="Market & Domain Researcher",
            role="researcher",
            description="Conducts deep domain research, user pain point synthesis, and market trend reports.",
            capabilities=["deep_research", "market_trends", "domain_synthesis", "user_interviews"],
            required_connectors=[],
            permissions=["network:read"],
            supported_task_types=["research_topic", "synthesize_trends", "report_domain"],
            phase_affinity=["validate", "research", "phase_2"],
            worker_class_path="agents.specialist.research_agent",
        ),
        WorkerDescriptor(
            worker_id="worker_pricing",
            name="Pricing Strategy & Economics Worker",
            role="pricing_strategist",
            description="Designs value-based SaaS pricing models, tier structures, and unit economics calculations.",
            capabilities=["pricing_strategy", "unit_economics", "saas_tiers", "monetization"],
            required_connectors=[],
            permissions=[],
            supported_task_types=["model_pricing", "calculate_unit_economics", "design_tiers"],
            phase_affinity=["validate", "pricing", "phase_2"],
            worker_class_path="agents.specialist.pricing_agent",
        ),

        # --- QA, SIMULATION & SECURITY ---
        WorkerDescriptor(
            worker_id="worker_qa_simulation",
            name="QA & Behavioral Simulation Tester",
            role="qa_tester",
            description="Simulates runtime user traffic, stress tests webhooks, and verifies edge cases.",
            capabilities=["qa_testing", "behavioral_simulation", "payload_stress_test", "smoke_test"],
            required_connectors=[],
            permissions=["execution:test"],
            supported_task_types=["run_simulation", "test_payloads", "validate_endpoints"],
            phase_affinity=["simulation", "phase_simulation", "phase_2", "qa"],
            worker_class_path="simulation.engine",
        ),
        WorkerDescriptor(
            worker_id="worker_security",
            name="Security & Permission Auditor",
            role="security_auditor",
            description="Audits API contracts, secret redaction, credential isolation, and permission boundaries.",
            capabilities=["security_audit", "vulnerability_scan", "permission_check", "secret_redaction"],
            required_connectors=[],
            permissions=["audit:inspect"],
            supported_task_types=["audit_security", "check_permissions", "validate_secrets"],
            phase_affinity=["simulation", "security", "phase_2"],
            worker_class_path="agents.specialist.reviewer_agent",
        ),

        # --- MARKETING & DISTRIBUTION ---
        WorkerDescriptor(
            worker_id="worker_campaign",
            name="Marketing & Campaign Strategist",
            role="campaign_strategist",
            description="Produces multi-channel distribution plans, pitch copy, and targeted outreach sequences.",
            capabilities=["campaign_strategy", "copywriting", "content_generation", "launch_messaging"],
            required_connectors=[],
            permissions=[],
            supported_task_types=["plan_campaign", "write_copy", "generate_distribution_plan"],
            phase_affinity=["marketing", "distribution", "phase_3"],
            worker_class_path="agents.specialist.campaign_agent",
        ),
        WorkerDescriptor(
            worker_id="worker_reddit",
            name="Reddit Community Distribution Specialist",
            role="reddit_specialist",
            description="Executes authorized community posts and comment discussions on Reddit with verified receipts.",
            capabilities=["reddit_distribution", "reddit_post", "reddit_comment", "community_engagement"],
            required_connectors=["redditapis"],
            permissions=["network:write:approval_required"],
            supported_task_types=["post_reddit", "reply_to_post", "search_reddit"],
            phase_affinity=["marketing", "distribution", "phase_3"],
            worker_class_path="execution.reddit_executor",
        ),
        WorkerDescriptor(
            worker_id="worker_x",
            name="Twitter/X Social Growth Worker",
            role="x_specialist",
            description="Publishes product launches, update threads, and social announcements to Twitter/X.",
            capabilities=["x_distribution", "twitter_post", "social_growth", "tweet_thread"],
            required_connectors=["twitter"],
            permissions=["network:write:approval_required"],
            supported_task_types=["post_tweet", "create_thread"],
            phase_affinity=["marketing", "distribution", "phase_3"],
            worker_class_path="execution.x_executor",
        ),
        WorkerDescriptor(
            worker_id="worker_linkedin",
            name="LinkedIn B2B Outreach Specialist",
            role="linkedin_specialist",
            description="Publishes professional articles, founder updates, and B2B announcements to LinkedIn.",
            capabilities=["linkedin_distribution", "b2b_networking", "article_post", "company_update"],
            required_connectors=["linkedin"],
            permissions=["network:write:approval_required"],
            supported_task_types=["post_linkedin", "share_update"],
            phase_affinity=["marketing", "distribution", "phase_3"],
            worker_class_path="execution.linkedin_executor",
        ),
        WorkerDescriptor(
            worker_id="worker_email",
            name="Direct Email & Outreach Specialist",
            role="email_specialist",
            description="Sends validated outreach emails and beta invitations via SendGrid or SMTP with receipts.",
            capabilities=["email_outreach", "cold_email", "newsletter", "send_email"],
            required_connectors=["sendgrid", "smtp"],
            permissions=["network:write:approval_required"],
            supported_task_types=["send_email", "send_sequence"],
            phase_affinity=["marketing", "distribution", "phase_3"],
            worker_class_path="execution.email_executor",
        ),

        # --- DEPLOYMENT & OPERATIONS ---
        WorkerDescriptor(
            worker_id="worker_deployment",
            name="Hosting & Deployment Engineer",
            role="deployment_engineer",
            description="Prepares build packages, configures deployment manifests, and deploys to Vercel/cloud.",
            capabilities=["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            required_connectors=["vercel"],
            permissions=["deployment:execute"],
            supported_task_types=["prepare_deployment", "deploy_vercel", "build_production"],
            phase_affinity=["deployment", "launch", "phase_4"],
            worker_class_path="execution.vercel_executor",
        ),
        WorkerDescriptor(
            worker_id="worker_launch_verification",
            name="Live Launch Verification & Reachability Engineer",
            role="launch_verification_engineer",
            description="Performs live HTTP smoke checks, verifies reachability of deployed endpoints, and certifies live service status.",
            capabilities=["launch_verification", "live_smoke_test", "http_verification", "reachability_check"],
            required_connectors=[],
            permissions=["network:read"],
            supported_task_types=["verify_launch", "smoke_test_endpoint", "check_live_reachability"],
            phase_affinity=["launch_verification", "launch", "operate", "phase_4", "phase_5"],
            worker_class_path="orchestration.worker_runtime",
        ),
        WorkerDescriptor(
            worker_id="worker_health",
            name="Operational Health & Uptime Monitor",
            role="health_monitor",
            description="Monitors live endpoints, HTTP health status codes, response times, and recurring jobs.",
            capabilities=["health_monitoring", "endpoint_check", "synthetic_monitoring", "cron_inspection"],
            required_connectors=[],
            permissions=["network:read"],
            supported_task_types=["check_health", "monitor_endpoint", "report_uptime"],
            phase_affinity=["health", "operate", "phase_5"],
            worker_class_path="routes.health",
        ),
    ]


_DEFAULT_REGISTRY: Optional[WorkerRegistry] = None


def get_default_registry() -> WorkerRegistry:
    """
    Returns the singleton default WorkerRegistry populated with all 15 standard Tetris workers.
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        reg = WorkerRegistry()
        for desc in build_default_worker_descriptors():
            reg.register(desc)
        _DEFAULT_REGISTRY = reg
    return _DEFAULT_REGISTRY
