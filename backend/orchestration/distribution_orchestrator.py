"""
Tetris — M3.5-B Distribution Orchestrator
==========================================

Authoritative orchestration and state layer connecting the Phase 2/3
distribution intelligence/plan to the underlying platform workers.

Key Responsibilities:
1. Deterministic campaign state machine:
   PLANNED -> AWAITING_CONNECTION -> AWAITING_APPROVAL -> READY -> RUNNING -> (COMPLETED | PARTIAL | BLOCKED | FAILED)
2. User-scoped DB session enforcement:
   Every execution requires a live SQLAlchemy DB session. db=None is strictly forbidden.
3. Connector readiness evaluation:
   Queries M3.5-A StoredCredential repository without duplicating credential logic.
4. Strict approval lifecycle:
   PREPARE -> REVIEW -> APPROVE -> EXECUTE -> VERIFY.
   Unapproved external actions are blocked from dispatch.
5. Sequential action dispatch:
   Dispatches through execute_distribution_action with db passed explicitly.
6. Idempotency & safe retry:
   Successful actions are never duplicated; failed actions require explicit retry.
7. Real worker receipt preservation:
   Captures authentic provider receipts without fabrication.
8. Persistence across server restarts via SQLite distribution_campaigns table.
9. Structured observability events without credential exposure.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from database.operations import (
    get_distribution_campaign_by_id,
    save_distribution_campaign,
    get_phase_results,
    save_phase_result,
)
from execution.distribution_models import (
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
    create_distribution_action,
)
from execution.execution_router import execute_distribution_action
from integrations.credential_manager import get_connected_apps

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Contracts
# ---------------------------------------------------------------------------

class CampaignStatus:
    PLANNED = "PLANNED"
    AWAITING_CONNECTION = "AWAITING_CONNECTION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    VALID_STATUSES = {
        PLANNED,
        AWAITING_CONNECTION,
        AWAITING_APPROVAL,
        READY,
        RUNNING,
        PARTIAL,
        COMPLETED,
        BLOCKED,
        FAILED,
    }


class ActionStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class ObservabilityEvent:
    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"
    READINESS_CHECKED = "READINESS_CHECKED"
    AWAITING_CONNECTION = "AWAITING_CONNECTION"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ACTION_APPROVED = "ACTION_APPROVED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    CAMPAIGN_COMPLETED = "CAMPAIGN_COMPLETED"
    CAMPAIGN_PARTIAL = "CAMPAIGN_PARTIAL"
    CAMPAIGN_FAILED = "CAMPAIGN_FAILED"
    CAMPAIGN_BLOCKED = "CAMPAIGN_BLOCKED"


# ---------------------------------------------------------------------------
# Helper Utilities
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_for_logging(data: Any) -> Any:
    """Recursively strip any credentials or secret keys from data structures."""
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            if any(secret_term in k.lower() for secret_term in ("token", "secret", "password", "key", "auth")):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = _sanitize_for_logging(v)
        return clean
    if isinstance(data, list):
        return [_sanitize_for_logging(item) for item in data]
    return data


def _normalize_platform(worker: str, platform: str) -> str:
    p = (platform or "").strip().lower()
    w = (worker or "").strip().lower()

    if p in ("x", "twitter", "x/twitter", "x / twitter") or w == "social" and p in ("", "twitter", "x"):
        return "twitter"
    if p in ("reddit",) or w == "community":
        return "reddit"
    if p in ("linkedin",):
        return "linkedin"
    if p in ("sendgrid", "smtp", "email", "mail", "gmail") or w == "outreach":
        if p in ("sendgrid", "smtp"):
            return p
        return "email"
    return p or w or "unknown"


def _resolve_required_connector(action: dict, connected_platforms: set[str]) -> str:
    """
    Given an action and the user's currently connected platforms, determines
    the authoritative connector key (e.g. reddit, twitter, linkedin, sendgrid, smtp).
    """
    platform = (action.get("platform") or "").strip().lower()
    worker = (action.get("worker") or "").strip().lower()

    if platform in ("reddit",) or worker == "community":
        return "reddit"
    if platform in ("twitter", "x", "x/twitter", "x / twitter"):
        return "twitter"
    if platform in ("linkedin",):
        return "linkedin"

    # Outreach / Email resolution:
    if platform in ("email", "mail", "gmail", "sendgrid", "smtp") or worker == "outreach":
        target = action.get("target") or {}
        explicit_provider = str(action.get("provider") or target.get("provider") or "").lower()
        if explicit_provider == "smtp":
            return "smtp"
        if explicit_provider == "sendgrid":
            return "sendgrid"
        # Preference based on what user already has connected:
        if "sendgrid" in connected_platforms:
            return "sendgrid"
        if "smtp" in connected_platforms:
            return "smtp"
        return "sendgrid"

    return platform or "unknown"


def _record_event(
    events_list: list,
    event_type: str,
    campaign_id: str,
    execution_id: str,
    status: str,
    action_id: Optional[str] = None,
    platform: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    evt = {
        "event": event_type,
        "campaign_id": campaign_id,
        "execution_id": execution_id,
        "status": status,
        "action_id": action_id,
        "platform": platform,
        "timestamp": _utc_now_iso(),
        "details": _sanitize_for_logging(details or {}),
    }
    events_list.append(evt)
    return evt


def _compute_summary(actions: list[dict]) -> dict:
    total = len(actions)
    success = sum(1 for a in actions if a.get("execution", {}).get("status") == ExecutionStatus.SUCCESS)
    failed = sum(1 for a in actions if a.get("execution", {}).get("status") == ExecutionStatus.FAILED)
    blocked = sum(1 for a in actions if a.get("execution", {}).get("status") == ExecutionStatus.BLOCKED)
    skipped = sum(1 for a in actions if a.get("execution", {}).get("status") == "SKIPPED")
    pending = sum(
        1 for a in actions
        if a.get("execution", {}).get("status") in (ExecutionStatus.NOT_STARTED, None, "")
    )

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "blocked": blocked,
        "pending": pending,
        "skipped": skipped,
    }


def _aggregate_campaign_status(actions: list[dict], connector_requirements: list[dict]) -> str:
    """
    Deterministic campaign state aggregation:
    - If connector requirements are not all READY -> AWAITING_CONNECTION
    - If no actions have started and any need approval -> AWAITING_APPROVAL
    - If no actions have started and all approved -> READY
    - Once execution has commenced:
      - All success -> COMPLETED
      - Some success, some failed/blocked -> PARTIAL
      - No success, at least one failed -> FAILED
      - No success, all attempted are blocked -> BLOCKED
    """
    # Check connector readiness first:
    has_unconnected = any(req.get("status") != "READY" for req in connector_requirements)
    if has_unconnected:
        return CampaignStatus.AWAITING_CONNECTION

    if not actions:
        return CampaignStatus.READY

    statuses = [a.get("execution", {}).get("status", ExecutionStatus.NOT_STARTED) for a in actions]
    approvals = [a.get("approval", {}).get("status", ApprovalStatus.PENDING_APPROVAL) for a in actions]

    started_any = any(st in (ExecutionStatus.RUNNING, ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.BLOCKED) for st in statuses)

    if not started_any:
        # Has not executed yet
        if any(appr != ApprovalStatus.APPROVED for appr in approvals):
            return CampaignStatus.AWAITING_APPROVAL
        return CampaignStatus.READY

    total = len(actions)
    success_count = sum(1 for st in statuses if st == ExecutionStatus.SUCCESS)
    failed_count = sum(1 for st in statuses if st == ExecutionStatus.FAILED)
    blocked_count = sum(1 for st in statuses if st == ExecutionStatus.BLOCKED)

    if success_count == total:
        return CampaignStatus.COMPLETED
    if success_count > 0:
        return CampaignStatus.PARTIAL
    if failed_count > 0:
        return CampaignStatus.FAILED
    if blocked_count > 0:
        return CampaignStatus.BLOCKED

    return CampaignStatus.READY


# ---------------------------------------------------------------------------
# Core Campaign Operations
# ---------------------------------------------------------------------------

def create_campaign(
    db,
    execution_id: str,
    user_id: str = "user_001",
    distribution_plan: Optional[dict] = None,
    actions: Optional[list] = None,
    campaign_id: Optional[str] = None,
) -> dict:
    """
    Initializes a persistent DistributionCampaign.
    Validates user DB session and formats proposed actions to standard contracts.
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    cid = campaign_id or f"cmp_{uuid.uuid4().hex[:12]}"

    # Extract actions from supplied arguments or PhaseResult
    raw_actions = actions or []
    if not raw_actions and distribution_plan:
        raw_actions = distribution_plan.get("actions", [])

    if not raw_actions and execution_id:
        prs = get_phase_results(db, execution_id)
        for pr in prs:
            if getattr(pr, "distribution_plan", None):
                plan = pr.distribution_plan
                if isinstance(plan, dict) and "actions" in plan:
                    raw_actions = plan.get("actions", [])
                    break

    normalized_actions = []
    for item in raw_actions:
        if isinstance(item, dict):
            act_copy = copy.deepcopy(item)
            if not act_copy.get("action_id"):
                act_copy["action_id"] = str(uuid.uuid4())
            if not act_copy.get("execution_id"):
                act_copy["execution_id"] = execution_id
            if "approval" not in act_copy or not isinstance(act_copy["approval"], dict):
                act_copy["approval"] = {
                    "required": True,
                    "status": ApprovalStatus.PENDING_APPROVAL,
                }
            if "execution" not in act_copy or not isinstance(act_copy["execution"], dict):
                act_copy["execution"] = {
                    "status": ExecutionStatus.NOT_STARTED,
                }
            if "receipt" not in act_copy or not isinstance(act_copy["receipt"], dict):
                act_copy["receipt"] = {
                    "verified": False,
                    "verification_status": VerificationStatus.NOT_TESTED,
                    "external_id": None,
                    "external_url": None,
                }
            normalized_actions.append(act_copy)

    events: list[dict] = []
    _record_event(
        events,
        ObservabilityEvent.CAMPAIGN_CREATED,
        cid,
        execution_id,
        CampaignStatus.PLANNED,
        details={"total_actions": len(normalized_actions)},
    )

    summary = _compute_summary(normalized_actions)

    campaign_obj = save_distribution_campaign(
        db=db,
        campaign_id=cid,
        execution_id=execution_id,
        user_id=user_id,
        status=CampaignStatus.PLANNED,
        actions=normalized_actions,
        summary=summary,
        connector_requirements=[],
        events=events,
        phase=3,
    )

    return get_canonical_campaign(db, cid)


