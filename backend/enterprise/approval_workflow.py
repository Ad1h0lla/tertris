import uuid
from datetime import datetime, timezone


_approvals = {}
_audit_logs = {}


def create_approval_request(
    execution_id,
    phase,
    outcome,
    team_id,
    submitted_by,
):
    try:
        approval_id = str(uuid.uuid4())

        timestamp = datetime.now(timezone.utc).isoformat()

        approval = {
            "approval_id": approval_id,
            "execution_id": execution_id,
            "phase": phase,
            "outcome": outcome,
            "team_id": team_id,
            "submitted_by": submitted_by,
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
        }

        _approvals[approval_id] = approval

        if execution_id not in _audit_logs:
            _audit_logs[execution_id] = []

        _audit_logs[execution_id].append({
            "action": "submitted",
            "by": submitted_by,
            "timestamp": timestamp,
            "approval_id": approval_id,
            "phase": phase,
        })

        return {
            "approval_id": approval_id,
            "status": "pending",
            "phase": phase,
            "team_id": team_id,
            "submitted_by": submitted_by,
            "created_at": timestamp,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def get_pending_approvals(team_id):
    try:
        results = []

        for approval in _approvals.values():
            if approval.get("team_id") != team_id:
                continue

            if approval.get("status") != "pending":
                continue

            results.append(approval)

        return results

    except Exception:
        return []


def approve_phase(
    approval_id,
    approved_by,
    notes,
):
    try:
        if approval_id not in _approvals:
            return {
                "success": False,
                "error": "Approval request not found",
            }

        approval = _approvals[approval_id]

        if approval["status"] != "pending":
            return {
                "success": False,
                "error": f"Approval is already {approval['status']}",
            }

        timestamp = datetime.now(timezone.utc).isoformat()

        approval["status"] = "approved"
        approval["approved_by"] = approved_by
        approval["notes"] = notes
        approval["updated_at"] = timestamp

        execution_id = approval.get("execution_id")

        if execution_id:
            if execution_id not in _audit_logs:
                _audit_logs[execution_id] = []

            _audit_logs[execution_id].append({
                "action": "approved",
                "by": approved_by,
                "timestamp": timestamp,
                "notes": notes,
                "approval_id": approval_id,
            })

        return {
            "success": True,
            "approval_id": approval_id,
            "status": "approved",
            "approved_by": approved_by,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def reject_phase(
    approval_id,
    rejected_by,
    reason,
):
    try:
        if approval_id not in _approvals:
            return {
                "success": False,
                "error": "Approval request not found",
            }

        approval = _approvals[approval_id]

        if approval["status"] != "pending":
            return {
                "success": False,
                "error": f"Approval is already {approval['status']}",
            }

        timestamp = datetime.now(timezone.utc).isoformat()

        approval["status"] = "rejected"
        approval["rejected_by"] = rejected_by
        approval["reason"] = reason
        approval["updated_at"] = timestamp

        execution_id = approval.get("execution_id")

        if execution_id:
            if execution_id not in _audit_logs:
                _audit_logs[execution_id] = []

            _audit_logs[execution_id].append({
                "action": "rejected",
                "by": rejected_by,
                "timestamp": timestamp,
                "reason": reason,
                "approval_id": approval_id,
            })

        return {
            "success": True,
            "approval_id": approval_id,
            "status": "rejected",
            "reason": reason,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def get_audit_trail(execution_id):
    try:
        return _audit_logs.get(execution_id, [])
    except Exception:
        return []


def get_approval_status(approval_id):
    try:
        approval = _approvals.get(approval_id)

        if not approval:
            return {
                "success": False,
                "error": "Approval request not found",
            }

        return {
            "success": True,
            "approval_id": approval_id,
            "status": approval.get("status"),
            "execution_id": approval.get("execution_id"),
            "phase": approval.get("phase"),
            "created_at": approval.get("created_at"),
            "updated_at": approval.get("updated_at"),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
