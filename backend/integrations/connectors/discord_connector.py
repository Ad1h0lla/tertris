import os
import httpx
from dotenv import load_dotenv

load_dotenv()

DISCORD_API = os.getenv(
    "DISCORD_API",
    "https://discord.com/api/v10"
)


async def send_discord_message(
    bot_token: str,
    channel_id: str,
    content: str,
    embed: dict | None = None,
) -> dict:
    """
    Sends a message to a Discord channel.
    Returns success/failure with message ID.
    """

    if not bot_token or not channel_id:
        return {
            "success": False,
            "error": "Missing DISCORD_BOT_TOKEN or channel_id",
            "action_required": "Add your Discord bot token via POST /credentials/connect",
        }

    payload = {
        "content": content,
    }

    if embed:
        payload["embeds"] = [embed]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {bot_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if res.status_code in (200, 201):
                data = res.json()

                return {
                    "success": True,
                    "message_id": data.get("id"),
                    "channel_id": channel_id,
                    "content_preview": content[:80],
                }

            return {
                "success": False,
                "error": f"Discord API error: {res.status_code}",
                "detail": res.text,
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def send_phase_complete_notification(
    bot_token: str,
    channel_id: str,
    phase: int,
    outcome_type: str,
    goal: str,
    score: float,
) -> dict:
    """
    Sends a formatted phase completion notification to Discord.
    Called automatically when any phase completes.
    """

    phase_names = {
        1: "BUILD",
        2: "VALIDATE",
        3: "MARKET",
        4: "LAUNCH",
    }

    phase_colors = {
        1: 8960409,
        2: 15779444,
        3: 9092791,
        4: 13395558,
    }

    embed = {
        "title": f"✓ PHASE {phase} — {phase_names.get(phase, 'COMPLETE')}",
        "description": f"**Goal:** {goal[:120]}",
        "color": phase_colors.get(phase, 8960409),
        "fields": [
            {
                "name": "OUTCOME TYPE",
                "value": outcome_type.replace("_", " ").upper(),
                "inline": True,
            },
            {
                "name": "VALIDATION SCORE",
                "value": f"{round(score * 100)}%",
                "inline": True,
            },
            {
                "name": "STATUS",
                "value": "COMPLETE — Ready for next phase",
                "inline": False,
            },
        ],
        "footer": {
            "text": "EXECUTA // AGENT CONTROLLER v3.0"
        },
    }

    return await send_discord_message(
        bot_token=bot_token,
        channel_id=channel_id,
        content=f"Phase {phase} execution complete.",
        embed=embed,
    )


async def validate_discord_token(bot_token: str) -> dict:
    """
    Validates a Discord bot token by calling the /users/@me endpoint.
    Returns bot username if valid.
    """

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                f"{DISCORD_API}/users/@me",
                headers={
                    "Authorization": f"Bot {bot_token}",
                },
            )

            if res.status_code == 200:
                data = res.json()

                return {
                    "valid": True,
                    "bot_username": data.get("username"),
                    "bot_id": data.get("id"),
                }

            return {
                "valid": False,
                "error": f"Invalid token (status code: {res.status_code})",
            }

    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }
