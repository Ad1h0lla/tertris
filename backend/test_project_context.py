"""
Unit Tests for Workforce Engine — Stage 4A: Project Context Foundation
=====================================================================

Tests:
1. ProjectContext creation & identity fields
2. Project definition (idea, goal, target users, requirements, constraints, acceptance criteria)
3. Artifact creation, provenance tracking, and multiple artifacts
4. PhaseOutcomeReference & phase history
5. Decision logging with provenance (why decisions were made)
6. ReceiptReference (verified external outcomes without secrets)
7. Controlled context slice retrieval (get_slice)
8. Requested keys only & missing key handling
9. Context update methods & validation
10. Serialization & deserialization round-trip equality
11. Security: Strict secret redaction & zero secrets in serialization
12. Duplicate artifact prevention & explicit replacement
13. Legacy projection from existing SQLite Execution/PhaseResult data
14. Full Realistic End-to-End Project Context Simulation (Crypto price tracker SaaS)
"""

import json
import pytest

from orchestration.project_context import (
    Artifact,
    PhaseOutcomeReference,
    ReceiptReference,
    Decision,
    ProjectDefinition,
    ProjectContext,
)


# =============================================================================
# 1. ProjectContext Creation & Identity Tests
# =============================================================================

class TestProjectContextIdentity:
    def test_context_creation_and_identity_fields(self):
        defn = ProjectDefinition(
            idea="AI workflow automation builder",
            goal="Enable users to create multi-step agent pipelines",
            target_users="Automation engineers and founders",
            requirements=["Drag and drop canvas", "Webhook triggers"],
            constraints=["Must run on Python 3.11+"],
            acceptance_criteria=["Pipeline executes end-to-end"],
        )
        context = ProjectContext(
            project_id="proj_identity_01",
            execution_id="exec_identity_02",
            user_id="user_admin",
            definition=defn,
        )

        assert context.project_id == "proj_identity_01"
        assert context.execution_id == "exec_identity_02"
        assert context.user_id == "user_admin"
        assert context.definition.idea == "AI workflow automation builder"
        assert len(context.definition.requirements) == 2
        assert len(context.definition.constraints) == 1
        assert len(context.definition.acceptance_criteria) == 1
        assert context.created_at is not None
        assert context.updated_at is not None


# =============================================================================
# 2. Artifact Creation & Provenance Tests
# =============================================================================

class TestArtifacts:
    def test_artifact_creation_with_provenance(self):
        art = Artifact(
            artifact_id="art_code_001",
            name="FastAPI Webhook Server",
            artifact_type="code_workspace",
            phase_id="phase_build",
            producer_worker="worker_code",
            producer_task="task_scaffold_backend",
            location="e:/tetris.io/workspace/phase_1",
            content_summary={"files_count": 8, "endpoints": ["/webhook", "/health"]},
            status="AVAILABLE",
        )

        assert art.artifact_id == "art_code_001"
        assert art.artifact_type == "code_workspace"
        assert art.phase_id == "phase_build"
        assert art.producer_worker == "worker_code"
        assert art.producer_task == "task_scaffold_backend"
        assert art.location == "e:/tetris.io/workspace/phase_1"
        assert art.content_summary["files_count"] == 8

    def test_multiple_artifacts_and_type_query(self):
        context = ProjectContext(
            definition=ProjectDefinition(idea="Test", goal="Test"),
        )
        art1 = Artifact(
            artifact_id="art_1",
            name="Backend API",
            artifact_type="code_workspace",
            phase_id="phase_build",
            producer_worker="worker_code",
        )
        art2 = Artifact(
            artifact_id="art_2",
            name="Frontend React",
            artifact_type="code_workspace",
            phase_id="phase_build",
            producer_worker="worker_ui",
        )
        art3 = Artifact(
            artifact_id="art_3",
            name="Simulation Test Suite",
            artifact_type="simulation_result",
            phase_id="phase_simulation",
            producer_worker="worker_qa_simulation",
        )

        context.add_artifact(art1)
        context.add_artifact(art2)
        context.add_artifact(art3)

        assert len(context.artifacts) == 3
        code_arts = context.get_artifacts_by_type("code_workspace")
        assert len(code_arts) == 2
        assert {a.artifact_id for a in code_arts} == {"art_1", "art_2"}

        sim_arts = context.get_artifacts_by_phase("phase_simulation")
        assert len(sim_arts) == 1
        assert sim_arts[0].artifact_id == "art_3"

    def test_duplicate_artifact_prevention_and_explicit_replace(self):
        context = ProjectContext(
            definition=ProjectDefinition(idea="Test", goal="Test"),
        )
        art = Artifact(
            artifact_id="art_unique_1",
            name="Spec v1",
            artifact_type="specification",
            phase_id="phase_build",
            producer_worker="worker_code",
        )
        context.add_artifact(art)

        # Attempt duplicate without allow_replace
        art_dup = Artifact(
            artifact_id="art_unique_1",
            name="Spec v2",
            artifact_type="specification",
            phase_id="phase_build",
            producer_worker="worker_code",
        )
        with pytest.raises(ValueError, match="already exists"):
            context.add_artifact(art_dup, allow_replace=False)

        # Succeeded with allow_replace
        context.add_artifact(art_dup, allow_replace=True)
        assert context.get_artifact("art_unique_1").name == "Spec v2"


