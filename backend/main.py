"""
Tetris Backend — main.py
========================

Authoritative entry point for the idea-engine backend.

Strategy
--------
The recovered backend (main_working.py) registers 29 routes, but the
/intake and /intake/reply handlers crash at runtime: the decompiled
bytecode lost Pydantic type annotations, so FastAPI treats `input` as a
raw query string, and `input.idea` raises AttributeError.

Fix: import the recovered `app`, REMOVE the broken route objects from
     app.routes, then ADD new correct routes directly to the same app.
     FastAPI rebuilds its dispatch table from app.routes, so this works.

The recovered backend is NOT modified.

Running
-------
From e:\\tetris.io\\idea-engine\\backend (use INSTEAD of main_working):

  .venv-rebuild\\Scripts\\uvicorn.exe main:app --host 127.0.0.1 --port 8000

Stop the existing recovered-source server first, then run this.
"""

import os
import sys

# ── Ensure recovered agents are importable ────────────────────────────────────
_RECOVERED = os.environ.get('RECOVERED_SOURCE', 'E:/tetris-recovery/recovered-source')
if _RECOVERED not in sys.path:
    sys.path.insert(0, _RECOVERED)

# ── Import the recovered app (registers 29 routes + CORS) ────────────────────
from main_working import app  # noqa: E402

# ── M3.5-A: Ensure all DB tables (incl. stored_credentials) exist ─────────────
import sys as _sys
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)
from database.models import init_db as _init_db
_init_db()
print('[main.py] init_db() called — stored_credentials table guaranteed.')

# ── Fix CORS for the Vite frontend on port 5173 ───────────────────────────────
# The recovered backend only allows localhost:3000.
# Starlette's Middleware namedtuple: Middleware(cls, **kwargs)
# We replace the existing CORS entry in user_middleware before uvicorn
# builds the ASGI middleware stack at startup.
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

_new_cors = Middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:3000',
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'http://localhost:5174',
    ],
    allow_methods=['*'],
    allow_headers=['*'],
    allow_credentials=False,
)

# Replace any existing CORS middleware entries
app.user_middleware = [
    m if not (hasattr(m, 'cls') and m.cls is CORSMiddleware) else _new_cors
    for m in app.user_middleware
]

# If there was no CORS middleware at all, add it
if not any(getattr(m, 'cls', None) is CORSMiddleware for m in app.user_middleware):
    app.user_middleware.insert(0, _new_cors)

# Force the middleware stack to be rebuilt (it's None before first request)
app.middleware_stack = None
print('[main.py] CORS reconfigured — allows localhost:5173')

# ── Pydantic models for fixed routes ──────────────────────────────────────────
import json
from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class IntakeRequest(BaseModel):
    idea: str
    conversation_history: List[Dict[str, Any]] = []
    user_id: str = 'user_001'


class IntakeReplyRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    goal: Dict[str, Any] = {}
    user_id: str = 'user_001'


class ExecuteRequest(BaseModel):
    confirmed: bool = True
    confirmed_goal: Dict[str, Any] = {}
    user_id: str = 'user_001'
    webhook_url: Optional[str] = None
    phase: int = 1
    review_mode: str = 'auto'


class ExecuteAgentRequest(BaseModel):
    confirmed_goal: Dict[str, Any] = {}
    phase: int = 1
    agent_type: str = 'code'
    context: str = ''
    user_id: str = 'user_001'
    execution_id: Optional[str] = None
    feedback: Optional[str] = None


class ApproveRequest(BaseModel):
    execution_id: str
    approved: bool = True
    feedback: str = ''
    phase: Optional[int] = None
    user_id: str = 'user_001'


class NextPhaseRequest(BaseModel):
    confirmed_goal: Dict[str, Any] = {}
    user_id: str = 'user_001'
    phase: int = 1
    review_mode: str = 'auto'


class ExecuteDistributionActionRequest(BaseModel):
    action: Dict[str, Any]
    user_id: str = 'user_001'
    approved: bool = True


# ── Fixed route handlers ──────────────────────────────────────────────────────

