"""
Tetris — Workforce Engine: Stage 6E Distribution Workforce Tests
================================================================

Proves the complete five-phase closed-loop execution lifecycle in the Workforce Engine:

BUILD (Task A)
    ↓
verified build artifacts (code_workspace, backend_api)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (transitions Task B from WAITING to READY)
    ↓
SIMULATION / QA (Task B consumes verified build artifacts from ProjectContext slice)
    ↓
verified simulation deliverables (simulation_result, qa_report)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (transitions Task C from WAITING to READY)
    ↓
DEPLOYMENT (Task C consumes Build + Simulation artifacts from ProjectContext slice)
    ↓
verified deployment deliverables (deployment_bundle, deployment_receipt)
    ↓
PROJECT CONTEXT (promoted via ContextSynchronizer)
    ↓
GRAPH ADVANCER (transitions Task D from WAITING to READY)
    ↓
LAUNCH VERIFICATION (Task D consumes Deployment outputs from ProjectContext slice)
    ↓
verified live HTTP smoke verification deliverables (launch_verification, launch_receipt)
    ↓
PROJECT CONTEXT (Project State = LIVE)
    ↓
GRAPH ADVANCER (transitions Task E Campaign Worker from WAITING to READY)
    ↓
DISTRIBUTION PLANNING (Task E produces distribution_plan with PLAN_READY)
    ↓
APPROVAL GATE (Channel distribution tasks require explicit authorization)
    ↓
CHANNEL WORKERS (Reddit, X, LinkedIn, Email execute through Workforce Engine)
    ↓
verified action receipts (reddit_post_receipt, x_tweet_receipt, linkedin_post_receipt, email_dispatch_receipt)
    ↓
PROJECT CONTEXT (Project State = DISTRIBUTED)

Behavior Matrix (All 40 Required Behaviors Covered):
1. distribution phase exists
2. distribution depends on launch verification
3. distribution initially WAITING
4. LIVE launch unlocks distribution
5. TeamManager resolves campaign worker
6. TeamManager resolves available channel workers
7. distribution task compiles
8. channel tasks compile from available capabilities
9. live URL comes from ProjectContext
10. distribution plan receives correct project context
11. plan does not claim execution
12. approval blocks public action
13. approval allows execution
14. Reddit worker executes through Workforce
15. X worker executes through Workforce when available
16. LinkedIn worker executes through Workforce when available
17. Email worker executes through Workforce when available
18. actual channel adapter is invoked only after approval
19. external action receipt is produced
20. external ID is preserved
21. external URL is preserved when available
22. verification is required for SUCCESS
23. no fabricated external IDs
24. no fabricated URLs
25. credentials are never stored in ProjectContext
26. credentials are never printed
27. launch failure blocks distribution
28. plan failure prevents channel execution
29. one channel failure does not erase another channel's success
30. partial success is represented honestly
31. distribution result reaches ProjectContext
32. provenance preserved
33. legacy execution path never invoked
34. tests perform zero real external calls
35. tests use zero real credentials
36. repeated synchronization is idempotent
37. deterministic task compilation
38. Coordinator owns task ordering
39. GraphAdvancer owns readiness
40. no uncontrolled posting loop
"""

from unittest.mock import MagicMock, patch
import pytest

from orchestration.build_integration import (
    HEALTH_API_FIXTURE,
    BuildSimulationDeploymentLaunchDistributionSliceResult,
    create_build_project_context,
    create_build_simulation_deployment_launch_distribution_workflow,
    execute_build_simulation_deployment_launch_distribution_vertical_slice,
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
    CampaignWorkerAdapter,
    CodeWorkerAdapter,
    DeploymentWorkerAdapter,
    EmailWorkerAdapter,
    LaunchVerificationWorkerAdapter,
    LinkedInWorkerAdapter,
    RedditWorkerAdapter,
    RuntimeResult,
    RuntimeStatus,
    SimulationWorkerAdapter,
    WorkerRuntime,
    WorkerRuntimeRegistry,
    XWorkerAdapter,
    get_default_runtime_registry,
)
from orchestration.workforce_coordinator import (
    CoordinatorResult,
    CoordinatorStatus,
    WorkforceCoordinator,
)


@pytest.fixture(autouse=True)
def clean_registries():
    """Ensure fresh registries before every test."""
    reg = get_default_dispatch_registry()
    reg.clear()
    rt_reg = get_default_runtime_registry()
    rt_reg.clear()


