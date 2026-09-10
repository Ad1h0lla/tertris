import os
import uuid
import httpx
import json

from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def ingest_from_transcript(
    transcript: str,
    platform: str,
    meeting_id: str
) -> dict:
    try:
        word_count = len(transcript.split())

        return {
            "success": True,
            "transcript": transcript,
            "platform": platform,
            "meeting_id": meeting_id or str(uuid.uuid4()),
            "word_count": word_count,
            "ingested_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "transcript": None
        }


def ingest_from_fireflies(
    api_key: str,
    transcript_id: str
) -> dict:
    url = "https://api.fireflies.ai/graphql"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    query = """
        query Transcript($id: String!) {
          transcript(id: $id) {
            id
            sentences {
              text
            }
          }
        }
    """

    params = {
        "query": query,
        "variables": {
            "id": transcript_id
        }
    }

    try:
        response = httpx.get(
            url,
            headers=headers,
            params=params,
            timeout=15.0
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"API request failed with status {response.status_code}",
                "transcript": None
            }

        data = response.json()

        sentences = data["data"]["transcript"]["sentences"]

        transcript_text = " ".join(
            s["text"]
            for s in sentences
        )

        return ingest_from_transcript(
            transcript=transcript_text,
            platform="fireflies",
            meeting_id=transcript_id
        )

    except (KeyError, TypeError):
        return {
            "success": False,
            "error": "Could not parse transcript from Fireflies response",
            "transcript": None
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "transcript": None
        }


def get_supported_platforms() -> list:
    return [
        "manual",
        "fireflies",
        "zoom (coming soon)",
        "google_meet (coming soon)",
        "teams (coming soon)"
    ]
