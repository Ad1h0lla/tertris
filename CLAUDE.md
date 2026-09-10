# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

This is the **Executa** idea execution engine — a full-stack app that takes raw ideas, orchestrates specialist agents through phased execution, and deploys outcomes.

```
idea-engine/
 backend/ # FastAPI server, agents, orchestrator, integrations, database
 frontend/ # Vite + React dashboard
```

Run backend commands from `idea-engine/backend/` and frontend commands from `idea-engine/frontend/`.

## Backend Commands

The backend uses a **recovered** source tree with a patch layer. `main.py` is the authoritative entry point — it imports the recovered `app` from `main_working`, removes broken routes, and adds fixed ones.

```powershell
# Start backend (from idea-engine/backend/)
.\.venv-rebuild\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000

# Run pipeline tests
.\.venv-rebuild\Scripts\python.exe test_execution_pipeline.py

# Run full audit test
.\.venv-rebuild\Scripts\python.exe test_full_execution_audit.py

# Run smoke test
.\.venv-rebuild\Scripts\python.exe smoke_test.py
```

**Important**: The recovered source at `E:/tetris-recovery/recovered-source` must be on `sys.path`. `main.py` handles this via the `RECOVERED_SOURCE` env var. Do not modify `main-recovered-raw.py` — it is the source artifact and not meant to be executed directly.

The SQLite database is `executa.db` at the backend root. It auto-migrates missing columns on startup via `init_db()` in `models.py`.

## Frontend Commands

```powershell
# Dev server (from idea-engine/frontend/)
npm run dev

# Lint
npm run lint

# Build
npm run build
```

The dev server runs on port 5173. The API client targets port 8001 (`src/api/client.js`), but the backend starts on 8000 — update `API_BASE` or the uvicorn port as needed.

## Architecture

### Execution Pipeline
The core loop: **Intake → Phase 1 (Build) → Phase 2 (Validate) → Phase 3 (Market) → Phase 4 (Launch)**. Each phase has a strict state machine: `LOCKED → READY → RUNNING → WAITING_FOR_APPROVAL → APPROVED/REVISION_REQUIRED`. Phases unlock sequentially — a phase can only execute when the previous one is approved.

- **Phase mapping**: `orchestrator/phase_map.py` defines which specialist agent runs for each phase and which intent types need which phases.
- **Specialist routing**: `orchestrator/router.py` normalizes agent type aliases and dispatches to the correct specialist module under `agents/specialist/`.
- **Orchestrator engine**: `orchestrator/engine.py` runs the full idea execution flow.

### Key Backend Modules
- `agents/` — Intake brain (natural language → structured goal), reviewer (3-pass validation loop), planner, and specialist agents.
- `execution/` — `runner.py` runs controlled verification against generated outputs. `execution_router.py` dispatches side-effect actions.
- `integrations/` — Encrypted credential vault (`vault.py`), connector registry with 20+ third-party integrations (`connectors/registry.py`), individual connector implementations in `connectors/`.
- `scheduler/` — Background job tick loop (`agent_scheduler.py`) for continuous agents (health monitors, market watchers, SEO monitors, etc.).
- `database/` — SQLAlchemy models for `Execution`, `PhaseResult`, `ScheduledJob`, `StoredCredential`, and `ConnectorAction`. All DB operations go through `database/operations.py`.

### Frontend State & Routing
- **State**: Zustand store in `src/store/projectStore.js` — the canonical client-side state for the project lifecycle (jam session, understanding, workflow, phases, agents, connectors, bots, health). Persisted to localStorage.
- **Routes**: `Dashboard`, `JamSession`, `Understanding`, `Workflow`, `PhaseCockpit`, `Connectors`, `Health` — all scoped under `/project/:id/*`.
- **API layer**: `src/api/client.js` — thin fetch wrapper with typed methods for every backend endpoint.

### Design System
The frontend uses a retro-cybernetic aesthetic with HSL token colors defined in `src/index.css`. Two UI modes: **Mode A** (Human Command Center — clean, readable) for Dashboard/Understanding/Workflow/Health, and **Mode B** (Execution Cockpit — technical, dark, dense) for Phase/Agent views.

## Known Limitations
- The recovered backend bytecode lost Pydantic type annotations on some routes — the fixed routes in `main.py` handle `/intake`, `/intake/reply`, `/execute`, `/execute/agent`, `/approve`, `/next-phase`, and add a new `/executions/{user_id}/{execution_id}/status` endpoint.
- Some agent implementations under `agents/specialist/` may be incomplete or stubbed.
- The `.venv-rebuild` virtual environment is the active Python environment for the backend.