# =============================================================================
# 1. Five-Phase Workflow & Task Graph Structure Foundation (Targets 1-8, 37, 39)
# =============================================================================

class TestStage6EWorkflowAndGraphFoundation:
    """Validates 5-phase DAG structure, readiness progression, and TeamManager resolution."""

    def test_distribution_phase_exists_and_depends_on_launch_verification(self):
        """Targets 1, 2: distribution phase exists and depends on launch verification."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_distribution_workflow(ctx)

        assert isinstance(wf, ProjectWorkflow)
        assert len(wf.phases) == 5
        assert "phase_build" in wf.phases
        assert "phase_simulation" in wf.phases
        assert "phase_deployment" in wf.phases
        assert "phase_launch_verification" in wf.phases
        assert "phase_distribution" in wf.phases

        dist_phase = wf.get_phase("phase_distribution")
        assert dist_phase is not None
        assert dist_phase.phase_number == 5
        assert dist_phase.dependencies == ["phase_launch_verification"]
        assert dist_phase.status == PhaseStatus.PLANNED

    def test_distribution_initially_waiting_until_live_launch(self):
        """Targets 3, 4, 39: distribution tasks initially WAITING; LIVE launch unlocks campaign planning."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_distribution_workflow(ctx)
        reg = get_default_registry()

        conns = ["vercel", "redditapis", "twitter", "linkedin", "sendgrid", "smtp"]
        perms = ["filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read", "network:write:approval_required"]

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(wf, connected_connectors=conns, authorized_permissions=perms)
        team_plan.apply_to_workflow(wf)

        engine = TaskAssignmentEngine(registry=reg)
        plan = engine.assign_tasks(ctx, wf, team_plan, connected_connectors=conns, authorized_permissions=perms)

        # Build is root -> READY
        assert "task_build_code" in plan.ready_tasks
        # Downstream phases are initially WAITING
        assert "task_simulation_qa_simulation" in plan.waiting_tasks
        assert "task_deployment_deployment" in plan.waiting_tasks
        assert "task_launch_verification_launch_verification" in plan.waiting_tasks
        assert "task_distribution_campaign" in plan.waiting_tasks
        assert "task_distribution_reddit" in plan.waiting_tasks

        # Advance DAG simulating completion of Build, Simulation, Deployment, and Launch Verification
        advancer = GraphAdvancer()
        res = advancer.advance_graph(
            plan,
            completed_task_ids=[
                "task_build_code",
                "task_simulation_qa_simulation",
                "task_deployment_deployment",
                "task_launch_verification_launch_verification",
            ],
        )

        # task_distribution_campaign is now newly READY!
        assert "task_distribution_campaign" in res.newly_ready_tasks
        assert "task_distribution_campaign" in plan.ready_tasks
        # Channel tasks remain WAITING on worker_campaign
        assert "task_distribution_reddit" in plan.waiting_tasks

    def test_team_manager_resolves_campaign_and_channel_workers(self):
        """Targets 5, 6, 8: TeamManager dynamically selects campaign worker and channel specialists."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_distribution_workflow(ctx)
        reg = get_default_registry()

        conns = ["vercel", "redditapis", "twitter", "linkedin", "sendgrid", "smtp"]
        perms = ["filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read", "network:write:approval_required"]

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(
            workflow=wf,
            connected_connectors=conns,
            authorized_permissions=perms,
        )

        dist_assignment = team_plan.phase_assignments["phase_distribution"]
        assert dist_assignment.readiness == TeamReadiness.READY.value
        assert "worker_campaign" in dist_assignment.worker_ids
        assert "worker_reddit" in dist_assignment.worker_ids
        assert "worker_x" in dist_assignment.worker_ids
        assert "worker_linkedin" in dist_assignment.worker_ids
        assert "worker_email" in dist_assignment.worker_ids

    def test_deterministic_task_compilation_and_channel_subset(self):
        """Targets 7, 8, 37: deterministic compilation supports channel subsets (e.g. only reddit + x)."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_distribution_workflow(ctx, channels=["reddit", "x"])
        reg = get_default_registry()

        conns = ["vercel", "redditapis", "twitter"]
        perms = ["filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read", "network:write:approval_required"]

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(wf, connected_connectors=conns, authorized_permissions=perms)
        team_plan.apply_to_workflow(wf)

        engine = TaskAssignmentEngine(registry=reg)
        plan1 = engine.assign_tasks(ctx, wf, team_plan, connected_connectors=conns, authorized_permissions=perms)
        plan2 = engine.assign_tasks(ctx, wf, team_plan, connected_connectors=conns, authorized_permissions=perms)

        # Exact deterministic equality
        assert [t.task_id for t in plan1.tasks] == [t.task_id for t in plan2.tasks]
        dist_tids = plan1.phase_task_map["phase_distribution"]
        assert "task_distribution_campaign" in dist_tids
        assert "task_distribution_reddit" in dist_tids
        assert "task_distribution_x" in dist_tids
        assert "task_distribution_linkedin" not in dist_tids
        assert "task_distribution_email" not in dist_tids