def check_connector_readiness(
    db,
    campaign_id: str,
    user_id: str = "user_001",
) -> dict:
    """
    Evaluates connector requirements for all actions in the campaign against the user's
    active StoredCredentials in the database.
    Does not duplicate credential logic or make external API write calls.
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    if not campaign:
        raise ValueError(f"Distribution campaign '{campaign_id}' not found.")

    actions = list(campaign.actions or [])
    events = list(campaign.events or [])

    # Fetch active credentials for THIS specific user
    user_credentials = get_connected_apps(db, user_id=user_id)
    connected_platforms = {c["app_name"].lower() for c in user_credentials}

    # Determine unique required connectors
    required_platforms: set[str] = set()
    for act in actions:
        req_conn = _resolve_required_connector(act, connected_platforms)
        if req_conn and req_conn != "unknown":
            required_platforms.add(req_conn)

    connector_requirements = []
    all_ready = True
    for plat in sorted(list(required_platforms)):
        is_connected = (plat in connected_platforms)
        if not is_connected:
            all_ready = False
        connector_requirements.append({
            "platform": plat,
            "status": "READY" if is_connected else "NOT_CONNECTED",
        })

    # Evaluate new status
    new_status = _aggregate_campaign_status(actions, connector_requirements)

    _record_event(
        events,
        ObservabilityEvent.READINESS_CHECKED,
        campaign_id,
        campaign.execution_id,
        new_status,
        details={"connector_requirements": connector_requirements},
    )

    if not all_ready:
        _record_event(
            events,
            ObservabilityEvent.AWAITING_CONNECTION,
            campaign_id,
            campaign.execution_id,
            new_status,
            details={"missing": [r["platform"] for r in connector_requirements if r["status"] != "READY"]},
        )
    elif new_status == CampaignStatus.AWAITING_APPROVAL:
        _record_event(
            events,
            ObservabilityEvent.APPROVAL_REQUIRED,
            campaign_id,
            campaign.execution_id,
            new_status,
            details={"message": "All required connectors ready; actions require approval"},
        )

    summary = _compute_summary(actions)

    save_distribution_campaign(
        db=db,
        campaign_id=campaign_id,
        execution_id=campaign.execution_id,
        user_id=user_id,
        status=new_status,
        actions=actions,
        summary=summary,
        connector_requirements=connector_requirements,
        events=events,
        phase=campaign.phase,
    )

    return get_canonical_campaign(db, campaign_id)


def approve_actions(
    db,
    campaign_id: str,
    user_id: str = "user_001",
    action_ids: Optional[list[str]] = None,
    approve_all: bool = False,
) -> dict:
    """
    Transitions specified actions from PENDING_APPROVAL to APPROVED.
    Supports approving specific action IDs or all campaign actions.
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    if not campaign:
        raise ValueError(f"Distribution campaign '{campaign_id}' not found.")

    actions = list(campaign.actions or [])
    events = list(campaign.events or [])
    target_ids = set(action_ids or []) if not approve_all and action_ids is not None else None

    approved_count = 0
    now_iso = _utc_now_iso()

    for act in actions:
        aid = act.get("action_id")
        if approve_all or target_ids is None or aid in target_ids:
            if "approval" not in act or not isinstance(act["approval"], dict):
                act["approval"] = {}
            act["approval"]["status"] = ApprovalStatus.APPROVED
            act["approval"]["approved_at"] = now_iso
            approved_count += 1
            _record_event(
                events,
                ObservabilityEvent.ACTION_APPROVED,
                campaign_id,
                campaign.execution_id,
                act.get("execution", {}).get("status", ExecutionStatus.NOT_STARTED),
                action_id=aid,
                platform=act.get("platform"),
            )

    reqs = list(campaign.connector_requirements or [])
    new_status = _aggregate_campaign_status(actions, reqs)
    summary = _compute_summary(actions)

    save_distribution_campaign(
        db=db,
        campaign_id=campaign_id,
        execution_id=campaign.execution_id,
        user_id=user_id,
        status=new_status,
        actions=actions,
        summary=summary,
        connector_requirements=reqs,
        events=events,
        phase=campaign.phase,
    )

    return get_canonical_campaign(db, campaign_id)


