"""
Tetris — Workforce Engine: Context Synchronizer (Stage 5C)
==========================================================

Consumes verified RuntimeResults (Stage 5B) and updates ProjectContext (Stage 4A)
with complete provenance, defense-in-depth secret redaction, and strict verification gates:

1. SyncStatus (SYNCED, REJECTED, SKIPPED, FAILED)
2. SyncResult (Typed audit of artifacts created, receipts recorded, and phase outcomes updated)
3. ContextSynchronizer (Atomic, idempotent synchronization engine)

Architectural Rules:
- Verification Gate: ONLY RuntimeResults with verified == True (PASS) promote successful deliverables.
- Defense-in-Depth: Redacts any sensitive credentials before persisting to ProjectContext.
- Idempotency: Re-applying the same RuntimeResult produces zero duplicate artifacts, receipts, or outcomes.
- Full Provenance: Preserves project -> phase -> worker -> task -> execution -> result -> deliverable links.
- Atomic & Safe: Incomplete or unverified results leave ProjectContext unmutated or record failure honestly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, Field

from orchestration.execution_dispatcher import detect_unredacted_secrets
from orchestration.project_context import (
    Artifact,
    Decision,
    PhaseOutcomeReference,
    ProjectContext,
    ReceiptReference,
    _sanitize_dict_secrets,
)
from orchestration.worker_contract import WorkerState
from orchestration.worker_runtime import RuntimeResult, RuntimeStatus

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. SyncStatus: Universal Context Synchronization States
# =============================================================================

class SyncStatus(str, Enum):
    """
    Outcome status of a ProjectContext synchronization operation.
    """
    SYNCED = "SYNCED"       # Deliverables verified and promoted to ProjectContext
    REJECTED = "REJECTED"   # Rejected due to verification failure or security violation
    SKIPPED = "SKIPPED"     # Already synchronized (idempotent no-op)
    FAILED = "FAILED"       # Execution failed; failure recorded in phase history


# =============================================================================
# 2. SyncResult: Synchronization Outcome & Audit Payload
# =============================================================================

class SyncResult(BaseModel):
    """
    Detailed audit payload returned after synchronizing a RuntimeResult with ProjectContext.
    """
    status: str  # from SyncStatus
    runtime_id: str
    task_id: str
    execution_id: str
    project_id: str
    worker_id: str
    artifacts_created: List[str] = Field(default_factory=list)
    receipts_created: List[str] = Field(default_factory=list)
    phase_outcomes_updated: List[str] = Field(default_factory=list)
    reason: str = ""
    validation_errors: List[str] = Field(default_factory=list)
    synced_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_synced(self) -> bool:
        return self.status == SyncStatus.SYNCED.value

    @property
    def is_rejected(self) -> bool:
        return self.status == SyncStatus.REJECTED.value

    @property
    def is_skipped(self) -> bool:
        return self.status == SyncStatus.SKIPPED.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SyncResult:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 3. ContextSynchronizer: Atomic Provenance & Deliverable Promotor
# =============================================================================

class ContextSynchronizer:
    """
    Synchronizes verified worker RuntimeResults into authoritative ProjectContext shared memory.
    Guarantees idempotency, provenance integrity, and zero secret leakage.
    """

    def __init__(self, synchronized_runtimes: Optional[Set[str]] = None):
        self._synchronized_runtimes: Set[str] = set(synchronized_runtimes or set())

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate_result(self, runtime_result: RuntimeResult) -> tuple[bool, str, List[str]]:
        """
        Validates whether a RuntimeResult is structurally sound and satisfies verification requirements.
        Returns (is_valid, reason, validation_errors).
        """
        errors: List[str] = []

        if not runtime_result.runtime_id:
            errors.append("Missing runtime_id.")
        if not runtime_result.task_id:
            errors.append("Missing task_id.")
        if not runtime_result.execution_id:
            errors.append("Missing execution_id.")
        if not runtime_result.project_id:
            errors.append("Missing project_id.")
        if not runtime_result.worker_id:
            errors.append("Missing worker_id.")

        # Check for unredacted secrets in results or metadata
        if runtime_result.task_result:
            if detect_unredacted_secrets(runtime_result.task_result.output) or detect_unredacted_secrets(runtime_result.task_result.metadata):
                errors.append("Security violation: Unredacted sensitive credentials detected in task result.")

        if detect_unredacted_secrets(runtime_result.metadata):
            errors.append("Security violation: Unredacted sensitive credentials detected in runtime metadata.")

        if errors:
            return False, f"Validation failed: {'; '.join(errors)}", errors

        # Verification check
        if runtime_result.status != RuntimeStatus.COMPLETED.value:
            return False, f"Runtime status is '{runtime_result.status}', not COMPLETED.", ["Status not COMPLETED."]

        if not runtime_result.task_result or runtime_result.task_result.state != WorkerState.SUCCESS:
            return False, "Task execution did not report SUCCESS state.", ["TaskState not SUCCESS."]

        if not runtime_result.verification_result or not runtime_result.verification_result.verified or runtime_result.verification_result.status != "PASS":
            return False, "Verification was not passed (status not PASS).", ["Verification failed or missing."]

        return True, "Validation passed.", []

    # -------------------------------------------------------------------------
    # Synchronization
    # -------------------------------------------------------------------------

    def apply_result(
        self,
        project_context: ProjectContext,
        runtime_result: RuntimeResult,
        phase_id: Optional[str] = None,
    ) -> SyncResult:
        """
        Atomically applies a verified RuntimeResult to ProjectContext.
        """
        rid = runtime_result.runtime_id.strip() if runtime_result and runtime_result.runtime_id else "unknown_rt"
        tid = runtime_result.task_id.strip() if runtime_result and runtime_result.task_id else "unknown_task"
        eid = runtime_result.execution_id.strip() if runtime_result and runtime_result.execution_id else "unknown_exec"
        pid = runtime_result.project_id.strip() if runtime_result and runtime_result.project_id else "unknown_proj"
        wid = runtime_result.worker_id.strip() if runtime_result and runtime_result.worker_id else "unknown_worker"

        effective_phase_id = phase_id or runtime_result.metadata.get("phase_id", "phase_unknown")

        # 1. Structural and Secret Validation
        is_valid, reason, errors = self.validate_result(runtime_result)
        if any("Security violation" in e for e in errors) or any("Missing" in e for e in errors):
            return SyncResult(
                status=SyncStatus.REJECTED.value,
                runtime_id=rid,
                task_id=tid,
                execution_id=eid,
                project_id=pid,
                worker_id=wid,
                reason=reason,
                validation_errors=errors,
            )

        # 2. Idempotency Check
        if rid in self._synchronized_runtimes:
            return SyncResult(
                status=SyncStatus.SKIPPED.value,
                runtime_id=rid,
                task_id=tid,
                execution_id=eid,
                project_id=pid,
                worker_id=wid,
                reason=f"RuntimeResult '{rid}' has already been synchronized.",
            )

        # 3. Handle Failure / Unverified Cases Honestly
        if not is_valid:
            # Record failure reference in phase history without creating false success artifacts
            phase_ref = PhaseOutcomeReference(
                phase_id=effective_phase_id,
                phase_name=effective_phase_id.replace("phase_", "").title(),
                status="FAILED",
                producer_worker=wid,
                verification_status=runtime_result.verification_result.status if runtime_result.verification_result else "FAIL",
                summary=runtime_result.error or f"Task '{tid}' failed during execution or verification.",
                completed_at=_utc_now_iso(),
                metadata={"task_id": tid, "runtime_id": rid, "execution_id": eid},
            )
            project_context.add_phase_outcome(phase_ref)
            self._synchronized_runtimes.add(rid)

            return SyncResult(
                status=SyncStatus.FAILED.value if runtime_result.status == RuntimeStatus.FAILED.value else SyncStatus.REJECTED.value,
                runtime_id=rid,
                task_id=tid,
                execution_id=eid,
                project_id=pid,
                worker_id=wid,
                phase_outcomes_updated=[effective_phase_id],
                reason=reason,
                validation_errors=errors,
            )

        # 4. Verified Success Case (Execution SUCCEEDED + Verification PASSED)
        artifacts_created: List[str] = []
        receipts_created: List[str] = []
        phase_outcomes_updated: List[str] = []

        task_res = runtime_result.task_result
        verif_res = runtime_result.verification_result

        # A. Register Produced Artifacts with Full Provenance
        if task_res and task_res.artifacts:
            for idx, raw_art in enumerate(task_res.artifacts):
                art_type = raw_art.get("artifact_type", "deliverable")
                art_id = f"art_{tid}_{art_type}" if idx == 0 else f"art_{tid}_{art_type}_{idx}"

                art = Artifact(
                    artifact_id=art_id,
                    name=raw_art.get("name", f"{art_type.replace('_', ' ').title()} Deliverable"),
                    artifact_type=art_type,
                    phase_id=effective_phase_id,
                    producer_worker=wid,
                    producer_task=tid,
                    status="AVAILABLE",
                    location=raw_art.get("location", ""),
                    content_summary=_sanitize_dict_secrets(raw_art.get("summary") or raw_art.get("content") or raw_art),
                    metadata={
                        "runtime_id": rid,
                        "execution_id": eid,
                        "verified": True,
                        "verification_status": "PASS",
                    },
                    created_at=_utc_now_iso(),
                )
                project_context.add_artifact(art, allow_replace=True)
                artifacts_created.append(art_id)
        elif task_res and task_res.output:
            # Primary output artifact synthesis if not explicitly listed in artifacts
            primary_type = f"{wid.replace('worker_', '')}_deliverable"
            art_id = f"art_{tid}_{primary_type}"
            art = Artifact(
                artifact_id=art_id,
                name=f"{primary_type.replace('_', ' ').title()} Deliverable",
                artifact_type=primary_type,
                phase_id=effective_phase_id,
                producer_worker=wid,
                producer_task=tid,
                status="AVAILABLE",
                content_summary=_sanitize_dict_secrets(task_res.output),
                metadata={"runtime_id": rid, "execution_id": eid, "verified": True},
                created_at=_utc_now_iso(),
            )
            project_context.add_artifact(art, allow_replace=True)
            artifacts_created.append(art_id)

        # B. Register External Receipts if Verified Side-Effect Actions Exist
        if verif_res and (verif_res.external_id or verif_res.permalink or verif_res.evidence.get("receipt_id")):
            rcpt_id = verif_res.evidence.get("receipt_id") or f"rcpt_{tid}"
            # Deduplicate receipts
            if not any(r.receipt_id == rcpt_id for r in project_context.receipts):
                receipt = ReceiptReference(
                    receipt_id=rcpt_id,
                    platform=verif_res.evidence.get("platform", "external"),
                    action_type=verif_res.evidence.get("action_type", "execute_action"),
                    external_id=verif_res.external_id,
                    permalink=verif_res.permalink,
                    verified=True,
                    verification_status="PASS",
                    evidence=_sanitize_dict_secrets(verif_res.evidence),
                    phase_id=effective_phase_id,
                    producer_worker=wid,
                    executed_at=_utc_now_iso(),
                )
                project_context.add_receipt(receipt)
                receipts_created.append(rcpt_id)

        # C. Update Phase History Reference
        phase_outcome = PhaseOutcomeReference(
            phase_id=effective_phase_id,
            phase_name=effective_phase_id.replace("phase_", "").title(),
            status="COMPLETED",
            result_reference=rid,
            outcome_type=artifacts_created[0] if artifacts_created else "deliverable",
            producer_worker=wid,
            verification_status="PASS",
            summary=f"Task '{tid}' verified successfully by {wid}.",
            completed_at=_utc_now_iso(),
            metadata={
                "task_id": tid,
                "runtime_id": rid,
                "execution_id": eid,
                "artifacts_produced": artifacts_created,
            },
        )
        project_context.add_phase_outcome(phase_outcome)
        phase_outcomes_updated.append(effective_phase_id)

        # Mark runtime as synchronized
        self._synchronized_runtimes.add(rid)

        return SyncResult(
            status=SyncStatus.SYNCED.value,
            runtime_id=rid,
            task_id=tid,
            execution_id=eid,
            project_id=pid,
            worker_id=wid,
            artifacts_created=artifacts_created,
            receipts_created=receipts_created,
            phase_outcomes_updated=phase_outcomes_updated,
            reason=f"RuntimeResult '{rid}' successfully synchronized with ProjectContext.",
        )