async def _intake_fixed(body: IntakeRequest):
    """
    POST /intake — accepts JSON body.
    """
    from agents.intake_agent import run_intake, generate_smart_reply

    goal = run_intake(
        user_idea=body.idea,
        conversation_history=body.conversation_history,
    )

    reply_result = generate_smart_reply(
        user_message=body.idea,
        conversation_history=body.conversation_history,
        goal=goal,
    )

    return {
        **goal,
        'stage': 'needs_confirmation',
        'reply': reply_result.get('reply', ''),
        'ready': reply_result.get('ready', False),
    }


async def _intake_reply_fixed(body: IntakeReplyRequest):
    """
    POST /intake/reply — accepts JSON body.
    """
    from agents.intake_agent import generate_smart_reply

    return generate_smart_reply(
        user_message=body.message,
        conversation_history=body.history,
        goal=body.goal,
    )


async def _execute_fixed(body: ExecuteRequest):
    """
    POST /execute — initializes an execution workflow in SQLite executa.db.
    """
    from database.models import SessionLocal
    from database.operations import create_execution, get_execution_by_id
    from orchestrator.phase_map import get_agent_for_phase
    import uuid

    goal = dict(body.confirmed_goal or {})
    execution_id = goal.get("execution_id")

    rec_phases = goal.get("recommended_phases", [1, 2, 3, 4])
    phase_names = goal.get("phase_names", ["Build", "Validate", "Market", "Launch"])

    db = SessionLocal()
    try:
        ex = None
        if execution_id:
            ex = get_execution_by_id(db, execution_id)

        if not ex:
            ex = create_execution(
                db=db,
                user_id=body.user_id,
                original_idea=goal.get("understood_goal", ""),
                understood_goal=goal.get("understood_goal", ""),
                intent_classification=goal.get("intent_classification", "full_product"),
                idea_type=goal.get("idea_type", "saas"),
                recommended_phases=rec_phases,
                phase_names=phase_names,
            )
            execution_id = ex.id

        phase_statuses = ex.phase_statuses or {}
        if not phase_statuses:
            phase_statuses = {str(ph): ("READY" if idx == 0 else "LOCKED") for idx, ph in enumerate(rec_phases)}

        workflow = []
        for idx, ph_id in enumerate(rec_phases):
            name = phase_names[idx] if idx < len(phase_names) else f"Phase {ph_id}"
            agent_info = get_agent_for_phase(ph_id, goal)
            workflow.append({
                "id": ph_id,
                "name": name,
                "status": phase_statuses.get(str(ph_id), "READY" if idx == 0 else "LOCKED"),
                "agent": agent_info,
            })
    finally:
        db.close()

    goal["execution_id"] = execution_id

    return {
        "stage": "ready",
        "execution_id": execution_id,
        "workflow": workflow,
        "goal": goal,
        "recommended_phases": rec_phases
    }


async def _execute_agent_fixed(body: ExecuteAgentRequest):
    """
    POST /execute/agent — executes phase-specific agent, runs verification, and evaluates reviewer.
    """
    import uuid
    from fastapi import HTTPException
    from database.models import SessionLocal
    from database.operations import get_execution_by_id, save_phase_result, update_execution_status
    from orchestrator.phase_map import get_agent_for_phase
    from orchestrator.router import route_to_specialist
    from execution.runner import run_controlled_verification
    from agents.reviewer_agent import run_reviewer
    from simulation.engine import run_simulation

    goal_dict = dict(body.confirmed_goal or {})
    execution_id = body.execution_id or goal_dict.get("execution_id") or str(uuid.uuid4())
    goal_dict["execution_id"] = execution_id

    phase_num = int(body.phase or 1)

    db = SessionLocal()
    try:
        ex = get_execution_by_id(db, execution_id)
        if not ex:
            from database.operations import create_execution
            ex = create_execution(
                db=db,
                user_id=body.user_id,
                original_idea=goal_dict.get("understood_goal", "") or goal_dict.get("original_idea", "New Project"),
                understood_goal=goal_dict.get("understood_goal", "") or goal_dict.get("original_idea", "New Project"),
                intent_classification=goal_dict.get("intent_classification", "full_product"),
                idea_type=goal_dict.get("idea_type", "saas"),
                recommended_phases=goal_dict.get("recommended_phases", [1, 2, 3, 4]),
            )
        else:
            if not goal_dict.get("understood_goal"):
                goal_dict["understood_goal"] = ex.understood_goal or ex.original_idea
            if not goal_dict.get("idea_type"):
                goal_dict["idea_type"] = ex.idea_type or "saas"
            if not goal_dict.get("recommended_phases"):
                goal_dict["recommended_phases"] = ex.recommended_phases or [1, 2, 3, 4]

        phase_statuses = dict(ex.phase_statuses or {})
        current_status = phase_statuses.get(str(phase_num), "READY" if phase_num == 1 else "LOCKED")

        if current_status == "LOCKED":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot execute Phase {phase_num}: Phase is LOCKED. Previous phase must be approved first."
            )

        phase_statuses[str(phase_num)] = "RUNNING"
        update_execution_status(db, execution_id, "running", current_phase=phase_num, phase_statuses=phase_statuses)
    finally:
        db.close()

    assigned_agent = get_agent_for_phase(phase_num, goal_dict)
    agent_type = body.agent_type if body.agent_type and body.agent_type != "code" else assigned_agent["type"]

    goal_text = goal_dict.get("understood_goal", "")
    criteria = goal_dict.get("acceptance_criteria", [])

    workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")
    os.makedirs(workspace_path, exist_ok=True)

    # Pass workspace_path, execution_id, and feedback so specialist agents write files to the correct location and handle revisions
    goal_dict["_workspace_path"] = workspace_path
    goal_dict["_execution_id"] = execution_id
    goal_dict["_feedback"] = body.feedback

    # Context continuity: if context is empty and phase > 1, fetch prior phase outputs from database
    execution_context = body.context or ""
    if (not execution_context or not execution_context.strip()) and phase_num > 1:
        db_ctx = SessionLocal()
        try:
            prev_results = get_phase_results(db_ctx, execution_id)
            prev_texts = [
                f"--- Phase {pr.phase_number} ({pr.outcome_type}) Output ---\n{pr.outcome}"
                for pr in prev_results if pr.phase_number < phase_num and pr.outcome
            ]
            if prev_texts:
                execution_context = "\n\n".join(prev_texts)
        finally:
            db_ctx.close()

    try:
        agent_output = route_to_specialist(
            outcome_type=agent_type,
            confirmed_goal=goal_dict,
            context=execution_context,
            phase=phase_num,
        )
    except Exception as exc:
        agent_output = {"error": str(exc), "success": False}

    files_written = []
    manifest = {}
    if isinstance(agent_output, dict):
        files_written = agent_output.get("files_written", [])
        manifest = agent_output.get("manifest", {})
        outcome_markdown = agent_output.get("code_output", "")
        if not outcome_markdown:
            outcome_markdown = json.dumps(agent_output, indent=2)
            art_file = os.path.join(workspace_path, f"phase_{phase_num}_deliverable.json")
            with open(art_file, "w", encoding="utf-8") as f:
                f.write(outcome_markdown)
            files_written.append(f"phase_{phase_num}_deliverable.json")
    else:
        outcome_markdown = str(agent_output)
        art_file = os.path.join(workspace_path, f"phase_{phase_num}_deliverable.md")
        with open(art_file, "w", encoding="utf-8") as f:
            f.write(outcome_markdown)
        files_written.append(f"phase_{phase_num}_deliverable.md")

    runner_res = run_controlled_verification(workspace_path)
    sim_res = run_simulation(workspace_path=workspace_path, acceptance_criteria=criteria)

    review_res = run_reviewer(
        confirmed_goal=goal_text,
        outcome_type=agent_type,
        acceptance_criteria=criteria,
        built_output=agent_output,
        workspace_path=workspace_path,
        runner_result=runner_res,
        simulation_result=sim_res,
    )

    runner_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False
    sim_passed = (sim_res.get("simulation_status") != "FAIL") if isinstance(sim_res, dict) else True
    reviewer_passed = bool(review_res.get("passed")) if isinstance(review_res, dict) else False
    phase_passed = runner_passed and sim_passed and reviewer_passed
    phase_status = "WAITING_FOR_APPROVAL" if phase_passed else "REVISION_REQUIRED"
    exec_status = "waiting_for_approval" if phase_passed else "revision_required"
    db = SessionLocal()
    try:
        trace = [
            {"step": "agent_selected", "type": agent_type, "name": assigned_agent["name"]},
            {"step": "agent_completed", "phase": phase_num},
            {"step": "runner_completed", "passed": runner_res.get("passed"), "exit_code": runner_res.get("exit_code")},
            {"step": "simulation_completed", "status": sim_res.get("simulation_status"), "passed_checks": sim_res.get("passed_checks"), "total_checks": sim_res.get("total_checks")},
            {"step": "reviewer_completed", "score": review_res.get("score"), "passed": phase_passed},
        ]

        deploy_res = agent_output.get("deployment") if isinstance(agent_output, dict) else None
        if deploy_res:
            trace.append({
                "step": "deployment_completed",
                "provider": deploy_res.get("provider"),
                "status": deploy_res.get("deployment_status"),
                "url": deploy_res.get("url"),
                "verified": deploy_res.get("verified"),
            })

        dist_plan = agent_output.get("distribution_plan") if isinstance(agent_output, dict) else None

        save_phase_result(
            db=db,
            execution_id=execution_id,
            phase=phase_num,
            outcome_type=agent_type,
            outcome=outcome_markdown,
            score=review_res.get("score", 0.0),
            trace=trace,
            status=phase_status,
            selected_agents=[assigned_agent],
            verification_result=runner_res,
            simulation_result=sim_res,
            deployment_result=deploy_res,
            review_result=review_res,
            distribution_plan=dist_plan,
        )

        phase_statuses[str(phase_num)] = phase_status
        update_execution_status(db, execution_id, exec_status, current_phase=phase_num, phase_statuses=phase_statuses)
    finally:
        db.close()

    resp_payload = {
        "stage": exec_status,
        "execution_id": execution_id,
        "phase": phase_num,
        "status": phase_status,
        "agent": assigned_agent,
        "workspace_path": workspace_path,
        "manifest": manifest,
        "files_written": files_written,
        "outcome": outcome_markdown,
        "runner_result": runner_res,
        "simulation_result": sim_res,
        "validation": review_res,
    }
    if deploy_res:
        resp_payload["deployment_result"] = deploy_res
        resp_payload["deployment_status"] = deploy_res.get("deployment_status")
        resp_payload["url"] = deploy_res.get("url")
    if dist_plan:
        resp_payload["distribution_plan"] = dist_plan
        resp_payload["distribution_actions"] = dist_plan.get("actions", [])
    return resp_payload


async def _approve_fixed(body: ApproveRequest):
    """
    POST /approve — approves current phase and unlocks next phase in SQLite executa.db.
    """
    from fastapi import HTTPException
    from database.models import SessionLocal, PhaseResult
    from database.operations import get_execution_by_id, update_execution_status

    db = SessionLocal()
    try:
        ex = get_execution_by_id(db, body.execution_id)
        if not ex:
            raise HTTPException(status_code=404, detail="Execution ID not found in database.")

        rec_phases = ex.recommended_phases or [1, 2, 3, 4]
        current_phase = body.phase if body.phase is not None else (ex.current_phase or 1)
        phase_statuses = dict(ex.phase_statuses or {})

        current_status = phase_statuses.get(str(current_phase), "READY")
        if body.approved and current_status not in ("WAITING_FOR_APPROVAL", "COMPLETED"):
            phase_res = (
                db.query(PhaseResult)
                .filter(PhaseResult.execution_id == body.execution_id, PhaseResult.phase_number == current_phase)
                .order_by(PhaseResult.created_at.desc())
                .first()
            )
            if not phase_res or not phase_res.validation_score:
                raise HTTPException(status_code=400, detail=f"Phase {current_phase} cannot be approved before execution completes.")

        if body.approved:
            phase_statuses[str(current_phase)] = "APPROVED"

            phase_res = (
                db.query(PhaseResult)
                .filter(PhaseResult.execution_id == body.execution_id, PhaseResult.phase_number == current_phase)
                .order_by(PhaseResult.created_at.desc())
                .first()
            )
            if phase_res:
                phase_res.status = "APPROVED"

            next_phase = current_phase + 1
            if next_phase <= max(rec_phases):
                phase_statuses[str(next_phase)] = "READY"
                update_execution_status(db, body.execution_id, "running", current_phase=next_phase, phase_statuses=phase_statuses)
                message = f"Phase {current_phase} approved. Phase {next_phase} is now UNLOCKED & READY."
                stage = "phase_approved"
            else:
                update_execution_status(db, body.execution_id, "completed", current_phase=current_phase, phase_statuses=phase_statuses)
                message = "All phases completed and approved!"
                stage = "complete"

            db.commit()

            return {
                "stage": stage,
                "execution_id": body.execution_id,
                "approved_phase": current_phase,
                "next_phase": next_phase if next_phase <= max(rec_phases) else None,
                "status": "APPROVED",
                "phase_statuses": phase_statuses,
                "message": message,
            }
        else:
            phase_statuses[str(current_phase)] = "REVISION_REQUIRED"
            update_execution_status(db, body.execution_id, "revision_required", phase_statuses=phase_statuses)

            phase_res = (
                db.query(PhaseResult)
                .filter(PhaseResult.execution_id == body.execution_id, PhaseResult.phase_number == current_phase)
                .order_by(PhaseResult.created_at.desc())
                .first()
            )
            if phase_res:
                phase_res.status = "REVISION_REQUIRED"
                trace = list(phase_res.execution_trace or [])
                trace.append({"step": "user_revision_requested", "feedback": body.feedback})
                phase_res.execution_trace = trace
                db.commit()

            return {
                "stage": "revision_needed",
                "execution_id": body.execution_id,
                "status": "REVISION_REQUIRED",
                "feedback": body.feedback,
                "message": "Revision feedback saved in SQLite database.",
            }
    finally:
        db.close()


