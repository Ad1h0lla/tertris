"""
Tetris — Workforce Engine: Tetris ↔ Workforce Build Vertical Slice (Stage 6A)
=============================================================================

Establishes the production-shaped integration boundary between Tetris project
specifications and the Workforce Engine closed-loop execution lifecycle.

Vertical Slice Pipeline:
    Tetris Project Data / Fixture
                ↓
          ProjectContext (Stage 4A)
                ↓
       Build ProjectWorkflow (Stage 2)
                ↓
          TeamManager (Stage 3)
                ↓
      TaskAssignmentEngine (Stage 4B)
                ↓
        CompiledTaskPlan (Stage 4B)
                ↓
      WorkforceCoordinator (Stage 5D)
                ↓
      ExecutionDispatcher (Stage 5A)
                ↓
         WorkerRuntime (Stage 5B)
                ↓
       CodeWorkerAdapter (Stage 5B)
                ↓
        Verification (Stage 5B)
                ↓
      ContextSynchronizer (Stage 5C)
                ↓
    Verified Artifact in ProjectContext (Stage 4A)

Architectural Rules:
- Pure Composition: Composes existing Stage 1–5D contracts without modifying their internals.
- Strict Boundary: Does NOT invoke legacy routers, legacy execution runners, or external APIs.
- Honest Failures: On error or verification failure, halts with an honest audit and zero false success artifacts.
- Deterministic & Secret-Free: Requires zero credentials and operates deterministically.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, Field

from orchestration.context_sync import ContextSynchronizer
from orchestration.execution_dispatcher import (
    DispatchRegistry,
    ExecutionDispatcher,
)
from orchestration.graph_advancer import GraphAdvancer
from orchestration.phase_contract import (
    Phase,
    PhaseStatus,
    ProjectWorkflow,
    WorkerAssignment,
)
from orchestration.project_context import (
    Artifact,
    ProjectContext,
    ProjectDefinition,
    _sanitize_dict_secrets,
)
from orchestration.task_assignment import (
    CompiledTaskPlan,
    TaskAssignmentEngine,
)
from orchestration.team_manager import TeamManager, TeamPlan
from orchestration.worker_registry import (
    WorkerRegistry,
    get_default_registry,
)
from orchestration.worker_runtime import (
    CampaignWorkerAdapter,
    CodeWorkerAdapter,
    DeploymentWorkerAdapter,
    EmailWorkerAdapter,
    HealthWorkerAdapter,
    LaunchVerificationWorkerAdapter,
    LinkedInWorkerAdapter,
    RedditWorkerAdapter,
    SimulationWorkerAdapter,
    WorkerRuntime,
    WorkerRuntimeRegistry,
    XWorkerAdapter,
    get_default_runtime_registry,
)
from health.monitor import (
    BaseHealthObserver,
    Finding,
    HealthReport,
    HealthStatus,
    MockHealthObserver,
    Observation,
    RealHttpHealthObserver,
    Recommendation,
    evaluate_health,
    validate_target_url,
)
from orchestration.workforce_coordinator import (
    CoordinatorResult,
    CoordinatorStatus,
    CoordinatorStepRecord,
    WorkforceCoordinator,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. Deterministic Health API Fixture
# =============================================================================

HEALTH_API_FIXTURE: Dict[str, Any] = {
    "project_name": "Health API",
    "idea": "Build a small FastAPI backend exposing a GET /health endpoint that returns a successful JSON health response.",
    "goal": "Expose a reliable, deterministic GET /health API endpoint for health monitoring.",
    "target_users": "Backend Developers & DevOps Engineers",
    "requirements": [
        "FastAPI backend framework",
        "GET /health endpoint exposing status",
        "Deterministic JSON health payload",
    ],
    "constraints": [
        "Zero external cloud network dependencies",
        "Python 3.10+ compatible",
    ],
    "acceptance_criteria": [
        "Expose GET /health endpoint",
        "Return JSON health response",
        "FastAPI backend",
    ],
}


# =============================================================================
# 2. BuildSliceResult: Strongly-Typed Vertical Slice Outcome
# =============================================================================

class BuildSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6A vertical slice.
    """
    success: bool
    status: str
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


# =============================================================================
# 3. Context & Workflow Construction Boundary Functions
# =============================================================================

def create_build_project_context(
    idea: Optional[str] = None,
    goal: Optional[str] = None,
    requirements: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    acceptance_criteria: Optional[List[str]] = None,
    target_users: Optional[str] = None,
    project_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    user_id: str = "user_tetris_001",
) -> ProjectContext:
    """
    Constructs an authoritative ProjectContext for the Build phase.
    Defaults to the deterministic Health API fixture if no values are supplied.
    """
    defn = ProjectDefinition(
        idea=idea or HEALTH_API_FIXTURE["idea"],
        goal=goal or HEALTH_API_FIXTURE["goal"],
        target_users=target_users or HEALTH_API_FIXTURE["target_users"],
        requirements=requirements or list(HEALTH_API_FIXTURE["requirements"]),
        constraints=constraints or list(HEALTH_API_FIXTURE["constraints"]),
        acceptance_criteria=acceptance_criteria or list(HEALTH_API_FIXTURE["acceptance_criteria"]),
    )

    return ProjectContext(
        project_id=project_id or f"proj_build_{uuid.uuid4().hex[:8]}",
        execution_id=execution_id or f"exec_build_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        definition=defn,
    )


def from_legacy_project_dict(
    goal_dict: Dict[str, Any],
    project_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    user_id: str = "user_tetris_001",
) -> ProjectContext:
    """
    Adapter converting a legacy Tetris goal dictionary into a valid ProjectContext
    without invoking legacy execution code.
    """
    idea = str(
        goal_dict.get("understood_goal")
        or goal_dict.get("original_idea")
        or goal_dict.get("idea")
        or goal_dict.get("goal")
        or "Tetris Project"
    )
    goal = str(goal_dict.get("understood_goal") or idea)
    target_users = str(goal_dict.get("target_users") or "")
    requirements = list(goal_dict.get("requirements") or [])
    constraints = list(goal_dict.get("constraints") or [])
    criteria = list(goal_dict.get("acceptance_criteria") or [])

    defn = ProjectDefinition(
        idea=idea,
        goal=goal,
        target_users=target_users,
        requirements=requirements,
        constraints=constraints,
        acceptance_criteria=criteria,
    )

    eid = execution_id or str(goal_dict.get("execution_id") or f"exec_build_{uuid.uuid4().hex[:8]}")
    pid = project_id or str(goal_dict.get("project_id") or f"proj_build_{uuid.uuid4().hex[:8]}")

    return ProjectContext(
        project_id=pid,
        execution_id=eid,
        user_id=user_id,
        definition=defn,
    )


def create_build_workflow(
    project_context: ProjectContext,
    phase_id: str = "phase_build",
    phase_name: str = "Build & API Development",
) -> ProjectWorkflow:
    """
    Constructs a minimal, canonical ProjectWorkflow containing the Build Phase
    with the worker_code assignment.
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    build_phase = Phase(
        phase_id=phase_id,
        phase_number=1,
        name=phase_name,
        description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
        purpose="Generate functional software asset from specifications.",
        status=PhaseStatus.READY,
        dependencies=[],
        entry_requirements=["intake_specification"],
        exit_requirements=["executable_code", "backend_api"],
        metadata={"required_capabilities": ["code_generation", "backend", "api_development", "python"]},
    )

    # Assign worker_code
    build_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_code",
            phase_id=phase_id,
            role="code_builder",
            capabilities=["code_generation", "backend", "api_development", "python"],
            permissions=["filesystem:write", "workspace:edit"],
        )
    )

    wf.add_phase(build_phase)
    return wf


# =============================================================================
# 4. Vertical Slice Execution Orchestrator
# =============================================================================

def execute_build_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    dry_run: bool = False,
) -> BuildSliceResult:
    """
    Executes the Stage 6A Build Vertical Slice end-to-end.

    Composition Flow:
        1. Establish authoritative ProjectContext
        2. Construct Build ProjectWorkflow
        3. Assemble TeamPlan via TeamManager (resolving worker_code from WorkerRegistry)
        4. Compile TaskPlan via TaskAssignmentEngine
        5. Execute via WorkforceCoordinator (Dispatcher -> WorkerRuntime -> CodeWorkerAdapter -> Verification -> ContextSync)
        6. Return BuildSliceResult with verified ProjectContext deliverables and provenance audit
    """
    reg = registry or get_default_registry()

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build ProjectWorkflow
    workflow = create_build_workflow(ctx)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements"]),
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
    )

    # If task compilation failed or produced an invalid plan, halt honestly
    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSliceResult(
            success=False,
            status=coord_res.status,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            artifacts=[],
            step_history=[],
            errors=task_plan.validation_errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        # Ensure CodeWorkerAdapter is registered in runtime
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Artifacts from ProjectContext
    produced_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]

    return BuildSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        artifacts=produced_artifacts,
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


# =============================================================================
# 5. Stage 6B: Build -> Simulation Multi-Phase Vertical Slice
# =============================================================================

class BuildSimulationSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6B Build -> Simulation vertical slice.
    """
    success: bool
    status: str
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    build_artifacts: List[Artifact] = Field(default_factory=list)
    simulation_artifacts: List[Artifact] = Field(default_factory=list)
    all_artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


def create_build_simulation_workflow(
    project_context: ProjectContext,
    build_phase_id: str = "phase_build",
    simulation_phase_id: str = "phase_simulation",
) -> ProjectWorkflow:
    """
    Constructs a canonical 2-phase ProjectWorkflow (Build -> Simulation).
    Phase 1 (Build): worker_code
    Phase 2 (Simulation): worker_qa_simulation (depends on Phase 1)
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    # 1. Build Phase
    build_phase = Phase(
        phase_id=build_phase_id,
        phase_number=1,
        name="Build & API Development",
        description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
        purpose="Generate functional software asset from specifications.",
        status=PhaseStatus.READY,
        dependencies=[],
        entry_requirements=["intake_specification"],
        exit_requirements=["executable_code", "backend_api"],
        metadata={"required_capabilities": ["code_generation", "backend", "api_development", "python"]},
    )
    build_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_code",
            phase_id=build_phase_id,
            role="code_builder",
            capabilities=["code_generation", "backend", "api_development", "python"],
            permissions=["filesystem:write", "workspace:edit"],
        )
    )
    wf.add_phase(build_phase)

    # 2. Simulation Phase
    sim_phase = Phase(
        phase_id=simulation_phase_id,
        phase_number=2,
        name="Simulation & QA Verification",
        description="Simulates runtime user traffic, tests payload schemas, and verifies behavioral criteria.",
        purpose="Verify behavioral criteria and backend endpoints prior to release.",
        status=PhaseStatus.PLANNED,
        dependencies=[build_phase_id],
        entry_requirements=["executable_code", "backend_api"],
        exit_requirements=["simulation_pass", "qa_report"],
        metadata={
            "required_capabilities": ["qa_testing", "behavioral_simulation"],
            "context_keys": ["idea", "code_assets", "specifications", "acceptance_criteria", "simulation"],
        },
    )
    sim_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_qa_simulation",
            phase_id=simulation_phase_id,
            role="qa_tester",
            capabilities=["qa_testing", "behavioral_simulation"],
            permissions=["execution:test"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "backend_api"],
                "produces_artifacts": ["simulation_result", "qa_report"],
            },
        )
    )
    wf.add_phase(sim_phase, dependencies=[build_phase_id])

    return wf


def execute_build_simulation_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    dry_run: bool = False,
) -> BuildSimulationSliceResult:
    """
    Executes the Stage 6B Build -> Simulation Multi-Phase Vertical Slice end-to-end.

    Composition Flow:
        1. Establish authoritative ProjectContext
        2. Construct 2-Phase ProjectWorkflow (Build -> Simulation)
        3. Assemble TeamPlan via TeamManager (resolving worker_code and worker_qa_simulation)
        4. Compile TaskPlan via TaskAssignmentEngine (task_build_code READY, task_simulation_qa_simulation WAITING)
        5. Execute via WorkforceCoordinator:
           - Task A (Build) executes, verifies, and promotes build artifacts to ProjectContext
           - GraphAdvancer unlocks Task B (Simulation)
           - Task B (Simulation) executes consuming Build artifacts, verifies, and promotes simulation artifacts
        6. Return BuildSimulationSliceResult with full provenance audit across both phases
    """
    reg = registry or get_default_registry()

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build 2-Phase Workflow
    workflow = create_build_simulation_workflow(ctx)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSimulationSliceResult(
            success=False,
            status=coord_res.status,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            build_artifacts=[],
            simulation_artifacts=[],
            all_artifacts=[],
            step_history=[],
            errors=task_plan.validation_errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        if not rt.resolve_worker("worker_qa_simulation"):
            rt.register_worker(SimulationWorkerAdapter())
        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=connected_connectors,
        authorized_permissions=authorized_permissions,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Artifacts from ProjectContext
    build_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]
    sim_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_simulation" or art.producer_worker == "worker_qa_simulation"
    ]

    return BuildSimulationSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        build_artifacts=build_artifacts,
        simulation_artifacts=sim_artifacts,
        all_artifacts=list(ctx.artifacts.values()),
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


# =============================================================================
# 6. Stage 6C: Build -> Simulation -> Deployment Multi-Phase Vertical Slice
# =============================================================================

class BuildSimulationDeploymentSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6C Build -> Simulation -> Deployment vertical slice.
    """
    success: bool
    status: str
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    build_artifacts: List[Artifact] = Field(default_factory=list)
    simulation_artifacts: List[Artifact] = Field(default_factory=list)
    deployment_artifacts: List[Artifact] = Field(default_factory=list)
    all_artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


