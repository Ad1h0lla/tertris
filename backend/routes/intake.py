"""
Intake routes — wraps the recovered intake_agent.py functions
with proper FastAPI JSON body endpoints.

These routes replace the recovered backend's broken ?input= query param
approach with standard JSON body endpoints that the frontend can call normally.

HOW: The recovered backend is running at port 8000 with broken routes.
     These routes are registered to the same app instance and use the
     correct Pydantic Body() pattern.

NOTE: The recovered main_working.py routes are SHADOWED by these handlers
     because FastAPI registers routes in order and raises an error on exact
     path duplicates — BUT if we mount these as a router that gets included
     BEFORE the recovered routes load, they take priority.

For V1 stabilization, we write a thin proxy that the frontend calls.
The correct approach is to run this as the authoritative backend.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import sys
import os

# Make sure the recovered agents are importable
_RECOVERED = os.environ.get('RECOVERED_SOURCE', 'E:/tetris-recovery/recovered-source')
if _RECOVERED not in sys.path:
    sys.path.insert(0, _RECOVERED)

router = APIRouter()


# ─── Request models ───────────────────────────────────────────────────────────

class IntakeRequest(BaseModel):
    idea: str
    conversation_history: List[Dict[str, Any]] = []
    user_id: str = 'user_001'


class IntakeReplyRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    goal: Dict[str, Any] = {}
    user_id: str = 'user_001'


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post('/intake')
async def intake(body: IntakeRequest):
    """
    First message in a Jam Session.

    Returns the raw goal dict (flat, not nested under 'goal')
    plus stage and reply fields for the frontend.
    """
    from agents.intake_agent import run_intake, generate_smart_reply

    goal = run_intake(
        user_idea=body.idea,
        conversation_history=body.conversation_history
    )

    # Generate the first reply so the frontend doesn't have to call /intake/reply
    # separately on the first turn.
    reply_result = generate_smart_reply(
        user_message=body.idea,
        conversation_history=body.conversation_history,
        goal=goal
    )

    return {
        # Flat goal fields (all accessible at top level)
        **goal,
        # Stage and reply for the frontend's jam session
        'stage': 'needs_confirmation',
        'reply': reply_result.get('reply', ''),
        'ready': reply_result.get('ready', False),
    }


@router.post('/intake/reply')
async def intake_reply(body: IntakeReplyRequest):
    """
    All subsequent Jam Session messages after the first.

    Returns: { reply: str, ready: bool }
    """
    from agents.intake_agent import generate_smart_reply

    result = generate_smart_reply(
        user_message=body.message,
        conversation_history=body.history,
        goal=body.goal
    )

    return result