async def _next_phase_fixed(body: NextPhaseRequest):
    """
    POST /next-phase — advances to the next phase after verifying approval in SQLite executa.db.
    """
    from fastapi import HTTPException
    from database.models import SessionLocal
    from database.operations import get_execution_by_id

    goal = dict(body.confirmed_goal or {})
    execution_id = goal.get("execution_id")

    if execution_id:
        db = SessionLocal()
        try:
            ex = get_execution_by_id(db, execution_id)
            if ex:
                phase_statuses = ex.phase_statuses or {}
                prev_phase = body.phase - 1
                if prev_phase >= 1 and phase_statuses.get(str(prev_phase)) != "APPROVED":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot transition to Phase {body.phase}: Phase {prev_phase} is not APPROVED."
                    )
        finally:
            db.close()

    from orchestrator.engine import execute_idea

    return execute_idea(
        user_idea="",
        user_confirmed=True,
        confirmed_goal=body.confirmed_goal,
        user_id=body.user_id,
        phase=body.phase,
        review_mode=body.review_mode if isinstance(body.review_mode, bool) else (body.review_mode.lower() in ("true", "auto", "1") if isinstance(body.review_mode, str) else True),
    )


async def _get_execution_status_fixed(execution_id: str, user_id: str = "user_001"):
    """
    GET /executions/{user_id}/{execution_id}/status — authoritative state of execution & phases from SQLite executa.db.
    """
    from fastapi import HTTPException
    from database.models import SessionLocal
    from database.operations import get_execution_by_id, get_phase_results
    from orchestrator.phase_map import get_agent_for_phase

    projects_dir_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects")

    db = SessionLocal()
    try:
        ex = get_execution_by_id(db, execution_id)
        if not ex:
            # Check if project folder exists on disk (e.g. PRJ-1 or recovered project)
            disk_dir = os.path.join(projects_dir_local, execution_id)
            if os.path.exists(disk_dir):
                from database.operations import create_execution
                ex = create_execution(
                    db=db,
                    user_id=user_id,
                    original_idea=f"Workspace Project ({execution_id})",
                    understood_goal=f"Workspace Project ({execution_id})",
                    intent_classification="full_product",
                    idea_type="saas",
                    recommended_phases=[1, 2, 3, 4],
                )
            else:
                raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found.")

        rec_phases = ex.recommended_phases or [1, 2, 3, 4]
        phase_statuses = dict(ex.phase_statuses or {})
        goal_dict = {
            "understood_goal": ex.understood_goal,
            "idea_type": ex.idea_type,
            "intent_classification": ex.intent_classification,
            "recommended_phases": rec_phases,
        }

        phase_results = get_phase_results(db, execution_id)
        phase_outputs = {}
        for pr in phase_results:
            phase_outputs[pr.phase_number] = {
                "outcome_type": pr.outcome_type,
                "outcome": pr.outcome,
                "validation_score": pr.validation_score,
                "status": pr.status,
                "verification_result": pr.verification_result,
                "simulation_result": getattr(pr, "simulation_result", None),
                "deployment_result": getattr(pr, "deployment_result", None),
                "distribution_plan": getattr(pr, "distribution_plan", None),
                "review_result": pr.review_result,
            }

        workflow = []
        phase_names = ["Build", "Validate", "Market", "Launch"]
        for idx, ph_id in enumerate(rec_phases):
            name = phase_names[idx] if idx < len(phase_names) else f"Phase {ph_id}"
            agent_info = get_agent_for_phase(ph_id, goal_dict)
            st = phase_statuses.get(str(ph_id), "READY" if idx == 0 else "LOCKED")

            # Scan actual files on disk for this phase to ensure 100% accurate file listing
            disk_phase_dir = os.path.join(projects_dir_local, execution_id, f"phase_{ph_id}")
            files_on_disk = []
            if os.path.exists(disk_phase_dir):
                files_on_disk = [
                    f for f in os.listdir(disk_phase_dir)
                    if os.path.isfile(os.path.join(disk_phase_dir, f))
                ]

            has_portal = ("index.html" in files_on_disk)
            portal_url = f"http://localhost:8000/projects/{execution_id}/phase_{ph_id}/index.html" if has_portal else None

            ph_out = phase_outputs.get(ph_id) or {}
            ph_out["files_written"] = files_on_disk
            ph_out["has_web_portal"] = has_portal
            ph_out["web_portal_url"] = portal_url
            phase_outputs[ph_id] = ph_out

            workflow.append({
                "id": ph_id,
                "name": name,
                "status": st,
                "agent": agent_info,
                "output": ph_out,
                "files_written": files_on_disk,
                "has_web_portal": has_portal,
                "web_portal_url": portal_url,
            })

        # Top-level portal check (Phase 1 index.html)
        p1_index = os.path.join(projects_dir_local, execution_id, "phase_1", "index.html")
        has_web_portal = os.path.exists(p1_index)
        web_portal_url = f"http://localhost:8000/projects/{execution_id}/phase_1/index.html" if has_web_portal else None

        # Top-level portal check (Phase 1 index.html)
        p1_index = os.path.join(projects_dir_local, execution_id, "phase_1", "index.html")
        has_web_portal = os.path.exists(p1_index)
        web_portal_url = f"http://localhost:8000/projects/{execution_id}/phase_1/index.html" if has_web_portal else None

        # Fetch executed connector/distribution actions
        from database.operations import get_connector_actions, get_distribution_campaign_by_execution
        conn_acts = get_connector_actions(db, execution_id)
        connector_actions_list = [
            {
                "id": ca.id,
                "connector_id": ca.connector_id,
                "action": ca.action,
                "status": ca.status,
                "result": ca.result,
                "error": ca.error,
                "executed_at": ca.executed_at.isoformat() if ca.executed_at else None,
            }
            for ca in conn_acts
        ]

        # Fetch canonical distribution campaign if one exists for this execution
        camp = get_distribution_campaign_by_execution(db, execution_id)
        distribution_campaign_data = None
        if camp:
            try:
                from orchestration.distribution_orchestrator import get_canonical_campaign
                distribution_campaign_data = get_canonical_campaign(db, camp.id)
            except Exception:
                distribution_campaign_data = {
                    "campaign_id": camp.id,
                    "status": camp.status,
                    "summary": camp.summary or {},
                    "connector_requirements": camp.connector_requirements or [],
                }

        return {
            "execution_id": execution_id,
            "status": ex.status,
            "current_phase": ex.current_phase,
            "understood_goal": ex.understood_goal,
            "recommended_phases": rec_phases,
            "workflow": workflow,
            "phase_outputs": phase_outputs,
            "connector_actions": connector_actions_list,
            "distribution_campaign": distribution_campaign_data,
            "has_web_portal": has_web_portal,
            "web_portal_url": web_portal_url,
        }
    finally:
        db.close()


