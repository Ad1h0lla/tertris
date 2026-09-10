import os
import json

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_groq_client():
    return Groq(api_key=os.environ.get("GROQ_API_KEY"))


def summarize_meeting(
    transcript: str,
    meeting_type: str
) -> dict:

    default_response = {
        "executive_summary": "Failed to parse meeting summary from AI.",
        "key_decisions": [],
        "action_items": [],
        "blockers": [],
        "opportunities": [],
        "follow_up_required": [],
        "participants_mentioned": [],
        "sentiment": "neutral",
        "meeting_type": meeting_type or "other"
    }

    try:
        client = get_groq_client()

        system_prompt = """You are an expert meeting summarizer for enterprise teams.
Analyze this meeting transcript and extract structured information.
Return ONLY valid JSON:
{
"executive_summary": "3 sentence summary for C-suite",
"key_decisions": ["decision 1", "decision 2"],
"action_items": [
{"task": "description", "assigned_to": "name or role mentioned", "deadline": "date mentioned or inferred", "priority": "high|medium|low"}
],
"blockers": ["blocker 1", "blocker 2"],
"opportunities": ["opportunity 1"],
"follow_up_required": ["topic 1"],
"participants_mentioned": ["name1", "name2"],
"sentiment": "positive|neutral|negative|mixed",
"meeting_type": "standup|planning|review|brainstorm|client|other"
}"""

        user_message = (
            f"Meeting context: {meeting_type}"
            f"\n\nTranscript:\n{transcript}"
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

        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            return default_response

    except Exception as e:
        error_response = default_response.copy()
        error_response["executive_summary"] = (
            f"Error during summarization: {str(e)}"
        )
        error_response["success"] = False

        return error_response