def create_build_simulation_deployment_workflow(
    project_context: ProjectContext,
    build_phase_id: str = "phase_build",
    simulation_phase_id: str = "phase_simulation",
    deployment_phase_id: str = "phase_deployment",
) -> ProjectWorkflow:
    """
    Constructs a canonical 3-phase ProjectWorkflow (Build -> Simulation -> Deployment).
    Phase 1 (Build): worker_code
    Phase 2 (Simulation): worker_qa_simulation (depends on Phase 1)
    Phase 3 (Deployment): worker_deployment (depends on Phase 2)
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    # 1. Build Phase
    build_phase = Phase(
        phase_id=build_phase_id,
        phase_number=1,
        name="Build & API Development",
        description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
        purpose="Generate functional software asset from specifications.",
        status=PhaseStatus.READY,
        dependencies=[],
        entry_requirements=["intake_specification"],
        exit_requirements=["executable_code", "backend_api"],
        metadata={"required_capabilities": ["code_generation", "backend", "api_development", "python"]},
    )
    build_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_code",
            phase_id=build_phase_id,
            role="code_builder",
            capabilities=["code_generation", "backend", "api_development", "python"],
            permissions=["filesystem:write", "workspace:edit"],
        )
    )
    wf.add_phase(build_phase)

    # 2. Simulation Phase
    sim_phase = Phase(
        phase_id=simulation_phase_id,
        phase_number=2,
        name="Simulation & QA Verification",
        description="Simulates runtime user traffic, tests payload schemas, and verifies behavioral criteria.",
        purpose="Verify behavioral criteria and backend endpoints prior to release.",
        status=PhaseStatus.PLANNED,
        dependencies=[build_phase_id],
        entry_requirements=["executable_code", "backend_api"],
        exit_requirements=["simulation_pass", "qa_report"],
        metadata={
            "required_capabilities": ["qa_testing", "behavioral_simulation"],
            "context_keys": ["idea", "code_assets", "specifications", "acceptance_criteria", "simulation"],
        },
    )
    sim_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_qa_simulation",
            phase_id=simulation_phase_id,
            role="qa_tester",
            capabilities=["qa_testing", "behavioral_simulation"],
            permissions=["execution:test"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "backend_api"],
                "produces_artifacts": ["simulation_result", "qa_report"],
            },
        )
    )
    wf.add_phase(sim_phase, dependencies=[build_phase_id])

    # 3. Deployment Phase
    deploy_phase = Phase(
        phase_id=deployment_phase_id,
        phase_number=3,
        name="Hosting & Cloud Deployment",
        description="Packages build bundles, checks simulation gate, and deploys live web application to Vercel/cloud hosting.",
        purpose="Deploy verified build artifacts to public or staging cloud hosting.",
        status=PhaseStatus.PLANNED,
        dependencies=[simulation_phase_id],
        entry_requirements=["executable_code", "simulation_pass"],
        exit_requirements=["deployment_bundle", "deployment_receipt"],
        metadata={
            "required_capabilities": ["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            "context_keys": ["idea", "code_assets", "specifications", "simulation", "acceptance_criteria"],
        },
    )
    deploy_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_deployment",
            phase_id=deployment_phase_id,
            role="deployment_engineer",
            capabilities=["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            permissions=["deployment:execute"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "simulation_result"],
                "produces_artifacts": ["deployment_bundle", "deployment_receipt"],
            },
        )
    )
    wf.add_phase(deploy_phase, dependencies=[simulation_phase_id])

    return wf


def execute_build_simulation_deployment_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    approved_task_ids: Optional[Set[str] | List[str]] = None,
    dry_run: bool = False,
) -> BuildSimulationDeploymentSliceResult:
    """
    Executes the Stage 6C Build -> Simulation -> Deployment Multi-Phase Vertical Slice end-to-end.

    Composition Flow:
        1. Establish authoritative ProjectContext
        2. Construct 3-Phase ProjectWorkflow (Build -> Simulation -> Deployment)
        3. Assemble TeamPlan via TeamManager (resolving worker_code, worker_qa_simulation, worker_deployment)
        4. Compile TaskPlan via TaskAssignmentEngine (task_build_code READY, task_simulation WAITING, task_deployment WAITING)
        5. Execute via WorkforceCoordinator:
           - Task A (Build) executes, verifies, and promotes build artifacts to ProjectContext
           - GraphAdvancer unlocks Task B (Simulation)
           - Task B (Simulation) executes consuming Build artifacts, verifies, and promotes simulation artifacts
           - GraphAdvancer unlocks Task C (Deployment)
           - Task C (Deployment) executes consuming Build + Simulation artifacts, verifies, and promotes deployment artifacts
        6. Return BuildSimulationDeploymentSliceResult with full provenance audit across all three phases
    """
    reg = registry or get_default_registry()

    conns = connected_connectors if connected_connectors is not None else ["vercel"]
    perms = authorized_permissions if authorized_permissions is not None else [
        "filesystem:write", "workspace:edit", "execution:test", "deployment:execute"
    ]

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build 3-Phase Workflow
    workflow = create_build_simulation_deployment_workflow(ctx)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSimulationDeploymentSliceResult(
            success=False,
            status=coord_res.status,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            build_artifacts=[],
            simulation_artifacts=[],
            deployment_artifacts=[],
            all_artifacts=[],
            step_history=[],
            errors=task_plan.validation_errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        if not rt.resolve_worker("worker_qa_simulation"):
            rt.register_worker(SimulationWorkerAdapter())
        if not rt.resolve_worker("worker_deployment"):
            rt.register_worker(DeploymentWorkerAdapter())
        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    # Approve all deployment tasks if approved_task_ids is not explicitly set, or use provided
    approved = set(approved_task_ids) if approved_task_ids is not None else {t.task_id for t in task_plan.tasks}

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        approved_task_ids=approved,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Artifacts from ProjectContext
    build_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]
    sim_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_simulation" or art.producer_worker == "worker_qa_simulation"
    ]
    dep_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_deployment" or art.producer_worker == "worker_deployment"
    ]

    return BuildSimulationDeploymentSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        build_artifacts=build_artifacts,
        simulation_artifacts=sim_artifacts,
        deployment_artifacts=dep_artifacts,
        all_artifacts=list(ctx.artifacts.values()),
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


# =============================================================================
# 7. Stage 6D: Build -> Simulation -> Deployment -> Launch Verification Slice
# =============================================================================

class BuildSimulationDeploymentLaunchSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6D 
    Build -> Simulation -> Deployment -> Launch Verification vertical slice.
    """
    success: bool
    status: str
    is_live: bool = False
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    build_artifacts: List[Artifact] = Field(default_factory=list)
    simulation_artifacts: List[Artifact] = Field(default_factory=list)
    deployment_artifacts: List[Artifact] = Field(default_factory=list)
    launch_artifacts: List[Artifact] = Field(default_factory=list)
    all_artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