async def _execute_distribution_action_fixed(body: ExecuteDistributionActionRequest):
    """
    POST /execute/distribution-action & POST /execute/action — executes an approved distribution action.
    """
    from database.models import SessionLocal
    from execution.execution_router import execute_distribution_action

    action_dict = dict(body.action or {})
    if body.approved:
        if "approval" not in action_dict or not isinstance(action_dict["approval"], dict):
            action_dict["approval"] = {}
        action_dict["approval"]["status"] = "APPROVED"

    db = SessionLocal()
    try:
        return execute_distribution_action(action=action_dict, user_id=body.user_id, db=db)
    finally:
        db.close()


async def _list_projects_fixed(user_id: str = "user_001"):
    """
    GET /api/projects & GET /executions/{user_id} — returns all projects in SQLite executa.db.
    """
    from database.models import SessionLocal, Execution
    projects_dir_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects")

    db = SessionLocal()
    try:
        executions = db.query(Execution).order_by(Execution.created_at.desc()).all()
        projects = []
        for ex in executions:
            p1_index = os.path.join(projects_dir_local, ex.id, "phase_1", "index.html")
            has_portal = os.path.exists(p1_index)

            raw_title = ex.understood_goal or ex.original_idea or "Untitled Project"
            title = raw_title.strip()
            if len(title) > 95:
                title = title[:92] + "..."

            projects.append({
                "id": ex.id,
                "title": title,
                "original_idea": ex.original_idea,
                "understood_goal": ex.understood_goal,
                "status": ex.status,
                "current_phase": ex.current_phase or 1,
                "phase_statuses": ex.phase_statuses or {"1": "READY"},
                "has_web_portal": has_portal,
                "web_portal_url": f"http://localhost:8000/projects/{ex.id}/phase_1/index.html" if has_portal else None,
                "created_at": ex.created_at.isoformat() if ex.created_at else None,
            })
        return {"projects": projects}
    finally:
        db.close()


