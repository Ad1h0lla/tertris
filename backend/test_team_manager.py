"""
Unit Tests for Workforce Engine — Stage 3: Worker Registry & Dynamic Team Manager
================================================================================

Tests:
1. Worker registration
2. Duplicate worker rejection
3. Worker lookup by ID
4. Capability lookup
5. Task-type lookup
6. Phase-affinity matching
7. Connector requirement detection
8. Permission requirement detection
9. Capability satisfied
10. Capability missing
11. Capable-but-connector-missing readiness
12. No capable worker readiness
13. Single-worker phase
14. Multi-worker phase
15. Multi-phase team assembly
16. Same worker reused across phases
17. Unnecessary workers are not selected (minimal team property)
18. Deterministic team assignment
19. TeamPlan serialization & deserialization
20. Legacy workers represented without changing execution
21. Scenario A: Simple portfolio website (Minimal Code/UI + Deployment, no Reddit/Email)
22. Scenario B: SaaS product requiring web app + database (Code + UI + Database)
23. Scenario C: Marketing phase requiring Reddit with/without connected credentials
24. Scenario D: Unknown capability handling
"""

import json
import pytest

from orchestration.phase_contract import Phase, PhaseStatus, ProjectWorkflow
from orchestration.worker_registry import (
    WorkerDescriptor,
    WorkerRegistry,
    get_default_registry,
    build_default_worker_descriptors,
)
from orchestration.team_manager import (
    TeamManager,
    TeamPlan,
    TeamReadiness,
    PhaseTeamAssignment,
)


# =============================================================================
# 1. Worker Registry Core Tests (Tests 1-8)
# =============================================================================

class TestWorkerRegistryCore:
    def test_worker_registration_and_lookup(self):
        reg = WorkerRegistry()
        desc = WorkerDescriptor(
            worker_id="test_worker_1",
            name="Test Worker",
            role="tester",
            capabilities=["test_cap_1", "test_cap_2"],
            required_connectors=["test_conn"],
            permissions=["perm_write"],
            supported_task_types=["test_task"],
            phase_affinity=["build"],
        )
        reg.register(desc)

        assert reg.has_worker("test_worker_1") is True
        fetched = reg.get("test_worker_1")
        assert fetched is not None
        assert fetched.name == "Test Worker"
        assert fetched.has_capability("test_cap_1") is True
        assert fetched.has_capability("non_existent") is False
        assert fetched.has_connector("test_conn") is True

    def test_duplicate_worker_rejection(self):
        reg = WorkerRegistry()
        desc = WorkerDescriptor(worker_id="dup_worker", name="Dup", role="test")
        reg.register(desc)

        with pytest.raises(ValueError, match="already registered"):
            reg.register(desc, allow_override=False)

        # Allowed when allow_override is True
        desc2 = WorkerDescriptor(worker_id="dup_worker", name="Dup Updated", role="test")
        reg.register(desc2, allow_override=True)
        assert reg.get("dup_worker").name == "Dup Updated"

    def test_capability_lookup(self):
        reg = get_default_registry()
        code_workers = reg.find_by_capability("code_generation")
        assert any(w.worker_id == "worker_code" for w in code_workers)

        db_workers = reg.find_by_capability("database")
        assert any(w.worker_id == "worker_database" for w in db_workers)

        empty = reg.find_by_capability("quantum_teleportation")
        assert len(empty) == 0

    def test_task_type_lookup(self):
        reg = get_default_registry()
        reddit_workers = reg.find_by_task_type("post_reddit")
        assert any(w.worker_id == "worker_reddit" for w in reddit_workers)

        deploy_workers = reg.find_by_task_type("deploy_vercel")
        assert any(w.worker_id == "worker_deployment" for w in deploy_workers)

    def test_phase_affinity_lookup(self):
        reg = get_default_registry()
        build_aff = reg.find_by_phase_affinity("build")
        assert any(w.worker_id == "worker_code" for w in build_aff)
        assert any(w.worker_id == "worker_ui" for w in build_aff)

    def test_connector_and_permission_requirement_detection(self):
        reg = get_default_registry()
        reddit = reg.get("worker_reddit")
        assert "redditapis" in reddit.required_connectors
        assert "network:write:approval_required" in reddit.permissions

        email = reg.get("worker_email")
        assert "sendgrid" in email.required_connectors


# =============================================================================
# 2. Team Manager Capability Matching & Scenarios (Tests 9-20)
# =============================================================================

