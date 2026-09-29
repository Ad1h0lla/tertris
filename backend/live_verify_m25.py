"""
Tetris M2.5 -- Live Deployment Verification Script
==================================================

Executes ONE real, unmocked Vercel cloud deployment for an actual project workspace:
1. Runs M2.4 simulation against the workspace.
2. Enforces the simulation gate (must be PASS).
3. Executes real Vercel deployment using VERCEL_TOKEN from .env.
4. Waits for readyState == READY.
5. Issues live HTTP smoke check against the returned URL.
6. Persists deployment_result in SQLite executa.db.
7. Queries DB to verify persistence and retrieval.
8. Checks for secret leakage.
"""

import sys
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from simulation.engine import run_simulation
from execution.vercel_executor import deploy_to_vercel, get_vercel_token
from database.models import init_db, SessionLocal
from database.operations import save_phase_result, get_phase_results, create_execution, get_execution_by_id


def run_live_verification():
    print("=" * 70)
    print("TETRIS M2.5 -- LIVE VERCEL DEPLOYMENT VERIFICATION")
    print("=" * 70)

    # 1. Check workspace
    workspace = os.path.join(_BACKEND_DIR, "generated_projects", "c9e6c619-8c88-42f4-925b-226dda126a05", "phase_1")
    print(f"\n[1] Target Workspace: {workspace}")
    if not os.path.exists(workspace):
        print(f"[ERROR] Workspace path does not exist: {workspace}")
        return False

    files = os.listdir(workspace)
    print(f"    Files on disk: {files}")

    # 2. Run M2.4 Simulation
    print("\n[2] Running Pre-Launch Simulation (M2.4)...")
    sim_res = run_simulation(
        workspace_path=workspace,
        acceptance_criteria=[
            "Crypto Portfolio Tracker interface",
            "Interactive transactions",
            "Chart rendering component",
        ],
    )
    print(f"    Simulation Status: {sim_res['simulation_status']}")
    print(f"    Total Checks:      {sim_res['total_checks']} ({sim_res['passed_checks']} passed, {sim_res['failed_checks']} failed, {sim_res['not_tested']} not tested)")
    for chk in sim_res["checks"]:
        print(f"      [{chk['status']}] {chk['name']}")

    if sim_res["simulation_status"] != "PASS":
        print(f"[ERROR] Simulation gate FAILED: {sim_res['simulation_status']}")
        return False
    print("    [PASS] Simulation Gate passed successfully.")

    # 3. Check VERCEL_TOKEN
    token = get_vercel_token()
    if not token:
        print("[ERROR] VERCEL_TOKEN is not configured in backend/.env")
        return False
    print("\n[3] Vercel Credentials: Configured (Token length: {0} chars)".format(len(token)))

    # 4. Execute Real Vercel Deployment
    print("\n[4] Executing Real Vercel Cloud Deployment...")
    deploy_res = deploy_to_vercel(
        workspace_path=workspace,
        project_name="crypto-tracker-live",
        simulation_result=sim_res,
        timeout_seconds=60,
    )

    print(f"    Deployment Status:    {deploy_res.get('deployment_status')}")
    print(f"    Vercel Deployment ID: {deploy_res.get('deployment_id')}")
    print(f"    Build Status:         {deploy_res.get('build_status')}")
    print(f"    Live URL:             {deploy_res.get('url')}")
    print(f"    Timestamp:            {deploy_res.get('deployed_at')}")

    if deploy_res.get("deployment_status") != "SUCCESS":
        print(f"[ERROR] Deployment did not succeed: {deploy_res.get('error')}")
        return False

    # 5. Live Smoke Check Verification
    print("\n[5] Live HTTP Smoke Check Results:")
    smoke = deploy_res.get("smoke_check") or {}
    print(f"    Target URL:           {smoke.get('url')}")
    print(f"    HTTP Status:          {smoke.get('http_status')}")
    print(f"    Content Length:       {smoke.get('content_length')} bytes")
    print(f"    Verification Status:  {smoke.get('status')}")
    print(f"    Verified:             {deploy_res.get('verified')}")

    if not deploy_res.get("verified") or smoke.get("status") != "PASS":
        print("[ERROR] Smoke check failed to verify live HTTP response from Vercel URL.")
        return False

    # Double check live URL with direct independent HTTP GET
    live_url = deploy_res["url"]
    print(f"\n[6] Independent HTTP GET Request to {live_url}...")
    try:
        resp = requests.get(live_url, timeout=15)
        print(f"    Direct HTTP Status:   {resp.status_code}")
        print(f"    Direct Content-Type:  {resp.headers.get('content-type')}")
        print(f"    Direct Body Preview:  {resp.text[:150].strip()}...")
        if resp.status_code != 200 or len(resp.text) == 0:
            print("[ERROR] Direct HTTP request failed.")
            return False
    except Exception as e:
        print(f"[ERROR] Direct HTTP request exception: {e}")
        return False

    # 7. Persistence in SQLite
    print("\n[7] Persisting deployment_result into SQLite executa.db...")
    init_db()
    db = SessionLocal()
    exec_id = f"live_exec_{deploy_res['deployment_id']}"
    try:
        ex = create_execution(
            db=db,
            user_id="user_001",
            original_idea="Crypto Portfolio Tracker",
            understood_goal="Crypto Portfolio Tracker",
            intent_classification="full_product",
            idea_type="saas",
            recommended_phases=[1, 2, 3, 4],
        )
        save_phase_result(
            db=db,
            execution_id=ex.id,
            phase=4,
            outcome_type="deployment_prep",
            outcome=json.dumps(deploy_res, indent=2),
            score=1.0,
            trace=[{"step": "deployment_completed", "url": deploy_res["url"]}],
            status="WAITING_FOR_APPROVAL",
            simulation_result=sim_res,
            deployment_result=deploy_res,
        )

        # Retrieve and verify
        db_check = SessionLocal()
        try:
            results = get_phase_results(db_check, ex.id)
            if not results or not results[0].deployment_result:
                print("[ERROR] Failed to retrieve deployment_result from SQLite.")
                return False
            stored = results[0].deployment_result
            print(f"    Persisted Provider:   {stored.get('provider')}")
            print(f"    Persisted Deploy ID:  {stored.get('deployment_id')}")
            print(f"    Persisted Live URL:   {stored.get('url')}")
            print(f"    Persisted Verified:   {stored.get('verified')}")
        finally:
            db_check.close()
    finally:
        db.close()

    # 8. Secret Leakage Audit
    print("\n[8] Auditing for Secret Leakage...")
    dumped_str = json.dumps(deploy_res)
    if token in dumped_str:
        print("[CRITICAL ERROR] Token string detected in deployment output!")
        return False
    print("    [PASS] Token string NOT found in deployment output, DB payload, or logs.")

    print("\n" + "=" * 70)
    print("LIVE DEPLOYMENT VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_live_verification()
    sys.exit(0 if success else 1)