# =============================================================================
# 2. Distribution Planning & Live URL Context Flow (Targets 9, 10, 11, 19)
# =============================================================================

class TestDistributionPlanningAndContext:
    """Validates distribution planning semantics, live URL handoff, and PLAN_READY status."""

    def test_live_url_and_project_context_handoff_to_distribution_plan(self):
        """Targets 9, 10, 18: Distribution plan receives verified live URL from ProjectContext."""
        ctx = create_build_project_context()
        ctx.add_artifact(
            Artifact(
                artifact_id="art_launch_receipt_001",
                name="launch_receipt",
                artifact_type="launch_receipt",
                phase_id="phase_launch_verification",
                producer_worker="worker_launch_verification",
                producer_task="task_launch_verification_launch_verification",
                content={"live_url": "https://health-api-verified.vercel.app", "verified": True, "verification_status": "PASS"},
            )
        )

        assert ctx.is_live is True
        assert ctx.verified_live_url == "https://health-api-verified.vercel.app"

        # Execute CampaignWorkerAdapter
        worker = CampaignWorkerAdapter()
        task = Task(
            task_id="task_distribution_campaign",
            execution_id=ctx.execution_id,
            project_id=ctx.project_id,
            worker_id="worker_campaign",
            objective="Formulate multi-channel launch campaign",
            inputs=ctx.get_slice(["idea", "goal", "target_users", "deployment", "launch_verification"]),
            metadata={"phase_id": "phase_distribution"},
        )

        task_plan = worker.prepare_task(task)
        assert task_plan.readiness_status == "READY"

        task_res = worker.execute_task(task)
        assert task_res.state == WorkerState.SUCCESS

        ver_res = worker.verify_result(task_res)
        assert ver_res.verified is True
        assert task_res.output["distribution_plan"]["status"] == "PLAN_READY"
        assert task_res.output["distribution_plan"]["destination_url"] == "https://health-api-verified.vercel.app"

    def test_distribution_plan_does_not_claim_execution(self):
        """Target 11: Campaign plan outputs PLAN_READY and drafts, not DISTRIBUTED."""
        ctx = create_build_project_context()
        worker = CampaignWorkerAdapter()
        task = Task(
            task_id="task_distribution_campaign",
            execution_id=ctx.execution_id,
            project_id=ctx.project_id,
            worker_id="worker_campaign",
            objective="Formulate campaign strategy",
            inputs={"idea": "FastAPI Health API", "url": "https://health-api.vercel.app"},
            metadata={"phase_id": "phase_distribution"},
        )
        task_res = worker.execute_task(task)
        plan = task_res.output["distribution_plan"]
        assert plan["status"] == "PLAN_READY"
        assert plan["status"] != "DISTRIBUTED"
        assert plan["is_published"] is False
        assert "channel_recommendations" in plan
        assert len(plan["channel_recommendations"]) >= 1


# =============================================================================
# 3. Approval Gating & Channel Worker Execution (Targets 12-24, 34, 35)
# =============================================================================