async def _get_simulation_result_fixed(execution_id: str):
    """
    GET /simulation/{execution_id} — retrieves pre-launch simulation results for a project.
    """
    from fastapi import HTTPException
    from database.models import SessionLocal
    from database.operations import get_phase_results, get_execution_by_id

    db = SessionLocal()
    try:
        ex = get_execution_by_id(db, execution_id)
        if not ex:
            raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found.")

        phase_results = get_phase_results(db, execution_id)
        sim_res = None
        for pr in phase_results:
            if getattr(pr, "simulation_result", None):
                sim_res = pr.simulation_result
                break

        if not sim_res:
            workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, "phase_1")
            if os.path.exists(workspace_path):
                from simulation.engine import run_simulation
                sim_res = run_simulation(workspace_path)
            else:
                return {
                    "execution_id": execution_id,
                    "simulation_status": "NOT_TESTED",
                    "message": "No generated workspace found for simulation",
                    "checks": [],
                    "acceptance_criteria": [],
                    "issues": [],
                }

        return {
            "execution_id": execution_id,
            **sim_res
        }
    finally:
        db.close()


# ── Remove broken routes and add fixed ones ────────────────────────────────────

from fastapi.routing import APIRoute

# M3.5-A: Remove broken decompiled credential handlers from recovered app.
# The correct handlers are registered below via the credentials router.
_BROKEN_CREDENTIAL_PATHS = {
    '/credentials/connect',
    '/credentials/{user_id}',
    '/credentials/{user_id}/{app_name}',
    '/connect-app',
    '/connected-apps/{user_id}',
}
for _cp in list(app.router.routes):
    if isinstance(_cp, APIRoute) and _cp.path in _BROKEN_CREDENTIAL_PATHS:
        app.router.routes.remove(_cp)