def execute_campaign(
    db,
    campaign_id: str,
    user_id: str = "user_001",
    action_ids: Optional[list[str]] = None,
    router_dispatch_fn: Optional[Callable] = None,
    **kwargs,
) -> dict:
    """
    Sequentially executes approved campaign actions through the authoritative execution router.

    Enforces:
    1. db session mandatory (raises ValueError if db is None).
    2. Connector readiness check (refuses execution if connectors missing).
    3. Approval check (unapproved actions are never dispatched).
    4. Idempotency (successful actions are never re-run).
    5. Real receipt preservation (never fabricates external verification).
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    if not campaign:
        raise ValueError(f"Distribution campaign '{campaign_id}' not found.")

    if campaign.user_id != user_id:
        raise PermissionError(f"User '{user_id}' is not authorized to execute campaign owned by '{campaign.user_id}'.")

    # Re-evaluate connector readiness first
    readiness_res = check_connector_readiness(db, campaign_id, user_id=user_id)
    reqs = readiness_res.get("connector_requirements", [])
    if any(r.get("status") != "READY" for r in reqs):
        # Missing connector blocks campaign execution
        return readiness_res

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    actions = list(campaign.actions or [])
    events = list(campaign.events or [])
    target_ids = set(action_ids) if action_ids is not None else None

    # Set campaign to RUNNING
    save_distribution_campaign(
        db=db,
        campaign_id=campaign_id,
        execution_id=campaign.execution_id,
        user_id=user_id,
        status=CampaignStatus.RUNNING,
        actions=actions,
        summary=campaign.summary,
        connector_requirements=reqs,
        events=events,
        phase=campaign.phase,
    )

    for act in actions:
        aid = act.get("action_id")
        if target_ids is not None and aid not in target_ids:
            continue

        exec_status = act.get("execution", {}).get("status", ExecutionStatus.NOT_STARTED)
        approval_status = act.get("approval", {}).get("status", ApprovalStatus.PENDING_APPROVAL)

        # Idempotency guard: already successful actions must not execute again
        if exec_status == ExecutionStatus.SUCCESS:
            continue

        # Idempotency guard: running actions must not be duplicated
        if exec_status == ExecutionStatus.RUNNING:
            continue

        # Idempotency guard: failed actions require explicit retry
        if exec_status == ExecutionStatus.FAILED:
            continue

        # Approval gate
        if approval_status != ApprovalStatus.APPROVED:
            act["execution"]["status"] = ExecutionStatus.BLOCKED
            act["error"] = f"Approval required before execution. Current approval status: '{approval_status}'."
            act["reason"] = "APPROVAL_REQUIRED"
            _record_event(
                events,
                ObservabilityEvent.ACTION_BLOCKED,
                campaign_id,
                campaign.execution_id,
                ExecutionStatus.BLOCKED,
                action_id=aid,
                platform=act.get("platform"),
                details={"reason": "APPROVAL_REQUIRED"},
            )
            continue

        # Mark action RUNNING
        act["execution"]["status"] = ExecutionStatus.RUNNING
        _record_event(
            events,
            ObservabilityEvent.ACTION_STARTED,
            campaign_id,
            campaign.execution_id,
            ExecutionStatus.RUNNING,
            action_id=aid,
            platform=act.get("platform"),
        )

        # Dispatch via authoritative execution router
        try:
            if router_dispatch_fn:
                try:
                    receipt = router_dispatch_fn(action=act, user_id=user_id, db=db, **kwargs)
                except TypeError:
                    receipt = router_dispatch_fn(act, user_id, db)
            else:
                receipt = execute_distribution_action(action=act, user_id=user_id, db=db, **kwargs)
        except Exception as exc:
            receipt = {
                "status": ExecutionStatus.FAILED,
                "verified": False,
                "verification_status": VerificationStatus.FAIL,
                "error": f"Execution router error: {str(exc)}",
                "reason": "DISPATCH_EXCEPTION",
            }

        # Parse worker outcome
        worker_status = receipt.get("status") or (
            ExecutionStatus.SUCCESS if receipt.get("verified") else ExecutionStatus.FAILED
        )
        verified = bool(receipt.get("verified", False))
        verification_status = receipt.get("verification_status") or (
            VerificationStatus.PASS if verified else VerificationStatus.FAIL
        )
        ext_id = receipt.get("external_id")
        ext_url = receipt.get("external_url") or receipt.get("permalink") or receipt.get("url")
        err = receipt.get("error")
        reason = receipt.get("reason")

        # Crucial integrity check: missing receipt cannot become SUCCESS
        if worker_status == ExecutionStatus.SUCCESS and not verified:
            worker_status = ExecutionStatus.FAILED
            err = err or "Verification failed: Worker returned SUCCESS without verified external receipt."
            verification_status = VerificationStatus.FAIL

        act["execution"]["status"] = worker_status
        act["receipt"] = {
            "verified": verified,
            "verification_status": verification_status,
            "external_id": ext_id,
            "external_url": ext_url,
        }
        if err:
            act["error"] = err
        if reason:
            act["reason"] = reason
        act["executed_at"] = _utc_now_iso()

        # Observability event
        if worker_status == ExecutionStatus.SUCCESS:
            _record_event(
                events,
                ObservabilityEvent.ACTION_COMPLETED,
                campaign_id,
                campaign.execution_id,
                worker_status,
                action_id=aid,
                platform=act.get("platform"),
                details={"external_id": ext_id, "external_url": ext_url},
            )
        elif worker_status == ExecutionStatus.BLOCKED:
            _record_event(
                events,
                ObservabilityEvent.ACTION_BLOCKED,
                campaign_id,
                campaign.execution_id,
                worker_status,
                action_id=aid,
                platform=act.get("platform"),
                details={"reason": reason, "error": err},
            )
        else:
            _record_event(
                events,
                ObservabilityEvent.ACTION_FAILED,
                campaign_id,
                campaign.execution_id,
                worker_status,
                action_id=aid,
                platform=act.get("platform"),
                details={"reason": reason, "error": err},
            )

    # Compute aggregation
    summary = _compute_summary(actions)
    final_status = _aggregate_campaign_status(actions, reqs)

    # Record campaign terminal event
    if final_status == CampaignStatus.COMPLETED:
        _record_event(events, ObservabilityEvent.CAMPAIGN_COMPLETED, campaign_id, campaign.execution_id, final_status)
    elif final_status == CampaignStatus.PARTIAL:
        _record_event(events, ObservabilityEvent.CAMPAIGN_PARTIAL, campaign_id, campaign.execution_id, final_status)
    elif final_status == CampaignStatus.FAILED:
        _record_event(events, ObservabilityEvent.CAMPAIGN_FAILED, campaign_id, campaign.execution_id, final_status)
    elif final_status == CampaignStatus.BLOCKED:
        _record_event(events, ObservabilityEvent.CAMPAIGN_BLOCKED, campaign_id, campaign.execution_id, final_status)

    # Sync with PhaseResult if one exists for this execution
    if campaign.execution_id:
        prs = get_phase_results(db, campaign.execution_id)
        for pr in prs:
            if getattr(pr, "distribution_plan", None):
                plan_copy = copy.deepcopy(pr.distribution_plan)
                if isinstance(plan_copy, dict):
                    plan_copy["actions"] = actions
                    pr.distribution_plan = plan_copy
                    db.commit()
                break

    save_distribution_campaign(
        db=db,
        campaign_id=campaign_id,
        execution_id=campaign.execution_id,
        user_id=user_id,
        status=final_status,
        actions=actions,
        summary=summary,
        connector_requirements=reqs,
        events=events,
        phase=campaign.phase,
    )

    return get_canonical_campaign(db, campaign_id)


def retry_failed_actions(
    db,
    campaign_id: str,
    user_id: str = "user_001",
    action_ids: Optional[list[str]] = None,
    router_dispatch_fn: Optional[Callable] = None,
    **kwargs,
) -> dict:
    """
    Explicitly retries failed or blocked actions.
    Resets their status to NOT_STARTED and dispatches them sequentially.
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    if not campaign:
        raise ValueError(f"Distribution campaign '{campaign_id}' not found.")

    actions = list(campaign.actions or [])
    target_ids = set(action_ids) if action_ids is not None else None

    retrying_ids = []
    for act in actions:
        aid = act.get("action_id")
        st = act.get("execution", {}).get("status")
        if target_ids is not None and aid not in target_ids:
            continue

        if st in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED) or target_ids is not None:
            act["execution"]["status"] = ExecutionStatus.NOT_STARTED
            act["error"] = None
            act["reason"] = None
            retrying_ids.append(aid)

    if not retrying_ids:
        return get_canonical_campaign(db, campaign_id)

    save_distribution_campaign(
        db=db,
        campaign_id=campaign_id,
        execution_id=campaign.execution_id,
        user_id=user_id,
        status=CampaignStatus.RUNNING,
        actions=actions,
        summary=campaign.summary,
        connector_requirements=campaign.connector_requirements,
        events=campaign.events,
        phase=campaign.phase,
    )

    return execute_campaign(
        db=db,
        campaign_id=campaign_id,
        user_id=user_id,
        action_ids=retrying_ids,
        router_dispatch_fn=router_dispatch_fn,
        **kwargs,
    )


