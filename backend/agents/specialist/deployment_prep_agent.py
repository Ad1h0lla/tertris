import os
import json

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def run_deployment_prep(
    code_output: str,
    project_name: str,
    outcome_type: str
) -> dict:

    default_response = {
        "framework": "Unknown",
        "recommended_platform": "Vercel",
        "install_command": "",
        "build_command": None,
        "start_command": None,
        "environment_variables_needed": [],
        "deploy_steps": [
            "Deploy manually via hosting provider."
        ],
        "estimated_time": "Unknown",
        "monthly_cost": "Unknown",
        "one_click_ready": False,
        "deploy_button_url": "https://vercel.com/new"
    }

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

        clean = raw_content.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["deploy_steps"] = [
            f"Error during deployment preparation: {str(e)}"
        ]
        return error_response