# =============================================================================
# 3. Phase Outcome & Decision Logging Tests
# =============================================================================

class TestPhaseHistoryAndDecisions:
    def test_phase_outcome_recording(self):
        context = ProjectContext(
            definition=ProjectDefinition(idea="Test", goal="Test"),
        )
        outcome = PhaseOutcomeReference(
            phase_id="phase_build",
            phase_name="Build / Coding",
            status="COMPLETED",
            result_reference="phase_res_12345",
            outcome_type="code",
            producer_worker="worker_code",
            validation_score=0.95,
            verification_status="PASS",
            summary="Synthesized backend FastAPI and SQLite schema.",
        )
        context.add_phase_outcome(outcome)

        assert "phase_build" in context.phase_history
        saved = context.phase_history["phase_build"]
        assert saved.status == "COMPLETED"
        assert saved.validation_score == 0.95
        assert saved.result_reference == "phase_res_12345"

    def test_decision_logging_with_provenance(self):
        context = ProjectContext(
            definition=ProjectDefinition(idea="Test", goal="Test"),
        )
        entry = context.record_decision(
            decision="Use Reddit for initial developer distribution.",
            reason="Target audience is developers and research identified r/n8n as high value.",
            source="worker_campaign",
            phase_id="phase_marketing",
            worker_id="worker_campaign",
            metadata={"target_subreddits": ["r/n8n", "r/webdev"]},
        )

        assert len(context.decisions) == 1
        assert context.decisions[0].decision == "Use Reddit for initial developer distribution."
        assert context.decisions[0].source == "worker_campaign"
        assert context.decisions[0].phase_id == "phase_marketing"
        assert context.decisions[0].metadata["target_subreddits"] == ["r/n8n", "r/webdev"]


# =============================================================================
# 4. Receipt References Tests (Verified External Outcomes)
# =============================================================================

class TestReceiptReferences:
    def test_receipt_reference_recording_without_secrets(self):
        context = ProjectContext(
            definition=ProjectDefinition(idea="Test", goal="Test"),
        )
        receipt = ReceiptReference(
            receipt_id="rcpt_reddit_live_01",
            platform="reddit",
            action_type="reply_to_post",
            external_id="t1_pe95jxd",
            permalink="https://www.reddit.com/r/n8n/comments/1wxsr8b/comment/pe95jxd/",
            verified=True,
            verification_status="PASS",
            evidence={"status_code": 200, "comment_id": "pe95jxd"},
            phase_id="phase_marketing",
            producer_worker="worker_reddit",
        )
        context.add_receipt(receipt)

        assert len(context.receipts) == 1
        r = context.receipts[0]
        assert r.platform == "reddit"
        assert r.external_id == "t1_pe95jxd"
        assert r.verified is True
        assert "reddit.com" in r.permalink


# =============================================================================
# 5. Controlled Context Retrieval (get_slice) Tests
# =============================================================================

