import uuid
from datetime import datetime

from database.models import (
    Execution,
    PhaseResult,
    ScheduledJob,
    StoredCredential,
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
    review_result=None,
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
        if review_result:
            existing.review_result = review_result
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
        review_result=review_result,
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
