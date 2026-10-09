"""
Tetris Stage 7B — Workforce API Routes
======================================

Additive FastAPI endpoints exposing the canonical Workforce execution engine,
persistence layer, approval gating, and health monitoring:

- POST /api/workforce/execute
- GET  /api/workforce/{execution_id}/status
- POST /api/workforce/{execution_id}/tasks/{task_id}/approve
- GET  /api/workforce/{execution_id}/health
- POST /api/workforce/{execution_id}/health
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database.models import get_db
from orchestration.workforce_service import (
    execute_workforce_pipeline,
    approve_and_resume_workforce_task,
    assess_and_persist_health,
    get_workforce_status_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workforce", tags=["workforce"])


# =============================================================================
# Request & Response Models
# =============================================================================

class WorkforceExecuteRequest(BaseModel):
    execution_id: str
    phase_id: Optional[str] = None
    workflow_type: Optional[str] = None
    user_id: str = "user_001"
    approved_task_ids: Optional[List[str]] = None
    dry_run: bool = False


class TaskApproveRequest(BaseModel):
    user_id: str = "user_001"
    feedback: Optional[str] = None


class HealthAssessRequest(BaseModel):
    user_id: str = "user_001"
    target_url: Optional[str] = None
    response_time_threshold_ms: float = 500.0


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/execute")
def execute_workforce_endpoint(
    body: WorkforceExecuteRequest,
    db=Depends(get_db),
):
    """
    Executes a workforce workflow through the canonical closed-loop engine:
    ProjectContext → TeamManager → TaskAssignmentEngine → WorkforceCoordinator
    → Dispatcher → WorkerRuntime → ContextSynchronizer → GraphAdvancer → SQLite.
    """
    try:
        res = execute_workforce_pipeline(
            db=db,
            execution_id=body.execution_id,
            phase_id=body.phase_id,
            workflow_type=body.workflow_type,
            approved_task_ids=body.approved_task_ids,
            user_id=body.user_id,
            dry_run=body.dry_run,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error executing workforce pipeline")
        raise HTTPException(status_code=500, detail=f"Workforce execution failed: {str(e)}")


@router.get("/{execution_id}/status")
def get_workforce_status_endpoint(
    execution_id: str,
    db=Depends(get_db),
):
    """
    Retrieves the authoritative workforce state from SQLite (tasks, artifacts, receipts, steps, health).
    """
    try:
        return get_workforce_status_payload(db=db, execution_id=execution_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error fetching workforce status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{execution_id}/tasks/{task_id}/approve")
def approve_workforce_task_endpoint(
    execution_id: str,
    task_id: str,
    body: TaskApproveRequest,
    db=Depends(get_db),
):
    """
    Approves a specific blocked task and safely resumes execution through WorkforceCoordinator.
    """
    try:
        return approve_and_resume_workforce_task(
            db=db,
            execution_id=execution_id,
            task_id=task_id,
            user_id=body.user_id,
            feedback=body.feedback,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error approving workforce task")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{execution_id}/health")
def get_workforce_health_endpoint(
    execution_id: str,
    db=Depends(get_db),
):
    """
    Retrieves the latest persisted health assessment report for the project.
    Returns status: 'NOT_ASSESSED' if no assessment has been conducted.
    """
    from database.operations import get_latest_health_report, get_execution_by_id
    exec_row = get_execution_by_id(db, execution_id)
    if not exec_row:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found.")

    report = get_latest_health_report(db, execution_id)
    if not report:
        return {
            "status": "NOT_ASSESSED",
            "message": "No health assessment has been performed for this project.",
            "report": None,
            "is_healthy": None,
        }

    return {
        "report_id": report.id,
        "execution_id": report.execution_id,
        "project_id": report.project_id,
        "status": report.status,
        "assessed_url": report.assessed_url,
        "observations": report.observations,
        "findings": report.findings,
        "unavailable_signals": report.unavailable_signals,
        "recommendations": report.recommendations,
        "provenance": report.provenance,
        "assessed_at": report.assessed_at.isoformat() if report.assessed_at else None,
        "is_healthy": (report.status == "HEALTHY"),
    }


@router.post("/{execution_id}/health")
def assess_workforce_health_endpoint(
    execution_id: str,
    body: HealthAssessRequest,
    db=Depends(get_db),
):
    """
    Executes a bounded, evidence-backed Stage 6F health assessment for the project's verified deployment.
    """
    try:
        return assess_and_persist_health(
            db=db,
            execution_id=execution_id,
            user_id=body.user_id,
            target_url=body.target_url,
            response_time_threshold_ms=body.response_time_threshold_ms,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error conducting health assessment")
        raise HTTPException(status_code=500, detail=str(e))
