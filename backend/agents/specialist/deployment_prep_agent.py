import os
import json
from typing import Optional, Dict, Any, List

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def run_deployment_prep(
    code_output: str = "",
    project_name: str = "Project",
    outcome_type: str = "code",
    workspace_path: Optional[str] = None,
    simulation_result: Optional[dict] = None,
) -> dict:

    default_response = {
        "framework": "Client Web App",
        "recommended_platform": "Vercel",
        "install_command": "",
        "build_command": None,
        "start_command": None,
        "environment_variables_needed": [],
        "deploy_steps": [
            "Deploy to Vercel production hosting."
        ],
        "estimated_time": "1-2 minutes",
        "monthly_cost": "Free on hobby tier",
        "one_click_ready": False,
        "deploy_button_url": "https://vercel.com/new",
        "pre_flight_simulation": "NOT_TESTED",
        "deployment_status": "NOT_STARTED",
        "url": None,
        "deployment_id": None,
    }

    # 1. Enforce pre-launch simulation gate
    if simulation_result and isinstance(simulation_result, dict):
        sim_status = simulation_result.get("simulation_status", "UNKNOWN")
        default_response["pre_flight_simulation"] = sim_status
        if sim_status == "FAIL":
            issues = simulation_result.get("issues", [])
            issue_msgs = [f"[{i.get('check', 'check')}]: {i.get('message', '')}" for i in issues]
            return {
                "framework": "Client Web App",
                "recommended_platform": "Vercel",
                "install_command": "",
                "build_command": None,
                "start_command": None,
                "environment_variables_needed": [],
                "deploy_steps": [
                    "BLOCKER: Pre-launch simulation failed. Fix critical issues before deploying:",
                ] + (issue_msgs or ["Deterministic validation detected code or configuration errors."]),
                "estimated_time": "N/A - Blocked",
                "monthly_cost": "N/A",
                "one_click_ready": False,
                "deploy_button_url": "",
                "pre_flight_simulation": "FAIL",
                "deployment_status": "BLOCKED",
                "url": None,
                "deployment_id": None,
                "blockers": issues,
            }

    # 2. Execute Real Vercel Cloud Deployment if workspace is available
    deploy_res = None
    if workspace_path and os.path.exists(workspace_path):
        from execution.vercel_executor import deploy_to_vercel
        deploy_res = deploy_to_vercel(
            workspace_path=workspace_path,
            project_name=project_name,
            simulation_result=simulation_result,
        )

    try:
        code_lower = str(code_output or "").lower()

        if "django" in code_lower:
            framework = "Django"
        elif "flask" in code_lower:
            framework = "Flask"
        elif "fastapi" in code_lower:
            framework = "FastAPI"
        elif "next" in code_lower:
            framework = "Next.js"
        elif "react" in code_lower:
            framework = "React"
        elif "express" in code_lower or "node" in code_lower:
            framework = "Express/Node.js"
        else:
            framework = "Unknown"

        client = get_groq_client()

        system_prompt = f"""Produce a deployment guide for a {framework} project.
Return ONLY valid JSON:
{{
"framework": "{framework}",
"recommended_platform": "Vercel|Railway|Render",
"install_command": "pip install -r requirements.txt",
"build_command": "command or null",
"start_command": "python main.py",
"environment_variables_needed": ["VAR_NAME - description"],
"deploy_steps": ["step 1", "step 2", "step 3"],
"estimated_time": "2 minutes",
"monthly_cost": "Free on hobby plan",
"one_click_ready": true,
"deploy_button_url": "https://vercel.com/new or https://railway.app/new"
}}"""

        code_context = str(code_output or "")[:3000]

        user_message = (
            f"Project Name: {project_name}"
            f"\nOutcome Type: {outcome_type}"
            f"\n\nCode Snippet for context:\n"
            f"{code_context or 'No code provided.'}"
        )

        from llm.router import get_llm_response

        raw_content = get_llm_response(
            task="deployment",
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.2,
        )

        guide = default_response.copy()
        try:
            guide = json.loads(clean)
        except json.JSONDecodeError:
            guide = default_response.copy()

        if deploy_res:
            guide["deployment"] = deploy_res
            guide["deployment_status"] = deploy_res.get("deployment_status", "UNKNOWN")
            guide["url"] = deploy_res.get("url")
            guide["deployment_id"] = deploy_res.get("deployment_id")
            guide["verification_status"] = deploy_res.get("verification_status", "NOT_TESTED")
            guide["one_click_ready"] = (deploy_res.get("deployment_status") == "SUCCESS")
            if deploy_res.get("url"):
                guide["deploy_button_url"] = deploy_res["url"]
            if deploy_res.get("error"):
                guide["error"] = deploy_res["error"]

        return guide

    except Exception as e:
        error_response = default_response.copy()
        error_response["deploy_steps"] = [
            f"Error during deployment preparation: {str(e)}"
        ]
        if deploy_res:
            error_response["deployment"] = deploy_res
            error_response["deployment_status"] = deploy_res.get("deployment_status", "UNKNOWN")
            error_response["url"] = deploy_res.get("url")
        return error_response