class TestTeamManagerMatching:
    def test_single_worker_phase_satisfied(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p1")
        phase = Phase(
            phase_id="phase_research",
            name="Research Phase",
            metadata={"required_capabilities": ["deep_research"]},
        )
        wf.add_phase(phase)

        plan = manager.evaluate_team(wf)
        assert plan.readiness == TeamReadiness.READY.value
        assert "phase_research" in plan.phase_assignments
        p_assign = plan.phase_assignments["phase_research"]
        assert p_assign.worker_ids == ["worker_research"]
        assert p_assign.capabilities_satisfied == ["deep_research"]
        assert p_assign.capabilities_missing == []

    def test_multi_worker_phase_satisfied(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p2")
        phase = Phase(
            phase_id="phase_build_full",
            name="Full Build Phase",
            metadata={"required_capabilities": ["code_generation", "frontend", "database"]},
        )
        wf.add_phase(phase)

        plan = manager.evaluate_team(wf)
        assert plan.readiness == TeamReadiness.READY.value
        p_assign = plan.phase_assignments["phase_build_full"]
        assert set(p_assign.worker_ids) == {"worker_code", "worker_ui", "worker_database"}
        assert set(p_assign.capabilities_satisfied) == {"code_generation", "frontend", "database"}
        assert p_assign.capabilities_missing == []

    def test_capable_but_missing_connector(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p3")
        phase = Phase(
            phase_id="phase_reddit_outreach",
            name="Reddit Outreach Phase",
            metadata={"required_capabilities": ["reddit_distribution"]},
        )
        wf.add_phase(phase)

        # 1. When redditapis is NOT in connected connectors
        plan_disconnected = manager.evaluate_team(wf, connected_connectors=set())
        assert plan_disconnected.readiness == TeamReadiness.CAPABLE_BUT_MISSING_CONNECTOR.value
        assert plan_disconnected.is_executable() is False
        p_assign = plan_disconnected.phase_assignments["phase_reddit_outreach"]
        assert "worker_reddit" in p_assign.worker_ids
        assert "redditapis" in p_assign.missing_connectors

        # 2. When redditapis IS connected
        plan_connected = manager.evaluate_team(wf, connected_connectors={"redditapis"})
        assert plan_connected.readiness == TeamReadiness.READY.value
        assert plan_connected.is_executable() is True
        p_assign_conn = plan_connected.phase_assignments["phase_reddit_outreach"]
        assert p_assign_conn.missing_connectors == []

    def test_no_capable_worker_found(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p4")
        phase = Phase(
            phase_id="phase_quantum",
            name="Quantum Computing Phase",
            metadata={"required_capabilities": ["quantum_teleportation_entanglement"]},
        )
        wf.add_phase(phase)

        plan = manager.evaluate_team(wf)
        assert plan.readiness == TeamReadiness.NO_CAPABLE_WORKER.value
        assert "quantum_teleportation_entanglement" in plan.unresolved_requirements

    def test_blocked_by_permission(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p5")
        phase = Phase(
            phase_id="phase_deploy",
            name="Deployment Phase",
            metadata={"required_capabilities": ["vercel_deployment"]},
        )
        wf.add_phase(phase)

        # Authorized permissions do NOT include "deployment:execute"
        plan = manager.evaluate_team(
            wf,
            connected_connectors={"vercel"},
            authorized_permissions={"filesystem:read"},
        )
        assert plan.readiness == TeamReadiness.BLOCKED_BY_PERMISSION.value
        p_assign = plan.phase_assignments["phase_deploy"]
        assert "deployment:execute" in p_assign.denied_permissions

    def test_same_worker_reused_across_multiple_phases(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p6")
        p1 = Phase(phase_id="p1", name="Simulation", metadata={"required_capabilities": ["qa_testing"]})
        p2 = Phase(phase_id="p2", name="Regression QA", metadata={"required_capabilities": ["smoke_test"]})
        wf.add_phase(p1)
        wf.add_phase(p2)

        plan = manager.evaluate_team(wf)
        assert plan.readiness == TeamReadiness.READY.value
        assert "worker_qa_simulation" in plan.phase_assignments["p1"].worker_ids
        assert "worker_qa_simulation" in plan.phase_assignments["p2"].worker_ids

    def test_unnecessary_workers_are_not_selected(self):
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="p7")
        phase = Phase(
            phase_id="phase_copy",
            name="Copywriting Phase",
            metadata={"required_capabilities": ["copywriting"]},
        )
        wf.add_phase(phase)

        plan = manager.evaluate_team(wf)
        selected_ids = plan.phase_assignments["phase_copy"].worker_ids
        assert selected_ids == ["worker_campaign"]
        # Must not select code, reddit, or deployment workers
        assert "worker_code" not in selected_ids
        assert "worker_reddit" not in selected_ids
        assert "worker_deployment" not in selected_ids

    def test_deterministic_team_assignment(self):
        manager = TeamManager()
        wf = ProjectWorkflow.create_default_lifecycle(project_id="det_1")

        plan1 = manager.evaluate_team(wf, connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"})
        plan2 = manager.evaluate_team(wf, connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"})

        assert plan1.readiness == plan2.readiness
        for pid in plan1.phase_assignments:
            assert plan1.phase_assignments[pid].worker_ids == plan2.phase_assignments[pid].worker_ids

    def test_team_plan_serialization_and_workflow_apply(self):
        manager = TeamManager()
        wf = ProjectWorkflow.create_default_lifecycle(project_id="p_ser")
        plan = manager.evaluate_team(wf, connected_connectors={"redditapis", "twitter", "sendgrid", "vercel"})

        d = plan.to_dict()
        assert d["project_id"] == "p_ser"
        assert len(d["phase_assignments"]) == 5

        json_str = json.dumps(d)
        reloaded_dict = json.loads(json_str)
        reloaded_plan = TeamPlan.from_dict(reloaded_dict)

        assert reloaded_plan.project_id == plan.project_id
        assert len(reloaded_plan.phase_assignments) == len(plan.phase_assignments)

        # Apply to workflow
        plan.apply_to_workflow(wf)
        p_build = wf.get_phase("phase_build")
        assert len(p_build.workers) > 0


# =============================================================================
# 3. Explicit User Scenarios (Tests 21-24)
# =============================================================================

class TestUserScenarios:
    def test_scenario_a_simple_portfolio_website(self):
        """
        SCENARIO A: Simple portfolio website
        Expected: Build -> Code/UI worker; Deployment -> Deployment worker.
        Do NOT assign Reddit, Email, or Marketing workers unnecessarily.
        """
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="scenario_a")
        p_build = Phase(
            phase_id="build",
            name="Build Portfolio",
            metadata={"required_capabilities": ["frontend", "html_css"]},
        )
        p_deploy = Phase(
            phase_id="deploy",
            name="Deploy Site",
            metadata={"required_capabilities": ["vercel_deployment"]},
            dependencies=["build"],
        )
        wf.add_phase(p_build)
        wf.add_phase(p_deploy)

        plan = manager.evaluate_team(wf, connected_connectors={"vercel"})

        # Assert correct minimal assignments
        build_workers = plan.phase_assignments["build"].worker_ids
        deploy_workers = plan.phase_assignments["deploy"].worker_ids

        assert "worker_ui" in build_workers
        assert "worker_deployment" in deploy_workers

        # Assert no unnecessary marketing/distribution workers selected
        all_worker_ids = [w.worker_id for w in plan.workers]
        assert "worker_reddit" not in all_worker_ids
        assert "worker_email" not in all_worker_ids
        assert "worker_x" not in all_worker_ids
        assert "worker_campaign" not in all_worker_ids

    def test_scenario_b_saas_product_requiring_web_app_and_database(self):
        """
        SCENARIO B: SaaS product requiring web app + database
        Expected: Build -> Code/UI/Database-capable workers.
        """
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="scenario_b")
        p_build = Phase(
            phase_id="build",
            name="Build SaaS App",
            metadata={"required_capabilities": ["backend", "frontend", "postgresql", "api_development"]},
        )
        wf.add_phase(p_build)

        plan = manager.evaluate_team(wf)
        build_workers = set(plan.phase_assignments["build"].worker_ids)
        assert "worker_code" in build_workers
        assert "worker_ui" in build_workers
        assert "worker_database" in build_workers
        assert plan.readiness == TeamReadiness.READY.value

    def test_scenario_c_marketing_phase_requiring_reddit(self):
        """
        SCENARIO C: Marketing phase requiring Reddit.
        Expected: Reddit Worker selected if registered.
        If Reddit connector is missing: team remains CAPABLE_BUT_MISSING_CONNECTOR, NOT READY.
        """
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="scenario_c")
        p_mkt = Phase(
            phase_id="marketing",
            name="Reddit Outreach",
            metadata={"required_capabilities": ["reddit_distribution"]},
        )
        wf.add_phase(p_mkt)

        # Case 1: Missing redditapis connector
        plan_missing = manager.evaluate_team(wf, connected_connectors=set())
        assert "worker_reddit" in plan_missing.phase_assignments["marketing"].worker_ids
        assert plan_missing.readiness == TeamReadiness.CAPABLE_BUT_MISSING_CONNECTOR.value
        assert plan_missing.is_executable() is False
        assert "redditapis" in plan_missing.missing_connectors

        # Case 2: Connected redditapis connector
        plan_ready = manager.evaluate_team(wf, connected_connectors={"redditapis"})
        assert "worker_reddit" in plan_ready.phase_assignments["marketing"].worker_ids
        assert plan_ready.readiness == TeamReadiness.READY.value
        assert plan_ready.is_executable() is True

    def test_scenario_d_unknown_capability(self):
        """
        SCENARIO D: Unknown capability.
        Expected: NO_CAPABLE_WORKER.
        """
        manager = TeamManager()
        wf = ProjectWorkflow(project_id="scenario_d")
        p_alien = Phase(
            phase_id="alien_tech",
            name="Alien Tech Phase",
            metadata={"required_capabilities": ["faster_than_light_communication"]},
        )
        wf.add_phase(p_alien)

        plan = manager.evaluate_team(wf)
        assert plan.readiness == TeamReadiness.NO_CAPABLE_WORKER.value
        assert plan.is_executable() is False
        assert "faster_than_light_communication" in plan.unresolved_requirements
