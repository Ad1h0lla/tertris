import os
from dotenv import load_dotenv

load_dotenv()


def route_execution(
    action_type: str,
    payload: dict,
    user_id: str = ""
):
    """
    Routes an execution action to the right executor.

    Supported actions:
    - post_reddit
    - send_email
    - deploy_vercel
    - post_twitter
    - post_linkedin
    - post_slack
    """

    try:
        from execution.openclaw_executor import (
            check_openclaw_available,
            execute_via_openclaw,
        )

        openclaw_available = check_openclaw_available()

    except Exception:
        openclaw_available = False

    if action_type == "post_reddit":

        if openclaw_available:
            return execute_via_openclaw(
                "post_reddit",
                payload
            )

        try:
            from execution.reddit_executor import post_to_reddit

            return post_to_reddit(
                subreddit=payload.get("subreddit", ""),
                title=payload.get("title", ""),
                body=payload.get("body", "")
            )

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    if action_type == "send_email":

        if openclaw_available:
            return execute_via_openclaw(
                "send_email",
                payload
            )

        try:
            from execution.email_executor import send_email_sequence

            return send_email_sequence(
                emails=payload.get("emails", []),
                sequence=payload.get("sequence", []),
                from_email=payload.get(
                    "from_email",
                    "noreply@executa.ai"
                )
            )

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    if action_type == "deploy_vercel":

        try:
            from execution.vercel_executor import prepare_deployment

            return prepare_deployment(
                code_output=payload.get(
                    "code_output",
                    ""
                ),
                project_name=payload.get(
                    "project_name",
                    "my-project"
                ),
                outcome_type=payload.get(
                    "outcome_type",
                    "code"
                )
            )

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    if action_type in (
        "post_twitter",
        "post_linkedin",
        "post_slack"
    ):

        if openclaw_available:
            return execute_via_openclaw(
                action_type,
                payload
            )

        return {
            "success": False,
            "error": (
                f"{action_type} requires OpenClaw "
                "or direct API credentials"
            ),
            "action_required": (
                "Install OpenClaw from openclaw.ai "
                "or add API credentials to .env"
            ),
            "openclaw_available": False
        }

    return {
        "success": False,
        "error": f"Unknown action type: {action_type}"
    }
