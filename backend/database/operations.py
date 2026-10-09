import uuid
from datetime import datetime

from database.models import (
    Execution,
    PhaseResult,
    ScheduledJob,
    StoredCredential,
    WorkforceTask,
    ProjectArtifact,
    WorkforceStep,
    HealthReportRecord,
)


def create_execution(
    db,
    user_id,
    original_idea,
    understood_goal,
    intent_classification,
    idea_type,
    recommended_phases,
    phase_names=None,
):
    phases_list = recommended_phases or [1, 2, 3, 4]
    phase_statuses = {}
    for idx, ph_id in enumerate(phases_list):
        phase_statuses[str(ph_id)] = "READY" if idx == 0 else "LOCKED"

    execution = Execution(
        id=str(uuid.uuid4()),
        user_id=user_id,
        original_idea=original_idea,
        understood_goal=understood_goal,
        intent_classification=intent_classification,
        idea_type=idea_type,
        recommended_phases=phases_list,
        status="running",
        current_phase=phases_list[0] if phases_list else 1,
        phase_statuses=phase_statuses,
        phase_names=phase_names,
    )

    db.add(execution)
    db.commit()
    db.refresh(execution)

    return execution


def get_execution_by_id(db, execution_id):
    return (
        db.query(Execution)
        .filter(Execution.id == execution_id)
        .first()
    )


def get_executions(db, user_id, limit=20):
    return (
        db.query(Execution)
        .filter(Execution.user_id == user_id)
        .order_by(Execution.created_at.desc())
        .limit(limit)
        .all()
    )


def update_execution_status(db, execution_id, status, current_phase=None, phase_statuses=None):
    update_data = {
        "status": status,
        "updated_at": datetime.utcnow(),
    }
    if current_phase is not None:
        update_data["current_phase"] = current_phase
    if phase_statuses is not None:
        update_data["phase_statuses"] = phase_statuses

    (
        db.query(Execution)
        .filter(Execution.id == execution_id)
        .update(update_data)
    )

    db.commit()


