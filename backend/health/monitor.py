"""
Tetris — Operational Health & Monitoring Foundation (Stage 6F)
==============================================================

Defines the typed models, evaluation rules, safety controls, and observation
adapters for Stage 6F Health / Operate Workforce.

1. URL & Network Safety Policies (Scheme/host validation, timeout limits, response size limits)
2. Observation (Actual telemetry/observation records)
3. Finding (Derived evidence-backed operational findings)
4. Recommendation (Structured non-executing improvement proposals)
5. HealthReport (Deterministic typed health assessment deliverable)
6. BaseHealthObserver & Injectable Observers (Real HTTP, deterministic mock)
7. Health Evaluator (Evidence-based derivation of product health)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.parse
import uuid

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Sensitive keys that must NEVER be stored or serialized in Health observations/reports
FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "session_cookies",
    "cookie",
    "cookies",
    "authorization",
    "auth_header",
    "bearer_token",
    "private_key",
}


def _sanitize_dict_secrets(obj: Any) -> Any:
    """
    Recursively scans and removes or masks any forbidden credential fields.
    """
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                clean[k] = "[REDACTED_SECRET]"
            else:
                clean[k] = _sanitize_dict_secrets(v)
        return clean
    elif isinstance(obj, list):
        return [_sanitize_dict_secrets(item) for item in obj]
    return obj


# =============================================================================
# 1. URL & Network Safety Policy
# =============================================================================

ALLOWED_URL_SCHEMES = {"http", "https"}
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MB maximum response read limit
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0


def validate_target_url(url: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates the target URL for scheme, format, and network safety.
    Returns (is_valid: bool, sanitized_url: Optional[str], error_message: Optional[str]).
    """
    if not url or not isinstance(url, str) or not url.strip():
        return False, None, "Target URL is empty or missing."

    raw_url = url.strip()
    try:
        parsed = urllib.parse.urlparse(raw_url)
    except Exception as exc:
        return False, None, f"Malformed URL format: {str(exc)}"

    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        return False, None, f"Unsupported or dangerous URL scheme: '{parsed.scheme}'. Only 'http' and 'https' are allowed."

    if not parsed.netloc:
        return False, None, "URL hostname/netloc is missing."

    hostname = parsed.hostname or ""
    if not hostname:
        return False, None, "URL hostname is empty."

    # Validate hostname syntax
    if any(ch in hostname for ch in [" ", "\t", "\r", "\n", "<", ">", '"', "'", ";", "|", "&"]):
        return False, None, "URL hostname contains forbidden special characters."

    return True, raw_url, None


# =============================================================================
# 2. Observation, Finding, Recommendation & Health Models
# =============================================================================

class ObservationStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Observation(BaseModel):
    """
    Typed record of an observed signal (e.g. HTTP status, latency, deployment state).
    """
    observation_id: str
    category: str  # "http_availability", "performance", "deployment", "distribution", "application"
    status: str    # from ObservationStatus
    value: Any
    unit: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    observed_at: str = Field(default_factory=_utc_now_iso)

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Observation:
        return cls.model_validate(_sanitize_dict_secrets(data))


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Finding(BaseModel):
    """
    Evidence-backed operational issue or assessment finding derived from observations.
    """
    finding_id: str
    category: str  # "availability", "performance", "deployment", "distribution", "monitoring"
    severity: str  # from FindingSeverity
    description: str
    supporting_observation_ids: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    recommended_action: str

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Finding:
        return cls.model_validate(_sanitize_dict_secrets(data))


class RecommendationPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Recommendation(BaseModel):
    """
    Structured, actionable, non-executing improvement proposal tied to findings.
    """
    recommendation_id: str
    category: str  # "investigation", "performance", "monitoring", "operations"
    priority: str  # from RecommendationPriority
    title: str
    description: str
    supporting_finding_ids: List[str] = Field(default_factory=list)
    actionable_steps: List[str] = Field(default_factory=list)
    executed: bool = False  # Must ALWAYS remain False in Stage 6F!

    model_config = {
        "extra": "ignore",
    }

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Recommendation:
        return cls.model_validate(_sanitize_dict_secrets(data))


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"
    ASSESSMENT_FAILED = "ASSESSMENT_FAILED"


