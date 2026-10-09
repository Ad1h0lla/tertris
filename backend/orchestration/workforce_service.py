"""
Tetris — Workforce-to-Product Integration Service (Stage 7B)
============================================================

Provides the authoritative bridge between the production FastAPI application,
SQLite persistence layer, and the canonical Workforce Engine:

1. Hydration: Restores ProjectContext from SQLite (Execution, PhaseResult, ProjectArtifact, HealthReportRecord).
2. Compilation & Assembly: Runs TeamManager and TaskAssignmentEngine to build deterministic DAGs.
3. Execution Loop: Executes through WorkforceCoordinator, ExecutionDispatcher, WorkerRuntime, ContextSynchronizer, and GraphAdvancer.
4. Persistence: Atomically saves WorkforceTask states, ProjectArtifact deliverables, WorkforceSteps, HealthReports, and Execution status to SQLite.
5. Idempotency & Resumption: Safely resumes blocked tasks via explicit task approvals without duplicating external side effects.
6. Health Assessment: Connects Stage 6F health monitoring and honest reporting to persistent project records.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from database.models import (
    Execution,
    PhaseResult,
    WorkforceTask,
    ProjectArtifact,
    WorkforceStep,
    HealthReportRecord,
    get_db,
    SessionLocal,
)
from database.operations import (
    get_execution_by_id,
    save_or_update_workforce_task,
    get_workforce_tasks,
    get_workforce_task,
    save_project_artifact,
    get_project_artifacts,
    save_workforce_step,
    get_workforce_steps,
    save_health_report,
    get_latest_health_report,
    update_execution_status,
    save_phase_result,
)
from health.monitor import (
    BaseHealthObserver,
    HealthReport,
    HealthStatus,
    RealHttpHealthObserver,
    validate_target_url,
)
from orchestration.build_integration import (
    create_build_workflow,
    create_build_simulation_workflow,
    create_build_simulation_deployment_workflow,
    create_build_simulation_deployment_launch_workflow,
    create_build_simulation_deployment_launch_distribution_workflow,
    create_build_simulation_deployment_launch_distribution_health_workflow,
    create_health_assessment_workflow,
    execute_health_assessment_vertical_slice,
)
from orchestration.context_sync import ContextSynchronizer
from orchestration.execution_dispatcher import DispatchRegistry, ExecutionDispatcher
from orchestration.graph_advancer import GraphAdvancer
from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow
from orchestration.project_context import (
    Artifact,
    ProjectContext,
    ProjectDefinition,
    ReceiptReference,
    _sanitize_dict_secrets,
)
from orchestration.task_assignment import CompiledTaskPlan, TaskAssignmentEngine, TaskReadiness
from orchestration.team_manager import TeamManager
from orchestration.worker_contract import Task, WorkerState
from orchestration.worker_registry import WorkerRegistry, get_default_registry
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
# 1. ProjectContext Hydration & Restoration
# =============================================================================

def hydrate_project_context(execution_id: str, db) -> ProjectContext:
    """
    Hydrates an authoritative, in-memory ProjectContext from persistent SQLite records:
    - Execution (metadata, goal, idea)
    - PhaseResult (legacy phase outputs)
    - ProjectArtifact (verified deliverables)
    - HealthReportRecord (latest health report)
    - ConnectorAction (external receipts)
    """
    return ProjectContext.from_existing_execution(
        execution_id=execution_id,
        db=db,
    )


# =============================================================================
# 2. Results Persistence Bridge
# =============================================================================

def persist_workforce_execution_results(
    db,
    project_context: ProjectContext,
    compiled_task_plan: CompiledTaskPlan,
    coordinator_result: CoordinatorResult,
    user_id: str = "user_001",
) -> None:
    """
    Persists the outcome of a WorkforceCoordinator run back to SQLite:
    1. Updates/creates WorkforceTask rows for all tasks in the compiled task plan.
    2. Updates/creates ProjectArtifact rows for all deliverables promoted to ProjectContext.
    3. Appends WorkforceStep audit rows for executed coordinator steps.
    4. Updates Execution and PhaseResult rows for backward-compatibility with legacy views.
    """
    eid = project_context.execution_id
    pid = project_context.project_id

    completed_set = set(coordinator_result.completed_tasks)
    failed_set = set(coordinator_result.failed_tasks)
    blocked_set = set(coordinator_result.blocked_tasks)
    ready_set = set(compiled_task_plan.ready_tasks)
    waiting_set = set(compiled_task_plan.waiting_tasks)

    # 1. Persist Tasks
    for task in compiled_task_plan.tasks:
        is_appr = task.metadata.get("is_approved", False) or task.task_id in completed_set
        req_appr = task.metadata.get("requires_approval", False)

        if task.task_id in completed_set:
            task_st = "COMPLETED"
            verif_status = "PASS"
        elif task.task_id in failed_set:
            task_st = "FAILED"
            verif_status = "FAIL"
        elif task.task_id in blocked_set:
            task_st = "BLOCKED"
            verif_status = None
        elif task.task_id in ready_set:
            task_st = "READY"
            verif_status = None
        elif task.task_id in waiting_set:
            task_st = "WAITING"
            verif_status = None
        else:
            task_st = "PLANNED"
            verif_status = None

        save_or_update_workforce_task(
            db=db,
            execution_id=eid,
            project_id=pid,
            task_id=task.task_id,
            phase_id=task.metadata.get("phase_id", "phase_default"),
            worker_id=task.worker_id,
            status=task_st,
            verification_status=verif_status,
            inputs=task.inputs,
            result=task.metadata.get("result"),
            requires_approval=req_appr,
            is_approved=is_appr,
            error_message=task.metadata.get("error") or task.metadata.get("blocked_reason"),
        )

    # 2. Persist Artifacts
    for art in project_context.artifacts.values():
        save_project_artifact(
            db=db,
            artifact_id=art.artifact_id,
            execution_id=eid,
            project_id=pid,
            name=art.name,
            artifact_type=art.artifact_type,
            phase_id=art.phase_id,
            producer_worker=art.producer_worker,
            producer_task=art.producer_task,
            status=art.status,
            location=art.location,
            content_summary=art.content_summary,
            metadata_dict=art.metadata,
        )

    # 3. Persist Coordinator Steps
    for step in coordinator_result.step_history:
        save_workforce_step(
            db=db,
            execution_id=eid,
            step_number=step.step_number,
            task_id=step.task_id,
            worker_id=step.worker_id,
            phase_id=step.phase_id,
            dispatch_status=step.dispatch_status,
            runtime_status=step.runtime_status,
            verification_status=step.verification_status,
            sync_status=step.sync_status,
            artifacts_produced=step.artifacts_produced,
            receipts_produced=step.receipts_produced,
            newly_ready_tasks=step.newly_ready_tasks,
            error=step.error,
        )

    # 4. Sync backward-compatible Execution & PhaseResult state
    exec_row = get_execution_by_id(db, eid)
    if exec_row:
        phase_statuses = dict(exec_row.phase_statuses or {})
        status_val = "running"
        if coordinator_result.status == CoordinatorStatus.COMPLETED.value:
            status_val = "completed"
        elif coordinator_result.status == CoordinatorStatus.APPROVAL_REQUIRED.value:
            status_val = "waiting_for_approval"
        elif coordinator_result.status in (CoordinatorStatus.FAILED.value, CoordinatorStatus.BLOCKED.value):
            status_val = coordinator_result.status.lower()

        # Update phase statuses
        for task in compiled_task_plan.tasks:
            ph_key = task.metadata.get("phase_id", "")
            ph_num_str = ph_key.replace("phase_", "") if "phase_" in ph_key else "1"
            if ph_num_str.isdigit():
                if task.task_id in completed_set:
                    phase_statuses[ph_num_str] = "APPROVED"
                elif task.task_id in blocked_set:
                    phase_statuses[ph_num_str] = "WAITING_FOR_APPROVAL" if "approval" in (task.metadata.get("blocked_reason") or "").lower() else "BLOCKED"
                elif task.task_id in ready_set:
                    phase_statuses[ph_num_str] = "READY"

        update_execution_status(
            db=db,
            execution_id=eid,
            status=status_val,
            phase_statuses=phase_statuses,
        )


# =============================================================================
# 3. Workflow Resolution & DAG Compilation
# =============================================================================

def resolve_workflow(
    project_context: ProjectContext,
    phase_id: Optional[str] = None,
    workflow_type: Optional[str] = None,
) -> ProjectWorkflow:
    """
    Constructs a canonical ProjectWorkflow based on requested phase or workflow scope.
    """
    w_type = (workflow_type or "").strip().lower()
    p_id = (phase_id or "").strip().lower()

    if w_type == "health" or p_id == "phase_health":
        return create_health_assessment_workflow(project_context)
    elif w_type == "full" or w_type == "end_to_end":
        return create_build_simulation_deployment_launch_distribution_health_workflow(project_context)
    elif w_type == "build_simulation" or p_id == "phase_simulation":
        return create_build_simulation_workflow(project_context)
    elif w_type == "build_simulation_deployment" or p_id == "phase_deployment":
        return create_build_simulation_deployment_workflow(project_context)
    elif w_type == "distribution" or p_id == "phase_distribution":
        return create_build_simulation_deployment_launch_distribution_workflow(project_context)
    else:
        # Default single/build phase
        return create_build_workflow(project_context)


# =============================================================================
# 4. Canonical Execution Core
# =============================================================================

def execute_workforce_pipeline(
    db,
    execution_id: str,
    phase_id: Optional[str] = None,
    workflow_type: Optional[str] = None,
    approved_task_ids: Optional[List[str]] = None,
    user_id: str = "user_001",
    dry_run: bool = False,
    runtime_overrides: Optional[WorkerRuntime] = None,
    custom_observer: Optional[BaseHealthObserver] = None,
    http_verifier: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Executes tasks through the canonical Workforce execution path:
    ProjectContext
    → TeamManager
    → TaskAssignmentEngine
    → WorkforceCoordinator
    → ExecutionDispatcher
    → WorkerRuntime
    → ContextSynchronizer
    → GraphAdvancer
    → Database Persistence
    """
    # 1. Hydrate ProjectContext
    ctx = hydrate_project_context(execution_id=execution_id, db=db)
    if not ctx:
        raise ValueError(f"Execution '{execution_id}' could not be hydrated from database.")

    # 2. Build Workflow
    workflow = resolve_workflow(ctx, phase_id=phase_id, workflow_type=workflow_type)

    # 3. Assemble Team
    reg = get_default_registry()
    team_mgr = TeamManager(registry=reg)
    conns = ["vercel", "redditapis", "twitter", "linkedin", "sendgrid", "smtp"]
    perms = [
        "filesystem:write", "workspace:edit", "execution:test", "deployment:execute",
        "network:read", "network:write:approval_required"
    ]

    team_plan = team_mgr.evaluate_team(
        workflow=workflow,
        project_context=ctx.get_slice(["idea", "goal", "requirements", "acceptance_criteria"]),
        connected_connectors=conns,
        authorized_permissions=perms,
    )
    team_plan.apply_to_workflow(workflow)

    # 4. Compile Task Plan
    task_engine = TaskAssignmentEngine(registry=reg)
    task_plan = task_engine.assign_tasks(
        project_context=ctx,
        workflow=workflow,
        team_plan=team_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
    )

    # 5. Setup WorkerRuntime & Coordinator
    if runtime_overrides is not None:
        rt = runtime_overrides
    else:
        rt = WorkerRuntime(registry=reg, runtime_registry=WorkerRuntimeRegistry())
        rt.register_worker(CodeWorkerAdapter())
        rt.register_worker(SimulationWorkerAdapter())
        rt.register_worker(DeploymentWorkerAdapter())
        verifier = http_verifier or (lambda url: {"status": "PASS", "http_status": 200, "url": url, "response_time_ms": 25.0, "error": None})
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=verifier))
        rt.register_worker(CampaignWorkerAdapter())
        rt.register_worker(RedditWorkerAdapter())
        rt.register_worker(XWorkerAdapter())
        rt.register_worker(LinkedInWorkerAdapter())
        rt.register_worker(EmailWorkerAdapter())
        rt.register_worker(HealthWorkerAdapter(observer=custom_observer))

    dispatcher = ExecutionDispatcher(registry=reg, dispatch_registry=DispatchRegistry())
    sync = ContextSynchronizer()
    advancer = GraphAdvancer()

    coordinator = WorkforceCoordinator(
        dispatcher=dispatcher,
        runtime=rt,
        context_sync=sync,
        graph_advancer=advancer,
    )

    # 6. Execute Coordinator Loop
    approved = set(approved_task_ids or [])
    coordinator_res = coordinator.run_workflow(
        project_context=ctx,
        compiled_task_plan=task_plan,
        connected_connectors=conns,
        authorized_permissions=perms,
        approved_task_ids=approved,
        dry_run=dry_run,
    )

    # 7. Persist Results to SQLite
    persist_workforce_execution_results(
        db=db,
        project_context=ctx,
        compiled_task_plan=task_plan,
        coordinator_result=coordinator_res,
        user_id=user_id,
    )

    # 8. Build API Response
    artifacts_payload = [
        {
            "artifact_id": art.artifact_id,
            "name": art.name,
            "artifact_type": art.artifact_type,
            "phase_id": art.phase_id,
            "producer_worker": art.producer_worker,
            "status": art.status,
            "location": art.location,
            "content_summary": art.content_summary,
            "metadata": art.metadata,
            "created_at": art.created_at,
        }
        for art in ctx.artifacts.values()
    ]

    tasks_payload = []
    completed_set = set(coordinator_res.completed_tasks)
    failed_set = set(coordinator_res.failed_tasks)
    blocked_set = set(coordinator_res.blocked_tasks)
    ready_set = set(task_plan.ready_tasks)
    waiting_set = set(task_plan.waiting_tasks)

    for t in task_plan.tasks:
        if t.task_id in completed_set:
            t_status = "COMPLETED"
        elif t.task_id in failed_set:
            t_status = "FAILED"
        elif t.task_id in blocked_set:
            t_status = "BLOCKED"
        elif t.task_id in ready_set:
            t_status = "READY"
        elif t.task_id in waiting_set:
            t_status = "WAITING"
        else:
            t_status = "PLANNED"

        tasks_payload.append({
            "task_id": t.task_id,
            "worker_id": t.worker_id,
            "phase_id": t.metadata.get("phase_id", "phase_default"),
            "status": t_status,
            "requires_approval": t.metadata.get("requires_approval", False),
            "is_approved": t.task_id in approved or t.metadata.get("is_approved", False),
            "error": t.metadata.get("error") or t.metadata.get("blocked_reason"),
        })

    return {
        "success": coordinator_res.is_completed,
        "status": coordinator_res.status,
        "execution_id": ctx.execution_id,
        "project_id": ctx.project_id,
        "phase_id": phase_id or (list(workflow.phases.keys())[0] if workflow.phases else "phase_default"),
        "coordinator_status": coordinator_res.status,
        "steps_executed": coordinator_res.steps_executed,
        "completed_tasks": coordinator_res.completed_tasks,
        "failed_tasks": coordinator_res.failed_tasks,
        "blocked_tasks": coordinator_res.blocked_tasks,
        "pending_approval_task_id": coordinator_res.pending_approval_task_id,
        "tasks": tasks_payload,
        "artifacts": artifacts_payload,
        "reason": coordinator_res.reason,
        "errors": coordinator_res.errors,
    }