class TestControlledContextRetrieval:
    @pytest.fixture
    def populated_context(self):
        defn = ProjectDefinition(
            idea="SaaS Analytics Engine",
            goal="Track product events in real-time",
            target_users="SaaS Product Managers",
            requirements=["Event ingestion endpoint", "Live dashboard"],
            constraints=["GDPR compliant"],
            acceptance_criteria=["Dashboard displays events within 500ms"],
        )
        context = ProjectContext(
            project_id="proj_slice_1",
            definition=defn,
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_code_1",
                name="FastAPI Ingestion",
                artifact_type="code_workspace",
                phase_id="phase_build",
                producer_worker="worker_code",
            )
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_sim_1",
                name="Simulation Load Test",
                artifact_type="simulation_result",
                phase_id="phase_simulation",
                producer_worker="worker_qa_simulation",
            )
        )
        context.record_decision(
            decision="Adopt Postgres for timeseries events",
            reason="High throughput event writes",
            source="worker_database",
            phase_id="phase_build",
        )
        return context

    def test_get_slice_returns_only_requested_keys(self, populated_context):
        # Code worker requests definition items only
        code_slice = populated_context.get_slice(
            required_keys=["idea", "requirements", "acceptance_criteria", "code_assets"]
        )

        assert "idea" in code_slice
        assert "requirements" in code_slice
        assert "acceptance_criteria" in code_slice
        assert "code_assets" in code_slice

        # Must NOT leak unrequested items
        assert "target_users" not in code_slice
        assert "constraints" not in code_slice
        assert "simulation" not in code_slice
        assert "decisions" not in code_slice

        assert len(code_slice["code_assets"]) == 1
        assert code_slice["code_assets"][0]["artifact_id"] == "art_code_1"

    def test_get_slice_missing_keys_handled_gracefully(self, populated_context):
        empty_slice = populated_context.get_slice(
            required_keys=["non_existent_key", "research"]
        )
        assert "research" in empty_slice
        assert empty_slice["research"] == []
        assert "non_existent_key" not in empty_slice


# =============================================================================
# 6. Serialization & Security Tests (Zero Secrets)
# =============================================================================

class TestSerializationAndSecurity:
    def test_json_roundtrip_equality(self):
        defn = ProjectDefinition(
            idea="Crypto Price Alert",
            goal="Send price alert emails",
            requirements=["Price fetcher", "Email dispatcher"],
        )
        context = ProjectContext(
            project_id="proj_roundtrip_01",
            definition=defn,
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_10",
                name="Email Template",
                artifact_type="distribution_plan",
                phase_id="phase_marketing",
                producer_worker="worker_campaign",
            )
        )

        d = context.to_dict()
        json_str = json.dumps(d)
        reloaded_dict = json.loads(json_str)
        reloaded_context = ProjectContext.from_dict(reloaded_dict)

        assert reloaded_context.project_id == context.project_id
        assert reloaded_context.definition.idea == context.definition.idea
        assert len(reloaded_context.artifacts) == 1
        assert reloaded_context.get_artifact("art_10").name == "Email Template"

    def test_security_zero_secrets_serialized(self):
        # Attempt to insert sensitive credentials in metadata or content summary
        context = ProjectContext(
            definition=ProjectDefinition(
                idea="Secret test",
                goal="Secret test",
                metadata={"api_key": "SUPER_SECRET_12345", "password": "DONT_LEAK_ME"},
            ),
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_sec",
                name="Config",
                artifact_type="config",
                phase_id="phase_1",
                producer_worker="worker_1",
                metadata={"reddit_session": "SECRET_SESSION_TOKEN", "client_secret": "OAUTH_SECRET"},
            )
        )

        serialized = context.to_dict()
        serialized_str = json.dumps(serialized)

        assert "SUPER_SECRET_12345" not in serialized_str
        assert "DONT_LEAK_ME" not in serialized_str
        assert "SECRET_SESSION_TOKEN" not in serialized_str
        assert "OAUTH_SECRET" not in serialized_str
        assert "[REDACTED_SECRET]" in serialized_str


# =============================================================================
# 7. Legacy Execution & PhaseResult Projection Adapter Tests
# =============================================================================