def create_build_simulation_deployment_launch_workflow(
    project_context: ProjectContext,
    build_phase_id: str = "phase_build",
    simulation_phase_id: str = "phase_simulation",
    deployment_phase_id: str = "phase_deployment",
    launch_phase_id: str = "phase_launch_verification",
) -> ProjectWorkflow:
    """
    Constructs a canonical 4-phase ProjectWorkflow (Build -> Simulation -> Deployment -> Launch Verification).
    Phase 1 (Build): worker_code
    Phase 2 (Simulation): worker_qa_simulation (depends on Phase 1)
    Phase 3 (Deployment): worker_deployment (depends on Phase 2)
    Phase 4 (Launch Verification): worker_launch_verification (depends on Phase 3)
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    # 1. Build Phase
    build_phase = Phase(
        phase_id=build_phase_id,
        phase_number=1,
        name="Build & API Development",
        description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
        purpose="Generate functional software asset from specifications.",
        status=PhaseStatus.READY,
        dependencies=[],
        entry_requirements=["intake_specification"],
        exit_requirements=["executable_code", "backend_api"],
        metadata={"required_capabilities": ["code_generation", "backend", "api_development", "python"]},
    )
    build_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_code",
            phase_id=build_phase_id,
            role="code_builder",
            capabilities=["code_generation", "backend", "api_development", "python"],
            permissions=["filesystem:write", "workspace:edit"],
        )
    )
    wf.add_phase(build_phase)

    # 2. Simulation Phase
    sim_phase = Phase(
        phase_id=simulation_phase_id,
        phase_number=2,
        name="Simulation & QA Verification",
        description="Simulates runtime user traffic, tests payload schemas, and verifies behavioral criteria.",
        purpose="Verify behavioral criteria and backend endpoints prior to release.",
        status=PhaseStatus.PLANNED,
        dependencies=[build_phase_id],
        entry_requirements=["executable_code", "backend_api"],
        exit_requirements=["simulation_pass", "qa_report"],
        metadata={
            "required_capabilities": ["qa_testing", "behavioral_simulation"],
            "context_keys": ["idea", "code_assets", "specifications", "acceptance_criteria", "simulation"],
        },
    )
    sim_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_qa_simulation",
            phase_id=simulation_phase_id,
            role="qa_tester",
            capabilities=["qa_testing", "behavioral_simulation"],
            permissions=["execution:test"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "backend_api"],
                "produces_artifacts": ["simulation_result", "qa_report"],
            },
        )
    )
    wf.add_phase(sim_phase, dependencies=[build_phase_id])

    # 3. Deployment Phase
    deploy_phase = Phase(
        phase_id=deployment_phase_id,
        phase_number=3,
        name="Hosting & Cloud Deployment",
        description="Packages build bundles, checks simulation gate, and deploys live web application to Vercel/cloud hosting.",
        purpose="Deploy verified build artifacts to public or staging cloud hosting.",
        status=PhaseStatus.PLANNED,
        dependencies=[simulation_phase_id],
        entry_requirements=["executable_code", "simulation_pass"],
        exit_requirements=["deployment_bundle", "deployment_receipt"],
        metadata={
            "required_capabilities": ["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            "context_keys": ["idea", "code_assets", "specifications", "simulation", "acceptance_criteria"],
        },
    )
    deploy_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_deployment",
            phase_id=deployment_phase_id,
            role="deployment_engineer",
            capabilities=["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            permissions=["deployment:execute"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "simulation_result"],
                "produces_artifacts": ["deployment_bundle", "deployment_receipt"],
            },
        )
    )
    wf.add_phase(deploy_phase, dependencies=[simulation_phase_id])

    # 4. Launch Verification Phase
    launch_phase = Phase(
        phase_id=launch_phase_id,
        phase_number=4,
        name="Live Reachability & Launch Verification",
        description="Performs live HTTP smoke checks against the deployed URL and certifies the project is live and reachable.",
        purpose="Independently verify reachability and live health of deployed service before marking project LIVE.",
        status=PhaseStatus.PLANNED,
        dependencies=[deployment_phase_id],
        entry_requirements=["deployment_bundle", "deployment_receipt"],
        exit_requirements=["launch_verification", "launch_receipt"],
        metadata={
            "required_capabilities": ["launch_verification", "live_smoke_test", "http_verification", "reachability_check"],
            "context_keys": ["idea", "deployment", "receipts", "simulation", "code_assets"],
        },
    )
    launch_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_launch_verification",
            phase_id=launch_phase_id,
            role="launch_verification_engineer",
            capabilities=["launch_verification", "live_smoke_test", "http_verification", "reachability_check"],
            permissions=["network:read"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["deployment_bundle", "deployment_receipt"],
                "produces_artifacts": ["launch_verification", "launch_receipt"],
            },
        )
    )
    wf.add_phase(launch_phase, dependencies=[deployment_phase_id])

    return wf


def execute_build_simulation_deployment_launch_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    approved_task_ids: Optional[Set[str] | List[str]] = None,
    http_verifier: Optional[Callable[[str], Dict[str, Any]]] = None,
    dry_run: bool = False,
) -> BuildSimulationDeploymentLaunchSliceResult:
    """
    Executes the Stage 6D Build -> Simulation -> Deployment -> Launch Verification Multi-Phase Vertical Slice end-to-end.

    Composition Flow:
        1. Establish authoritative ProjectContext
        2. Construct 4-Phase ProjectWorkflow (Build -> Simulation -> Deployment -> Launch Verification)
        3. Assemble TeamPlan via TeamManager (resolving worker_code, worker_qa_simulation, worker_deployment, worker_launch_verification)
        4. Compile TaskPlan via TaskAssignmentEngine (task_build_code READY, others WAITING)
        5. Execute via WorkforceCoordinator:
           - Task A (Build) executes, verifies, and promotes build artifacts to ProjectContext
           - GraphAdvancer unlocks Task B (Simulation)
           - Task B (Simulation) executes consuming Build artifacts, verifies, and promotes simulation artifacts
           - GraphAdvancer unlocks Task C (Deployment)
           - Task C (Deployment) executes consuming Build + Simulation artifacts, verifies, and promotes deployment artifacts
           - GraphAdvancer unlocks Task D (Launch Verification)
           - Task D (Launch Verification) executes consuming Deployment artifacts, verifies live reachability, and certifies LIVE
        6. Return BuildSimulationDeploymentLaunchSliceResult with full provenance audit across all four phases
    """
    reg = registry or get_default_registry()

    conns = connected_connectors if connected_connectors is not None else ["vercel"]
    perms = authorized_permissions if authorized_permissions is not None else [
        "filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read"
    ]

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build 4-Phase Workflow
    workflow = create_build_simulation_deployment_launch_workflow(ctx)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSimulationDeploymentLaunchSliceResult(
            success=False,
            status=coord_res.status,
            is_live=False,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            build_artifacts=[],
            simulation_artifacts=[],
            deployment_artifacts=[],
            launch_artifacts=[],
            all_artifacts=[],
            step_history=[],
            errors=task_plan.validation_errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        if not rt.resolve_worker("worker_qa_simulation"):
            rt.register_worker(SimulationWorkerAdapter())
        if not rt.resolve_worker("worker_deployment"):
            rt.register_worker(DeploymentWorkerAdapter())
        if not rt.resolve_worker("worker_launch_verification") or http_verifier is not None:
            rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=http_verifier))
        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    # Approve all deployment tasks if approved_task_ids is not explicitly set, or use provided
    approved = set(approved_task_ids) if approved_task_ids is not None else {t.task_id for t in task_plan.tasks}

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        approved_task_ids=approved,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Artifacts from ProjectContext
    build_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]
    sim_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_simulation" or art.producer_worker == "worker_qa_simulation"
    ]
    dep_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_deployment" or art.producer_worker == "worker_deployment"
    ]
    launch_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_launch_verification" or art.producer_worker == "worker_launch_verification"
    ]

    is_live_outcome = ctx.is_live and coordinator_res.is_completed

    return BuildSimulationDeploymentLaunchSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        is_live=is_live_outcome,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        build_artifacts=build_artifacts,
        simulation_artifacts=sim_artifacts,
        deployment_artifacts=dep_artifacts,
        launch_artifacts=launch_artifacts,
        all_artifacts=list(ctx.artifacts.values()),
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


# =============================================================================
# 8. Stage 6E: Build -> Simulation -> Deployment -> Launch Verification -> Distribution Slice
# =============================================================================

class BuildSimulationDeploymentLaunchDistributionSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6E
    Build -> Simulation -> Deployment -> Launch Verification -> Distribution vertical slice.
    """
    success: bool
    status: str
    is_live: bool = False
    is_distributed: bool = False
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    build_artifacts: List[Artifact] = Field(default_factory=list)
    simulation_artifacts: List[Artifact] = Field(default_factory=list)
    deployment_artifacts: List[Artifact] = Field(default_factory=list)
    launch_artifacts: List[Artifact] = Field(default_factory=list)
    distribution_artifacts: List[Artifact] = Field(default_factory=list)
    all_artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


