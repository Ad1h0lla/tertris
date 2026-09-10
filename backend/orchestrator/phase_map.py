"""
Executa Phase Map

Recovered contract:
- get_recommended_phases(intent_classification)
- get_platform_checklist(idea_type)
"""

PHASES = {
    1: {
        "phase": 1,
        "name": "Core Outcome",
        "label": "Phase 1 — Build",
        "description": "Build the core asset required by the user's goal.",
    },
    2: {
        "phase": 2,
        "name": "Business Layer",
        "label": "Phase 2 — Validate",
        "description": "Validate the business, market, competition, pricing, and economics.",
    },
    3: {
        "phase": 3,
        "name": "Marketing Layer",
        "label": "Phase 3 — Market",
        "description": "Create messaging, channels, campaigns, and distribution assets.",
    },
    4: {
        "phase": 4,
        "name": "Launch Layer",
        "label": "Phase 4 — Launch",
        "description": "Prepare the launch plan, operational checklist, and launch calendar.",
    },
}


# Recovered from the application contract.
# Most executions use the complete four-phase chain.
DEFAULT_PHASES = [1, 2, 3, 4]


# Some intent types may not need every phase.
# Keep this conservative: unknown types receive the full chain.
PHASE_RECOMMENDATIONS = {
    "saas": [1, 2, 3, 4],
    "startup": [1, 2, 3, 4],
    "product": [1, 2, 3, 4],
    "mobile_app": [1, 2, 3, 4],
    "web_app": [1, 2, 3, 4],
    "chrome_extension": [1, 2, 3, 4],
    "automation": [1, 2, 3, 4],
    "ai_agent": [1, 2, 3, 4],
    "api": [1, 2, 3, 4],
    "document": [1, 2, 3, 4],
    "content": [1, 3, 4],
    "marketing": [1, 3, 4],
}


# Platform checklist used by the /detect-platforms endpoint.
PLATFORM_CHECKLISTS = {
    "saas": [
        "Product Hunt",
        "Indie Hackers",
        "Reddit",
        "Hacker News",
        "LinkedIn",
    ],
    "startup": [
        "Product Hunt",
        "Indie Hackers",
        "Reddit",
        "Hacker News",
        "LinkedIn",
    ],
    "mobile_app": [
        "Product Hunt",
        "Reddit",
        "X",
        "LinkedIn",
    ],
    "web_app": [
        "Product Hunt",
        "Indie Hackers",
        "Reddit",
        "Hacker News",
    ],
    "chrome_extension": [
        "Chrome Web Store",
        "Product Hunt",
        "Reddit",
        "LinkedIn",
    ],
    "ai_agent": [
        "Product Hunt",
        "Hacker News",
        "Reddit",
        "Indie Hackers",
        "LinkedIn",
    ],
    "automation": [
        "Product Hunt",
        "Indie Hackers",
        "Reddit",
        "LinkedIn",
    ],
    "content": [
        "Reddit",
        "LinkedIn",
        "X",
        "Substack",
    ],
    "marketing": [
        "Reddit",
        "LinkedIn",
        "X",
        "Product Hunt",
    ],
}


def get_recommended_phases(intent_classification):
    """
    Return phase numbers recommended for an intent.

    The recovered application passes the intent classification directly
    into this function.
    """
    if not intent_classification:
        return DEFAULT_PHASES.copy()

    key = str(intent_classification).strip().lower()

    # Handle common classifier variations.
    aliases = {
        "chrome-extension": "chrome_extension",
        "mobile-app": "mobile_app",
        "web-app": "web_app",
        "ai-agent": "ai_agent",
        "startup-idea": "startup",
    }

    key = aliases.get(key, key)

    return PHASE_RECOMMENDATIONS.get(key, DEFAULT_PHASES.copy())


def get_platform_checklist(idea_type):
    """
    Return target platforms appropriate for the idea type.
    """
    if not idea_type:
        return []

    key = str(idea_type).strip().lower()

    aliases = {
        "chrome-extension": "chrome_extension",
        "mobile-app": "mobile_app",
        "web-app": "web_app",
        "ai-agent": "ai_agent",
    }

    key = aliases.get(key, key)

    return PLATFORM_CHECKLISTS.get(
        key,
        PLATFORM_CHECKLISTS.get("startup", []),
    ).copy()


def get_phase(phase_number):
    """Return metadata for one phase."""
    try:
        phase_number = int(phase_number)
    except (TypeError, ValueError):
        return None

    return PHASES.get(phase_number)


DEFAULT_PHASE_AGENTS = {
    1: {"type": "code", "name": "Code Builder & Executor"},
    2: {"type": "competitor_intel", "name": "Market & Competitor Intel Specialist"},
    3: {"type": "campaign", "name": "Marketing Campaign & Distribution Agent"},
    4: {"type": "deployment_prep", "name": "Deployment & Launch Operations Specialist"},
}


def get_agent_for_phase(phase_number: int, goal_dict: dict = None) -> dict:
    """
    Return the primary specialist agent assigned to execute a given phase.
    Supports dynamic overriding from goal['recommended_agents'].
    """
    try:
        phase_number = int(phase_number)
    except (TypeError, ValueError):
        phase_number = 1

    goal_dict = goal_dict or {}

    rec_agents = goal_dict.get("recommended_agents", [])
    if isinstance(rec_agents, list) and len(rec_agents) >= phase_number:
        agent_type = str(rec_agents[phase_number - 1]).lower()
        agent_names = {
            "code": "Code Builder & Executor",
            "research": "Market Research Agent",
            "competitor_intel": "Market & Competitor Intel Specialist",
            "campaign": "Marketing Campaign Specialist",
            "pricing": "Pricing Strategy Agent",
            "business_plan": "Business Model Specialist",
            "deployment_prep": "Deployment & Launch Specialist",
            "document": "Documentation Specialist",
            "automation": "Workflow Automation Agent",
        }
        return {
            "type": agent_type,
            "name": agent_names.get(agent_type, f"{agent_type.capitalize()} Specialist")
        }

    return DEFAULT_PHASE_AGENTS.get(
        phase_number,
        {"type": "code", "name": "Code Builder & Executor"}
    ).copy()


__all__ = [
    "PHASES",
    "get_phase",
    "get_recommended_phases",
    "get_platform_checklist",
    "get_agent_for_phase",
]