def save_phase_result(
    db,
    execution_id,
    phase,
    outcome_type,
    outcome,
    score,
    trace,
    status="complete",
    phase_name=None,
    selected_agents=None,
    verification_result=None,
    simulation_result=None,
    deployment_result=None,
    review_result=None,
    distribution_plan=None,
    error_message=None,
):
    # Upsert: update existing phase result for this phase or create new one
    existing = (
        db.query(PhaseResult)
        .filter(PhaseResult.execution_id == execution_id, PhaseResult.phase_number == phase)
        .order_by(PhaseResult.created_at.desc())
        .first()
    )

    if existing:
        existing.outcome_type = outcome_type
        existing.outcome = outcome
        existing.validation_score = score
        existing.execution_trace = trace
        existing.status = status
        if phase_name:
            existing.phase_name = phase_name
        if selected_agents:
            existing.selected_agents = selected_agents
        if verification_result:
            existing.verification_result = verification_result
        if simulation_result:
            existing.simulation_result = simulation_result
        if deployment_result:
            existing.deployment_result = deployment_result
        if review_result:
            existing.review_result = review_result
        if distribution_plan:
            existing.distribution_plan = distribution_plan
        if error_message:
            existing.error_message = error_message
        existing.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    result = PhaseResult(
        id=str(uuid.uuid4()),
        execution_id=execution_id,
        phase_number=phase,
        phase_name=phase_name,
        outcome_type=outcome_type,
        outcome=outcome,
        validation_score=score,
        execution_trace=trace,
        status=status,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        selected_agents=selected_agents,
        verification_result=verification_result,
        simulation_result=simulation_result,
        deployment_result=deployment_result,
        review_result=review_result,
        distribution_plan=distribution_plan,
        error_message=error_message,
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    return result


def get_phase_results(db, execution_id):
    return (
        db.query(PhaseResult)
        .filter(PhaseResult.execution_id == execution_id)
        .order_by(PhaseResult.phase_number)
        .all()
    )


def save_job(db, job):
    existing = (
        db.query(ScheduledJob)
        .filter(ScheduledJob.id == job["job_id"])
        .first()
    )

    if existing:
        return existing

    sj = ScheduledJob(
        id=job["job_id"],
        user_id=job["user_id"],
        agent_type=job["agent_type"],
        payload=job["payload"],
        interval_hours=job["interval_hours"],
        notify_via=job.get("notify_via", "none"),
        notify_target=job.get("notify_target", ""),
        status="active",
        next_run=datetime.fromisoformat(job["next_run"]),
    )

    db.add(sj)
    db.commit()
    db.refresh(sj)

    return sj


def load_all_jobs(db):
    jobs = (
        db.query(ScheduledJob)
        .filter(ScheduledJob.status == "active")
        .all()
    )

    return [
        {
            "job_id": j.id,
            "user_id": j.user_id,
            "agent_type": j.agent_type,
            "payload": j.payload,
            "interval_hours": j.interval_hours,
            "notify_via": j.notify_via,
            "notify_target": j.notify_target,
            "status": j.status,
            "run_count": j.run_count,
            "last_run": j.last_run.isoformat() if j.last_run else None,
            "next_run": j.next_run.isoformat(),
            "last_result": j.last_result,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]


def update_job_after_run(db, job_id, result, next_run):
    (
        db.query(ScheduledJob)
        .filter(ScheduledJob.id == job_id)
        .update({
            "last_run": datetime.utcnow(),
            "next_run": next_run,
            "run_count": ScheduledJob.run_count + 1,
            "last_result": result,
        })
    )

    db.commit()


def update_job_status(db, job_id, status):
    (
        db.query(ScheduledJob)
        .filter(ScheduledJob.id == job_id)
        .update({
            "status": status,
        })
    )

    db.commit()


def store_credential(
    db,
    user_id,
    app_name,
    credential_encrypted,
    connection_type="",
    display_name="",
):
    existing = (
        db.query(StoredCredential)
        .filter(
            StoredCredential.user_id == user_id,
            StoredCredential.app_name == app_name,
        )
        .first()
    )

    if existing:
        existing.credential_encrypted = credential_encrypted
        existing.connected_at = datetime.utcnow()
        existing.is_active = True

        db.commit()
        db.refresh(existing)

        return existing

    cred = StoredCredential(
        id=str(uuid.uuid4()),
        user_id=user_id,
        app_name=app_name,
        credential_encrypted=credential_encrypted,
        connection_type=connection_type,
        display_name=display_name or app_name,
    )

    db.add(cred)
    db.commit()
    db.refresh(cred)

    return cred


def get_credential(db, user_id, app_name):
    cred = (
        db.query(StoredCredential)
        .filter(
            StoredCredential.user_id == user_id,
            StoredCredential.app_name == app_name,
            StoredCredential.is_active == True,
        )
        .first()
    )

    if cred:
        return cred.credential_encrypted

    return None


def list_credentials(db, user_id):
    creds = (
        db.query(StoredCredential)
        .filter(
            StoredCredential.user_id == user_id,
            StoredCredential.is_active == True,
        )
        .all()
    )

    return [
        {
            "app_name": c.app_name,
            "connection_type": c.connection_type,
            "display_name": c.display_name,
            "connected_at": c.connected_at.isoformat(),
            "last_used": c.last_used.isoformat() if c.last_used else None,
        }
        for c in creds
    ]


def delete_credential(db, user_id, app_name):
    (
        db.query(StoredCredential)
        .filter(
            StoredCredential.user_id == user_id,
            StoredCredential.app_name == app_name,
        )
        .update({
            "is_active": False,
        })
    )

    db.commit()


def save_connector_action(
    db,
    user_id: str,
    execution_id: str,
    connector_id: str,
    action: str,
    status: str,
    result: dict = None,
    error: str = None,
    action_id: str = None,
):
    from database.models import ConnectorAction
    aid = action_id or str(uuid.uuid4())
    existing = db.query(ConnectorAction).filter(ConnectorAction.id == aid).first()
    if existing:
        existing.status = status
        existing.result = result or {}
        existing.error = error
        existing.executed_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    action_obj = ConnectorAction(
        id=aid,
        user_id=user_id,
        execution_id=execution_id,
        connector_id=connector_id,
        action=action,
        status=status,
        result=result or {},
        error=error,
        executed_at=datetime.utcnow(),
    )
    db.add(action_obj)
    db.commit()
    db.refresh(action_obj)
    return action_obj


def get_connector_actions(db, execution_id: str):
    from database.models import ConnectorAction
    return (
        db.query(ConnectorAction)
        .filter(ConnectorAction.execution_id == execution_id)
        .order_by(ConnectorAction.executed_at.asc())
        .all()
    )


def save_distribution_campaign(
    db,
    campaign_id: str,
    execution_id: str,
    user_id: str,
    status: str = "PLANNED",
    actions: list = None,
    summary: dict = None,
    connector_requirements: list = None,
    events: list = None,
    phase: int = 3,
):
    from database.models import DistributionCampaign
    existing = (
        db.query(DistributionCampaign)
        .filter(DistributionCampaign.id == campaign_id)
        .first()
    )

    if existing:
        existing.status = status
        from sqlalchemy.orm.attributes import flag_modified
        import copy
        if actions is not None:
            existing.actions = copy.deepcopy(actions)
            flag_modified(existing, "actions")
        if summary is not None:
            existing.summary = copy.deepcopy(summary)
            flag_modified(existing, "summary")
        if connector_requirements is not None:
            existing.connector_requirements = copy.deepcopy(connector_requirements)
            flag_modified(existing, "connector_requirements")
        if events is not None:
            existing.events = copy.deepcopy(events)
            flag_modified(existing, "events")
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    campaign_obj = DistributionCampaign(
        id=campaign_id or f"cmp_{uuid.uuid4().hex[:12]}",
        execution_id=execution_id,
        user_id=user_id,
        phase=phase,
        status=status,
        actions=actions or [],
        summary=summary or {},
        connector_requirements=connector_requirements or [],
        events=events or [],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(campaign_obj)
    db.commit()
    db.refresh(campaign_obj)
    return campaign_obj


def get_distribution_campaign_by_id(db, campaign_id: str):
    from database.models import DistributionCampaign
    return (
        db.query(DistributionCampaign)
        .filter(DistributionCampaign.id == campaign_id)
        .first()
    )


def get_distribution_campaign_by_execution(db, execution_id: str):
    from database.models import DistributionCampaign
    return (
        db.query(DistributionCampaign)
        .filter(DistributionCampaign.execution_id == execution_id)
        .order_by(DistributionCampaign.created_at.desc())
        .first()
    )


# =============================================================================
# Workforce Persistence Operations
# =============================================================================

def save_or_update_workforce_task(
    db,
    execution_id: str,
    task_id: str,
    phase_id: str,
    worker_id: str,
    status: str,
    project_id: str = None,
    verification_status: str = None,
    inputs: dict = None,
    result: dict = None,
    requires_approval: bool = False,
    is_approved: bool = False,
    approved_at: datetime = None,
    approved_by: str = None,
    error_message: str = None,
    started_at: datetime = None,
    completed_at: datetime = None,
):
    from sqlalchemy.orm.attributes import flag_modified
    import copy

    existing = (
        db.query(WorkforceTask)
        .filter(WorkforceTask.execution_id == execution_id, WorkforceTask.task_id == task_id)
        .first()
    )

    if existing:
        existing.status = status
        existing.phase_id = phase_id
        existing.worker_id = worker_id
        if project_id is not None:
            existing.project_id = project_id
        if verification_status is not None:
            existing.verification_status = verification_status
        if inputs is not None:
            existing.inputs = copy.deepcopy(inputs)
            flag_modified(existing, "inputs")
        if result is not None:
            existing.result = copy.deepcopy(result)
            flag_modified(existing, "result")
        existing.requires_approval = requires_approval
        existing.is_approved = is_approved
        if approved_at is not None:
            existing.approved_at = approved_at
        if approved_by is not None:
            existing.approved_by = approved_by
        if error_message is not None:
            existing.error_message = error_message
        if started_at is not None:
            existing.started_at = started_at
        if completed_at is not None:
            existing.completed_at = completed_at
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    record_id = f"wt_{execution_id[:8]}_{task_id}"
    task_record = WorkforceTask(
        id=record_id,
        execution_id=execution_id,
        project_id=project_id,
        task_id=task_id,
        phase_id=phase_id,
        worker_id=worker_id,
        status=status,
        verification_status=verification_status,
        inputs=inputs or {},
        result=result,
        requires_approval=requires_approval,
        is_approved=is_approved,
        approved_at=approved_at,
        approved_by=approved_by,
        error_message=error_message,
        started_at=started_at or datetime.utcnow(),
        completed_at=completed_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(task_record)
    db.commit()
    db.refresh(task_record)
    return task_record


def get_workforce_tasks(db, execution_id: str):
    return (
        db.query(WorkforceTask)
        .filter(WorkforceTask.execution_id == execution_id)
        .order_by(WorkforceTask.created_at.asc())
        .all()
    )


def get_workforce_task(db, execution_id: str, task_id: str):
    return (
        db.query(WorkforceTask)
        .filter(WorkforceTask.execution_id == execution_id, WorkforceTask.task_id == task_id)
        .first()
    )


def save_project_artifact(
    db,
    artifact_id: str,
    execution_id: str,
    name: str,
    artifact_type: str,
    phase_id: str,
    producer_worker: str,
    project_id: str = None,
    producer_task: str = None,
    status: str = "AVAILABLE",
    location: str = "",
    content_summary: dict = None,
    metadata_dict: dict = None,
):
    from sqlalchemy.orm.attributes import flag_modified
    import copy

    existing = db.query(ProjectArtifact).filter(ProjectArtifact.id == artifact_id).first()
    if existing:
        existing.name = name
        existing.artifact_type = artifact_type
        existing.phase_id = phase_id
        existing.producer_worker = producer_worker
        existing.producer_task = producer_task
        existing.status = status
        existing.location = location
        if content_summary is not None:
            existing.content_summary = copy.deepcopy(content_summary)
            flag_modified(existing, "content_summary")
        if metadata_dict is not None:
            existing.metadata_dict = copy.deepcopy(metadata_dict)
            flag_modified(existing, "metadata_dict")
        db.commit()
        db.refresh(existing)
        return existing

    art_record = ProjectArtifact(
        id=artifact_id,
        execution_id=execution_id,
        project_id=project_id,
        name=name,
        artifact_type=artifact_type,
        phase_id=phase_id,
        producer_worker=producer_worker,
        producer_task=producer_task,
        status=status,
        location=location or "",
        content_summary=content_summary or {},
        metadata_dict=metadata_dict or {},
        created_at=datetime.utcnow(),
    )
    db.add(art_record)
    db.commit()
    db.refresh(art_record)
    return art_record


def get_project_artifacts(db, execution_id: str):
    return (
        db.query(ProjectArtifact)
        .filter(ProjectArtifact.execution_id == execution_id)
        .order_by(ProjectArtifact.created_at.asc())
        .all()
    )


def save_workforce_step(
    db,
    execution_id: str,
    step_number: int,
    task_id: str,
    worker_id: str,
    phase_id: str,
    dispatch_status: str,
    runtime_status: str = None,
    verification_status: str = None,
    sync_status: str = None,
    artifacts_produced: list = None,
    receipts_produced: list = None,
    newly_ready_tasks: list = None,
    error: str = None,
):
    step_id = f"step_{execution_id[:8]}_{step_number}_{uuid.uuid4().hex[:6]}"
    step_record = WorkforceStep(
        id=step_id,
        execution_id=execution_id,
        step_number=step_number,
        task_id=task_id,
        worker_id=worker_id,
        phase_id=phase_id,
        dispatch_status=dispatch_status,
        runtime_status=runtime_status,
        verification_status=verification_status,
        sync_status=sync_status,
        artifacts_produced=artifacts_produced or [],
        receipts_produced=receipts_produced or [],
        newly_ready_tasks=newly_ready_tasks or [],
        error=error,
        executed_at=datetime.utcnow(),
    )
    db.add(step_record)
    db.commit()
    db.refresh(step_record)
    return step_record


def get_workforce_steps(db, execution_id: str):
    return (
        db.query(WorkforceStep)
        .filter(WorkforceStep.execution_id == execution_id)
        .order_by(WorkforceStep.step_number.asc())
        .all()
    )


def save_health_report(
    db,
    report_id: str,
    execution_id: str,
    status: str,
    project_id: str = None,
    assessed_url: str = None,
    observations: list = None,
    findings: list = None,
    unavailable_signals: list = None,
    recommendations: list = None,
    provenance: dict = None,
):
    from sqlalchemy.orm.attributes import flag_modified
    import copy

    existing = db.query(HealthReportRecord).filter(HealthReportRecord.id == report_id).first()
    if existing:
        existing.status = status
        existing.assessed_url = assessed_url
        if observations is not None:
            existing.observations = copy.deepcopy(observations)
            flag_modified(existing, "observations")
        if findings is not None:
            existing.findings = copy.deepcopy(findings)
            flag_modified(existing, "findings")
        if unavailable_signals is not None:
            existing.unavailable_signals = copy.deepcopy(unavailable_signals)
            flag_modified(existing, "unavailable_signals")
        if recommendations is not None:
            existing.recommendations = copy.deepcopy(recommendations)
            flag_modified(existing, "recommendations")
        if provenance is not None:
            existing.provenance = copy.deepcopy(provenance)
            flag_modified(existing, "provenance")
        existing.assessed_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    report_record = HealthReportRecord(
        id=report_id,
        execution_id=execution_id,
        project_id=project_id,
        status=status,
        assessed_url=assessed_url,
        observations=observations or [],
        findings=findings or [],
        unavailable_signals=unavailable_signals or [],
        recommendations=recommendations or [],
        provenance=provenance or {},
        assessed_at=datetime.utcnow(),
    )
    db.add(report_record)
    db.commit()
    db.refresh(report_record)
    return report_record


def get_latest_health_report(db, execution_id: str):
    return (
        db.query(HealthReportRecord)
        .filter(HealthReportRecord.execution_id == execution_id)
        .order_by(HealthReportRecord.assessed_at.desc())
        .first()
    )