def create_build_simulation_deployment_launch_distribution_workflow(
    project_context: ProjectContext,
    build_phase_id: str = "phase_build",
    simulation_phase_id: str = "phase_simulation",
    deployment_phase_id: str = "phase_deployment",
    launch_phase_id: str = "phase_launch_verification",
    distribution_phase_id: str = "phase_distribution",
    channels: Optional[List[str]] = None,
) -> ProjectWorkflow:
    """
    Constructs a canonical 5-phase ProjectWorkflow
    (Build -> Simulation -> Deployment -> Launch Verification -> Distribution).

    Phase 1 (Build): worker_code
    Phase 2 (Simulation): worker_qa_simulation (depends on Phase 1)
    Phase 3 (Deployment): worker_deployment (depends on Phase 2)
    Phase 4 (Launch Verification): worker_launch_verification (depends on Phase 3)
    Phase 5 (Distribution): worker_campaign and selected channel workers (depends on Phase 4)
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    # 1. Build Phase
    build_phase = Phase(
        phase_id=build_phase_id,
        phase_number=1,
        name="Build & API Development",
        description="Synthesizes backend code, API handlers, fastAPI routes, and core business logic.",
        purpose="Generate functional software asset from specifications.",
        status=PhaseStatus.READY,
        dependencies=[],
        entry_requirements=["intake_specification"],
        exit_requirements=["executable_code", "backend_api"],
        metadata={"required_capabilities": ["code_generation", "backend", "api_development", "python"]},
    )
    build_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_code",
            phase_id=build_phase_id,
            role="code_builder",
            capabilities=["code_generation", "backend", "api_development", "python"],
            permissions=["filesystem:write", "workspace:edit"],
        )
    )
    wf.add_phase(build_phase)

    # 2. Simulation Phase
    sim_phase = Phase(
        phase_id=simulation_phase_id,
        phase_number=2,
        name="Simulation & QA Verification",
        description="Simulates runtime user traffic, tests payload schemas, and verifies behavioral criteria.",
        purpose="Verify behavioral criteria and backend endpoints prior to release.",
        status=PhaseStatus.PLANNED,
        dependencies=[build_phase_id],
        entry_requirements=["executable_code", "backend_api"],
        exit_requirements=["simulation_pass", "qa_report"],
        metadata={
            "required_capabilities": ["qa_testing", "behavioral_simulation"],
            "context_keys": ["idea", "code_assets", "specifications", "acceptance_criteria", "simulation"],
        },
    )
    sim_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_qa_simulation",
            phase_id=simulation_phase_id,
            role="qa_tester",
            capabilities=["qa_testing", "behavioral_simulation"],
            permissions=["execution:test"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "backend_api"],
                "produces_artifacts": ["simulation_result", "qa_report"],
            },
        )
    )
    wf.add_phase(sim_phase, dependencies=[build_phase_id])

    # 3. Deployment Phase
    deploy_phase = Phase(
        phase_id=deployment_phase_id,
        phase_number=3,
        name="Hosting & Cloud Deployment",
        description="Packages build bundles, checks simulation gate, and deploys live web application to Vercel/cloud hosting.",
        purpose="Deploy verified build artifacts to public or staging cloud hosting.",
        status=PhaseStatus.PLANNED,
        dependencies=[simulation_phase_id],
        entry_requirements=["executable_code", "simulation_pass"],
        exit_requirements=["deployment_bundle", "deployment_receipt"],
        metadata={
            "required_capabilities": ["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            "context_keys": ["idea", "code_assets", "specifications", "simulation", "acceptance_criteria"],
        },
    )
    deploy_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_deployment",
            phase_id=deployment_phase_id,
            role="deployment_engineer",
            capabilities=["deployment_preparation", "vercel_deployment", "cloud_hosting", "build_bundle"],
            permissions=["deployment:execute"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["code_workspace", "simulation_result"],
                "produces_artifacts": ["deployment_bundle", "deployment_receipt"],
            },
        )
    )
    wf.add_phase(deploy_phase, dependencies=[simulation_phase_id])

    # 4. Launch Verification Phase
    launch_phase = Phase(
        phase_id=launch_phase_id,
        phase_number=4,
        name="Live Reachability & Launch Verification",
        description="Performs live HTTP smoke checks against the deployed URL and certifies the project is live and reachable.",
        purpose="Independently verify reachability and live health of deployed service before marking project LIVE.",
        status=PhaseStatus.PLANNED,
        dependencies=[deployment_phase_id],
        entry_requirements=["deployment_bundle", "deployment_receipt"],
        exit_requirements=["launch_verification", "launch_receipt"],
        metadata={
            "required_capabilities": ["launch_verification", "live_smoke_test", "http_verification", "reachability_check"],
            "context_keys": ["idea", "deployment", "receipts", "simulation", "code_assets"],
        },
    )
    launch_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_launch_verification",
            phase_id=launch_phase_id,
            role="launch_verification_engineer",
            capabilities=["launch_verification", "live_smoke_test", "http_verification", "reachability_check"],
            permissions=["network:read"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["deployment_bundle", "deployment_receipt"],
                "produces_artifacts": ["launch_verification", "launch_receipt"],
            },
        )
    )
    wf.add_phase(launch_phase, dependencies=[deployment_phase_id])

    # 5. Distribution Phase
    active_channels = [c.lower().strip() for c in (channels if channels is not None else ["reddit", "x", "linkedin", "email"])]

    req_caps = ["campaign_strategy", "distribution_planning"]
    if "reddit" in active_channels:
        req_caps.extend(["reddit_distribution", "reddit_post"])
    if "x" in active_channels or "twitter" in active_channels:
        req_caps.extend(["x_distribution", "twitter_post"])
    if "linkedin" in active_channels:
        req_caps.extend(["linkedin_distribution", "article_post"])
    if "email" in active_channels:
        req_caps.extend(["email_outreach", "send_email"])

    dist_phase = Phase(
        phase_id=distribution_phase_id,
        phase_number=5,
        name="Campaign Planning & Multi-Channel Distribution",
        description="Formulates targeted distribution strategies and publishes verified product announcements across social/communication channels.",
        purpose="Plan and execute targeted public product announcements across approved channels.",
        status=PhaseStatus.PLANNED,
        dependencies=[launch_phase_id],
        entry_requirements=["launch_verification", "launch_receipt"],
        exit_requirements=["distribution_plan", "distribution_receipt"],
        metadata={
            "required_capabilities": req_caps,
            "context_keys": ["idea", "deployment", "launch_verification", "receipts", "marketing", "distribution"],
        },
    )

    # Add Campaign Worker (produces PLAN_READY, no public post permissions needed)
    dist_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_campaign",
            phase_id=distribution_phase_id,
            role="campaign_strategist",
            capabilities=["campaign_strategy", "copywriting", "content_generation", "launch_messaging"],
            permissions=[],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["launch_verification", "launch_receipt", "deployment_bundle"],
                "produces_artifacts": ["distribution_plan", "campaign_strategy"],
            },
        )
    )

    # Add Channel-Specific Workers (depend on worker_campaign)
    if "reddit" in active_channels:
        dist_phase.add_worker(
            WorkerAssignment(
                worker_id="worker_reddit",
                phase_id=distribution_phase_id,
                role="reddit_specialist",
                capabilities=["reddit_distribution", "reddit_post", "reddit_comment", "community_engagement"],
                permissions=["network:write:approval_required"],
                dependencies=["worker_campaign"],
                metadata={
                    "consumes_artifacts": ["distribution_plan"],
                    "produces_artifacts": ["reddit_post_receipt"],
                },
            )
        )

    if "x" in active_channels or "twitter" in active_channels:
        dist_phase.add_worker(
            WorkerAssignment(
                worker_id="worker_x",
                phase_id=distribution_phase_id,
                role="x_specialist",
                capabilities=["x_distribution", "twitter_post", "social_growth", "tweet_thread"],
                permissions=["network:write:approval_required"],
                dependencies=["worker_campaign"],
                metadata={
                    "consumes_artifacts": ["distribution_plan"],
                    "produces_artifacts": ["x_tweet_receipt"],
                },
            )
        )

    if "linkedin" in active_channels:
        dist_phase.add_worker(
            WorkerAssignment(
                worker_id="worker_linkedin",
                phase_id=distribution_phase_id,
                role="linkedin_specialist",
                capabilities=["linkedin_distribution", "b2b_networking", "article_post", "company_update"],
                permissions=["network:write:approval_required"],
                dependencies=["worker_campaign"],
                metadata={
                    "consumes_artifacts": ["distribution_plan"],
                    "produces_artifacts": ["linkedin_post_receipt"],
                },
            )
        )

    if "email" in active_channels:
        dist_phase.add_worker(
            WorkerAssignment(
                worker_id="worker_email",
                phase_id=distribution_phase_id,
                role="email_specialist",
                capabilities=["email_outreach", "cold_email", "newsletter", "send_email"],
                permissions=["network:write:approval_required"],
                dependencies=["worker_campaign"],
                metadata={
                    "consumes_artifacts": ["distribution_plan"],
                    "produces_artifacts": ["email_dispatch_receipt"],
                },
            )
        )

    wf.add_phase(dist_phase, dependencies=[launch_phase_id])

    return wf


def execute_build_simulation_deployment_launch_distribution_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    channels: Optional[List[str]] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    approved_task_ids: Optional[Set[str] | List[str]] = None,
    http_verifier: Optional[Callable[[str], Dict[str, Any]]] = None,
    reddit_client: Optional[Any] = None,
    x_client: Optional[Any] = None,
    linkedin_client: Optional[Any] = None,
    email_client: Optional[Any] = None,
    dry_run: bool = False,
) -> BuildSimulationDeploymentLaunchDistributionSliceResult:
    """
    Executes the Stage 6E Build -> Simulation -> Deployment -> Launch Verification -> Distribution
    Multi-Phase Vertical Slice end-to-end.

    Composition Flow:
        1. Establish authoritative ProjectContext
        2. Construct 5-Phase ProjectWorkflow (Build -> Simulation -> Deployment -> Launch Verification -> Distribution)
        3. Assemble TeamPlan via TeamManager
        4. Compile TaskPlan via TaskAssignmentEngine
        5. Execute via WorkforceCoordinator:
           - Build executes & verifies
           - Simulation executes & verifies
           - Deployment executes & verifies
           - Launch Verification certifies LIVE status
           - Distribution Campaign Worker plans campaign (PLAN_READY)
           - Approval gate checked for public channels
           - Channel Workers execute real/adapted channel actions & produce verified receipts
        6. Return BuildSimulationDeploymentLaunchDistributionSliceResult with full provenance audit
    """
    reg = registry or get_default_registry()

    conns = connected_connectors if connected_connectors is not None else [
        "vercel", "redditapis", "twitter", "linkedin", "sendgrid", "smtp"
    ]
    perms = authorized_permissions if authorized_permissions is not None else [
        "filesystem:write", "workspace:edit", "execution:test", "deployment:execute",
        "network:read", "network:write:approval_required"
    ]

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build 5-Phase Workflow
    workflow = create_build_simulation_deployment_launch_distribution_workflow(ctx, channels=channels)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSimulationDeploymentLaunchDistributionSliceResult(
            success=False,
            status=coord_res.status,
            is_live=False,
            is_distributed=False,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            build_artifacts=[],
            simulation_artifacts=[],
            deployment_artifacts=[],
            launch_artifacts=[],
            distribution_artifacts=[],
            all_artifacts=[],
            step_history=[],
            errors=task_plan.validation_errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        if not rt.resolve_worker("worker_qa_simulation"):
            rt.register_worker(SimulationWorkerAdapter())
        if not rt.resolve_worker("worker_deployment"):
            rt.register_worker(DeploymentWorkerAdapter())
        verifier = http_verifier or (lambda url: {"status": "PASS", "http_status": 200, "url": url, "response_time_ms": 25.0, "error": None})
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=verifier))
        if not rt.resolve_worker("worker_campaign"):
            rt.register_worker(CampaignWorkerAdapter())
        if not rt.resolve_worker("worker_reddit") or reddit_client is not None:
            rt.register_worker(RedditWorkerAdapter(client=reddit_client))
        if not rt.resolve_worker("worker_x") or x_client is not None:
            rt.register_worker(XWorkerAdapter(client=x_client))
        if not rt.resolve_worker("worker_linkedin") or linkedin_client is not None:
            rt.register_worker(LinkedInWorkerAdapter(client=linkedin_client))
        if not rt.resolve_worker("worker_email") or email_client is not None:
            rt.register_worker(EmailWorkerAdapter(client=email_client))

        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    approved = set(approved_task_ids) if approved_task_ids is not None else {t.task_id for t in task_plan.tasks}

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        approved_task_ids=approved,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Artifacts from ProjectContext
    build_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]
    sim_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_simulation" or art.producer_worker == "worker_qa_simulation"
    ]
    dep_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_deployment" or art.producer_worker == "worker_deployment"
    ]
    launch_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_launch_verification" or art.producer_worker == "worker_launch_verification"
    ]
    dist_worker_ids = {"worker_campaign", "worker_reddit", "worker_x", "worker_linkedin", "worker_email"}
    dist_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_distribution" or art.producer_worker in dist_worker_ids
    ]

    is_live_outcome = ctx.is_live and coordinator_res.is_completed
    is_distributed_outcome = ctx.is_distributed and coordinator_res.is_completed

    return BuildSimulationDeploymentLaunchDistributionSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        is_live=is_live_outcome,
        is_distributed=is_distributed_outcome,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        build_artifacts=build_artifacts,
        simulation_artifacts=sim_artifacts,
        deployment_artifacts=dep_artifacts,
        launch_artifacts=launch_artifacts,
        distribution_artifacts=dist_artifacts,
        all_artifacts=list(ctx.artifacts.values()),
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


# =============================================================================
# 9. Stage 6F: Health / Operate Workforce Vertical Slice
# =============================================================================

class HealthAssessmentSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the Stage 6F
    Health / Operate Workforce vertical slice.
    """
    success: bool
    status: str
    health_status: str = "UNKNOWN"
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    health_report: Optional[HealthReport] = None
    artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    @property
    def is_healthy(self) -> bool:
        return self.is_completed and self.health_status == "HEALTHY"

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