def get_canonical_campaign(db, campaign_id: str) -> dict:
    """
    Returns the canonical truth of the campaign as consumed by API and UI.
    Guarantees no raw secrets are present.
    """
    if db is None:
        raise ValueError("User-scoped DB session is mandatory for orchestrated execution; db cannot be None.")

    campaign = get_distribution_campaign_by_id(db, campaign_id)
    if not campaign:
        raise ValueError(f"Distribution campaign '{campaign_id}' not found.")

    actions_safe = []
    for act in (campaign.actions or []):
        act_clean = {
            "action_id": act.get("action_id"),
            "worker": act.get("worker"),
            "platform": act.get("platform"),
            "action_type": act.get("action_type"),
            "status": act.get("execution", {}).get("status", ExecutionStatus.NOT_STARTED),
            "approval_status": act.get("approval", {}).get("status", ApprovalStatus.PENDING_APPROVAL),
            "target": _sanitize_for_logging(act.get("target") or {}),
            "content": _sanitize_for_logging(act.get("content") or {}),
            "receipt": act.get("receipt") or {
                "verified": False,
                "verification_status": VerificationStatus.NOT_TESTED,
                "external_id": None,
                "external_url": None,
            },
            "error": act.get("error"),
            "reason": act.get("reason"),
            "created_at": act.get("created_at"),
            "executed_at": act.get("executed_at"),
        }
        actions_safe.append(act_clean)

    return {
        "campaign_id": campaign.id,
        "execution_id": campaign.execution_id,
        "user_id": campaign.user_id,
        "phase": campaign.phase,
        "status": campaign.status,
        "summary": campaign.summary or _compute_summary(campaign.actions or []),
        "connector_requirements": campaign.connector_requirements or [],
        "actions": actions_safe,
        "events": campaign.events or [],
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }
