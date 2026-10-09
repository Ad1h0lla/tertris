"""
Tetris — Workforce Engine: Stage 6F Health / Operate Workforce Tests
====================================================================

Proves the complete operational health assessment lifecycle in the Workforce Engine:

LIVE PROJECT
    ↓
HEALTH ASSESSMENT (Task F)
    ↓
OBSERVATIONS (via Injected Monitoring Adapter)
    ↓
FINDINGS (Evidence-Based Rule Derivation)
    ↓
VERIFIED HEALTH REPORT
    ↓
IMPROVEMENT RECOMMENDATIONS (Structured, Non-Executing)
    ↓
PROJECT CONTEXT (Promoted via ContextSynchronizer)

All 30 Required Behaviors Covered:
1. Health phase exists.
2. WorkerRegistry resolves `worker_health`.
3. TeamManager selects the health worker.
4. Health task compiles deterministically.
5. Valid LIVE project makes the task READY.
6. Missing verified deployment blocks assessment.
7. URL comes from ProjectContext.
8. HTTP observation adapter receives the resolved URL.
9. Healthy HTTP observation produces a HEALTHY report.
10. HTTP 5xx produces an UNHEALTHY finding.
11. High response time produces DEGRADED when a threshold is configured.
12. Missing analytics are marked UNAVAILABLE.
13. Observation errors never produce false HEALTHY status.
14. Health report includes evidence.
15. Recommendations are tied to findings.
16. Unsupported recommendations are not fabricated.
17. Health worker runs through ExecutionDispatcher.
18. Health worker runs through WorkerRuntime.
19. ContextSynchronizer promotes the verified report.
20. GraphAdvancer owns readiness transitions.
21. WorkforceCoordinator owns execution.
22. ProjectContext retains deployment artifacts.
23. ProjectContext retains launch-verification artifacts.
24. ProjectContext retains distribution receipts.
25. Report provenance is preserved.
26. Duplicate synchronization is idempotent.
27. Invalid URL is rejected before network access.
28. Tests perform zero real external network calls.
29. Tests use zero real credentials.
30. Assessment performs no deployment or distribution actions.
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSimulationDeploymentLaunchDistributionHealthSliceResult,
    HealthAssessmentSliceResult,
    create_build_project_context,
    create_build_simulation_deployment_launch_distribution_health_workflow,
    create_health_assessment_workflow,
    execute_build_simulation_deployment_launch_distribution_health_vertical_slice,
    execute_health_assessment_vertical_slice,
    from_legacy_project_dict,
)
from orchestration.context_sync import ContextSynchronizer, SyncResult, SyncStatus
from orchestration.execution_dispatcher import (
    DispatchRecord,
    DispatchRegistry,
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
    get_default_dispatch_registry,
)
from orchestration.graph_advancer import GraphAdvancer, TaskState
from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow, WorkerAssignment
from orchestration.project_context import (
    Artifact,
    ProjectContext,
    ProjectDefinition,
    ReceiptReference,
)
from orchestration.task_assignment import (
    CompiledTaskPlan,
    TaskAssignmentEngine,
    TaskReadiness,
)
from orchestration.team_manager import TeamManager, TeamPlan, TeamReadiness
from orchestration.worker_contract import (
    Task,
    TaskResult,
    VerificationResult,
    WorkerState,
)
from orchestration.worker_registry import WorkerDescriptor, WorkerRegistry, get_default_registry
from orchestration.worker_runtime import (
    HealthWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    WorkerRuntime,
    WorkerRuntimeRegistry,
    get_default_runtime_registry,
)
from orchestration.workforce_coordinator import (
    CoordinatorResult,
    CoordinatorStatus,
    WorkforceCoordinator,
)
from health.monitor import (
    BaseHealthObserver,
    Finding,
    FindingSeverity,
    HealthReport,
    HealthStatus,
    MockHealthObserver,
    Observation,
    ObservationStatus,
    Recommendation,
    RecommendationPriority,
    evaluate_health,
    validate_target_url,
)


@pytest.fixture(autouse=True)
def clean_registries():
    """Ensure fresh registries before every test."""
    reg = get_default_dispatch_registry()
    reg.clear()
    rt_reg = get_default_runtime_registry()
    rt_reg.clear()


def _create_verified_live_context(
    url: str = "https://health-api-live.vercel.app",
    with_distribution: bool = True,
) -> ProjectContext:
    """Helper creating a ProjectContext in verified LIVE state with upstream artifacts."""
    ctx = create_build_project_context()

    # 1. Build artifacts
    ctx.add_artifact(
        Artifact(
            artifact_id="art_build_backend_api",
            name="Backend API Handler",
            artifact_type="backend_api",
            phase_id="phase_build",
            producer_worker="worker_code",
            content_summary={"routes": ["/health"], "framework": "FastAPI"},
        )
    )

    # 2. Deployment artifacts
    ctx.add_artifact(
        Artifact(
            artifact_id="art_deploy_receipt",
            name="Vercel Deployment Receipt",
            artifact_type="deployment_receipt",
            phase_id="phase_deployment",
            producer_worker="worker_deployment",
            location=url,
            content_summary={"deployment_url": url, "deployment_status": "SUCCESS"},
        )
    )

    # 3. Launch verification artifacts
    ctx.add_artifact(
        Artifact(
            artifact_id="art_launch_verification",
            name="Live Smoke Check",
            artifact_type="launch_verification",
            phase_id="phase_launch_verification",
            producer_worker="worker_launch_verification",
            location=url,
            content_summary={"status": "LIVE", "live_url": url, "verification_status": "PASS"},
            metadata={"verification_status": "PASS"},
        )
    )

    # 4. Distribution receipts
    if with_distribution:
        ctx.add_artifact(
            Artifact(
                artifact_id="art_dist_reddit",
                name="Reddit Post Receipt",
                artifact_type="reddit_post_receipt",
                phase_id="phase_distribution",
                producer_worker="worker_reddit",
                content_summary={"status": "SUCCESS", "external_id": "t1_live_red_01"},
                metadata={"verification_status": "PASS"},
            )
        )
        ctx.add_receipt(
            ReceiptReference(
                receipt_id="rcpt_reddit_001",
                platform="reddit",
                action_type="reply_to_post",
                external_id="t1_live_red_01",
                verified=True,
                verification_status="PASS",
            )
        )

    return ctx


# =============================================================================
# 1. Workflow, Graph, and Worker Registry Foundation (Behaviors 1-6, 20, 21)
# =============================================================================

class TestStage6FWorkflowAndGraphFoundation:
    """Covers behaviors 1, 2, 3, 4, 5, 6, 20, 21."""

    def test_01_health_phase_exists(self):
        """1. Health phase exists in workflow definitions."""
        ctx = _create_verified_live_context()
        wf_standalone = create_health_assessment_workflow(ctx)
        assert "phase_health" in wf_standalone.phases
        assert wf_standalone.get_phase("phase_health").name == "Operational Health & Monitoring"

        wf_full = create_build_simulation_deployment_launch_distribution_health_workflow(ctx)
        assert "phase_health" in wf_full.phases
        assert "phase_distribution" in wf_full.get_phase("phase_health").dependencies

    def test_02_worker_registry_resolves_worker_health(self):
        """2. WorkerRegistry resolves worker_health and its capabilities."""
        reg = get_default_registry()
        desc = reg.get("worker_health")
        assert desc is not None
        assert desc.worker_id == "worker_health"
        assert desc.role == "health_monitor"
        assert desc.has_capability("health_monitoring")
        assert desc.has_capability("endpoint_check")
        assert desc.permissions == ["network:read"]

        # Test aliases
        assert reg.get("worker_monitor").worker_id == "worker_health"
        assert reg.get("worker_operate").worker_id == "worker_health"

    def test_03_team_manager_selects_health_worker(self):
        """3. TeamManager selects the health worker for phase_health."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        plan = tm.evaluate_team(
            workflow=wf,
            project_context=ctx.get_slice(["idea", "goal", "deployment"]),
            connected_connectors=[],
            authorized_permissions=["network:read"],
        )
        assert plan.readiness == TeamReadiness.READY.value
        assigned_wids = plan.phase_assignments["phase_health"].worker_ids
        assert "worker_health" in assigned_wids

    def test_04_health_task_compiles_deterministically(self):
        """4. Health task compiles deterministically via TaskAssignmentEngine."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()

        plan1 = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)
        plan2 = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        assert plan1.is_executable()
        assert len(plan1.tasks) == 1
        assert plan1.tasks[0].task_id == plan2.tasks[0].task_id
        assert plan1.tasks[0].worker_id == "worker_health"
        assert plan1.tasks[0].task_id == "task_health_health"

    def test_05_valid_live_project_makes_task_ready(self):
        """5. Valid LIVE project makes the health task READY."""
        ctx = _create_verified_live_context()
        assert ctx.is_live is True
        wf = create_health_assessment_workflow(ctx)
        assert wf.get_phase("phase_health").status == PhaseStatus.READY

        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        assert task_plan.readiness == TaskReadiness.READY.value
        assert "task_health_health" in task_plan.ready_tasks

    def test_06_missing_verified_deployment_blocks_assessment(self):
        """6. Missing verified deployment blocks assessment."""
        ctx = create_build_project_context()  # Fresh context without deployment or live URL
        assert ctx.is_live is False
        assert ctx.verified_live_url is None

        wf = create_health_assessment_workflow(ctx)
        assert wf.get_phase("phase_health").status == PhaseStatus.BLOCKED

        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        assert task_plan.readiness == TaskReadiness.BLOCKED.value
        assert "task_health_health" in task_plan.blocked_tasks

    def test_20_graph_advancer_owns_readiness_transitions(self):
        """20. GraphAdvancer owns readiness transitions in multi-phase workflow."""
        ctx = _create_verified_live_context()
        wf = create_build_simulation_deployment_launch_distribution_health_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        health_tid = "task_health_health"
        assert health_tid in task_plan.waiting_tasks

        advancer = GraphAdvancer()
        # Complete all upstream tasks
        upstream_tids = [t.task_id for t in task_plan.tasks if t.task_id != health_tid]
        delta = advancer.advance_graph(
            compiled_task_plan=task_plan,
            completed_task_ids=set(upstream_tids),
        )
        assert health_tid in delta.newly_ready_tasks
        assert health_tid in task_plan.ready_tasks

    def test_21_workforce_coordinator_owns_execution(self):
        """21. WorkforceCoordinator owns execution loop."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200, response_time_ms=85.0)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=observer,
        )

        assert res.success is True
        assert res.status == CoordinatorStatus.COMPLETED.value
        assert res.coordinator_result.steps_executed == 1
        assert observer.call_count == 1


# =============================================================================
# 2. Observation & URL Safety Policies (Behaviors 7, 8, 27, 28, 29, 30)
# =============================================================================

class TestStage6FObservationAndURLSafety:
    """Covers behaviors 7, 8, 27, 28, 29, 30."""

    def test_07_url_comes_from_project_context(self):
        """7. URL comes strictly from ProjectContext verified records."""
        expected_url = "https://custom-domain-live.vercel.app"
        ctx = _create_verified_live_context(url=expected_url)

        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        task = task_plan.get_task("task_health_health")
        assert task is not None
        assert task.inputs.get("verified_live_url") == expected_url

    def test_08_http_observation_adapter_receives_resolved_url(self):
        """8. HTTP observation adapter receives the resolved URL."""
        expected_url = "https://test-product-778.vercel.app"
        ctx = _create_verified_live_context(url=expected_url)
        observer = MockHealthObserver(http_status=200, response_time_ms=50.0)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=observer,
        )
        assert res.success is True
        assert observer.last_assessed_url == expected_url

    def test_27_invalid_url_rejected_before_network_access(self):
        """27. Invalid URL is rejected before network access."""
        is_safe, _, err = validate_target_url("ftp://unsupported.domain.com")
        assert is_safe is False
        assert "dangerous URL scheme" in err

        is_safe, _, err = validate_target_url("file:///etc/passwd")
        assert is_safe is False

        is_safe, _, err = validate_target_url("http://")
        assert is_safe is False

        # Adapter execution safety with bad URL
        bad_ctx = _create_verified_live_context(url="ftp://invalid.com")
        observer = MockHealthObserver()
        res = execute_health_assessment_vertical_slice(project_context=bad_ctx, observer=observer)
        assert res.success is False
        assert observer.call_count == 0  # Network observer never called!

    def test_28_tests_perform_zero_real_external_network_calls(self):
        """28. Tests perform zero real external network calls via MockHealthObserver."""
        ctx = _create_verified_live_context()
        mock_obs = MockHealthObserver(http_status=200, response_time_ms=100.0)

        with patch("urllib.request.urlopen") as mock_urllib, patch("requests.get") as mock_requests:
            res = execute_health_assessment_vertical_slice(project_context=ctx, observer=mock_obs)
            assert res.success is True
            assert mock_urllib.called is False
            assert mock_requests.called is False
            assert mock_obs.call_count == 1

    def test_29_tests_use_zero_real_credentials(self):
        """29. Tests use zero real credentials."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200)
        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)
        assert res.success is True

        # Audit entire context and result for secrets
        raw_dump = str(res.to_dict()) + str(ctx.to_dict())
        forbidden = ["api_key", "secret_key", "password", "bearer ", "token_secret"]
        for kw in forbidden:
            assert f"'{kw}':" not in raw_dump.lower()

    def test_30_assessment_performs_no_deployment_or_distribution_actions(self):
        """30. Assessment performs no deployment or distribution side effects."""
        ctx = _create_verified_live_context()
        initial_artifacts_count = len(ctx.artifacts)
        initial_receipts_count = len(ctx.receipts)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=MockHealthObserver(http_status=200),
        )

        assert res.success is True
        # Receipts did not increase (no distribution executed)
        assert len(ctx.receipts) == initial_receipts_count
        # Upstream deployment unchanged
        assert ctx.get_artifact("art_deploy_receipt") is not None


# =============================================================================
# 3. Evidence-Based Health Evaluation & Findings (Behaviors 9-16)
# =============================================================================

class TestStage6FHealthEvaluationAndFindings:
    """Covers behaviors 9, 10, 11, 12, 13, 14, 15, 16."""

    def test_09_healthy_http_observation_produces_healthy_report(self):
        """9. Healthy HTTP observation produces a HEALTHY report."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200, response_time_ms=110.0)

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)

        assert res.success is True
        assert res.health_status == HealthStatus.HEALTHY.value
        assert res.is_healthy is True
        assert res.health_report is not None
        assert res.health_report.status == "HEALTHY"
        assert len(res.health_report.findings) == 0

    def test_10_http_5xx_produces_unhealthy_finding(self):
        """10. HTTP 5xx produces an UNHEALTHY finding while assessment completes honestly."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=503, response_time_ms=210.0)

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)

        # Worker execution succeeded because it successfully diagnosed the unhealthy state
        assert res.success is True
        assert res.status == CoordinatorStatus.COMPLETED.value
        assert res.health_status == HealthStatus.UNHEALTHY.value
        assert res.is_healthy is False

        assert res.health_report is not None
        assert res.health_report.status == "UNHEALTHY"
        assert len(res.health_report.findings) >= 1

        f503 = next((f for f in res.health_report.findings if "503" in f.finding_id), None)
        assert f503 is not None
        assert f503.severity == FindingSeverity.CRITICAL.value
        assert "503" in f503.description
        assert f503.recommended_action != ""

    def test_11_high_response_time_produces_degraded(self):
        """11. High response time produces DEGRADED when threshold is configured."""
        ctx = _create_verified_live_context()
        # Latency is 750ms, threshold is 500ms
        observer = MockHealthObserver(http_status=200, response_time_ms=750.0)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=observer,
            response_time_threshold_ms=500.0,
        )

        assert res.success is True
        assert res.health_status == HealthStatus.DEGRADED.value
        assert res.health_report is not None
        assert res.health_report.status == "DEGRADED"

        perf_finding = next((f for f in res.health_report.findings if f.finding_id == "find_response_time_elevated"), None)
        assert perf_finding is not None
        assert perf_finding.severity == FindingSeverity.MEDIUM.value
        assert "750" in perf_finding.description

    def test_12_missing_analytics_marked_unavailable(self):
        """12. Missing analytics and unconfigured sources are marked UNAVAILABLE honestly."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200)

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)

        assert res.health_report is not None
        unavail = res.health_report.unavailable_signals
        assert "analytics" in unavail
        assert "server_logs" in unavail
        assert "application_metrics" in unavail
        assert "uptime_history" in unavail
        assert len(unavail["analytics"]) > 0

    def test_13_observation_errors_never_produce_false_healthy_status(self):
        """13. Observation errors never produce false HEALTHY status."""
        ctx = _create_verified_live_context()
        # Observer returns explicit connection failure
        observer = MockHealthObserver(http_status=None, error="Connection refused by remote host")

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)

        assert res.health_status != HealthStatus.HEALTHY.value
        assert res.health_status == HealthStatus.UNHEALTHY.value
        assert res.is_healthy is False
        assert any(f.finding_id == "find_endpoint_unreachable" for f in res.health_report.findings)

    def test_14_health_report_includes_evidence(self):
        """14. Health report includes observations and structured evidence."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200, response_time_ms=140.0)

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=observer)

        report = res.health_report
        assert report is not None
        assert len(report.observations) >= 4
        obs_ids = [o.observation_id for o in report.observations]
        assert "obs_http_reachability" in obs_ids
        assert "obs_http_status_code" in obs_ids
        assert "obs_response_time" in obs_ids
        assert "obs_deployment_state" in obs_ids

    def test_15_recommendations_are_tied_to_findings(self):
        """15. Recommendations are tied directly to findings."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=500, response_time_ms=800.0)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=observer,
            response_time_threshold_ms=500.0,
        )

        report = res.health_report
        assert report is not None
        assert len(report.findings) >= 2
        assert len(report.recommendations) >= 2

        for rec in report.recommendations:
            assert len(rec.supporting_finding_ids) > 0
            # Ensure each supporting finding actually exists
            for fid in rec.supporting_finding_ids:
                assert any(f.finding_id == fid for f in report.findings)
            assert rec.executed is False  # Non-executing proposal

    def test_16_unsupported_recommendations_not_fabricated(self):
        """16. Unsupported recommendations are not fabricated when no issues exist."""
        ctx = _create_verified_live_context()
        observer = MockHealthObserver(http_status=200, response_time_ms=90.0)

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=observer,
            response_time_threshold_ms=500.0,
        )

        assert res.health_status == "HEALTHY"
        assert len(res.health_report.findings) == 0
        assert len(res.health_report.recommendations) == 0  # Zero fabricated recommendations!