class TestLegacyProjectionAdapter:
    def test_projection_from_existing_execution(self):
        # Test projection with SQLite DB
        import uuid
        from database.models import SessionLocal, init_db, Execution, PhaseResult, ConnectorAction
        init_db()
        db = SessionLocal()

        rand_id = uuid.uuid4().hex[:8]
        exec_id = f"exec_proj_{rand_id}"
        pr_id = f"pr_{rand_id}"
        ca_id = f"ca_{rand_id}"

        db.add(
            Execution(
                id=exec_id,
                user_id="user_test",
                original_idea="Build AI Sales Assistant",
                understood_goal="AI Sales Outreach tool with email dispatch",
            )
        )
        db.add(
            PhaseResult(
                id=pr_id,
                execution_id=exec_id,
                phase_number=1,
                phase_name="Build Phase",
                outcome_type="code",
                status="complete",
                validation_score=0.9,
            )
        )
        db.add(
            ConnectorAction(
                id=ca_id,
                user_id="user_test",
                execution_id=exec_id,
                connector_id="reddit",
                action="reply_to_post",
                status="SUCCESS",
                result={"external_id": "t1_test99", "permalink": "https://reddit.com/r/test", "verified": True},
            )
        )
        db.commit()

        context = ProjectContext.from_existing_execution(execution_id=exec_id, db=db)

        assert context.execution_id == exec_id
        assert context.definition.idea == "Build AI Sales Assistant"
        assert "phase_1" in context.phase_history
        assert context.phase_history["phase_1"].outcome_type == "code"
        assert len(context.receipts) == 1
        assert context.receipts[0].platform == "reddit"
        assert context.receipts[0].external_id == "t1_test99"
        assert context.receipts[0].verified is True

        db.close()


# =============================================================================
# 8. Realistic Full Lifecycle Context Simulation Test
# =============================================================================

