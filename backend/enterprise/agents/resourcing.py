import os
import json

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def analyze_resourcing(
    action_items: list,
    decisions: list,
    team_context: str
) -> dict:

    default_response = {
        "roles_needed": [],
        "total_people_needed": 0,
        "estimated_total_hours": 0,
        "estimated_duration": "Unknown",
        "budget_estimate": "Failed to generate recommendations.",
        "critical_path_items": [],
        "recommendations": [],
        "risks": "Analysis failed."
    }

    try:
        client = get_groq_client()

        system_prompt = """You are an expert resource planning analyst for enterprise teams.
Based on these action items and decisions from a meeting, identify what resources are needed.
Return ONLY valid JSON:
{
"roles_needed": [
{"role": "Senior Developer", "count": 2, "reason": "why needed", "estimated_hours": 40, "skill_requirements": ["React", "Node.js"]}
],
"total_people_needed": 0,
"estimated_total_hours": 0,
"estimated_duration": "2 weeks",
"budget_estimate": "rough estimate if hourly rates assumed",
"critical_path_items": ["most important task"],
"recommendations": ["specific recommendation 1", "specific recommendation 2"],
"risks": ["risk if resource not available"]
}"""

        user_message = (
            "Team Context:\n"
            + (team_context or "None provided")
            + "\n\nDecisions Made:\n"
            + json.dumps(decisions, indent=2)
            + "\n\nAction Items:\n"
            + json.dumps(action_items, indent=2)
            + "\n\nPlease analyze resourcing needs and return the JSON."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            temperature=0.2,
            max_tokens=2048,
            response_format={
                "type": "json_object"
            }
        )

        raw_content = response.choices[0].message.content.strip()

        return json.loads(raw_content)

    except json.JSONDecodeError:
        return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["budget_estimate"] = (
            f"Error during analysis: {str(e)}"
        )
        error_response["success"] = False
        error_response["error"] = None
        return error_response