# =============================================================================
# 4. Execution Pipeline & Context Synchronization (Behaviors 17-19, 22-26)
# =============================================================================

class TestStage6FExecutionAndContextSync:
    """Covers behaviors 17, 18, 19, 22, 23, 24, 25, 26."""

    def test_17_health_worker_runs_through_execution_dispatcher(self):
        """17. Health worker runs through ExecutionDispatcher."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher()
        task = task_plan.get_task("task_health_health")
        dispatch_res = dispatcher.dispatch_task(task=task, compiled_task_plan=task_plan, authorized_permissions=["network:read"])

        assert dispatch_res.status == DispatchStatus.DISPATCHED.value
        assert dispatch_res.envelope is not None
        assert dispatch_res.envelope.worker_id == "worker_health"

    def test_18_health_worker_runs_through_worker_runtime(self):
        """18. Health worker runs through WorkerRuntime."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher()
        task = task_plan.get_task("task_health_health")
        dispatch_res = dispatcher.dispatch_task(task=task, compiled_task_plan=task_plan, authorized_permissions=["network:read"])

        runtime = WorkerRuntime()
        obs = MockHealthObserver(http_status=200, response_time_ms=95.0)
        runtime.register_worker(HealthWorkerAdapter(observer=obs))

        runtime_res = runtime.execute_envelope(dispatch_res.envelope)

        assert runtime_res.status == RuntimeStatus.COMPLETED.value
        assert runtime_res.is_completed is True
        assert runtime_res.verification_result.verified is True
        assert runtime_res.verification_result.status == "PASS"

    def test_19_context_synchronizer_promotes_verified_report(self):
        """19. ContextSynchronizer promotes the verified health report."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher()
        task = task_plan.get_task("task_health_health")
        dispatch_res = dispatcher.dispatch_task(task=task, compiled_task_plan=task_plan, authorized_permissions=["network:read"])

        runtime = WorkerRuntime()
        runtime.register_worker(HealthWorkerAdapter(observer=MockHealthObserver(http_status=200)))
        runtime_res = runtime.execute_envelope(dispatch_res.envelope)

        sync = ContextSynchronizer()
        sync_res = sync.apply_result(project_context=ctx, runtime_result=runtime_res)

        assert sync_res.status == SyncStatus.SYNCED.value
        assert any("health_report" in aid for aid in sync_res.artifacts_created)
        assert ctx.get_artifact("health_report") is not None
        assert ctx.is_healthy is True

    def test_22_project_context_retains_deployment_artifacts(self):
        """22. ProjectContext retains deployment artifacts after health assessment."""
        ctx = _create_verified_live_context()
        assert ctx.get_artifact("art_deploy_receipt") is not None

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=MockHealthObserver())
        assert res.success is True

        dep_art = ctx.get_artifact("art_deploy_receipt")
        assert dep_art is not None
        assert dep_art.producer_worker == "worker_deployment"

    def test_23_project_context_retains_launch_verification_artifacts(self):
        """23. ProjectContext retains launch-verification artifacts."""
        ctx = _create_verified_live_context()
        assert ctx.get_artifact("art_launch_verification") is not None

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=MockHealthObserver())
        assert res.success is True

        launch_art = ctx.get_artifact("art_launch_verification")
        assert launch_art is not None
        assert ctx.is_live is True

    def test_24_project_context_retains_distribution_receipts(self):
        """24. ProjectContext retains distribution receipts."""
        ctx = _create_verified_live_context(with_distribution=True)
        assert len(ctx.receipts) == 1
        assert ctx.get_artifact("art_dist_reddit") is not None

        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=MockHealthObserver())
        assert res.success is True

        assert len(ctx.receipts) == 1
        assert ctx.receipts[0].platform == "reddit"
        assert ctx.get_artifact("art_dist_reddit") is not None

    def test_25_report_provenance_is_preserved(self):
        """25. Report provenance is preserved with complete worker/task/phase links."""
        ctx = _create_verified_live_context()
        res = execute_health_assessment_vertical_slice(project_context=ctx, observer=MockHealthObserver())

        assert res.success is True
        report_art = next(a for a in ctx.artifacts.values() if a.artifact_type == "health_report")
        assert report_art.producer_worker == "worker_health"
        assert report_art.phase_id == "phase_health"
        assert "task_health_health" in report_art.producer_task
        assert report_art.metadata.get("verified") is True

    def test_26_duplicate_synchronization_is_idempotent(self):
        """26. Duplicate synchronization is idempotent."""
        ctx = _create_verified_live_context()
        wf = create_health_assessment_workflow(ctx)
        tm = TeamManager()
        team_plan = tm.evaluate_team(workflow=wf, project_context=ctx.get_slice(["idea"]))
        engine = TaskAssignmentEngine()
        task_plan = engine.assign_tasks(project_context=ctx, workflow=wf, team_plan=team_plan)

        dispatcher = ExecutionDispatcher()
        task = task_plan.get_task("task_health_health")
        dispatch_res = dispatcher.dispatch_task(task=task, compiled_task_plan=task_plan, authorized_permissions=["network:read"])

        runtime = WorkerRuntime()
        runtime.register_worker(HealthWorkerAdapter(observer=MockHealthObserver()))
        runtime_res = runtime.execute_envelope(dispatch_res.envelope)

        sync = ContextSynchronizer()
        sync_res1 = sync.apply_result(project_context=ctx, runtime_result=runtime_res)
        assert sync_res1.status == SyncStatus.SYNCED.value

        count_before = len(ctx.artifacts)
        sync_res2 = sync.apply_result(project_context=ctx, runtime_result=runtime_res)
        assert sync_res2.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == count_before


# =============================================================================
# 5. Multi-Phase End-to-End & Failure Isolation Tests
# =============================================================================

class TestStage6FFullLifecycleAndIsolation:
    """Full 6-phase vertical slice and isolation tests."""

    def test_full_6phase_lifecycle_healthy(self):
        """Complete 6-phase flow from fixture through health assessment (HEALTHY)."""
        ctx = create_build_project_context()
        health_obs = MockHealthObserver(http_status=200, response_time_ms=65.0)

        res = execute_build_simulation_deployment_launch_distribution_health_vertical_slice(
            project_context=ctx,
            health_observer=health_obs,
        )

        assert res.success is True
        assert res.status == CoordinatorStatus.COMPLETED.value
        assert res.is_live is True
        assert res.is_distributed is True
        assert res.health_status == "HEALTHY"
        assert len(res.build_artifacts) >= 1
        assert len(res.simulation_artifacts) >= 1
        assert len(res.deployment_artifacts) >= 1
        assert len(res.launch_artifacts) >= 1
        assert len(res.distribution_artifacts) >= 1
        assert len(res.health_artifacts) >= 1

    def test_full_6phase_lifecycle_unhealthy_endpoint(self):
        """Complete 6-phase flow where endpoint becomes HTTP 500 post-distribution."""
        ctx = create_build_project_context()
        health_obs = MockHealthObserver(http_status=500, response_time_ms=120.0)

        res = execute_build_simulation_deployment_launch_distribution_health_vertical_slice(
            project_context=ctx,
            health_observer=health_obs,
        )

        assert res.success is True
        assert res.status == CoordinatorStatus.COMPLETED.value
        assert res.is_live is True
        assert res.health_status == "UNHEALTHY"

    def test_observation_infrastructure_crash_fails_honestly(self):
        """Observation adapter crashing halts worker execution without promoting report."""
        ctx = _create_verified_live_context()

        def crashing_observer(url):
            raise RuntimeError("Underlying socket connection dropped unexpectedly")

        res = execute_health_assessment_vertical_slice(
            project_context=ctx,
            observer=crashing_observer,
        )

        assert res.success is False
        assert res.status == CoordinatorStatus.FAILED.value
        assert res.health_status == "UNKNOWN"
        assert ctx.get_artifact("health_report") is None
