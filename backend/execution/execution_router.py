import os
from dotenv import load_dotenv

load_dotenv()


def execute_distribution_action(
    action: dict,
    user_id: str = "user_001",
    db=None,
    reddit_client_override=None,
    **kwargs,
) -> dict:
    """
    Routes a structured DistributionAction (M3.1 model) to the appropriate worker/platform executor.
    In M3.2, executes Community Worker -> Reddit Executor.
    """
    worker = (action.get("worker") or "").lower()
    platform = (action.get("platform") or "").lower()

    if worker == "community" or platform == "reddit":
        if platform == "reddit":
            from execution.reddit_executor import execute_reddit_action
            return execute_reddit_action(
                action=action,
                user_id=user_id,
                db=db,
                reddit_client_override=reddit_client_override,
                **kwargs,
            )
        return {
            "status": "BLOCKED",
            "reason": "UNSUPPORTED_PLATFORM",
            "error": f"Unsupported community platform: '{platform}'. Only Reddit is supported in M3.2.",
            "verified": False,
            "verification_status": "NOT_TESTED",
        }

    if worker == "social" or platform in ("twitter", "x", "x/twitter", "linkedin"):
        if platform in ("twitter", "x", "x/twitter"):
            from execution.x_executor import execute_x_action
            return execute_x_action(
                action=action,
                user_id=user_id,
                db=db,
                tweepy_client_override=kwargs.get("tweepy_client_override"),
            )
        if platform == "linkedin":
            from execution.linkedin_executor import execute_linkedin_action
            return execute_linkedin_action(
                action=action,
                user_id=user_id,
                db=db,
                http_client_override=kwargs.get("http_client_override"),
            )
        return {
            "status": "BLOCKED",
            "reason": "UNSUPPORTED_PLATFORM",
            "error": f"Unsupported social platform: '{platform}'. Only Twitter/X and LinkedIn are supported in M3.3.",
            "verified": False,
            "verification_status": "NOT_TESTED",
        }

    if worker == "outreach" or platform in ("email", "mail", "gmail", "sendgrid", "smtp"):
        if platform in ("email", "mail", "gmail", "sendgrid", "smtp"):
            from execution.email_executor import execute_email_action
            return execute_email_action(
                action=action,
                user_id=user_id,
                db=db,
                provider_override=kwargs.get("provider_override") or kwargs.get("email_provider_override"),
                http_client=kwargs.get("http_client"),
                smtp_client=kwargs.get("smtp_client"),
            )
        return {
            "status": "BLOCKED",
            "reason": "UNSUPPORTED_PLATFORM",
            "error": f"Unsupported outreach platform: '{platform}'. Only email is supported in M3.4.",
            "verified": False,
            "verification_status": "NOT_TESTED",
        }

    return {
        "status": "BLOCKED",
        "reason": "UNSUPPORTED_WORKER",
        "error": f"Worker '{worker}' on platform '{platform}' is not yet implemented.",
        "verified": False,
        "verification_status": "NOT_TESTED",
    }



def route_execution(
    action_type: str,
    payload: dict,
    user_id: str = ""
):
    """
    Routes an execution action to the right executor.

    Supported actions:
    - post_reddit / create_post / reply_to_post
    - send_email
    - deploy_vercel
    - post_twitter
    - post_linkedin
    - post_slack
    """

    if action_type in ("post_reddit", "create_post", "reply_to_post") or (isinstance(payload, dict) and payload.get("platform") == "reddit"):
        from execution.reddit_executor import execute_reddit_action, post_to_reddit

        if isinstance(payload, dict) and "worker" in payload and "target" in payload:
            return execute_reddit_action(action=payload, user_id=user_id)
        elif action_type in ("create_post", "reply_to_post"):
            act = {
                "action_id": payload.get("action_id", ""),
                "execution_id": payload.get("execution_id", ""),
                "worker": "community",
                "platform": "reddit",
                "action_type": action_type,
                "target": payload.get("target") or {"community": payload.get("subreddit", "")},
                "content": payload.get("content") or {"title": payload.get("title", ""), "body": payload.get("body", "")},
                "approval": payload.get("approval") or {"required": False, "status": "APPROVED"},
            }
            return execute_reddit_action(action=act, user_id=user_id)
        else:
            return post_to_reddit(
                subreddit=payload.get("subreddit", ""),
                title=payload.get("title", ""),
                body=payload.get("body", ""),
                user_id=user_id,
            )

    if action_type == "send_email":
        from execution.email_executor import execute_email_action

        if isinstance(payload, dict) and "worker" in payload and "target" in payload:
            return execute_email_action(action=payload, user_id=user_id)

        target_email = payload.get("to_email") or payload.get("email") or ""
        if not target_email and isinstance(payload.get("emails"), list) and payload.get("emails"):
            target_email = payload.get("emails")[0]

        subject = payload.get("subject", "")
        body = payload.get("body") or payload.get("text", "")
        if not subject and isinstance(payload.get("sequence"), list) and payload.get("sequence"):
            first_step = payload.get("sequence")[0]
            subject = first_step.get("subject", "Outreach from Tetris")
            body = first_step.get("body", first_step.get("text", ""))

        act = {
            "action_id": payload.get("action_id", ""),
            "execution_id": payload.get("execution_id", ""),
            "worker": "outreach",
            "platform": "email",
            "action_type": "send_email",
            "target": payload.get("target") or {"email": target_email, "from_email": payload.get("from_email", "noreply@executa.ai")},
            "content": payload.get("content") or {"subject": subject or "Outreach from Tetris", "body": body or "Hello from Tetris"},
            "approval": payload.get("approval") or {"required": False, "status": "APPROVED"},
        }
        return execute_email_action(action=act, user_id=user_id)

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

    if action_type == "post_twitter":
        from execution.x_executor import execute_x_action
        act = {
            "action_id": payload.get("action_id", ""),
            "execution_id": payload.get("execution_id", ""),
            "worker": "social",
            "platform": "twitter",
            "action_type": "create_post",
            "target": payload.get("target") or {},
            "content": payload.get("content") or {"body": payload.get("text", "")},
            "approval": payload.get("approval") or {"required": False, "status": "APPROVED"},
        }
        return execute_x_action(action=act, user_id=user_id)

    if action_type == "post_linkedin":
        from execution.linkedin_executor import execute_linkedin_action
        act = {
            "action_id": payload.get("action_id", ""),
            "execution_id": payload.get("execution_id", ""),
            "worker": "social",
            "platform": "linkedin",
            "action_type": "create_post",
            "target": payload.get("target") or {},
            "content": payload.get("content") or {"body": payload.get("text", "")},
            "approval": payload.get("approval") or {"required": False, "status": "APPROVED"},
        }
        return execute_linkedin_action(action=act, user_id=user_id)

    if action_type == "post_slack":
        return {
            "success": False,
            "error": "post_slack is not yet implemented.",
        }

    return {
        "success": False,
        "error": f"Unknown action type: {action_type}"
    }
