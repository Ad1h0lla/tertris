"""
Tetris M3.5-B — Distribution Campaign API Routes
=================================================

FastAPI routes for campaign orchestration:
- POST /distribution/campaigns                      (Initialize campaign)
- GET  /distribution/campaigns/{campaign_id}        (Get canonical state)
- POST /distribution/campaigns/{campaign_id}/check-readiness
- POST /distribution/campaigns/{campaign_id}/approve
- POST /distribution/campaigns/{campaign_id}/execute
- POST /distribution/campaigns/{campaign_id}/retry
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database.models import get_db
from orchestration.distribution_orchestrator import (
    create_campaign,
    check_connector_readiness,
    approve_actions,
    execute_campaign,
    retry_failed_actions,
    get_canonical_campaign,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/distribution", tags=["distribution"])


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    execution_id: str
    user_id: str = "user_001"
    distribution_plan: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    campaign_id: Optional[str] = None


class ApproveCampaignRequest(BaseModel):
    user_id: str = "user_001"
    action_ids: Optional[List[str]] = None
    approve_all: bool = False


class ExecuteCampaignRequest(BaseModel):
    user_id: str = "user_001"
    action_ids: Optional[List[str]] = None


class RetryCampaignRequest(BaseModel):
    user_id: str = "user_001"
    action_ids: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/campaigns")
def create_distribution_campaign_endpoint(
    body: CreateCampaignRequest,
    db=Depends(get_db),
):
    """
    Creates and persists a distribution campaign from an execution distribution plan.
    """
    try:
        campaign = create_campaign(
            db=db,
            execution_id=body.execution_id,
            user_id=body.user_id,
            distribution_plan=body.distribution_plan,
            actions=body.actions,
            campaign_id=body.campaign_id,
        )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error creating campaign")
        raise HTTPException(status_code=500, detail=f"Failed to create campaign: {str(e)}")


@router.get("/campaigns/{campaign_id}")
def get_campaign_endpoint(
    campaign_id: str,
    db=Depends(get_db),
):
    """
    Returns the canonical campaign state consumed by the UI.
    """
    try:
        return get_canonical_campaign(db, campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error fetching campaign")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/check-readiness")
def check_readiness_endpoint(
    campaign_id: str,
    user_id: str = Query("user_001"),
    db=Depends(get_db),
):
    """
    Evaluates connector readiness for the campaign actions.
    Updates campaign state to AWAITING_CONNECTION, AWAITING_APPROVAL, or READY.
    """
    try:
        return check_connector_readiness(db, campaign_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error checking campaign readiness")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/approve")
def approve_actions_endpoint(
    campaign_id: str,
    body: ApproveCampaignRequest,
    db=Depends(get_db),
):
    """
    Approves selected or all actions in the campaign.
    """
    try:
        return approve_actions(
            db=db,
            campaign_id=campaign_id,
            user_id=body.user_id,
            action_ids=body.action_ids,
            approve_all=body.approve_all,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error approving actions")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/execute")
def execute_campaign_endpoint(
    campaign_id: str,
    body: ExecuteCampaignRequest,
    db=Depends(get_db),
):
    """
    Executes approved campaign actions sequentially.
    """
    try:
        return execute_campaign(
            db=db,
            campaign_id=campaign_id,
            user_id=body.user_id,
            action_ids=body.action_ids,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error executing campaign")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/retry")
def retry_campaign_endpoint(
    campaign_id: str,
    body: RetryCampaignRequest,
    db=Depends(get_db),
):
    """
    Explicitly retries failed or blocked actions.
    """
    try:
        return retry_failed_actions(
            db=db,
            campaign_id=campaign_id,
            user_id=body.user_id,
            action_ids=body.action_ids,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error retrying campaign")
        raise HTTPException(status_code=500, detail=str(e))