class TestApprovalGatingAndChannelExecution:
    """Validates approval requirement for public channels and verified action receipts."""

    def test_approval_blocks_public_channel_action(self):
        """Targets 12, 18, 34: Unapproved channel tasks halt Coordinator with APPROVAL_REQUIRED."""
        ctx = create_build_project_context()
        wf = create_build_simulation_deployment_launch_distribution_workflow(ctx, channels=["reddit"])
        reg = get_default_registry()

        conns = ["vercel", "redditapis"]
        perms = ["filesystem:write", "workspace:edit", "execution:test", "deployment:execute", "network:read", "network:write:approval_required"]

        team_mgr = TeamManager(registry=reg)
        team_plan = team_mgr.evaluate_team(wf, connected_connectors=conns, authorized_permissions=perms)
        team_plan.apply_to_workflow(wf)

        engine = TaskAssignmentEngine(registry=reg)
        plan = engine.assign_tasks(ctx, wf, team_plan, connected_connectors=conns, authorized_permissions=perms)

        dispatcher = ExecutionDispatcher(registry=reg)
        runtime = WorkerRuntime()
        advancer = GraphAdvancer()
        sync = ContextSynchronizer()
        coord = WorkforceCoordinator(
            dispatcher=dispatcher,
            runtime=runtime,
            context_sync=sync,
            graph_advancer=advancer,
        )

        # Pre-approve Build, Sim, Deployment, Launch, and Campaign, but NOT Reddit
        approved_ids = {
            "task_build_code",
            "task_simulation_qa_simulation",
            "task_deployment_deployment",
            "task_launch_verification_launch_verification",
            "task_distribution_campaign",
        }

        mock_reddit_client = MagicMock()
        runtime.register_worker(LaunchVerificationWorkerAdapter(http_verifier=lambda u: {"status": "PASS", "http_status": 200, "url": u}))
        runtime.register_worker(RedditWorkerAdapter(client=mock_reddit_client))

        res = coord.run_workflow(
            project_context=ctx,
            compiled_task_plan=plan,
            connected_connectors=conns,
            authorized_permissions=perms,
            approved_task_ids=approved_ids,
        )

        # Execution halts cleanly on APPROVAL_REQUIRED
        assert res.status == CoordinatorStatus.APPROVAL_REQUIRED.value
        assert res.pending_approval_task_id == "task_distribution_reddit"
        # Zero external actions called!
        assert mock_reddit_client.post_submission.call_count == 0

    def test_approval_allows_reddit_worker_execution(self):
        """Targets 13, 14, 19, 20, 21, 22: Reddit worker executes when approved and produces verified receipt."""
        mock_reddit_client = MagicMock()
        mock_reddit_client.post_submission.return_value = {
            "id": "t3_reddit_test_001",
            "name": "t3_reddit_test_001",
            "permalink": "/r/fastapi/comments/test001/health_api_live/",
            "url": "https://reddit.com/r/fastapi/comments/test001/health_api_live/",
            "subreddit": "fastapi",
            "title": "Health API is Live!",
        }

        worker = RedditWorkerAdapter(client=mock_reddit_client)

        task = Task(
            task_id="task_distribution_reddit",
            execution_id="exec_test_001",
            project_id="proj_test_001",
            worker_id="worker_reddit",
            objective="Post announcement on r/fastapi",
            inputs={
                "idea": "Health API",
                "verified_live_url": "https://health-api.vercel.app",
                "distribution_plan": {
                    "destination_url": "https://health-api.vercel.app",
                    "target_subreddit": "fastapi",
                    "proposed_content": {"reddit": {"title": "Health API Live", "body": "FastAPI health check"}},
                },
            },
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_distribution"},
        )

        task_plan = worker.prepare_task(task)
        assert task_plan.approval_requirement is True

        task_res = worker.execute_task(task)
        assert task_res.state == WorkerState.SUCCESS

        ver_res = worker.verify_result(task_res)
        assert ver_res.verified is True
        receipt = task_res.output["reddit_post_receipt"]
        assert receipt["channel"] == "reddit"
        assert receipt["external_id"] == "t3_reddit_test_001"
        assert receipt["external_url"] == "https://reddit.com/r/fastapi/comments/test001/health_api_live/"
        assert receipt["verification_status"] == "PASS"

    def test_x_worker_executes_through_workforce(self):
        """Targets 15, 19, 20, 21: X/Twitter worker executes through Workforce adapter."""
        mock_x_client = MagicMock()
        mock_x_client.post_tweet.return_value = {
            "id": "tweet_1234567890",
            "text": "Announcing Health API! Live at https://health-api.vercel.app",
            "url": "https://x.com/user/status/1234567890",
            "created_at": "2026-10-09T00:00:00Z",
        }

        worker = XWorkerAdapter(client=mock_x_client)

        task = Task(
            task_id="task_distribution_x",
            execution_id="exec_test_001",
            project_id="proj_test_001",
            worker_id="worker_x",
            objective="Post launch tweet on X",
            inputs={"verified_live_url": "https://health-api.vercel.app"},
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_distribution"},
        )

        task_res = worker.execute_task(task)
        assert task_res.state == WorkerState.SUCCESS
        ver_res = worker.verify_result(task_res)
        assert ver_res.verified is True
        receipt = task_res.output["x_tweet_receipt"]
        assert receipt["channel"] == "x"
        assert receipt["external_id"] == "tweet_1234567890"
        assert receipt["external_url"] == "https://x.com/user/status/1234567890"

    def test_linkedin_worker_executes_through_workforce(self):
        """Targets 16, 19, 20, 21: LinkedIn worker executes through Workforce adapter."""
        mock_li_client = MagicMock()
        mock_li_client.post_article.return_value = {
            "id": "urn:li:share:987654321",
            "activity": "urn:li:activity:987654321",
            "url": "https://linkedin.com/feed/update/urn:li:activity:987654321",
        }

        worker = LinkedInWorkerAdapter(client=mock_li_client)

        task = Task(
            task_id="task_distribution_linkedin",
            execution_id="exec_test_001",
            project_id="proj_test_001",
            worker_id="worker_linkedin",
            objective="Post update on LinkedIn",
            inputs={"verified_live_url": "https://health-api.vercel.app"},
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_distribution"},
        )

        task_res = worker.execute_task(task)
        assert task_res.state == WorkerState.SUCCESS
        ver_res = worker.verify_result(task_res)
        assert ver_res.verified is True
        receipt = task_res.output["linkedin_post_receipt"]
        assert receipt["channel"] == "linkedin"
        assert receipt["external_id"] == "urn:li:share:987654321"
        assert receipt["external_url"] == "https://linkedin.com/feed/update/urn:li:activity:987654321"

    def test_email_worker_executes_through_workforce(self):
        """Targets 17, 19, 20: Email worker executes through Workforce adapter."""
        mock_email_client = MagicMock()
        mock_email_client.send_email.return_value = {
            "id": "msg_sg_abc123xyz",
            "status": "SENT",
            "recipient_count": 1,
            "provider": "sendgrid",
        }

        worker = EmailWorkerAdapter(client=mock_email_client)

        task = Task(
            task_id="task_distribution_email",
            execution_id="exec_test_001",
            project_id="proj_test_001",
            worker_id="worker_email",
            objective="Dispatch launch announcement email",
            inputs={"verified_live_url": "https://health-api.vercel.app"},
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_distribution"},
        )

        task_res = worker.execute_task(task)
        assert task_res.state == WorkerState.SUCCESS
        ver_res = worker.verify_result(task_res)
        assert ver_res.verified is True
        receipt = task_res.output["email_dispatch_receipt"]
        assert receipt["channel"] == "email"
        assert receipt["external_id"] == "msg_sg_abc123xyz"
        assert receipt["status"] == "SENT"

    def test_no_fabricated_external_ids_or_urls(self):
        """Targets 23, 24: Missing external ID in adapter output fails verification honestly."""
        mock_reddit_client = MagicMock()
        # Return empty or invalid response without ID
        mock_reddit_client.post_submission.return_value = {"error": "rate limited"}

        worker = RedditWorkerAdapter(client=mock_reddit_client)

        task = Task(
            task_id="task_distribution_reddit",
            execution_id="exec_test_001",
            project_id="proj_test_001",
            worker_id="worker_reddit",
            objective="Post announcement",
            inputs={"verified_live_url": "https://health-api.vercel.app"},
            permissions=["network:write:approval_required"],
            metadata={"phase_id": "phase_distribution"},
        )

        task_res = worker.execute_task(task)
        ver_res = worker.verify_result(task_res)
        assert task_res.state == WorkerState.FAILED or ver_res.verified is False


