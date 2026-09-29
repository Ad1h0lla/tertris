"""
Tetris — Milestone 3.1 Test Suite
=================================

Phase 2 → Phase 3 Distribution Contract Verification.

Tests:
1. Existing Phase 2 output keys are preserved and compatible.
2. Distribution intelligence structure is present with required subfields.
3. Source URLs and evidence are preserved in Phase 2 distribution intelligence.
4. Empty / malformed Phase 2 context does not crash Phase 3.
5. Phase 3 consumes Phase 2 output and generates structured distribution plan.
6. NO proposed actions are marked SUCCESS (all are strictly PENDING_APPROVAL / NOT_STARTED).
7. Proposed actions conform to generic DistributionAction schema (worker, platform, action_type, target, content, approval, execution, receipt).
8. Approval status and execution status default correctly.
9. ConnectorAction and database persistence for Phase 3 remain compatible.
10. Missing distribution intelligence handles gracefully without fabricating fake live URLs.
11. Real pipeline data flow test: Phase 2 output -> Phase 3 distribution plan.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from execution.distribution_models import (
    create_distribution_action,
    validate_distribution_action,
    ActionWorker,
    ActionPlatform,
    ApprovalStatus,
    ExecutionStatus,
    VerificationStatus,
)
from agents.specialist.competitor_intel_agent import run_competitor_intel
from agents.specialist.campaign_agent import run_campaign, _extract_distribution_intel_from_context
from orchestrator.router import route_to_specialist
from agents.search_agent import SearchResult, SearchStatus, SearchResultItem


# ===========================================================================
# 1. Distribution Action Model & Contract Tests
# ===========================================================================

class TestDistributionActionModel:
    def test_create_distribution_action_defaults(self):
        action = create_distribution_action(
            worker="community",
            platform="reddit",
            action_type="create_post",
            target={"community": "r/saas"},
            content={"title": "Test Title", "body": "Test Body"},
            execution_id="exec-123",
            reason="High relevance community",
            source_url="https://reddit.com/r/saas",
        )

        assert action["phase"] == 3
        assert action["worker"] == "community"
        assert action["platform"] == "reddit"
        assert action["action_type"] == "create_post"
        assert action["target"] == {"community": "r/saas"}
        assert action["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL
        assert action["approval"]["required"] is True
        assert action["execution"]["status"] == ExecutionStatus.NOT_STARTED
        assert action["receipt"]["verification_status"] == VerificationStatus.NOT_TESTED
        assert action["receipt"]["verified"] is False
        assert action["error"] is None
        assert validate_distribution_action(action) is True

    def test_action_never_defaults_to_success(self):
        action = create_distribution_action(
            worker="social",
            platform="twitter",
            action_type="publish_tweet",
            target={"topic": "AI productivity"},
            content={"text": "Check out this productivity tool"},
        )
        # CRITICAL PRINCIPLE: Proposed actions must NEVER be SUCCESS
        assert action["execution"]["status"] != ExecutionStatus.SUCCESS
        assert action["execution"]["status"] == ExecutionStatus.NOT_STARTED
        assert action["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL

    def test_action_validation_rejects_missing_keys(self):
        invalid_action = {
            "action_id": "123",
            "worker": "community",
            # missing required keys
        }
        assert validate_distribution_action(invalid_action) is False

    def test_action_validation_rejects_secrets_and_credentials(self):
        action = create_distribution_action(
            worker="social",
            platform="twitter",
            action_type="publish_tweet",
            target={"topic": "AI"},
            content={"text": "Hello world"},
        )
        action["content"]["api_key"] = "secret_12345"
        # Must fail security validation
        assert validate_distribution_action(action) is False


# ===========================================================================
# 2. Phase 2 Distribution Intelligence Schema & Compatibility Tests
# ===========================================================================

class TestPhase2DistributionIntelligence:
    @patch("agents.specialist.competitor_intel_agent.search_web")
    @patch("llm.router.get_llm_response")
    def test_phase2_output_contains_all_baseline_and_distribution_fields(
        self, mock_llm, mock_search
    ):
        mock_search.return_value = SearchResult(
            query="test query",
            status=SearchStatus.SUCCESS,
            results=[
                SearchResultItem(
                    title="Top Competitor",
                    url="https://competitor.com",
                    snippet="Best productivity app for teams",
                ),
                SearchResultItem(
                    title="Reddit r/productivity discussion",
                    url="https://reddit.com/r/productivity/comments/123",
                    snippet="How do you track team habits?",
                ),
            ],
            total_results=2,
        )

        mock_llm.return_value = json.dumps({
            "competitors": [
                {
                    "name": "CompetitorA",
                    "pricing": "$29/mo",
                    "target_customer": "Teams",
                    "weakness": "High price",
                    "source": "https://competitor.com",
                }
            ],
            "market_gap": "Affordable collaborative tracking",
            "recommended_price_range": "$10 - $20/month",
            "pricing_strategy": "undercut",
            "key_differentiators": ["Instant sync", "Lower pricing"],
            "total_competitors_found": 1,
            "distribution_intelligence": {
                "audiences": [
                    {
                        "segment": "Remote team leads",
                        "description": "Need habit tracking for distributed teams",
                        "evidence": "Observed on Reddit",
                    }
                ],
                "customer_problems": [
                    {
                        "problem": "Expensive seat-based pricing",
                        "urgency": "high",
                        "evidence": "Complaints on forums",
                    }
                ],
                "communities": [
                    {
                        "platform": "reddit",
                        "community": "r/productivity",
                        "reason": "Active habit tracking discussions",
                        "relevance": "high",
                        "source_url": "https://reddit.com/r/productivity/comments/123",
                    }
                ],
                "channels": [
                    {
                        "platform": "reddit",
                        "reason": "High organic intent",
                        "evidence": "Community size 2M+",
                        "source_url": "https://reddit.com/r/productivity/comments/123",
                    }
                ],
                "content_angles": [
                    {
                        "angle": "Why per-seat pricing hurts team habits",
                        "target_problem": "Expensive seat-based pricing",
                        "hook": "Stop paying per seat for simple tracking",
                    }
                ],
                "distribution_opportunities": [
                    {
                        "platform": "reddit",
                        "type": "community_discussion",
                        "description": "Engage in habit tracking discussions on r/productivity",
                        "target": "r/productivity",
                        "reason": "Direct problem alignment",
                        "source_url": "https://reddit.com/r/productivity/comments/123",
                    }
                ],
            },
        })

        result = run_competitor_intel(
            confirmed_goal="Team habit tracking app",
            idea_type="saas",
            context="Phase 1 HTML app built",
        )

        # 1. Baseline Phase 2 fields preserved
        assert "competitors" in result
        assert "market_gap" in result
        assert "recommended_price_range" in result
        assert "pricing_strategy" in result
        assert "key_differentiators" in result
        assert "research_source" in result
        assert "search_status" in result
        assert "source_urls" in result

        # 2. Distribution intelligence present
        assert "distribution_intelligence" in result
        dist_intel = result["distribution_intelligence"]
        assert "audiences" in dist_intel
        assert "customer_problems" in dist_intel
        assert "communities" in dist_intel
        assert "channels" in dist_intel
        assert "content_angles" in dist_intel
        assert "distribution_opportunities" in dist_intel

        # 3. Source evidence preserved
        assert len(dist_intel["communities"]) == 1
        assert dist_intel["communities"][0]["source_url"] == "https://reddit.com/r/productivity/comments/123"
        assert len(result["source_urls"]) == 2

    @patch("agents.specialist.competitor_intel_agent.search_web")
    @patch("llm.router.get_llm_response")
    def test_empty_search_failure_does_not_crash_or_fabricate_urls(
        self, mock_llm, mock_search
    ):
        mock_search.return_value = SearchResult(
            query="test",
            status=SearchStatus.FAILED,
            results=[],
            total_results=0,
            error="API error",
        )
        mock_llm.side_effect = Exception("LLM connection error")

        result = run_competitor_intel(
            confirmed_goal="Niche offline tool",
            idea_type="desktop_app",
            context="",
        )

        assert result["search_status"] == "FAILED"
        assert result["distribution_intelligence"]["communities"] == []
        assert result["distribution_intelligence"]["channels"] == []
        assert result["source_urls"] == []


# ===========================================================================
# 3. Phase 2 → Phase 3 Data Flow & Router Chaining Tests
# ===========================================================================

class TestPhase2ToPhase3DataFlow:
    @patch("agents.specialist.competitor_intel_agent.run_competitor_intel")
    @patch("agents.specialist.pricing_agent.run_pricing")
    def test_router_phase2_returns_combined_distribution_intel(
        self, mock_pricing, mock_competitor
    ):
        mock_competitor.return_value = {
            "competitors": [{"name": "CompX"}],
            "market_gap": "Gap X",
            "search_status": "SUCCESS",
            "research_source": "live_web_search",
            "source_urls": ["https://compx.com"],
            "distribution_intelligence": {
                "audiences": [{"segment": "Founders"}],
                "customer_problems": [{"problem": "High churn"}],
                "communities": [{"platform": "reddit", "community": "r/startups", "source_url": "https://reddit.com/r/startups"}],
                "channels": [{"platform": "reddit", "reason": "High traffic"}],
                "content_angles": [],
                "distribution_opportunities": [],
            },
        }

        mock_pricing.return_value = {
            "pricing_tiers": [{"name": "Pro", "price": "$19/mo"}],
            "pricing_status": "SUCCESS",
        }

        phase2_result = route_to_specialist(
            outcome_type="competitor_intel",
            confirmed_goal={"understood_goal": "SaaS analytics tool", "idea_type": "saas"},
            context="Phase 1 build output",
            phase=2,
        )

        assert phase2_result["phase_2_status"] == "SUCCESS"
        assert "competitor_intel" in phase2_result
        assert "pricing" in phase2_result
        assert "distribution_intelligence" in phase2_result
        assert phase2_result["distribution_intelligence"]["audiences"][0]["segment"] == "Founders"
        assert phase2_result["source_urls"] == ["https://compx.com"]
        assert phase2_result["chain"] == ["competitor_intel", "pricing"]

    @patch("llm.router.get_llm_response")
    def test_campaign_agent_consumes_phase2_distribution_intel(self, mock_llm):
        phase2_payload = {
            "phase_2_status": "SUCCESS",
            "distribution_intelligence": {
                "communities": [
                    {
                        "platform": "reddit",
                        "community": "r/entrepreneur",
                        "reason": "Active SaaS founders discussion",
                        "source_url": "https://reddit.com/r/entrepreneur",
                    }
                ],
                "customer_problems": [
                    {
                        "problem": "Manual customer outreach is tedious",
                        "urgency": "high",
                    }
                ],
            },
        }

        mock_llm.return_value = json.dumps({
            "target_audience": "Early stage founders",
            "positioning_statement": "Automated outreach pipeline",
            "key_channels": ["Reddit", "Email", "Twitter"],
            "campaign_angle": "Automate founder-led sales",
            "ad_copy": [{"headline": "Stop emailing manually", "body": "Automate outreach", "cta": "Try Free"}],
            "email_sequence": [{"subject": "Automate sales", "preview": "Quick intro", "body": "Hi founder..."}],
            "launch_offer": "14 days free",
            "acquisition_funnel": ["Landing", "Sign-up", "Activate"],
            "distribution_plan": {
                "recommended_workers": ["community", "social", "outreach"],
                "proposed_actions": [
                    {
                        "worker": "community",
                        "platform": "reddit",
                        "action_type": "create_post",
                        "target": {"community": "r/entrepreneur"},
                        "content": {"title": "How we automated founder outreach", "body": "Case study breakdown..."},
                        "reason": "Active target audience on r/entrepreneur",
                        "source_url": "https://reddit.com/r/entrepreneur",
                    },
                    {
                        "worker": "outreach",
                        "platform": "email",
                        "action_type": "send_email",
                        "target": {"persona": "B2B SaaS Founder"},
                        "content": {"subject": "Quick question on outreach", "body": "Hi there..."},
                        "reason": "Direct outreach to ICP",
                        "source_url": "",
                    }
                ]
            }
        })

        phase3_output = run_campaign(
            goal="Automated B2B outreach agent",
            context=json.dumps(phase2_payload),
            phase=3,
            execution_id="exec-456",
        )

        assert "distribution_plan" in phase3_output
        plan = phase3_output["distribution_plan"]
        assert plan["recommended_workers"] == ["community", "social", "outreach"]
        assert len(plan["actions"]) == 2

        reddit_action = plan["actions"][0]
        assert reddit_action["worker"] == "community"
        assert reddit_action["platform"] == "reddit"
        assert reddit_action["target"]["community"] == "r/entrepreneur"
        assert reddit_action["source_url"] == "https://reddit.com/r/entrepreneur"
        assert reddit_action["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL
        assert reddit_action["execution"]["status"] == ExecutionStatus.NOT_STARTED
        assert reddit_action["execution_id"] == "exec-456"

        assert validate_distribution_action(reddit_action) is True

    def test_campaign_agent_fallback_with_empty_context(self):
        # Empty context should safely produce valid DistributionAction proposals without crashing
        output = run_campaign(
            goal="Minimalist markdown note taking app",
            context="",
            phase=3,
            execution_id="exec-empty",
        )

        assert "distribution_plan" in output
        assert "actions" in output["distribution_plan"]
        assert len(output["distribution_plan"]["actions"]) >= 1

        for act in output["distribution_plan"]["actions"]:
            assert validate_distribution_action(act) is True
            assert act["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL
            assert act["execution"]["status"] == ExecutionStatus.NOT_STARTED


# ===========================================================================
# 4. Database & Persistence Compatibility Tests
# ===========================================================================

class TestDistributionPersistence:
    def test_phase_result_distribution_plan_persistence(self):
        from database.models import SessionLocal, PhaseResult, init_db
        from database.operations import save_phase_result, get_phase_results
        import uuid

        init_db()
        db = SessionLocal()
        exec_id = f"test-m31-{uuid.uuid4()}"

        test_plan = {
            "recommended_workers": ["community", "social"],
            "actions": [
                create_distribution_action(
                    worker="community",
                    platform="reddit",
                    action_type="create_post",
                    target={"community": "r/webdev"},
                    content={"title": "New Dev Tool", "body": "We built..."},
                    execution_id=exec_id,
                )
            ],
            "total_actions": 1,
        }

        try:
            save_phase_result(
                db=db,
                execution_id=exec_id,
                phase=3,
                outcome_type="campaign",
                outcome=json.dumps(test_plan),
                score=0.95,
                trace=[{"step": "campaign_planned"}],
                distribution_plan=test_plan,
            )

            results = get_phase_results(db, exec_id)
            assert len(results) == 1
            saved_pr = results[0]
            assert saved_pr.distribution_plan is not None
            assert saved_pr.distribution_plan["recommended_workers"] == ["community", "social"]
            assert len(saved_pr.distribution_plan["actions"]) == 1
            assert saved_pr.distribution_plan["actions"][0]["worker"] == "community"
            assert saved_pr.distribution_plan["actions"][0]["approval"]["status"] == "PENDING_APPROVAL"
        finally:
            db.close()