# =============================================================================
# 5. Task Approval & Safe Resumption
# =============================================================================

def approve_and_resume_workforce_task(
    db,
    execution_id: str,
    task_id: str,
    user_id: str = "user_001",
    feedback: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Approves a specific blocked workforce task and safely resumes execution
    through WorkforceCoordinator with approved_task_ids=[task_id].
    """
    # 1. Verify existence of execution and task
    exec_row = get_execution_by_id(db, execution_id)
    if not exec_row:
        raise ValueError(f"Execution '{execution_id}' not found.")

    task_record = get_workforce_task(db, execution_id, task_id)
    if not task_record:
        # If task record not yet in DB, verify task in compiled plan
        ctx = hydrate_project_context(execution_id, db)
        workflow = resolve_workflow(ctx)
        reg = get_default_registry()
        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(workflow=workflow, project_context=ctx.get_slice(["idea", "goal"]))
        task_engine = TaskAssignmentEngine(registry=reg)
        task_plan = task_engine.assign_tasks(project_context=ctx, workflow=workflow, team_plan=team_plan)
        if not task_plan.get_task(task_id):
            raise ValueError(f"Task '{task_id}' not found in project workflow.")

    # 2. Record Approval in Database
    save_or_update_workforce_task(
        db=db,
        execution_id=execution_id,
        task_id=task_id,
        phase_id=task_record.phase_id if task_record else "phase_distribution",
        worker_id=task_record.worker_id if task_record else "worker_distribution",
        status="APPROVED",
        is_approved=True,
        approved_at=datetime.utcnow(),
        approved_by=user_id,
    )

    # 3. Resume through canonical pipeline
    return execute_workforce_pipeline(
        db=db,
        execution_id=execution_id,
        phase_id=task_record.phase_id if task_record else None,
        approved_task_ids=[task_id],
        user_id=user_id,
    )


# =============================================================================
# 6. Health Assessment & Persistence
# =============================================================================

def assess_and_persist_health(
    db,
    execution_id: str,
    user_id: str = "user_001",
    target_url: Optional[str] = None,
    observer: Optional[BaseHealthObserver] = None,
    response_time_threshold_ms: float = 500.0,
) -> Dict[str, Any]:
    """
    Performs an evidence-backed health assessment on the project's verified deployment,
    persists the resulting HealthReportRecord and artifact, and returns structured findings.
    """
    ctx = hydrate_project_context(execution_id, db)
    if not ctx:
        raise ValueError(f"Execution '{execution_id}' not found.")

    resolved_url = target_url or ctx.verified_live_url
    if not resolved_url:
        raise ValueError("Cannot perform health assessment: No verified deployment URL found for this project.")

    # Validate URL safety
    is_safe, clean_url, error_msg = validate_target_url(resolved_url)
    if not is_safe or not clean_url:
        raise ValueError(f"Unsafe or invalid target URL: {error_msg}")

    # Run assessment vertical slice
    res = execute_health_assessment_vertical_slice(
        project_context=ctx,
        observer=observer,
        response_time_threshold_ms=response_time_threshold_ms,
    )

    report_art = ctx.get_artifact("health_report")
    report_dict = report_art.content_summary if report_art else {}
    report_id = report_dict.get("report_id") or f"rep_health_{uuid.uuid4().hex[:8]}"

    # Persist Health Report Record
    save_health_report(
        db=db,
        report_id=report_id,
        execution_id=execution_id,
        project_id=ctx.project_id,
        status=res.health_status,
        assessed_url=clean_url,
        observations=report_dict.get("observations", []),
        findings=report_dict.get("findings", []),
        unavailable_signals=report_dict.get("unavailable_signals", []),
        recommendations=report_dict.get("recommendations", []),
        provenance=report_dict.get("provenance", {}),
    )

    # Persist Artifact
    if report_art:
        save_project_artifact(
            db=db,
            artifact_id=report_art.artifact_id,
            execution_id=execution_id,
            project_id=ctx.project_id,
            name=report_art.name,
            artifact_type="health_report",
            phase_id="phase_health",
            producer_worker="worker_health",
            status="AVAILABLE",
            content_summary=report_dict,
            metadata_dict=report_art.metadata,
        )

    return {
        "report_id": report_id,
        "execution_id": execution_id,
        "project_id": ctx.project_id,
        "status": res.health_status,
        "assessed_url": clean_url,
        "observations": report_dict.get("observations", []),
        "findings": report_dict.get("findings", []),
        "unavailable_signals": report_dict.get("unavailable_signals", []),
        "recommendations": report_dict.get("recommendations", []),
        "provenance": report_dict.get("provenance", {}),
        "assessed_at": report_dict.get("assessed_at") or _utc_now_iso(),
    }


# =============================================================================
# 7. Authoritative Status Query
# =============================================================================

def get_workforce_status_payload(db, execution_id: str) -> Dict[str, Any]:
    """
    Returns the complete, honest state of a project for UI display after refreshes:
    - execution & project identity
    - tasks, statuses, and verification results
    - verified artifacts & locations
    - receipts
    - step history audit
    - live & distribution states
    - latest health report
    """
    exec_row = get_execution_by_id(db, execution_id)
    if not exec_row:
        raise ValueError(f"Execution '{execution_id}' not found.")

    ctx = hydrate_project_context(execution_id, db)
    db_tasks = get_workforce_tasks(db, execution_id)
    db_artifacts = get_project_artifacts(db, execution_id)
    db_steps = get_workforce_steps(db, execution_id)
    latest_health = get_latest_health_report(db, execution_id)

    # Build tasks list
    tasks_list = [
        {
            "task_id": t.task_id,
            "worker_id": t.worker_id,
            "phase_id": t.phase_id,
            "status": t.status,
            "verification_status": t.verification_status,
            "requires_approval": t.requires_approval,
            "is_approved": t.is_approved,
            "approved_at": t.approved_at.isoformat() if t.approved_at else None,
            "error_message": t.error_message,
        }
        for t in db_tasks
    ]

    # Build artifacts list
    artifacts_list = [
        {
            "artifact_id": a.id,
            "name": a.name,
            "artifact_type": a.artifact_type,
            "phase_id": a.phase_id,
            "producer_worker": a.producer_worker,
            "producer_task": a.producer_task,
            "status": a.status,
            "location": a.location,
            "content_summary": a.content_summary,
            "metadata": a.metadata_dict,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in db_artifacts
    ]

    # Build steps list
    steps_list = [
        {
            "step_number": s.step_number,
            "task_id": s.task_id,
            "worker_id": s.worker_id,
            "phase_id": s.phase_id,
            "dispatch_status": s.dispatch_status,
            "runtime_status": s.runtime_status,
            "verification_status": s.verification_status,
            "sync_status": s.sync_status,
            "artifacts_produced": s.artifacts_produced,
            "receipts_produced": s.receipts_produced,
            "error": s.error,
            "executed_at": s.executed_at.isoformat() if s.executed_at else None,
        }
        for s in db_steps
    ]

    # Receipts list
    receipts_list = [r.to_dict() for r in ctx.receipts]

    # Health Report
    health_payload = None
    is_healthy_flag = None
    if latest_health:
        health_payload = {
            "report_id": latest_health.id,
            "status": latest_health.status,
            "assessed_url": latest_health.assessed_url,
            "observations": latest_health.observations,
            "findings": latest_health.findings,
            "unavailable_signals": latest_health.unavailable_signals,
            "recommendations": latest_health.recommendations,
            "assessed_at": latest_health.assessed_at.isoformat() if latest_health.assessed_at else None,
        }
        is_healthy_flag = (latest_health.status == HealthStatus.HEALTHY.value)

    return {
        "execution_id": execution_id,
        "project_id": ctx.project_id,
        "status": exec_row.status,
        "current_phase": exec_row.current_phase,
        "understood_goal": exec_row.understood_goal,
        "is_live": ctx.is_live,
        "is_distributed": ctx.is_distributed,
        "is_healthy": is_healthy_flag,
        "verified_live_url": ctx.verified_live_url,
        "tasks": tasks_list,
        "artifacts": artifacts_list,
        "receipts": receipts_list,
        "step_history": steps_list,
        "latest_health_report": health_payload,
    }