print('[main.py] Removed broken decompiled credential routes.')

# M3.5-A: Mount authoritative credential routes
from routes.credentials import router as _credentials_router
app.include_router(_credentials_router)
print('[main.py] Mounted M3.5-A credential router at /credentials')

# M3.5-B: Mount authoritative distribution orchestrator routes
from routes.distribution import router as _distribution_router
app.include_router(_distribution_router)
print('[main.py] Mounted M3.5-B distribution router at /distribution')

# Stage 7B: Mount additive Workforce API router at /api/workforce
from routes.workforce import router as _workforce_router
app.include_router(_workforce_router)
print('[main.py] Mounted Stage 7B Workforce router at /api/workforce')

# Stage 7B: Mount dedicated Health router at /health
from routes.health import router as _health_router
app.include_router(_health_router)
print('[main.py] Mounted Stage 7B Health router at /health')

_PATHS_TO_FIX = {'/intake', '/intake/reply', '/execute', '/execute/agent', '/approve', '/next-phase', '/execute/distribution-action', '/execute/action'}
_FIXED_HANDLERS = {
    '/intake':                      _intake_fixed,
    '/intake/reply':                _intake_reply_fixed,
    '/execute':                     _execute_fixed,
    '/execute/agent':               _execute_agent_fixed,
    '/approve':                     _approve_fixed,
    '/next-phase':                  _next_phase_fixed,
    '/execute/distribution-action': _execute_distribution_action_fixed,
    '/execute/action':              _execute_distribution_action_fixed,
}

router_routes = app.router.routes

original_count = len(router_routes)
for broken_path in _PATHS_TO_FIX:
    to_remove = [
        r for r in router_routes
        if isinstance(r, APIRoute) and r.path == broken_path
    ]
    for r in to_remove:
        router_routes.remove(r)

removed = original_count - len(router_routes)
print(f'[main.py] Removed {removed} broken route(s)')

for path, handler in _FIXED_HANDLERS.items():
    new_route = APIRoute(
        path=path,
        endpoint=handler,
        methods={'POST'},
        response_model=None,
    )
    router_routes.append(new_route)
    print(f'[main.py] Added fixed route: POST {path}')

# Add GET status and project listing endpoints
status_route = APIRoute(
    path='/executions/{user_id}/{execution_id}/status',
    endpoint=_get_execution_status_fixed,
    methods={'GET'},
    response_model=None,
)
router_routes.append(status_route)

simulation_route = APIRoute(
    path='/simulation/{execution_id}',
    endpoint=_get_simulation_result_fixed,
    methods={'GET'},
    response_model=None,
)
router_routes.append(simulation_route)

projects_route = APIRoute(
    path='/api/projects',
    endpoint=_list_projects_fixed,
    methods={'GET'},
    response_model=None,
)
router_routes.append(projects_route)

user_executions_route = APIRoute(
    path='/executions/{user_id}',
    endpoint=_list_projects_fixed,
    methods={'GET'},
    response_model=None,
)
router_routes.append(user_executions_route)

print('[main.py] Added status & projects routes: GET /executions/{user_id}/{execution_id}/status, GET /api/projects, GET /executions/{user_id}')

# Mount static file route for generated project artifacts (HTML/CSS/JS preview)
from starlette.staticfiles import StaticFiles
projects_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects")
os.makedirs(projects_dir, exist_ok=True)
app.mount("/projects", StaticFiles(directory=projects_dir, html=True), name="generated_projects")
print(f'[main.py] Mounted static generated_projects from {projects_dir} at /projects')

print('[main.py] Backend ready. Intake, Execution, Status & Project routes active.')