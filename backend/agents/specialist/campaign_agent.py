"""
Tetris — Campaign Specialist Agent
==================================

Phase 3 specialist agent that consumes Phase 2 market & distribution intelligence
and produces a structured distribution plan with proposed action candidates.

Core Principles:
----------------
- Phase 2 finds opportunities and market understanding.
- Phase 3 plans and coordinates distribution action candidates for execution workers.
- Proposed actions are NEVER marked SUCCESS. They are candidate actions awaiting approval:
    approval.status = "PENDING_APPROVAL"
    execution.status = "NOT_STARTED"
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from execution.distribution_models import (
    create_distribution_action,
    validate_distribution_action,
    ActionWorker,
    ActionPlatform,
    ApprovalStatus,
    ExecutionStatus,
)

load_dotenv()
logger = logging.getLogger(__name__)


def _extract_distribution_intel_from_context(context: str) -> Dict[str, Any]:
    """
    Extracts distribution_intelligence or competitor_intel from the incoming context string if present.
    """
    if not context or not context.strip():
        return {}

    # Try parsing context directly as JSON
    try:
        data = json.loads(context.strip())
        if isinstance(data, dict):
            if "distribution_intelligence" in data and isinstance(data["distribution_intelligence"], dict):
                return data["distribution_intelligence"]
            if "competitor_intel" in data and isinstance(data["competitor_intel"], dict):
                comp = data["competitor_intel"]
                if "distribution_intelligence" in comp and isinstance(comp["distribution_intelligence"], dict):
                    return comp["distribution_intelligence"]
    except Exception:
        pass

    # Try finding JSON block in text
    try:
        if "```json" in context:
            blocks = context.split("```json")
            for blk in blocks[1:]:
                json_str = blk.split("```")[0].strip()
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict):
                        if "distribution_intelligence" in data:
                            return data["distribution_intelligence"]
                        if "competitor_intel" in data and "distribution_intelligence" in data["competitor_intel"]:
                            return data["competitor_intel"]["distribution_intelligence"]
                except Exception:
                    continue
    except Exception:
        pass

    return {}


def run_campaign(
    goal: str = "",
    context: str = "",
    phase: int = 3,
    execution_id: str = "",
) -> Dict[str, Any]:
    """
    Generates a structured marketing campaign and Phase 3 distribution action candidates.

    Parameters
    ----------
    goal : str
        The understood product goal.
    context : str
        Phase 2 intelligence context (contains competitor intel, distribution intelligence, pricing).
    phase : int
        Execution phase number (default 3).
    execution_id : str
        ID of the current execution.

    Returns
    -------
    dict
        Structured distribution plan and campaign strategy with standardized DistributionAction objects.
    """
    from llm.router import get_llm_response

    dist_intel = _extract_distribution_intel_from_context(context)

    # Format distribution intelligence section for LLM prompt
    dist_intel_text = ""
    if dist_intel:
        dist_intel_text = f"\n\n--- Phase 2 Distribution Intelligence ---\n{json.dumps(dist_intel, indent=2)}"

    system_prompt = """You are the Distribution & Campaign Specialist inside TETRIS (Phase 3).
Your job is to translate Phase 2 market intelligence into an actionable distribution plan and proposed distribution action candidates for 3 worker types:
1. "community" (e.g. Reddit discussion posts, helpful answers in relevant communities)
2. "social" (e.g. Twitter/X launch announcements or thought leadership threads, LinkedIn posts)
3. "outreach" (e.g. Cold email sequences tailored to specific ICPs)

CRITICAL RULES:
- Use the provided Phase 2 distribution intelligence, communities, and customer problems as your evidence base.
- Propose specific, concrete actions referencing the discovered communities, channels, and problems.
- Do NOT fabricate live success or execution status.
- Return ONLY valid JSON with this exact structure:

{
  "target_audience": "Specific audience description derived from Phase 2 intel",
  "positioning_statement": "Clear positioning statement",
  "key_channels": ["Channel 1", "Channel 2", "Channel 3"],
  "campaign_angle": "Core narrative hook or campaign theme",
  "ad_copy": [
    {"headline": "Headline 1", "body": "Ad body text", "cta": "Call to action"}
  ],
  "email_sequence": [
    {"subject": "Subject Line", "preview": "Preview text", "body": "Email body"}
  ],
  "launch_offer": "Initial offer or hook",
  "acquisition_funnel": ["Step 1", "Step 2", "Step 3"],
  "distribution_plan": {
    "recommended_workers": ["community", "social", "outreach"],
    "proposed_actions": [
      {
        "worker": "community",
        "platform": "reddit",
        "action_type": "create_post",
        "target": {
          "community": "r/example_subreddit"
        },
        "content": {
          "title": "Discussion title",
          "body": "Helpful post body providing value and introducing solution"
        },
        "reason": "Why this community and topic were chosen based on Phase 2 research",
        "source_url": "URL from research if available or empty string"
      },
      {
        "worker": "social",
        "platform": "twitter",
        "action_type": "publish_tweet",
        "target": {
          "topic": "Key pain point topic"
        },
        "content": {
          "text": "Tweet copy with hook and solution"
        },
        "reason": "Why this angle resonates with target ICP",
        "source_url": ""
      },
      {
        "worker": "outreach",
        "platform": "email",
        "action_type": "send_email",
        "target": {
          "persona": "Target buyer role / segment"
        },
        "content": {
          "subject": "Email subject",
          "body": "Direct value proposition cold email"
        },
        "reason": "Direct outreach to validated customer segment",
        "source_url": ""
      }
    ]
  }
}"""

    user_message = f"""PROJECT GOAL:
{goal}

PRIOR CONTEXT & PHASE 2 RESEARCH:
{context[:3500]}
{dist_intel_text}

Generate the complete Phase 3 distribution plan and proposed action candidates as JSON."""

    parsed_response = None
    try:
        raw_output = get_llm_response(
            task="campaign",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=3500,
            temperature=0.3,
        )

        clean = (raw_output or "").strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        if "{" in clean and "}" in clean:
            first_brace = clean.find("{")
            last_brace = clean.rfind("}")
            clean = clean[first_brace:last_brace + 1].strip()

        res = json.loads(clean)
        if isinstance(res, dict):
            parsed_response = res
    except Exception as e:
        logger.warning(f"Campaign LLM call/parse failed: {e}")

    # Fallback structure if LLM parsing failed
    if not parsed_response:
        # Build derived opportunities from dist_intel if available
        communities = dist_intel.get("communities", [])
        top_comm = communities[0].get("community", "r/productivity") if communities else "r/productivity"
        comm_url = communities[0].get("source_url", "") if communities else ""

        parsed_response = {
            "target_audience": "Founders, builders, and growth operators",
            "positioning_statement": f"Automated execution and intelligence for {goal[:60]}",
            "key_channels": ["Reddit", "X/Twitter", "Direct Email", "Product Hunt"],
            "campaign_angle": "Solve core customer pain points with verified intelligence",
            "ad_copy": [
                {
                    "headline": f"Build & Scale {goal[:40]} Faster",
                    "body": "Automate discovery, market research, and multi-channel distribution from a single system.",
                    "cta": "Start Distributing"
                }
            ],
            "email_sequence": [
                {
                    "subject": f"How teams are solving {goal[:40]} problems",
                    "preview": "Actionable workflow breakdown",
                    "body": "Hello,\n\nWe noticed discussions around pain points in this space and built a streamlined solution..."
                }
            ],
            "launch_offer": "Early Access / Free Tier with 14-day Pro trial",
            "acquisition_funnel": ["Community Discovery", "Landing Page Demo", "Self-Serve Sign-up", "Value Delivery"],
            "distribution_plan": {
                "recommended_workers": ["community", "social", "outreach"],
                "proposed_actions": [
                    {
                        "worker": "community",
                        "platform": "reddit",
                        "action_type": "create_post",
                        "target": {"community": top_comm},
                        "content": {
                            "title": f"Addressing key challenges in {goal[:40]}",
                            "body": "Sharing research and insights on solving this workflow efficiently..."
                        },
                        "reason": f"Active community discussions identified in Phase 2 for {top_comm}",
                        "source_url": comm_url
                    },
                    {
                        "worker": "social",
                        "platform": "twitter",
                        "action_type": "publish_tweet",
                        "target": {"topic": "Market Problem & Solution"},
                        "content": {
                            "text": f"Most approaches to {goal[:40]} are overly complex. Here is how to streamline it with automated execution."
                        },
                        "reason": "Educate and attract ICP on social",
                        "source_url": ""
                    },
                    {
                        "worker": "outreach",
                        "platform": "email",
                        "action_type": "send_email",
                        "target": {"persona": "Product Lead / Founder"},
                        "content": {
                            "subject": f"Quick question regarding {goal[:30]}",
                            "body": "Hi there,\n\nWe analyzed the current tools in this space and built an automated solution. Would love your thoughts."
                        },
                        "reason": "Direct outreach to validated buyer persona",
                        "source_url": ""
                    }
                ]
            }
        }

    # ---------------------------------------------------------------
    # Standardize proposed actions into generic DistributionAction models
    # ---------------------------------------------------------------
    raw_plan = parsed_response.get("distribution_plan", {})
    if not isinstance(raw_plan, dict):
        raw_plan = {}

    proposed_raw_actions = raw_plan.get("proposed_actions", [])
    if not isinstance(proposed_raw_actions, list):
        proposed_raw_actions = []

    # Also check if Phase 2 distribution_opportunities can seed actions if proposed_raw_actions is empty
    if not proposed_raw_actions and dist_intel.get("distribution_opportunities"):
        for opp in dist_intel.get("distribution_opportunities", []):
            platform = opp.get("platform", "reddit")
            worker = ActionWorker.COMMUNITY if platform == "reddit" else (ActionWorker.OUTREACH if platform == "email" else ActionWorker.SOCIAL)
            proposed_raw_actions.append({
                "worker": worker,
                "platform": platform,
                "action_type": "create_post" if platform == "reddit" else ("send_email" if platform == "email" else "publish_tweet"),
                "target": {"target": opp.get("target", "")},
                "content": {"body": opp.get("description", "")},
                "reason": opp.get("reason", ""),
                "source_url": opp.get("source_url", ""),
            })

    standardized_actions: List[Dict[str, Any]] = []
    for raw_act in proposed_raw_actions:
        if not isinstance(raw_act, dict):
            continue

        worker = raw_act.get("worker", ActionWorker.COMMUNITY)
        platform = raw_act.get("platform", ActionPlatform.REDDIT)
        action_type = raw_act.get("action_type", "create_post")
        target = raw_act.get("target", {})
        content = raw_act.get("content", {})
        reason = raw_act.get("reason", "")
        source_url = raw_act.get("source_url", "")

        action_obj = create_distribution_action(
            worker=worker,
            platform=platform,
            action_type=action_type,
            target=target,
            content=content,
            execution_id=execution_id,
            approval_required=True,
            reason=reason,
            source_url=source_url,
        )
        standardized_actions.append(action_obj)

    recommended_workers = raw_plan.get("recommended_workers", [ActionWorker.COMMUNITY, ActionWorker.SOCIAL, ActionWorker.OUTREACH])
    if not isinstance(recommended_workers, list):
        recommended_workers = [ActionWorker.COMMUNITY, ActionWorker.SOCIAL, ActionWorker.OUTREACH]

    final_distribution_plan = {
        "recommended_workers": recommended_workers,
        "actions": standardized_actions,
        "total_actions": len(standardized_actions),
    }

    parsed_response["distribution_plan"] = final_distribution_plan
    parsed_response["distribution_actions"] = standardized_actions

    return parsed_response
