"""
Tetris — Distribution Action Models & Contracts
================================================

Defines the generic DistributionAction data model and lifecycle contracts for Phase 3.
This generic model serves all Phase 3 workers:
1. Community Bot (Reddit / forums)
2. Social Bot (Twitter/X, LinkedIn)
3. Outreach Bot (Email)

Lifecycle States:
-----------------
Approval:
  - PENDING_APPROVAL (default for all newly proposed actions)
  - APPROVED
  - REJECTED

Execution:
  - NOT_STARTED (default before execution begins)
  - RUNNING
  - SUCCESS (ONLY when external action was actually executed and verified)
  - FAILED (when external execution was attempted but failed)
  - BLOCKED (missing credentials, unconfigured connector, or policy block)

Receipt / Verification:
  - NOT_TESTED (default)
  - PASS
  - FAIL
"""

from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime, timezone


class ActionWorker:
    COMMUNITY = "community"
    SOCIAL = "social"
    OUTREACH = "outreach"
    VALID_WORKERS = {COMMUNITY, SOCIAL, OUTREACH}


class ActionPlatform:
    REDDIT = "reddit"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    EMAIL = "email"
    VALID_PLATFORMS = {REDDIT, TWITTER, LINKEDIN, EMAIL}


class ApprovalStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VALID_STATUSES = {PENDING_APPROVAL, APPROVED, REJECTED}


class ExecutionStatus:
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    VALID_STATUSES = {NOT_STARTED, RUNNING, SUCCESS, FAILED, BLOCKED}


class VerificationStatus:
    NOT_TESTED = "NOT_TESTED"
    PASS = "PASS"
    FAIL = "FAIL"
    VALID_STATUSES = {NOT_TESTED, PASS, FAIL}


def create_distribution_action(
    worker: str,
    platform: str,
    action_type: str,
    target: Dict[str, Any],
    content: Dict[str, Any],
    execution_id: str = "",
    action_id: Optional[str] = None,
    approval_required: bool = True,
    reason: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    """
    Constructs a standardized, valid DistributionAction dictionary.
    All proposed actions default strictly to PENDING_APPROVAL and NOT_STARTED.
    """
    worker_norm = (worker or "").lower().strip()
    platform_norm = (platform or "").lower().strip()
    action_type_norm = (action_type or "").lower().strip()

    # Map aliases if necessary
    if platform_norm in ("x", "x/twitter"):
        platform_norm = ActionPlatform.TWITTER
    elif platform_norm in ("mail", "gmail"):
        platform_norm = ActionPlatform.EMAIL

    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "action_id": action_id or str(uuid.uuid4()),
        "execution_id": execution_id or "",
        "phase": 3,
        "worker": worker_norm,
        "platform": platform_norm,
        "action_type": action_type_norm,
        "target": target if isinstance(target, dict) else {"target": str(target)},
        "content": content if isinstance(content, dict) else {"body": str(content)},
        "reason": reason or "",
        "source_url": source_url or "",
        "approval": {
            "required": bool(approval_required),
            "status": ApprovalStatus.PENDING_APPROVAL,
        },
        "execution": {
            "status": ExecutionStatus.NOT_STARTED,
        },
        "receipt": {
            "verified": False,
            "verification_status": VerificationStatus.NOT_TESTED,
            "external_id": None,
            "external_url": None,
        },
        "created_at": now_iso,
        "executed_at": None,
        "error": None,
    }


def validate_distribution_action(action: Dict[str, Any]) -> bool:
    """
    Validates that a dictionary adheres strictly to the generic DistributionAction contract.
    """
    if not isinstance(action, dict):
        return False

    required_keys = [
        "action_id",
        "phase",
        "worker",
        "platform",
        "action_type",
        "target",
        "content",
        "approval",
        "execution",
        "receipt",
    ]

    for k in required_keys:
        if k not in action:
            return False

    if action.get("phase") != 3:
        return False

    approval = action.get("approval")
    if not isinstance(approval, dict) or "status" not in approval:
        return False
    if approval.get("status") not in ApprovalStatus.VALID_STATUSES:
        return False

    execution = action.get("execution")
    if not isinstance(execution, dict) or "status" not in execution:
        return False
    if execution.get("status") not in ExecutionStatus.VALID_STATUSES:
        return False

    receipt = action.get("receipt")
    if not isinstance(receipt, dict) or "verification_status" not in receipt:
        return False
    if receipt.get("verification_status") not in VerificationStatus.VALID_STATUSES:
        return False

    # Security check: ensure no raw credentials exist in action payload
    for key in ("api_key", "secret", "token", "password", "authorization"):
        if key in action or key in action.get("content", {}) or key in action.get("target", {}):
            return False

    return True
