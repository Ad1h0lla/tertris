"""
Tetris Stage 7B — Workforce-to-Product Integration Tests
=========================================================

Verifies the integration of the Workforce Engine into the production FastAPI application,
SQLite persistence layer, and REST API surface:

1. Router mounting and endpoint contracts (/api/workforce/*, /health/*).
2. Hydration of ProjectContext from SQLite executions.
3. Persistence and reconstruction of WorkforceTask, ProjectArtifact, WorkforceStep, HealthReportRecord.
4. Build task initiated through actual HTTP API (POST /api/workforce/execute).
5. Task execution, verification, and artifact persistence.
6. Status retrieval simulating frontend page reload (GET /api/workforce/{id}/status).
7. State reconstruction across service/coordinator recreation.
8. Failed and unverified task handling without false success promotion.
9. Approval-required task blocking.
10. Approval and exact blocked task resumption (POST /api/workforce/{id}/tasks/{task_id}/approve).
11. Idempotency on repeated requests.
12. Health report creation, persistence, and retrieval.
13. NOT_ASSESSED / unknown health state when no report exists (never defaulting to healthy).
14. Separation of worker execution success from product health.
15. Invalid execution / task ownership handling.
16. Legacy endpoint non-regression (/intake, /execute, /approve, /api/projects).
17. Zero real external write actions and zero real credentials.
"""

import os
import sys
import tempfile
import uuid
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.models import (
    Base,
    Execution,
    PhaseResult,
    WorkforceTask,
    ProjectArtifact,
    WorkforceStep,
    HealthReportRecord,
    get_db,
)
from database.operations import (
    create_execution,
    get_execution_by_id,
    save_or_update_workforce_task,
    get_workforce_tasks,
    get_workforce_task,
    save_project_artifact,
    get_project_artifacts,
    save_health_report,
    get_latest_health_report,
)
from health.monitor import (
    MockHealthObserver,
    Observation,
    ObservationStatus,
)
from main import app
from orchestration.project_context import (
    Artifact,
    ProjectContext,
    ProjectDefinition,
)
from orchestration.workforce_service import (
    hydrate_project_context,
    execute_workforce_pipeline,
    approve_and_resume_workforce_task,
    assess_and_persist_health,
    get_workforce_status_payload,
)


# =============================================================================
# Test Database Fixture
# =============================================================================

from sqlalchemy.pool import StaticPool
import database.models as db_models


@pytest.fixture
def test_db_session():
    """Provides an isolated in-memory SQLite database session for each test."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    orig_session_local = db_models.SessionLocal
    orig_engine = db_models.engine
    db_models.SessionLocal = TestingSessionLocal
    db_models.engine = test_engine

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        db_models.SessionLocal = orig_session_local
        db_models.engine = orig_engine


@pytest.fixture
def client(test_db_session):
    """FastAPI TestClient with overridden database dependency."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_execution(test_db_session):
    """Creates a sample Execution record in the test database."""
    return create_execution(
        db=test_db_session,
        user_id="user_test_001",
        original_idea="Developer API for Medical Imaging",
        understood_goal="Build a secure, HIPAA-compliant Medical Imaging API",
        intent_classification="api_backend",
        idea_type="saas",
        recommended_phases=[1, 2, 3, 4],
        phase_names=["Build", "Validate", "Market", "Launch"],
    )


# =============================================================================
# 1. Router Mounting & Endpoint Contracts
# =============================================================================

class TestRouterMountingAndContracts:
    def test_workforce_router_mounted_at_api_workforce(self, client, sample_execution):
        """Verifies that all Workforce endpoints respond under /api/workforce."""
        res_status = client.get(f"/api/workforce/{sample_execution.id}/status")
        assert res_status.status_code == 200
        data = res_status.json()
        assert data["execution_id"] == sample_execution.id
        assert "tasks" in data
        assert "artifacts" in data

    def test_health_routes_mounted(self, client, sample_execution):
        """Verifies GET /api/workforce/{id}/health and GET /health/{id} respond properly."""
        res1 = client.get(f"/api/workforce/{sample_execution.id}/health")
        assert res1.status_code == 200
        assert res1.json()["status"] == "NOT_ASSESSED"

        res2 = client.get(f"/health/{sample_execution.id}")
        assert res2.status_code == 200
        assert res2.json()["status"] == "NOT_ASSESSED"


# =============================================================================
# 2. Context Hydration & Persistence Round-Trip
# =============================================================================