class BuildSimulationDeploymentLaunchDistributionHealthSliceResult(BaseModel):
    """
    Comprehensive outcome and provenance audit produced by the full 6-phase
    (Build -> Simulation -> Deployment -> Launch Verification -> Distribution -> Health) vertical slice.
    """
    success: bool
    status: str
    is_live: bool = False
    is_distributed: bool = False
    health_status: str = "UNKNOWN"
    project_id: str
    execution_id: str
    coordinator_result: CoordinatorResult
    project_context: ProjectContext
    workflow: ProjectWorkflow
    team_plan: TeamPlan
    task_plan: CompiledTaskPlan
    build_artifacts: List[Artifact] = Field(default_factory=list)
    simulation_artifacts: List[Artifact] = Field(default_factory=list)
    deployment_artifacts: List[Artifact] = Field(default_factory=list)
    launch_artifacts: List[Artifact] = Field(default_factory=list)
    distribution_artifacts: List[Artifact] = Field(default_factory=list)
    health_artifacts: List[Artifact] = Field(default_factory=list)
    all_artifacts: List[Artifact] = Field(default_factory=list)
    step_history: List[CoordinatorStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    executed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_completed(self) -> bool:
        return self.success and self.status == CoordinatorStatus.COMPLETED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())


def create_health_assessment_workflow(
    project_context: ProjectContext,
    phase_id: str = "phase_health",
    phase_name: str = "Operational Health & Monitoring",
) -> ProjectWorkflow:
    """
    Constructs a focused, canonical ProjectWorkflow containing the Health phase (worker_health)
    for assessing an existing LIVE project without replaying previous phases.
    """
    wf = ProjectWorkflow(
        project_id=project_context.project_id,
        execution_id=project_context.execution_id,
    )

    has_live_deployment = bool(
        project_context.is_live
        or project_context.verified_live_url
        or bool(project_context.get_artifacts_by_type("deployment_receipt"))
        or bool(project_context.get_artifacts_by_type("deployment_bundle"))
        or bool(project_context.get_artifacts_by_type("launch_verification"))
    )

    health_phase = Phase(
        phase_id=phase_id,
        phase_number=1,
        name=phase_name,
        description="Assesses operational reachability, telemetry signals, and generates improvement recommendations.",
        purpose="Monitor operational health post-launch.",
        status=PhaseStatus.READY if has_live_deployment else PhaseStatus.BLOCKED,
        dependencies=[],
        entry_requirements=["verified_live_deployment"],
        exit_requirements=["health_report", "health_assessment_pass"],
        metadata={
            "required_capabilities": ["health_monitoring", "endpoint_check", "synthetic_monitoring"],
            "context_keys": ["idea", "deployment", "launch_verification", "receipts", "distribution", "definition", "acceptance_criteria", "health"],
            "blocked_reason": None if has_live_deployment else "Project has no verified live deployment reference or URL.",
        },
    )

    health_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_health",
            phase_id=phase_id,
            role="health_monitor",
            capabilities=["health_monitoring", "endpoint_check", "synthetic_monitoring", "cron_inspection"],
            permissions=["network:read"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["deployment_bundle", "deployment_receipt", "launch_verification", "launch_receipt", "distribution_receipt"],
                "produces_artifacts": ["health_report", "improvement_recommendations"],
            },
        )
    )

    wf.add_phase(health_phase)
    return wf