class HealthReport(BaseModel):
    """
    Canonical deterministic health assessment deliverable.
    """
    report_id: str = Field(default_factory=lambda: f"hr_{uuid.uuid4().hex[:12]}")
    project_id: str
    execution_id: str
    assessed_at: str = Field(default_factory=_utc_now_iso)
    deployment_reference: Optional[str] = None
    assessed_url: Optional[str] = None
    status: str  # from HealthStatus
    summary: str
    observations: List[Observation] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    unavailable_signals: Dict[str, str] = Field(default_factory=dict)
    recommendations: List[Recommendation] = Field(default_factory=list)
    evaluation_rules_applied: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

    model_config = {
        "extra": "ignore",
    }

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY.value

    @property
    def is_degraded(self) -> bool:
        return self.status == HealthStatus.DEGRADED.value

    @property
    def is_unhealthy(self) -> bool:
        return self.status == HealthStatus.UNHEALTHY.value

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize_dict_secrets(self.model_dump())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HealthReport:
        return cls.model_validate(_sanitize_dict_secrets(data))


# =============================================================================
# 3. Injectable Observation Adapters
# =============================================================================

class BaseHealthObserver:
    """
    Abstract interface for injecting telemetry observations.
    """
    def observe_http(self, url: str, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> Dict[str, Any]:
        raise NotImplementedError

    def observe_custom_signals(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class MockHealthObserver(BaseHealthObserver):
    """
    Deterministic injected observer for test suites and demonstrations.
    Guarantees zero external network requests.
    """
    def __init__(
        self,
        http_status: Optional[int] = 200,
        response_time_ms: float = 120.0,
        final_url: Optional[str] = None,
        error: Optional[str] = None,
        redirects_count: int = 0,
        content_length: int = 128,
        custom_signals: Optional[Dict[str, Any]] = None,
    ):
        self.http_status = http_status
        self.response_time_ms = response_time_ms
        self.final_url = final_url
        self.error = error
        self.redirects_count = redirects_count
        self.content_length = content_length
        self.custom_signals = custom_signals or {}
        self.call_count = 0
        self.last_assessed_url: Optional[str] = None

    def observe_http(self, url: str, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> Dict[str, Any]:
        self.call_count += 1
        self.last_assessed_url = url

        status = "OK"
        if self.error or (self.http_status is not None and self.http_status >= 500) or self.http_status is None:
            status = "CRITICAL"
        elif self.http_status is not None and (self.http_status >= 400 or self.response_time_ms > 500):
            status = "WARNING"

        return {
            "status": status,
            "http_status": self.http_status,
            "response_time_ms": self.response_time_ms,
            "final_url": self.final_url or url,
            "redirects_count": self.redirects_count,
            "content_length": self.content_length,
            "error": self.error,
            "observed_at": _utc_now_iso(),
        }

    def observe_custom_signals(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self.custom_signals)


class RealHttpHealthObserver(BaseHealthObserver):
    """
    Production HTTP health observer using safe requests execution.
    """
    def observe_http(self, url: str, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> Dict[str, Any]:
        is_safe, clean_url, error_msg = validate_target_url(url)
        if not is_safe or not clean_url:
            return {
                "status": "ERROR",
                "http_status": None,
                "response_time_ms": 0.0,
                "final_url": url,
                "redirects_count": 0,
                "content_length": 0,
                "error": error_msg or "Unsafe or invalid target URL.",
                "observed_at": _utc_now_iso(),
            }

        try:
            import requests
        except ImportError:
            return {
                "status": "ERROR",
                "http_status": None,
                "response_time_ms": 0.0,
                "final_url": clean_url,
                "redirects_count": 0,
                "content_length": 0,
                "error": "Python requests library not installed.",
                "observed_at": _utc_now_iso(),
            }

        t0 = time.time()
        try:
            resp = requests.get(
                clean_url,
                timeout=timeout_seconds,
                headers={"User-Agent": "Tetris-Health-Monitor/1.0"},
                allow_redirects=True,
                stream=True,
            )
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)

            # Read bounded content size
            content = resp.raw.read(MAX_RESPONSE_BYTES)
            content_len = len(content)

            http_code = resp.status_code
            redirects_count = len(resp.history)
            final_url = resp.url

            status = "OK"
            error = None
            if http_code >= 500:
                status = "CRITICAL"
                error = f"HTTP {http_code} Server Error"
            elif http_code >= 400:
                status = "WARNING"
                error = f"HTTP {http_code} Client Error"

            return {
                "status": status,
                "http_status": http_code,
                "response_time_ms": elapsed_ms,
                "final_url": final_url,
                "redirects_count": redirects_count,
                "content_length": content_len,
                "error": error,
                "observed_at": _utc_now_iso(),
            }
        except Exception as exc:
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            return {
                "status": "CRITICAL",
                "http_status": None,
                "response_time_ms": elapsed_ms,
                "final_url": clean_url,
                "redirects_count": 0,
                "content_length": 0,
                "error": f"Connection error: {str(exc)}",
                "observed_at": _utc_now_iso(),
            }


# =============================================================================
# 4. Evidence-Based Health Evaluation Engine
# =============================================================================

def evaluate_health(
    project_id: str,
    execution_id: str,
    assessed_url: Optional[str],
    deployment_reference: Optional[str],
    http_observation: Dict[str, Any],
    deployment_artifact: Optional[Dict[str, Any]] = None,
    launch_artifact: Optional[Dict[str, Any]] = None,
    distribution_receipts: Optional[List[Dict[str, Any]]] = None,
    response_time_threshold_ms: float = 500.0,
    provenance: Optional[Dict[str, Any]] = None,
) -> HealthReport:
    """
    Pure, deterministic evaluation function that processes raw observations into
    typed Observations, Findings, Recommendations, and overall HealthStatus.
    """
    observations: List[Observation] = []
    findings: List[Finding] = []
    recommendations: List[Recommendation] = []
    rules_applied: List[str] = []
    errors: List[str] = []

    now_iso = _utc_now_iso()

    # 1. Process HTTP Observations
    http_status = http_observation.get("http_status")
    http_error = http_observation.get("error")
    response_time = http_observation.get("response_time_ms")
    final_url = http_observation.get("final_url")
    redirects_count = http_observation.get("redirects_count", 0)
    obs_status = http_observation.get("status", "OK")

    is_reachable = (http_status is not None and http_error is None)

    # Observation 1: HTTP Reachability
    reachability_obs = Observation(
        observation_id="obs_http_reachability",
        category="http_availability",
        status=ObservationStatus.OK.value if is_reachable else ObservationStatus.CRITICAL.value,
        value=is_reachable,
        details={"http_status": http_status, "error": http_error, "target_url": assessed_url},
        observed_at=now_iso,
    )
    observations.append(reachability_obs)

    # Observation 2: HTTP Status Code
    status_obs = Observation(
        observation_id="obs_http_status_code",
        category="http_availability",
        status=(
            ObservationStatus.OK.value if (http_status is not None and 200 <= http_status < 400)
            else (ObservationStatus.WARNING.value if (http_status is not None and 400 <= http_status < 500)
                  else ObservationStatus.CRITICAL.value)
        ),
        value=http_status,
        unit="status_code",
        details={"http_status": http_status, "error": http_error},
        observed_at=now_iso,
    )
    observations.append(status_obs)

    # Observation 3: Response Time
    if response_time is not None:
        latency_status = ObservationStatus.OK.value if response_time <= response_time_threshold_ms else ObservationStatus.WARNING.value
        latency_obs = Observation(
            observation_id="obs_response_time",
            category="performance",
            status=latency_status,
            value=response_time,
            unit="ms",
            details={"threshold_ms": response_time_threshold_ms, "measured_ms": response_time},
            observed_at=now_iso,
        )
        observations.append(latency_obs)

    # Observation 4: URL Resolution & Redirects
    redirect_obs = Observation(
        observation_id="obs_final_url",
        category="http_availability",
        status=ObservationStatus.OK.value,
        value=final_url or assessed_url,
        details={"redirects_count": redirects_count, "assessed_url": assessed_url},
        observed_at=now_iso,
    )
    observations.append(redirect_obs)

    # Observation 5: Deployment / Launch Status
    dep_summary = (deployment_artifact.get("content_summary") or deployment_artifact.get("content") or {}) if isinstance(deployment_artifact, dict) else {}
    launch_summary = (launch_artifact.get("content_summary") or launch_artifact.get("content") or {}) if isinstance(launch_artifact, dict) else {}
    
    verified_live_state = (
        launch_summary.get("status") == "LIVE"
        or launch_summary.get("verification_status") == "PASS"
        or dep_summary.get("deployment_status") == "SUCCESS"
    )
    dep_obs = Observation(
        observation_id="obs_deployment_state",
        category="deployment",
        status=ObservationStatus.OK.value if verified_live_state else ObservationStatus.WARNING.value,
        value="LIVE" if verified_live_state else "UNVERIFIED",
        details={"launch_status": launch_summary.get("status"), "deployment_id": deployment_reference},
        observed_at=now_iso,
    )
    observations.append(dep_obs)

    # Observation 6: Distribution Status from Receipts
    dist_receipts_list = distribution_receipts or []
    verified_receipts_count = sum(1 for r in dist_receipts_list if r.get("verified") is True or r.get("verification_status") == "PASS")
    failed_receipts_count = sum(1 for r in dist_receipts_list if r.get("verified") is False or r.get("verification_status") == "FAIL")

    dist_obs = Observation(
        observation_id="obs_distribution_state",
        category="distribution",
        status=ObservationStatus.OK.value if failed_receipts_count == 0 else ObservationStatus.WARNING.value,
        value=verified_receipts_count,
        unit="verified_channels",
        details={
            "total_receipts": len(dist_receipts_list),
            "verified_receipts": verified_receipts_count,
            "failed_receipts": failed_receipts_count,
        },
        observed_at=now_iso,
    )
    observations.append(dist_obs)

    # 2. Document Honest Unavailable Signals
    unavailable_signals: Dict[str, str] = {
        "server_logs": "Server log ingestion stream not configured for this project deployment.",
        "application_metrics": "Application runtime metrics collector (CPU/Memory/Prometheus) not configured.",
        "analytics": "Real-time user traffic analytics stream not configured.",
        "uptime_history": "Historical uptime time-series database not configured.",
    }

    # 3. Derive Evidence-Backed Findings & Actionable Recommendations

    # Rule A: Infrastructure observation error / connection failure
    if not is_reachable or obs_status == "ERROR":
        rules_applied.append("rule_http_reachability_check")
        err_msg = http_error or "Endpoint failed network reachability or returned no HTTP response."
        errors.append(err_msg)
        finding_a = Finding(
            finding_id="find_endpoint_unreachable",
            category="availability",
            severity=FindingSeverity.CRITICAL.value,
            description=f"Live endpoint '{assessed_url}' is unreachable or failed to respond: {err_msg}",
            supporting_observation_ids=["obs_http_reachability", "obs_http_status_code"],
            evidence={"error": err_msg, "target_url": assessed_url},
            confidence=1.0,
            recommended_action="Investigate DNS resolution, network routing, and hosting container status.",
        )
        findings.append(finding_a)

        recommendations.append(
            Recommendation(
                recommendation_id="rec_restore_reachability",
                category="operations",
                priority=RecommendationPriority.CRITICAL.value,
                title="Restore Endpoint Reachability",
                description=f"The live application endpoint at '{assessed_url}' is unreachable.",
                supporting_finding_ids=["find_endpoint_unreachable"],
                actionable_steps=[
                    "Check cloud hosting deployment health",
                    "Verify domain DNS A/CNAME records",
                    "Inspect backend service process logs for crashes",
                ],
                executed=False,
            )
        )

    # Rule B: HTTP 5xx Server Error
    elif http_status is not None and http_status >= 500:
        rules_applied.append("rule_http_5xx_server_error")
        finding_b = Finding(
            finding_id=f"find_http_{http_status}",
            category="availability",
            severity=FindingSeverity.CRITICAL.value,
            description=f"HTTP {http_status} server error detected at live endpoint '{assessed_url}'.",
            supporting_observation_ids=["obs_http_status_code", "obs_http_reachability"],
            evidence={"http_status": http_status, "response_time_ms": response_time, "target_url": assessed_url},
            confidence=1.0,
            recommended_action=f"Investigate backend server error logs and exception handlers causing HTTP {http_status}.",
        )
        findings.append(finding_b)

        recommendations.append(
            Recommendation(
                recommendation_id=f"rec_investigate_http_{http_status}",
                category="investigation",
                priority=RecommendationPriority.CRITICAL.value,
                title=f"Investigate HTTP {http_status} Server Error",
                description=f"Endpoint responded with HTTP {http_status} indicating an unhandled server exception or gateway failure.",
                supporting_finding_ids=[f"find_http_{http_status}"],
                actionable_steps=[
                    "Inspect backend application logs for 5xx stack traces",
                    "Verify database connections and upstream service dependencies",
                    "Add regression test reproducing the 5xx failure scenario",
                ],
                executed=False,
            )
        )

    # Rule C: HTTP 4xx Client / Route Error
    elif http_status is not None and 400 <= http_status < 500:
        rules_applied.append("rule_http_4xx_client_error")
        finding_c = Finding(
            finding_id=f"find_http_{http_status}",
            category="availability",
            severity=FindingSeverity.HIGH.value,
            description=f"HTTP {http_status} client error returned by endpoint '{assessed_url}'.",
            supporting_observation_ids=["obs_http_status_code"],
            evidence={"http_status": http_status, "target_url": assessed_url},
            confidence=1.0,
            recommended_action=f"Verify route configuration and authentication requirements for HTTP {http_status}.",
        )
        findings.append(finding_c)

        recommendations.append(
            Recommendation(
                recommendation_id=f"rec_verify_routing_{http_status}",
                category="investigation",
                priority=RecommendationPriority.HIGH.value,
                title=f"Verify Endpoint Routing for HTTP {http_status}",
                description=f"Endpoint returned HTTP {http_status}.",
                supporting_finding_ids=[f"find_http_{http_status}"],
                actionable_steps=[
                    "Check endpoint path and HTTP method routing",
                    "Verify public access permissions or authentication headers",
                ],
                executed=False,
            )
        )

    # Rule D: Elevated Response Latency
    if response_time is not None and response_time > response_time_threshold_ms:
        rules_applied.append("rule_response_time_threshold")
        finding_d = Finding(
            finding_id="find_response_time_elevated",
            category="performance",
            severity=FindingSeverity.MEDIUM.value,
            description=f"HTTP response time ({response_time} ms) exceeds configured threshold ({response_time_threshold_ms} ms).",
            supporting_observation_ids=["obs_response_time"],
            evidence={"response_time_ms": response_time, "threshold_ms": response_time_threshold_ms},
            confidence=1.0,
            recommended_action=f"Optimize backend handlers to bring response latency below {response_time_threshold_ms} ms.",
        )
        findings.append(finding_d)

        recommendations.append(
            Recommendation(
                recommendation_id="rec_tune_performance",
                category="performance",
                priority=RecommendationPriority.MEDIUM.value,
                title="Optimize Endpoint Response Latency",
                description=f"Measured latency of {response_time} ms exceeds threshold of {response_time_threshold_ms} ms.",
                supporting_finding_ids=["find_response_time_elevated"],
                actionable_steps=[
                    "Profile server execution time and database query latency",
                    "Implement caching headers or fast response caching",
                    "Check regional hosting proximity and CDN edge configuration",
                ],
                executed=False,
            )
        )

    # Rule E: Distribution Channels Review
    if failed_receipts_count > 0:
        rules_applied.append("rule_distribution_receipts_audit")
        failed_channels = [r.get("platform", "unknown") for r in dist_receipts_list if r.get("verified") is False or r.get("verification_status") == "FAIL"]
        finding_e = Finding(
            finding_id="find_distribution_receipts_failed",
            category="distribution",
            severity=FindingSeverity.LOW.value,
            description=f"One or more distribution channel actions failed: {', '.join(failed_channels)}.",
            supporting_observation_ids=["obs_distribution_state"],
            evidence={"failed_channels": failed_channels, "failed_count": failed_receipts_count},
            confidence=1.0,
            recommended_action="Review connector credentials and retry failed channel distribution.",
        )
        findings.append(finding_e)

        recommendations.append(
            Recommendation(
                recommendation_id="rec_review_distribution_receipts",
                category="operations",
                priority=RecommendationPriority.LOW.value,
                title="Review Failed Distribution Channels",
                description=f"Distribution actions encountered failures on {', '.join(failed_channels)}.",
                supporting_finding_ids=["find_distribution_receipts_failed"],
                actionable_steps=[
                    "Verify API credentials for failed channels",
                    "Check rate limits or authorization scopes",
                ],
                executed=False,
            )
        )

    # 4. Overall Health Status Synthesis
    if not is_reachable or obs_status == "ERROR":
        overall_status = HealthStatus.UNHEALTHY.value
        summary = f"Health Assessment: UNHEALTHY. Target endpoint '{assessed_url}' is unreachable or returned connection error."
    elif any(f.severity == FindingSeverity.CRITICAL.value for f in findings):
        overall_status = HealthStatus.UNHEALTHY.value
        crit_descs = [f.description for f in findings if f.severity == FindingSeverity.CRITICAL.value]
        summary = f"Health Assessment: UNHEALTHY. Critical issues detected: {'; '.join(crit_descs)}"
    elif any(f.severity == FindingSeverity.HIGH.value for f in findings) or any(f.severity == FindingSeverity.MEDIUM.value for f in findings):
        overall_status = HealthStatus.DEGRADED.value
        deg_descs = [f.description for f in findings if f.severity in (FindingSeverity.HIGH.value, FindingSeverity.MEDIUM.value)]
        summary = f"Health Assessment: DEGRADED. Operational warnings detected: {'; '.join(deg_descs)}"
    elif http_status is not None and 200 <= http_status < 400:
        overall_status = HealthStatus.HEALTHY.value
        rules_applied.append("rule_http_healthy_pass")
        summary = f"Health Assessment: HEALTHY. HTTP {http_status} verified at '{assessed_url}' with {response_time} ms latency."
    else:
        overall_status = HealthStatus.UNKNOWN.value
        summary = "Health Assessment: UNKNOWN. Unable to definitively determine operational status."

    report_id = f"hr_{uuid.uuid4().hex[:12]}"
    prov = dict(provenance or {})
    prov["evaluation_time"] = now_iso

    return HealthReport(
        report_id=report_id,
        project_id=project_id,
        execution_id=execution_id,
        assessed_at=now_iso,
        deployment_reference=deployment_reference,
        assessed_url=assessed_url,
        status=overall_status,
        summary=summary,
        observations=observations,
        findings=findings,
        unavailable_signals=unavailable_signals,
        recommendations=recommendations,
        evaluation_rules_applied=rules_applied,
        provenance=prov,
        errors=errors,
    )