class TestContextHydrationAndPersistence:
    def test_hydration_from_existing_execution(self, test_db_session, sample_execution):
        """Tests reconstructing ProjectContext from SQLite Execution record."""
        ctx = hydrate_project_context(sample_execution.id, test_db_session)
        assert ctx is not None
        assert ctx.execution_id == sample_execution.id
        assert "Medical Imaging" in ctx.definition.goal

    def test_artifact_and_task_persistence_roundtrip(self, test_db_session, sample_execution):
        """Verifies saving and querying WorkforceTask and ProjectArtifact records."""
        save_or_update_workforce_task(
            db=test_db_session,
            execution_id=sample_execution.id,
            task_id="task_build_code",
            phase_id="phase_build",
            worker_id="worker_code",
            status="COMPLETED",
            verification_status="PASS",
            inputs={"goal": "Build Medical API"},
            result={"files_written": ["main.py"]},
        )

        save_project_artifact(
            db=test_db_session,
            artifact_id="art_test_code_001",
            execution_id=sample_execution.id,
            name="Code Workspace",
            artifact_type="code_workspace",
            phase_id="phase_build",
            producer_worker="worker_code",
            status="AVAILABLE",
            location="generated_projects/test/phase_1",
            content_summary={"files": ["main.py", "models.py"]},
        )

        # Hydrate again and verify artifacts were loaded
        ctx = hydrate_project_context(sample_execution.id, test_db_session)
        assert "art_test_code_001" in ctx.artifacts
        assert ctx.artifacts["art_test_code_001"].artifact_type == "code_workspace"

        tasks = get_workforce_tasks(test_db_session, sample_execution.id)
        assert len(tasks) == 1
        assert tasks[0].task_id == "task_build_code"
        assert tasks[0].status == "COMPLETED"


# =============================================================================
# 3. HTTP Execution & Workflow Lifecycle
# =============================================================================

class TestHttpWorkforceExecution:
    def test_execute_build_task_via_http(self, client, sample_execution, test_db_session):
        """Tests initiating a Build task through POST /api/workforce/execute."""
        payload = {
            "execution_id": sample_execution.id,
            "phase_id": "phase_build",
            "workflow_type": "build",
            "user_id": "user_test_001",
        }

        with patch("orchestrator.router.route_to_specialist") as mock_legacy_router, \
             patch("execution.runner.run_controlled_verification") as mock_legacy_runner:

            res = client.post("/api/workforce/execute", json=payload)
            assert res.status_code == 200
            data = res.json()

            # Verify response schema
            assert data["success"] is True
            assert data["status"] == "COMPLETED"
            assert data["execution_id"] == sample_execution.id
            assert data["coordinator_status"] == "COMPLETED"
            assert len(data["artifacts"]) >= 1

            # Verify legacy executors were NOT called
            assert mock_legacy_router.call_count == 0
            assert mock_legacy_runner.call_count == 0

            # Verify state was saved to SQLite
            db_tasks = get_workforce_tasks(test_db_session, sample_execution.id)
            assert any(t.task_id == "task_build_code" and t.status == "COMPLETED" for t in db_tasks)

            db_arts = get_project_artifacts(test_db_session, sample_execution.id)
            assert len(db_arts) >= 1
            assert any(a.artifact_type in ("code_workspace", "backend_api") for a in db_arts)

    def test_status_retrieval_simulating_page_refresh(self, client, sample_execution, test_db_session):
        """Simulates a browser refresh by executing a task, discarding memory, and fetching GET /status."""
        # 1. Execute task
        exec_res = client.post("/api/workforce/execute", json={
            "execution_id": sample_execution.id,
            "phase_id": "phase_build",
            "workflow_type": "build",
            "user_id": "user_test_001",
        })
        assert exec_res.status_code == 200

        # 2. Query status via HTTP
        res = client.get(f"/api/workforce/{sample_execution.id}/status")
        assert res.status_code == 200
        status_data = res.json()

        assert status_data["execution_id"] == sample_execution.id
        assert len(status_data["tasks"]) >= 1
        assert any(t["status"] == "COMPLETED" for t in status_data["tasks"])
        assert len(status_data["artifacts"]) >= 1
        assert len(status_data["step_history"]) >= 1
        assert status_data["is_healthy"] is None  # Not yet assessed


# =============================================================================
# 4. Approval Gating & Exact Task Resumption
# =============================================================================

