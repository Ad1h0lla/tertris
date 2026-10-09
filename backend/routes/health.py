"""
Tetris Stage 7B — Dedicated Health Assessment API Routes
=========================================================

Exposes Stage 6F health evaluation and persistent retrieval:
- GET  /health/{execution_id}
- POST /health/{execution_id}/assess
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database.models import get_db
from database.operations import get_latest_health_report, get_execution_by_id
from orchestration.workforce_service import assess_and_persist_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthAssessRequest(BaseModel):
    user_id: str = "user_001"
    target_url: Optional[str] = None
    response_time_threshold_ms: float = 500.0


@router.get("/{execution_id}")
def get_health_report_endpoint(
    execution_id: str,
    db=Depends(get_db),
):
    """
    Retrieves the latest persisted health report for an execution.
    """
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


@router.post("/{execution_id}/assess")
def assess_health_endpoint(
    execution_id: str,
    body: HealthAssessRequest,
    db=Depends(get_db),
):
    """
    Triggers an evidence-backed health assessment and persists the report.
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
        logger.exception("Error assessing health")
        raise HTTPException(status_code=500, detail=str(e))