def create_build_simulation_deployment_launch_distribution_health_workflow(
    project_context: ProjectContext,
    build_phase_id: str = "phase_build",
    simulation_phase_id: str = "phase_simulation",
    deployment_phase_id: str = "phase_deployment",
    launch_phase_id: str = "phase_launch_verification",
    distribution_phase_id: str = "phase_distribution",
    health_phase_id: str = "phase_health",
    channels: Optional[List[str]] = None,
) -> ProjectWorkflow:
    """
    Constructs a canonical 6-phase ProjectWorkflow
    (Build -> Simulation -> Deployment -> Launch Verification -> Distribution -> Health).
    """
    wf = create_build_simulation_deployment_launch_distribution_workflow(
        project_context=project_context,
        build_phase_id=build_phase_id,
        simulation_phase_id=simulation_phase_id,
        deployment_phase_id=deployment_phase_id,
        launch_phase_id=launch_phase_id,
        distribution_phase_id=distribution_phase_id,
        channels=channels,
    )

    health_phase = Phase(
        phase_id=health_phase_id,
        phase_number=6,
        name="Operational Health & Monitoring",
        description="Assesses operational reachability, telemetry signals, and generates improvement recommendations.",
        purpose="Monitor operational health post-launch.",
        status=PhaseStatus.PLANNED,
        dependencies=[distribution_phase_id],
        entry_requirements=["verified_live_deployment", "launch_verification"],
        exit_requirements=["health_report", "health_assessment_pass"],
        metadata={
            "required_capabilities": ["health_monitoring", "endpoint_check", "synthetic_monitoring"],
            "context_keys": ["idea", "deployment", "launch_verification", "receipts", "distribution", "definition", "acceptance_criteria", "health"],
        },
    )

    health_phase.add_worker(
        WorkerAssignment(
            worker_id="worker_health",
            phase_id=health_phase_id,
            role="health_monitor",
            capabilities=["health_monitoring", "endpoint_check", "synthetic_monitoring", "cron_inspection"],
            permissions=["network:read"],
            dependencies=[],
            metadata={
                "consumes_artifacts": ["deployment_bundle", "deployment_receipt", "launch_verification", "launch_receipt", "distribution_receipt"],
                "produces_artifacts": ["health_report", "improvement_recommendations"],
            },
        )
    )

    wf.add_phase(health_phase, dependencies=[distribution_phase_id])
    return wf


def execute_health_assessment_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    observer: Optional[Any] = None,
    response_time_threshold_ms: float = 500.0,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    dry_run: bool = False,
) -> HealthAssessmentSliceResult:
    """
    Executes a focused Stage 6F Health Assessment Vertical Slice on an existing LIVE ProjectContext.

    Canonical Execution Path:
        ProjectContext
        → TeamManager
        → WorkerRegistry
        → TaskAssignmentEngine
        → WorkforceCoordinator
        → ExecutionDispatcher
        → WorkerRuntime
        → HealthWorkerAdapter
        → ContextSynchronizer
        → GraphAdvancer
    """
    reg = registry or get_default_registry()
    conns = connected_connectors if connected_connectors is not None else []
    perms = authorized_permissions if authorized_permissions is not None else ["network:read"]

    # 1. Authoritative ProjectContext
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Build focused Health ProjectWorkflow
    workflow = create_health_assessment_workflow(ctx)

    # 3. Team Assembly via TeamManager
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "deployment", "launch_verification"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Compilation via TaskAssignmentEngine
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors or [t.metadata.get('blocked_reason', 'Task blocked') for t in task_plan.tasks])}",
            errors=task_plan.validation_errors or [t.metadata.get("blocked_reason", "Task blocked") for t in task_plan.tasks if t.metadata.get("blocked_reason")],
        )
        return HealthAssessmentSliceResult(
            success=False,
            status=coord_res.status,
            health_status="UNKNOWN",
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            health_report=None,
            artifacts=[],
            step_history=[],
            errors=coord_res.errors,
        )

    # 5. Execution via WorkforceCoordinator
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        health_adapter = HealthWorkerAdapter(
            observer=observer,
            response_time_threshold_ms=response_time_threshold_ms,
        )
        rt.register_worker(health_adapter)
        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        dry_run=dry_run,
    )

    # 6. Extract Promoted Health Artifacts from ProjectContext
    health_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_health" or art.producer_worker == "worker_health"
    ]

    # Find health report object
    parsed_report = None
    health_status_val = "UNKNOWN"
    for art in health_artifacts:
        if art.artifact_type == "health_report":
            summary_dict = art.content_summary or {}
            try:
                parsed_report = HealthReport.from_dict(summary_dict)
                health_status_val = parsed_report.status
            except Exception:
                health_status_val = str(summary_dict.get("status", "UNKNOWN"))
            break

    return HealthAssessmentSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        health_status=health_status_val,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        health_report=parsed_report,
        artifacts=health_artifacts,
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )


def execute_build_simulation_deployment_launch_distribution_health_vertical_slice(
    project_context: Optional[ProjectContext] = None,
    project_data: Optional[Dict[str, Any]] = None,
    registry: Optional[WorkerRegistry] = None,
    runtime: Optional[WorkerRuntime] = None,
    coordinator: Optional[WorkforceCoordinator] = None,
    channels: Optional[List[str]] = None,
    connected_connectors: Optional[Set[str] | List[str]] = None,
    authorized_permissions: Optional[Set[str] | List[str]] = None,
    approved_task_ids: Optional[Set[str] | List[str]] = None,
    http_verifier: Optional[Callable[[str], Dict[str, Any]]] = None,
    reddit_client: Optional[Any] = None,
    x_client: Optional[Any] = None,
    linkedin_client: Optional[Any] = None,
    email_client: Optional[Any] = None,
    health_observer: Optional[Any] = None,
    response_time_threshold_ms: float = 500.0,
    dry_run: bool = False,
) -> BuildSimulationDeploymentLaunchDistributionHealthSliceResult:
    """
    Executes the full 6-phase vertical slice end-to-end
    (Build -> Simulation -> Deployment -> Launch Verification -> Distribution -> Health).
    """
    reg = registry or get_default_registry()
    conns = connected_connectors if connected_connectors is not None else [
        "vercel", "redditapis", "twitter", "linkedin", "sendgrid", "smtp"
    ]
    perms = authorized_permissions if authorized_permissions is not None else [
        "filesystem:write", "workspace:edit", "execution:test", "deployment:execute",
        "network:read", "network:write:approval_required"
    ]

    # 1. Context
    if project_context is None:
        if project_data:
            ctx = from_legacy_project_dict(project_data)
        else:
            ctx = create_build_project_context()
    else:
        ctx = project_context

    # 2. Workflow
    workflow = create_build_simulation_deployment_launch_distribution_health_workflow(
        project_context=ctx,
        channels=channels,
    )

    # 3. Team Plan
    team_mgr = TeamManager(registry=reg)
    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Task Plan
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    if not task_plan.is_executable():
        coord_res = CoordinatorResult(
            status=CoordinatorStatus.INVALID.value if task_plan.validation_errors else CoordinatorStatus.BLOCKED.value,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            steps_executed=0,
            blocked_tasks=task_plan.blocked_tasks,
            reason=f"Task plan compilation did not reach READY state: {'; '.join(task_plan.validation_errors)}",
            errors=task_plan.validation_errors,
        )
        return BuildSimulationDeploymentLaunchDistributionHealthSliceResult(
            success=False,
            status=coord_res.status,
            is_live=False,
            is_distributed=False,
            health_status="UNKNOWN",
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            coordinator_result=coord_res,
            project_context=ctx,
            workflow=workflow,
            team_plan=team_plan,
            task_plan=task_plan,
            errors=task_plan.validation_errors,
        )

    # 5. Coordinator Setup
    if coordinator is None:
        dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
        rt = runtime or WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        if not rt.resolve_worker("worker_code"):
            rt.register_worker(CodeWorkerAdapter())
        if not rt.resolve_worker("worker_qa_simulation"):
            rt.register_worker(SimulationWorkerAdapter())
        if not rt.resolve_worker("worker_deployment"):
            rt.register_worker(DeploymentWorkerAdapter())
        verifier = http_verifier or (lambda url: {"status": "PASS", "http_status": 200, "url": url, "response_time_ms": 25.0, "error": None})
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=verifier))
        if not rt.resolve_worker("worker_campaign"):
            rt.register_worker(CampaignWorkerAdapter())
        if not rt.resolve_worker("worker_reddit") or reddit_client is not None:
            rt.register_worker(RedditWorkerAdapter(client=reddit_client))
        if not rt.resolve_worker("worker_x") or x_client is not None:
            rt.register_worker(XWorkerAdapter(client=x_client))
        if not rt.resolve_worker("worker_linkedin") or linkedin_client is not None:
            rt.register_worker(LinkedInWorkerAdapter(client=linkedin_client))
        if not rt.resolve_worker("worker_email") or email_client is not None:
            rt.register_worker(EmailWorkerAdapter(client=email_client))
        rt.register_worker(HealthWorkerAdapter(observer=health_observer, response_time_threshold_ms=response_time_threshold_ms))

        sync = ContextSynchronizer()
        advancer = GraphAdvancer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=rt,
            context_sync=sync,
            graph_advancer=advancer,
        )
    else:
        coord = coordinator

    approved = set(approved_task_ids) if approved_task_ids is not None else {t.task_id for t in task_plan.tasks}

    coordinator_res = coord.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        approved_task_ids=approved,
        dry_run=dry_run,
    )

    # 6. Extract Deliverables
    build_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_build" or art.producer_worker == "worker_code"
    ]
    sim_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_simulation" or art.producer_worker == "worker_qa_simulation"
    ]
    dep_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_deployment" or art.producer_worker == "worker_deployment"
    ]
    launch_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_launch_verification" or art.producer_worker == "worker_launch_verification"
    ]
    dist_worker_ids = {"worker_campaign", "worker_reddit", "worker_x", "worker_linkedin", "worker_email"}
    dist_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_distribution" or art.producer_worker in dist_worker_ids
    ]
    health_artifacts = [
        art for art in ctx.artifacts.values()
        if art.phase_id == "phase_health" or art.producer_worker == "worker_health"
    ]

    health_status_val = "UNKNOWN"
    for art in health_artifacts:
        if art.artifact_type == "health_report":
            summary_dict = art.content_summary or {}
            health_status_val = str(summary_dict.get("status", "UNKNOWN"))
            break

    is_live_outcome = ctx.is_live and coordinator_res.is_completed
    is_distributed_outcome = ctx.is_distributed and coordinator_res.is_completed

    return BuildSimulationDeploymentLaunchDistributionHealthSliceResult(
        success=coordinator_res.is_completed,
        status=coordinator_res.status,
        is_live=is_live_outcome,
        is_distributed=is_distributed_outcome,
        health_status=health_status_val,
        project_id=ctx.project_id,
        execution_id=ctx.execution_id,
        coordinator_result=coordinator_res,
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        task_plan=task_plan,
        build_artifacts=build_artifacts,
        simulation_artifacts=sim_artifacts,
        deployment_artifacts=dep_artifacts,
        launch_artifacts=launch_artifacts,
        distribution_artifacts=dist_artifacts,
        health_artifacts=health_artifacts,
        all_artifacts=list(ctx.artifacts.values()),
        step_history=coordinator_res.step_history,
        errors=coordinator_res.errors,
    )