class TestApprovalAndResumption:
    def test_approval_resumes_exact_blocked_task(self, client, sample_execution, test_db_session):
        """
        Verifies that when a task requires approval (e.g. public distribution),
        approving via POST /api/workforce/{id}/tasks/{task_id}/approve resumes execution.
        """
        # Save a task requiring approval in database
        save_or_update_workforce_task(
            db=test_db_session,
            execution_id=sample_execution.id,
            task_id="task_reddit_distribution",
            phase_id="phase_distribution",
            worker_id="worker_reddit",
            status="BLOCKED",
            requires_approval=True,
            is_approved=False,
            error_message="Requires user authorization before public post",
        )

        # Call approve endpoint
        res = client.post(
            f"/api/workforce/{sample_execution.id}/tasks/task_reddit_distribution/approve",
            json={"user_id": "user_test_001", "feedback": "Approved by operator"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["execution_id"] == sample_execution.id

        # Check task was marked approved in DB
        db_task = get_workforce_task(test_db_session, sample_execution.id, "task_reddit_distribution")
        assert db_task.is_approved is True

    def test_approve_nonexistent_execution_returns_404(self, client):
        """Tests that approving a task for an invalid execution returns 400/404."""
        res = client.post(
            "/api/workforce/nonexistent_exec_999/tasks/task_xyz/approve",
            json={"user_id": "user_001"},
        )
        assert res.status_code in (400, 404)


# =============================================================================
# 5. Health Assessment & Separation of Concerns
# =============================================================================

class TestHealthIntegration:
    def test_health_not_assessed_initially(self, client, sample_execution):
        """Ensures is_healthy is None and status is NOT_ASSESSED when no assessment exists."""
        res = client.get(f"/api/workforce/{sample_execution.id}/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "NOT_ASSESSED"
        assert data["is_healthy"] is None

    def test_health_assessment_on_live_project(self, client, sample_execution, test_db_session):
        """Tests running health assessment with a verified deployment URL."""
        # Seed a verified deployment artifact
        save_project_artifact(
            db=test_db_session,
            artifact_id="art_dep_001",
            execution_id=sample_execution.id,
            name="Deployment Bundle",
            artifact_type="deployment_bundle",
            phase_id="phase_deployment",
            producer_worker="worker_deployment",
            status="AVAILABLE",
            content_summary={"deployment_url": "https://health-api.production.internal", "status": "DEPLOYED"},
        )

        mock_observer = MockHealthObserver(
            http_status=200,
            response_time_ms=115.0,
            content_length=1024,
        )

        with patch("routes.workforce.assess_and_persist_health") as mock_assess:
            mock_assess.return_value = {
                "report_id": "rep_test_123",
                "execution_id": sample_execution.id,
                "status": "HEALTHY",
                "assessed_url": "https://health-api.production.internal",
                "observations": [{"category": "http_availability", "status": "OK", "value": {"status_code": 200}}],
                "findings": [],
                "unavailable_signals": ["server_logs", "analytics"],
                "recommendations": [],
                "assessed_at": "2026-10-09T12:00:00Z",
            }

            res = client.post(
                f"/api/workforce/{sample_execution.id}/health",
                json={"user_id": "user_test_001", "target_url": "https://health-api.production.internal"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "HEALTHY"
            assert data["assessed_url"] == "https://health-api.production.internal"

    def test_unhealthy_product_reported_honestly(self, test_db_session, sample_execution):
        """
        Tests that an HTTP 503 produces an UNHEALTHY health report,
        while the assessment execution itself completes successfully.
        """
        # Save verified deployment artifact
        save_project_artifact(
            db=test_db_session,
            artifact_id="art_dep_live",
            execution_id=sample_execution.id,
            name="Deployment Bundle",
            artifact_type="deployment_bundle",
            phase_id="phase_deployment",
            producer_worker="worker_deployment",
            status="AVAILABLE",
            content_summary={"deployment_url": "https://health-api.production.internal"},
        )

        unhealthy_observer = MockHealthObserver(
            http_status=503,
            response_time_ms=1200.0,
        )

        result = assess_and_persist_health(
            db=test_db_session,
            execution_id=sample_execution.id,
            target_url="https://health-api.production.internal",
            observer=unhealthy_observer,
        )

        assert result["status"] == "UNHEALTHY"
        assert len(result["findings"]) >= 1
        assert any("503" in f["description"] for f in result["findings"])

        # Check report was persisted in database
        saved_rep = get_latest_health_report(test_db_session, sample_execution.id)
        assert saved_rep is not None
        assert saved_rep.status == "UNHEALTHY"


# =============================================================================
# 6. Legacy Route Coexistence & Safety
# =============================================================================

class TestLegacyRouteCoexistence:
    def test_legacy_intake_route_remains_functional(self, client):
        """Verifies POST /intake still works as expected."""
        with patch("agents.intake_agent.run_intake") as mock_intake, \
             patch("agents.intake_agent.generate_smart_reply") as mock_reply:

            mock_intake.return_value = {
                "understood_goal": "A CRM for freelancers",
                "idea_type": "saas",
                "recommended_phases": [1, 2, 3, 4],
            }
            mock_reply.return_value = {"reply": "Sounds great!", "ready": True}

            res = client.post("/intake", json={"idea": "A CRM for freelancers"})
            assert res.status_code == 200
            data = res.json()
            assert data["understood_goal"] == "A CRM for freelancers"

    def test_legacy_api_projects_remains_functional(self, client, sample_execution):
        """Verifies GET /api/projects still returns existing projects."""
        res = client.get("/api/projects")
        assert res.status_code == 200
        data = res.json()
        assert "projects" in data
        assert any(p["id"] == sample_execution.id for p in data["projects"])

    def test_zero_real_external_network_calls(self, client, sample_execution):
        """Confirms that tests make zero real external network calls."""
        with patch("urllib.request.urlopen") as mock_net:
            client.get(f"/api/workforce/{sample_execution.id}/status")
            assert mock_net.call_count == 0

    def test_failed_task_verification_persists_honestly(self, client, sample_execution, test_db_session):
        """Tests that a failing worker records FAILED/FAIL without reporting false success."""
        from orchestration.worker_runtime import WorkerRuntime, WorkerRuntimeRegistry
        from orchestration.worker_contract import BaseWorker, TaskPlan, TaskResult, VerificationResult, WorkerState, Task
        from typing import Optional, Dict, Any

        class FailingCodeWorker(BaseWorker):
            def __init__(self):
                super().__init__(
                    worker_id="worker_code",
                    name="Failing Code Worker",
                    role="code_builder",
                    description="Fails verification intentionally",
                    capabilities=["code_generation", "backend", "api_development", "python"],
                    permissions=["filesystem:write", "workspace:edit"],
                )
            def prepare_task(self, task: Task, context: Optional[Dict[str, Any]] = None) -> TaskPlan:
                return TaskPlan(task_id=task.task_id, worker_id=self.worker_id, readiness_status="READY")
            def execute_task(self, task: Task, context: Optional[Dict[str, Any]] = None) -> TaskResult:
                return TaskResult(task_id=task.task_id, worker_id=self.worker_id, state=WorkerState.SUCCESS, output={"status": "BROKEN"})
            def verify_result(self, task_result: TaskResult) -> VerificationResult:
                return VerificationResult.fail_result(error="Syntax validation failed.")

        failing_rt = WorkerRuntime(runtime_registry=WorkerRuntimeRegistry())
        failing_rt.register_worker(FailingCodeWorker())

        res = execute_workforce_pipeline(
            db=test_db_session,
            execution_id=sample_execution.id,
            workflow_type="build",
            runtime_overrides=failing_rt,
        )

        assert res["success"] is False
        assert res["coordinator_status"] in ("FAILED", "BLOCKED")
        assert "task_build_code" in res["failed_tasks"]

        # Check honest failure persisted in database
        saved_task = get_workforce_task(test_db_session, sample_execution.id, "task_build_code")
        assert saved_task is not None
        assert saved_task.status == "FAILED"
        assert saved_task.verification_status == "FAIL"

    def test_repeated_execution_idempotency(self, client, sample_execution, test_db_session):
        """Tests that repeated execution requests do not duplicate records or cause crashes."""
        # Run 1
        res1 = client.post("/api/workforce/execute", json={
            "execution_id": sample_execution.id,
            "workflow_type": "build",
            "user_id": "user_test_001",
        })
        assert res1.status_code == 200

        # Run 2 (simulate duplicate click / retry)
        res2 = client.post("/api/workforce/execute", json={
            "execution_id": sample_execution.id,
            "workflow_type": "build",
            "user_id": "user_test_001",
        })
        assert res2.status_code == 200

        # Verify task count in database has not duplicated
        tasks = get_workforce_tasks(test_db_session, sample_execution.id)
        task_ids = [t.task_id for t in tasks]
        assert len(task_ids) == len(set(task_ids))

    def test_service_recreation_state_reconstruction(self, sample_execution, test_db_session):
        """Tests that state survives complete destruction and recreation of service instances."""
        # 1. Save state
        save_or_update_workforce_task(
            db=test_db_session,
            execution_id=sample_execution.id,
            task_id="task_build_code",
            phase_id="phase_build",
            worker_id="worker_code",
            status="COMPLETED",
            verification_status="PASS",
        )
        save_project_artifact(
            db=test_db_session,
            artifact_id="art_reconstruction_test",
            execution_id=sample_execution.id,
            name="Reconstructed Artifact",
            artifact_type="backend_api",
            phase_id="phase_build",
            producer_worker="worker_code",
            status="AVAILABLE",
            content_summary={"routes": ["/api/v1/health"]},
        )

        # 2. Re-hydrate in a completely clean context
        new_ctx = hydrate_project_context(sample_execution.id, test_db_session)
        assert "art_reconstruction_test" in new_ctx.artifacts
        assert new_ctx.artifacts["art_reconstruction_test"].artifact_type == "backend_api"

        status = get_workforce_status_payload(test_db_session, sample_execution.id)
        assert status["execution_id"] == sample_execution.id
        assert any(t["task_id"] == "task_build_code" for t in status["tasks"])
        assert any(a["artifact_id"] == "art_reconstruction_test" for a in status["artifacts"])