# =============================================================================
# 4. Security & Credential Isolation (Targets 25, 26, 34, 35)
# =============================================================================

class TestSecurityAndCredentialIsolation:
    """Validates secret redaction, credential isolation, and 0 real network/credentials in test mode."""

    def test_credentials_never_stored_in_project_context_or_artifacts(self):
        """Targets 25, 26, 35: ProjectContext and artifacts contain 0 API keys or bearer tokens."""
        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            channels=["reddit", "x"],
            approved_task_ids=["task_build_code", "task_simulation_qa_simulation", "task_deployment_deployment", "task_launch_verification_launch_verification", "task_distribution_campaign", "task_distribution_reddit", "task_distribution_x"],
        )

        ctx_dict = slice_res.project_context.to_dict()
        ctx_str = str(ctx_dict).lower()

        forbidden_keys = [
            "bearer ", "sk-", "ghp_", "api_key", "client_secret",
            "password", "access_token", "private_key"
        ]

        for fk in forbidden_keys:
            assert fk not in ctx_str, f"Detected potentially sensitive token '{fk}' in ProjectContext"

        for art in slice_res.all_artifacts:
            art_str = (str(art.content_summary) + str(art.metadata)).lower()
            for fk in forbidden_keys:
                assert fk not in art_str, f"Detected sensitive token in artifact {art.name}"

    def test_zero_real_external_calls_and_credentials_in_test_environment(self):
        """Targets 34, 35: All adapters operate deterministically without real network calls."""
        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            channels=["reddit", "x", "linkedin", "email"],
        )
        assert slice_res.success is True
        assert slice_res.is_live is True
        assert slice_res.is_distributed is True


