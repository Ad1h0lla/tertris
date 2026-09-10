import os
import json

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def extract_action_items(
    transcript: str,
    summary: str
) -> dict:

    system_prompt = """You are an expert at extracting action items from meeting transcripts.
Find every task, commitment, or next step mentioned.
Return ONLY valid JSON array:
[
{
"task": "specific task description",
"assigned_to": "name or role mentioned, or Unknown if not specified",
"deadline": "specific date or relative time mentioned, or Not specified",
"priority": "high|medium|low",
"context": "why this task matters",
"dependencies": ["depends on what"],
"status": "pending"
}
]"""

    user_message = (
        "Meeting Summary Context:\n"
        + json.dumps(summary, indent=2)
        + "\n\nTranscript:\n"
        + transcript
        + "\n\nExtract all action items and output ONLY the JSON array."
    )

    try:
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
                    "content": user_message
                }
            ],
            temperature=0.2,
            max_tokens=2048
        )

        raw_content = response.choices[0].message.content.strip()

        if raw_content.startswith("```json"):
            raw_content = raw_content.replace("```json", "", 1)

        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]

        parsed = json.loads(raw_content.strip())

        if isinstance(parsed, list):
            return parsed

        if isinstance(parsed, dict):
            for key in ("action_items", "items", "tasks"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]

        return []

    except json.JSONDecodeError:
        return []

    except Exception:
        return []
