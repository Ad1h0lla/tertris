import os
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


INTAKE_PROMPT = """
You are the Tetris Intake Brain.

Your job is to understand what the user is trying to build.

Analyze the user's idea and conversation history.

Return ONLY valid JSON with this structure:

{
    "understood_goal": "...",
    "outcome_type": "code",
    "intent_classification": "full_product",
    "idea_type": "saas",
    "recommended_phases": [1, 2, 3, 4],
    "phase_names": ["Build", "Validate", "Market", "Launch"],
    "recommended_agents": ["code", "research", "campaign", "business_plan"],
    "suggested_apps": [],
    "assumptions": [],
    "clarifying_questions": [],
    "acceptance_criteria": [
        "Delivers a complete working outcome"
    ],
    "visual_summary": {
        "type": "flowchart",
        "title": "...",
        "nodes": [],
        "edges": []
    }
}

Important:

- Understand the entire conversation, not only the latest message.
- Identify what the user is actually trying to accomplish.
- Recommend phases based on the project.
- Recommend agents based on the actual work required.
- Recommend integrations/apps where useful.
- Identify assumptions and missing information.
- Generate useful clarifying questions.
- Focus on a working outcome.
- Do not invent requirements that the user did not imply.
"""


def _safe_default(idea: str) -> dict:
    """
    Safe fallback used if the LLM cannot produce valid JSON.
    """

    idea = idea or ""

    return {
        "understood_goal": idea[:200],
        "outcome_type": "code",
        "intent_classification": "full_product",
        "idea_type": "saas",
        "recommended_phases": [1, 2, 3, 4],
        "phase_names": [
            "Build",
            "Validate",
            "Market",
            "Launch"
        ],
        "recommended_agents": [
            "code",
            "research",
            "campaign",
            "business_plan"
        ],
        "suggested_apps": [],
        "assumptions": [],
        "clarifying_questions": [],
        "acceptance_criteria": [
            "Delivers a complete working outcome"
        ],
        "visual_summary": {
            "type": "flowchart",
            "title": idea[:40] or "Your Idea",
            "nodes": [
                {
                    "id": "1",
                    "label": "User",
                    "actor": "user"
                },
                {
                    "id": "2",
                    "label": idea[:28] or "Build",
                    "process": True
                },
                {
                    "id": "3",
                    "label": "Output",
                    "output": True
                }
            ],
            "edges": [
                {
                    "from": "1",
                    "to": "2",
                    "label": "uses"
                },
                {
                    "from": "2",
                    "to": "3",
                    "label": "produces"
                }
            ],
            "description": (
                f"How {idea[:100]} works"
                if idea
                else "How your idea works"
            )
        },
        "confidence": 0.7
    }


def _default_visual_summary(result: dict) -> dict:
    """
    Creates a basic visual flowchart when the LLM
    does not provide one.
    """

    goal_text = result.get(
        "understood_goal",
        "Your Idea"
    )

    idea_type = result.get(
        "idea_type",
        "product"
    )

    return {
        "type": "flowchart",
        "title": goal_text[:50] or "Your Idea",
        "nodes": [
            {
                "id": "1",
                "label": "User",
                "actor": "user"
            },
            {
                "id": "2",
                "label": goal_text[:28] or "Build",
                "process": True
            },
            {
                "id": "3",
                "label": "Output",
                "output": True
            }
        ],
        "edges": [
            {
                "from": "1",
                "to": "2",
                "label": "uses"
            },
            {
                "from": "2",
                "to": "3",
                "label": "produces"
            }
        ],
        "description": (
            f"How {idea_type} works"
        )
    }


def run_intake(
    user_idea: str,
    conversation_history: list
) -> dict:
    """
    Runs the intake brain using the best available LLM.

    Returns structured goal + visual_summary for
    SVG flowchart rendering.

    conversation_history:
        list of {
            "role": "user" | "agent",
            "content": str
        }
    """

    from llm.router import get_llm_response

    history = conversation_history or []

    history_text = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Agent'}: "
        f"{m.get('content', '')}"
        for m in history
    )

    if not history_text:
        history_text = "(no prior messages)"

    user_message = (
        "Previous conversation:\n"
        f"{history_text}"
        "\n\nLatest input: "
        f"{user_idea}"
        "\n\nAnalyze everything the user has said "
        "and return the JSON specification."
    )

    try:
        raw = get_llm_response(
            task="intake",
            system_prompt=INTAKE_PROMPT,
            user_message=user_message,
            max_tokens=2000,
            temperature=0.2
        )

        clean = (raw or "").strip()

        if clean.startswith("```json"):
            clean = clean.replace("```json", "", 1)

        if clean.endswith("```"):
            clean = clean[:-3]

        clean = clean.strip()

        result = json.loads(clean)

        if not isinstance(result, dict):
            return _safe_default(user_idea)

        result.setdefault(
            "recommended_phases",
            [1, 2, 3, 4]
        )

        result.setdefault(
            "phase_names",
            ["Build", "Validate", "Market", "Launch"]
        )

        result.setdefault(
            "recommended_agents",
            ["code", "research", "campaign", "business_plan"]
        )

        result.setdefault(
            "suggested_apps",
            []
        )

        result.setdefault(
            "assumptions",
            []
        )

        result.setdefault(
            "clarifying_questions",
            []
        )

        result.setdefault(
            "acceptance_criteria",
            ["Delivers a complete working outcome"]
        )

        if not result.get("visual_summary"):
            result["visual_summary"] = _default_visual_summary(
                result
            )

        return result

    except json.JSONDecodeError:
        return _safe_default(user_idea)

    except Exception as e:
        print(
            f"[Intake Agent] Failed: "
            f"{type(e).__name__}: {str(e)[:200]}"
        )
        return _safe_default(user_idea)