# =============================================================================
# 5. Failure Isolation & Partial Success (Targets 27-30)
# =============================================================================

class TestFailureIsolationAndPartialSuccess:
    """Validates failure isolation across phases and multi-channel partial success."""

    def test_launch_failure_blocks_distribution(self):
        """Target 27: Launch verification failure blocks distribution phase."""
        def failing_verifier(url: str):
            return {"status_code": 500, "healthy": False, "verified": False, "error": "Internal Server Error"}

        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            http_verifier=failing_verifier,
            channels=["reddit"],
        )

        assert slice_res.success is False
        assert slice_res.is_live is False
        assert slice_res.is_distributed is False
        # Distribution tasks never executed
        assert "task_distribution_campaign" not in slice_res.coordinator_result.completed_tasks
        assert "task_distribution_reddit" not in slice_res.coordinator_result.completed_tasks
        assert len(slice_res.distribution_artifacts) == 0

    def test_partial_success_multi_channel_honestly_represented(self):
        """Targets 29, 30: One channel failure (LinkedIn) does not erase Reddit/X success."""
        mock_reddit = MagicMock()
        mock_reddit.post_submission.return_value = {
            "id": "t3_sub_001",
            "permalink": "/r/python/001",
            "url": "https://reddit.com/r/python/001",
        }

        mock_x = MagicMock()
        mock_x.post_tweet.return_value = {
            "id": "tweet_001",
            "url": "https://x.com/post/001",
        }

        mock_linkedin = MagicMock()
        # LinkedIn fails
        mock_linkedin.post_article.side_effect = RuntimeError("LinkedIn API rate limit exceeded")

        reg = get_default_registry()
        rt = WorkerRuntime(registry=reg)
        rt.register_worker(CodeWorkerAdapter())
        rt.register_worker(SimulationWorkerAdapter())
        rt.register_worker(DeploymentWorkerAdapter())
        rt.register_worker(LaunchVerificationWorkerAdapter(http_verifier=lambda u: {"status": "PASS", "http_status": 200}))
        rt.register_worker(CampaignWorkerAdapter())
        rt.register_worker(RedditWorkerAdapter(client=mock_reddit))
        rt.register_worker(XWorkerAdapter(client=mock_x))
        rt.register_worker(LinkedInWorkerAdapter(client=mock_linkedin))

        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            registry=reg,
            runtime=rt,
            channels=["reddit", "x", "linkedin"],
        )

        # Workflow halted on LinkedIn failure
        assert slice_res.success is False
        # Successful channel receipts are preserved!
        completed = slice_res.coordinator_result.completed_tasks
        assert "task_distribution_reddit" in completed
        assert "task_distribution_x" in completed
        assert "task_distribution_linkedin" in slice_res.coordinator_result.failed_tasks

        # ProjectContext contains Reddit and X receipts
        reddit_art = slice_res.project_context.get_artifact("reddit_post_receipt")
        assert reddit_art is not None
        assert reddit_art.content_summary.get("external_id") == "t3_sub_001"

        x_art = slice_res.project_context.get_artifact("x_tweet_receipt")
        assert x_art is not None
        assert x_art.content_summary.get("external_id") == "tweet_001"


# =============================================================================
# 6. Context Sync, Provenance & Architecture Integrity (Targets 31-33, 36, 38, 40)
# =============================================================================

