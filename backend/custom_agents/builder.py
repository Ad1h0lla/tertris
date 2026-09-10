import os
import uuid
from datetime import datetime, timezone

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_agents = {}


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def build_custom_agent(
    user_id: str,
    name: str,
    description: str,
    input_description: str,
    output_description: str,
    tools_needed: list
) -> dict:

    try:
        client = get_groq_client()

        prompt = (
            f"Generate a detailed system prompt for an AI agent named '{name}' "
            f"that {description}. It receives {input_description} as input and "
            f"must produce {output_description} as output. Tools available: "
            f"{tools_needed}. The prompt must instruct the agent to always "
            f"produce complete, specific, actionable output. Never produce "
            f"generic content."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=2048
        )

        generated_prompt = response.choices[0].message.content.strip()

        agent_id = str(uuid.uuid4())

        _agents[agent_id] = {
            "id": agent_id,
            "user_id": user_id,
            "name": name,
            "description": description,
            "input_description": input_description,
            "output_description": output_description,
            "system_prompt": generated_prompt,
            "tools_needed": tools_needed,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        return {
            "success": True,
            "agent_id": agent_id,
            "name": name,
            "description": description,
            "system_prompt": generated_prompt,
            "tools_needed": tools_needed
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_custom_agent(
    agent_id: str,
    user_input: str
) -> str:

    try:
        agent = _agents.get(agent_id)

        if not agent:
            return "Agent not found. Create it first at POST /custom-agents"

        system_prompt = agent.get("system_prompt", "")

        client = get_groq_client()

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_input
                }
            ],
            temperature=0.7,
            max_tokens=4096
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Error running agent: {str(e)}"


def list_custom_agents(user_id: str) -> list:

    try:
        results = []

        for agent in _agents.values():
            if agent.get("user_id") == user_id:
                results.append({
                    "id": agent.get("id"),
                    "name": agent.get("name"),
                    "description": agent.get("description"),
                    "tools_needed": agent.get("tools_needed"),
                    "created_at": agent.get("created_at")
                })

        return results

    except Exception:
        return []


def delete_custom_agent(agent_id: str) -> dict:

    try:
        if agent_id in _agents:
            del _agents[agent_id]

            return {
                "success": True,
                "deleted_id": agent_id
            }

        return {
            "success": False,
            "error": "Agent not found"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