class TestRealisticProjectContextSimulation:
    def test_full_crypto_saas_project_lifecycle_accumulation(self):
        """
        Simulates the real accumulation of project memory across all phases
        for: 'Crypto price tracking and alert SaaS'
        """
        # --- INITIALIZATION ---
        defn = ProjectDefinition(
            idea="Crypto price tracking and alert SaaS",
            goal="Track live crypto prices and send automated user alerts",
            target_users="Retail crypto investors",
            requirements=[
                "Price tracking ingestion",
                "Alert engine",
                "Web dashboard",
                "User accounts",
            ],
            constraints=["Sub-second price alert delivery"],
            acceptance_criteria=[
                "User can add a tracked asset",
                "User can see current price",
                "User can create an alert",
                "Alert triggers on price threshold",
                "Dashboard loads successfully",
            ],
        )
        context = ProjectContext(
            project_id="proj_crypto_001",
            execution_id="exec_crypto_001",
            user_id="user_001",
            definition=defn,
        )

        # --- PHASE 1: BUILD ---
        context.add_artifact(
            Artifact(
                artifact_id="art_ws_build",
                name="Crypto Tracker Codebase",
                artifact_type="code_workspace",
                phase_id="phase_build",
                producer_worker="worker_code",
                location="generated_projects/crypto_tracker",
                content_summary={"entrypoint": "app.py", "routes": ["/prices", "/alerts"]},
            )
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_db_schema",
                name="Crypto Database Schema",
                artifact_type="database_schema",
                phase_id="phase_build",
                producer_worker="worker_database",
                content_summary={"tables": ["users", "assets", "alerts", "price_history"]},
            )
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_spec",
                name="Architecture Spec",
                artifact_type="specification",
                phase_id="phase_build",
                producer_worker="worker_code",
            )
        )
        context.add_phase_outcome(
            PhaseOutcomeReference(
                phase_id="phase_build",
                phase_name="Build / Coding",
                status="COMPLETED",
                outcome_type="code",
                producer_worker="worker_code",
                validation_score=0.92,
            )
        )
        context.record_decision(
            decision="Use WebSockets for live ticker prices",
            reason="Avoid HTTP polling overhead for real-time rates",
            source="worker_code",
            phase_id="phase_build",
        )

        # --- PHASE 2: SIMULATION ---
        context.add_artifact(
            Artifact(
                artifact_id="art_sim_qa",
                name="1000-User Price Spike Stress Test",
                artifact_type="simulation_result",
                phase_id="phase_simulation",
                producer_worker="worker_qa_simulation",
                content_summary={"latency_ms": 120, "dropped_alerts": 0},
                status="PASS",
            )
        )
        context.add_phase_outcome(
            PhaseOutcomeReference(
                phase_id="phase_simulation",
                phase_name="Simulation & QA",
                status="COMPLETED",
                outcome_type="simulation",
                producer_worker="worker_qa_simulation",
                verification_status="PASS",
                validation_score=0.98,
            )
        )

        # --- PHASE 3: MARKETING ---
        context.add_artifact(
            Artifact(
                artifact_id="art_competitor_intel",
                name="Crypto Alert Competitor Matrix",
                artifact_type="competitor_intelligence",
                phase_id="phase_marketing",
                producer_worker="worker_competitor_intel",
                content_summary={"competitors": ["CoinMarketCap Alerts", "CoinGecko Ticker"]},
            )
        )
        context.add_artifact(
            Artifact(
                artifact_id="art_dist_plan",
                name="Crypto Community Distribution Plan",
                artifact_type="distribution_plan",
                phase_id="phase_marketing",
                producer_worker="worker_campaign",
                content_summary={"target_subreddits": ["r/CryptoCurrency", "r/Bitcoin"]},
            )
        )
        context.add_phase_outcome(
            PhaseOutcomeReference(
                phase_id="phase_marketing",
                phase_name="Marketing & Distribution",
                status="COMPLETED",
                outcome_type="campaign",
                producer_worker="worker_campaign",
            )
        )
        context.record_decision(
            decision="Highlight sub-second alerts in Reddit launch copy",
            reason="Competitor analysis revealed slow alert delivery as main user complaint",
            source="worker_campaign",
            phase_id="phase_marketing",
        )

        # --- PHASE 4: DEPLOYMENT ---
        context.add_artifact(
            Artifact(
                artifact_id="art_deploy_bundle",
                name="Vercel Production Deployment",
                artifact_type="deployment_bundle",
                phase_id="phase_deployment",
                producer_worker="worker_deployment",
                location="https://crypto-alerts-live.vercel.app",
            )
        )
        context.add_receipt(
            ReceiptReference(
                receipt_id="rcpt_deploy_01",
                platform="vercel",
                action_type="deploy_vercel",
                external_id="dpl_abc123xyz",
                permalink="https://crypto-alerts-live.vercel.app",
                verified=True,
                verification_status="PASS",
                phase_id="phase_deployment",
                producer_worker="worker_deployment",
            )
        )
        context.add_phase_outcome(
            PhaseOutcomeReference(
                phase_id="phase_deployment",
                phase_name="Deployment",
                status="COMPLETED",
                outcome_type="deployment",
                producer_worker="worker_deployment",
                verification_status="PASS",
            )
        )

        # --- PHASE 5: HEALTH ---
        context.add_artifact(
            Artifact(
                artifact_id="art_health_config",
                name="Uptime & Endpoint Health Monitor",
                artifact_type="health_config",
                phase_id="phase_health",
                producer_worker="worker_health",
                content_summary={"check_interval_seconds": 60, "alert_webhook": "enabled"},
            )
        )

        # --- AUDIT VERIFICATION ---
        # 1. All artifacts remain available
        assert len(context.artifacts) == 8
        assert context.get_artifact("art_ws_build") is not None
        assert context.get_artifact("art_sim_qa").status == "PASS"

        # 2. Provenance is preserved
        assert context.get_artifact("art_db_schema").producer_worker == "worker_database"
        assert context.get_artifact("art_competitor_intel").producer_worker == "worker_competitor_intel"

        # 3. Phase history is complete
        assert len(context.phase_history) == 4
        assert context.phase_history["phase_build"].validation_score == 0.92
        assert context.phase_history["phase_simulation"].verification_status == "PASS"

        # 4. Decisions are preserved with reasons
        assert len(context.decisions) == 2
        assert any("sub-second alerts" in d.decision for d in context.decisions)

        # 5. Deployment receipt is preserved
        assert len(context.receipts) == 1
        assert context.receipts[0].platform == "vercel"
        assert context.receipts[0].permalink == "https://crypto-alerts-live.vercel.app"

        # 6. Controlled slice retrieval works for specific worker roles
        mkt_slice = context.get_slice(["idea", "target_users", "competitor_intelligence", "distribution"])
        assert "idea" in mkt_slice
        assert "competitor_intelligence" in mkt_slice
        assert len(mkt_slice["competitor_intelligence"]) == 1
        assert "code_assets" not in mkt_slice  # Marketing worker does not receive raw code workspaces

        deploy_slice = context.get_slice(["code_assets", "deployment", "receipts"])
        assert "code_assets" in deploy_slice
        assert len(deploy_slice["code_assets"]) == 2  # Workspace and Database schema
        assert "receipts" in deploy_slice

        # 7. Serialization is secret-free
        json_output = json.dumps(context.to_dict())
        assert "crypto-alerts-live.vercel.app" in json_output
        assert "api_key" not in json_output or "[REDACTED_SECRET]" in json_output