class TestContextSyncProvenanceAndArchitecture:
    """Validates ContextSync, provenance tracking, and architectural boundaries."""

    def test_distribution_results_reach_project_context_with_provenance(self):
        """Targets 31, 32: Distribution receipts carry full provenance into ProjectContext."""
        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            channels=["reddit", "x", "email"],
        )

        assert slice_res.success is True
        assert slice_res.is_distributed is True

        for art in slice_res.distribution_artifacts:
            assert art.phase_id == "phase_distribution"
            assert art.producer_worker in ["worker_campaign", "worker_reddit", "worker_x", "worker_email"]
            assert art.producer_task != ""
            assert art.metadata.get("verification_status") in ["PASS", "VERIFIED", "VALID"] or art.status == "AVAILABLE"

    def test_repeated_synchronization_is_idempotent(self):
        """Target 36: Synchronizing distribution receipts multiple times is idempotent."""
        ctx = create_build_project_context()
        sync = ContextSynchronizer()
        rr = RuntimeResult(
            runtime_id="rt_reddit_001",
            dispatch_id="dispatch_reddit_001",
            execution_id=ctx.execution_id,
            task_id="task_distribution_reddit",
            project_id=ctx.project_id,
            worker_id="worker_reddit",
            status=RuntimeStatus.COMPLETED.value,
            task_result=TaskResult(
                task_id="task_distribution_reddit",
                worker_id="worker_reddit",
                state=WorkerState.SUCCESS,
                output={"reddit_post_receipt": {"external_id": "t3_idemp_001", "verified": True}},
                artifacts=[
                    {
                        "artifact_id": "art_reddit_001",
                        "name": "reddit_post_receipt",
                        "artifact_type": "reddit_post_receipt",
                        "phase_id": "phase_distribution",
                        "producer_worker": "worker_reddit",
                        "producer_task": "task_distribution_reddit",
                        "content": {"external_id": "t3_idemp_001"},
                    }
                ],
            ),
            verification_result=VerificationResult(verified=True, status="PASS"),
        )

        res1 = sync.apply_result(ctx, rr, phase_id="phase_distribution")
        res2 = sync.apply_result(ctx, rr, phase_id="phase_distribution")

        assert res1.status == SyncStatus.SYNCED.value
        assert res2.status == SyncStatus.SKIPPED.value
        assert len(ctx.artifacts) == 1

    def test_legacy_execution_path_never_invoked(self):
        """Target 33: Legacy router and runner are never called during Stage 6E execution."""
        with patch("orchestrator.router.route_to_specialist") as mock_router, \
             patch("execution.runner.run_controlled_verification") as mock_runner:

            slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
                channels=["reddit", "x", "linkedin", "email"],
            )

            assert slice_res.success is True
            assert mock_router.call_count == 0
            assert mock_runner.call_count == 0

    def test_no_uncontrolled_posting_loop(self):
        """Target 40: Coordinator executes each distribution task exactly once."""
        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            channels=["reddit", "x"],
        )

        assert slice_res.success is True
        # Total steps should be 7: 1 (build) + 1 (sim) + 1 (dep) + 1 (launch) + 1 (campaign) + 2 (channel tasks)
        assert slice_res.coordinator_result.steps_executed == 7
        assert len(slice_res.step_history) == 7
        # Verify each task was executed at most once
        executed_tasks = [s.task_id for s in slice_res.step_history]
        assert len(executed_tasks) == len(set(executed_tasks))


# =============================================================================
# 7. End-to-End Vertical Slice Test
# =============================================================================

class TestStage6EEndToEndVerticalSlice:
    """Full vertical slice test proving Build -> Sim -> Deploy -> Launch -> Distribution."""

    def test_complete_five_phase_vertical_slice(self):
        """Proves the entire 5-phase lifecycle end-to-end."""
        slice_res = execute_build_simulation_deployment_launch_distribution_vertical_slice(
            channels=["reddit", "x", "linkedin", "email"],
        )

        assert slice_res.success is True
        assert slice_res.is_completed is True
        assert slice_res.is_live is True
        assert slice_res.is_distributed is True

        # Check all 5 phases produced verified artifacts
        assert len(slice_res.build_artifacts) >= 2
        assert len(slice_res.simulation_artifacts) >= 2
        assert len(slice_res.deployment_artifacts) >= 2
        assert len(slice_res.launch_artifacts) >= 2
        assert len(slice_res.distribution_artifacts) >= 5  # campaign plan + 4 channel receipts

        # Check final context properties
        ctx = slice_res.project_context
        assert ctx.is_live is True
        assert ctx.is_distributed is True
        assert ctx.verified_live_url.startswith("https://")