def generate_smart_reply(
    user_message: str,
    conversation_history: list,
    goal: dict
) -> dict:
    """
    Generates a smart context-aware reply for the Jam Session.

    Returns:

        {
            "reply": str,
            "ready": bool
        }

    ready=True signals the frontend to show the
    understood card + visual summary.
    """

    from llm.router import get_llm_response

    history = conversation_history or []

    history_text = " ".join(
        str(m.get("content", ""))
        for m in history
    )

    goal = goal or {}

    missing = []

    combined = (
        f"{history_text} {user_message}"
    ).lower()

    target_words = [
        "owner",
        "user",
        "customer",
        "person",
        "people",
        "who",
        "restaurant",
        "business",
        "founder",
        "team",
        "company",
        "client",
        "employee",
        "manager",
        "developer",
        "student"
    ]

    business_words = [
        "pay",
        "revenue",
        "money",
        "price",
        "charge",
        "subscription",
        "free",
        "paid",
        "cost",
        "profit",
        "earn",
        "income",
        "monetize"
    ]

    integration_words = [
        "stripe",
        "email",
        "slack",
        "api",
        "integrate",
        "connect",
        "platform",
        "database",
        "server",
        "cloud",
        "mobile",
        "web",
        "desktop"
    ]

    risk_words = [
        "problem",
        "issue",
        "risk",
        "wrong",
        "fail",
        "challenge",
        "worry",
        "concern",
        "difficult",
        "hard",
        "competitive",
        "barrier"
    ]

    if not any(word in combined for word in target_words):
        missing.append(
            "Who specifically uses this? "
            "Not a category — give me one real person "
            "with a specific pain."
        )

    if not any(word in combined for word in business_words):
        missing.append(
            "How does this make money? Even rough — "
            "subscription, one-time, commission, "
            "or free for now?"
        )

    if not any(word in combined for word in integration_words):
        missing.append(
            "What does this need to connect to? "
            "Payments, email, calendar, APIs, "
            "anything external?"
        )

    if not any(word in combined for word in risk_words):
        missing.append(
            "What's the one thing most likely "
            "to kill this idea?"
        )

    user_count = len(history)

    try:
        m = get_llm_response(
            task="intake",
            system_prompt=(
                "You are the Tetris Jam Session reasoning layer. "
                "Understand the user's project and determine "
                "the most useful next question."
            ),
            user_message=(
                f"Goal: {goal.get('understood_goal', '')}\n\n"
                f"Conversation:\n{history_text}\n\n"
                f"Latest message:\n{user_message}\n\n"
                f"Potential missing areas:\n{missing}\n\n"
                "Return a concise natural response."
            ),
            max_tokens=1000,
            temperature=0.2
        )

        reply = (m or "").strip()

    except Exception:
        reply = ""

    phases = goal.get(
        "phase_names",
        ["Build", "Validate", "Market", "Launch"]
    )

    confidence = goal.get(
        "confidence",
        0.88
    )

    if not reply:
        if missing:
            question = missing[0]

            ack = (
                f"Got it — "
                f"{user_message[:80]}."
            )

            reply = (
                f"{ack}\n\n"
                f"{question}"
            )

        else:
            reply = (
                "Got it — here's exactly what I understood:\n\n"
                f"**{goal.get('understood_goal', 'Your idea')}**\n\n"
                f"Confidence: {int(confidence * 100)}% · "
                f"Phases: {' → '.join(phases)}\n\n"
                "Review the diagram and plan below, "
                "then deploy your AI workforce."
            )

    understood = (
        bool(goal.get("understood_goal"))
        and not missing
    )

    return {
        "reply": reply,
        "ready": understood
    }