import os
import uuid
import asyncio
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()


_jobs = {}


AGENT_TYPES = {
    "reddit_poster": {
        "description": "Posts valuable content to Reddit communities.",
        "default_interval_hours": 24
    },
    "email_sender": {
        "description": "Sends the next email in an automated sequence.",
        "default_interval_hours": 24
    },
    "market_watcher": {
        "description": "Watches competitors and market changes.",
        "default_interval_hours": 24
    },
    "health_monitor": {
        "description": "Checks execution and system health.",
        "default_interval_hours": 24
    },
    "content_poster": {
        "description": "Posts content across multiple platforms.",
        "default_interval_hours": 24
    },
    "seo_monitor": {
        "description": "Monitors SEO performance and rankings.",
        "default_interval_hours": 24
    }
}


def schedule_agent(
    user_id,
    agent_type,
    payload,
    interval_hours=None,
    notify_via="none",
    notify_target="",
    start_immediately=True
):
    """
    Schedule an agent to run repeatedly on an interval.
    """

    if agent_type not in AGENT_TYPES:
        return {
            "success": False,
            "error": f"Unknown agent type: {agent_type}",
            "available_types": list(AGENT_TYPES.keys())
        }

    if interval_hours is None:
        interval_hours = AGENT_TYPES[agent_type]["default_interval_hours"]

    job_id = str(uuid.uuid4())
    now = datetime.utcnow()

    job = {
        "job_id": job_id,
        "user_id": user_id,
        "agent_type": agent_type,
        "agent_description": AGENT_TYPES[agent_type]["description"],
        "payload": payload,
        "interval_hours": interval_hours,
        "notify_via": notify_via,
        "notify_target": notify_target,
        "status": "active",
        "created_at": now.isoformat(),
        "last_run": None,
        "next_run": (
            now.isoformat()
            if start_immediately
            else (now + timedelta(hours=interval_hours)).isoformat()
        ),
        "run_count": 0,
        "last_result": None,
        "total_actions_taken": 0
    }

    _jobs[job_id] = job

    try:
        from database.models import SessionLocal
        from database.operations import save_job

        db = SessionLocal()
        try:
            save_job(db, job)
        finally:
            db.close()
    except Exception as e:
        print(f"Warning: could not persist scheduled job: {e}")

    return {
        "success": True,
        "job_id": job_id,
        "message": (
            f"Agent scheduled. Will run every "
            f"{interval_hours} hours automatically."
        )
    }


def get_scheduled_jobs(user_id):
    user_jobs = [
        job
        for job in _jobs.values()
        if job.get("user_id") == user_id
    ]

    return sorted(
        user_jobs,
        key=lambda job: job.get("created_at", ""),
        reverse=True
    )


def get_due_jobs():
    now = datetime.utcnow()
    due = []

    for job in _jobs.values():
        if job.get("status") != "active":
            continue

        next_run = job.get("next_run")

        if not next_run:
            continue

        if datetime.fromisoformat(next_run) <= now:
            due.append(job)

    return due


def pause_job(job_id):
    if job_id not in _jobs:
        return {
            "success": False,
            "error": "Job not found"
        }

    _jobs[job_id]["status"] = "paused"

    return {
        "success": True,
        "job_id": job_id,
        "status": "paused"
    }


def resume_job(job_id):
    if job_id not in _jobs:
        return {
            "success": False,
            "error": "Job not found"
        }

    _jobs[job_id]["status"] = "active"

    return {
        "success": True,
        "job_id": job_id,
        "status": "active"
    }


def cancel_job(job_id):
    if job_id not in _jobs:
        return {
            "success": False,
            "error": "Job not found"
        }

    del _jobs[job_id]

    return {
        "success": True,
        "job_id": job_id,
        "message": "Job cancelled permanently"
    }


def update_job_result(job_id, result):
    job = _jobs.get(job_id)

    if not job:
        return

    now = datetime.utcnow()

    job["last_run"] = now.isoformat()

    interval_hours = job.get("interval_hours", 24)

    job["next_run"] = (
        now + timedelta(hours=interval_hours)
    ).isoformat()

    job["run_count"] = job.get("run_count", 0) + 1
    job["last_result"] = result

    if isinstance(result, dict):
        job["total_actions_taken"] = (
            job.get("total_actions_taken", 0)
            + result.get("total_actions_taken", 0)
        )

    try:
        from database.models import SessionLocal
        from database.operations import update_job_after_run

        db = SessionLocal()
        try:
            update_job_after_run(db, job_id, result)
        finally:
            db.close()
    except Exception as e:
        print(f"Warning: could not persist job result: {e}")


def run_health_monitor(payload):
    user_id = payload.get("user_id", "user_001")

    try:
        due_jobs = get_due_jobs()
        all_jobs = list(_jobs.values())

        failed = [
            j for j in all_jobs
            if j.get("status") == "failed"
        ]

        report = {
            "success": True,
            "checked_at": datetime.utcnow().isoformat(),
            "active_jobs": len([
                j for j in all_jobs
                if j.get("status") == "active"
            ]),
            "failed_jobs": len(failed),
            "due_now": len(due_jobs),
            "healthy": len(failed) == 0,
            "message": (
                f"Health check complete. {len(failed)} failed jobs detected."
                if failed
                else "All systems healthy."
            )
        }

        return report

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def execute_job(job):
    agent_type = job.get("agent_type")
    payload = job.get("payload", {})

    try:
        if agent_type == "reddit_poster":
            result = run_reddit_poster(payload)
        elif agent_type == "email_sender":
            result = run_email_sender(payload)
        elif agent_type == "market_watcher":
            result = run_market_watcher(payload)
        elif agent_type == "health_monitor":
            result = run_health_monitor(payload)
        elif agent_type == "content_poster":
            result = run_content_poster(payload)
        elif agent_type == "seo_monitor":
            result = run_seo_monitor(payload)
        else:
            result = {
                "success": False,
                "error": "Unknown agent type"
            }

        update_job_result(job["job_id"], result)

        if job.get("notify_via") != "none":
            send_notification(job, result)

        return result

    except Exception as e:
        result = {
            "success": False,
            "error": str(e)
        }

        update_job_result(job["job_id"], result)

        return result


def run_reddit_poster(payload):
    from execution.execution_router import route_execution
    from agents.search_agent import search_web, format_search_results
    from groq import Groq
    import json

    content_goal = payload.get("content_goal", "")
    subreddit = payload.get("subreddit", "")

    trends = search_web(
        f"r/{subreddit} trending topics this week"
    )

    trends_text = format_search_results(trends)

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You write engaging Reddit posts. "
                    "Write a post that provides genuine value "
                    "to the community. Never sound promotional. "
                    "Be helpful first. "
                    'Return JSON: {"title": "post title", "body": "full post body"}'
                )
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {content_goal}\n"
                    f"Subreddit: r/{subreddit}\n"
                    f"Current trending topics: {trends_text}\n\n"
                    "Write a valuable post for this community right now."
                )
            }
        ]
    )

    raw = response.choices[0].message.content.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()

    post_content = json.loads(clean)

    result = route_execution(
        "post_reddit",
        {
            "subreddit": subreddit,
            "title": post_content.get("title", ""),
            "body": post_content.get("body", "")
        }
    )

    return {
        **result,
        "content_generated": post_content
    }


def run_email_sender(payload):
    from execution.execution_router import route_execution

    try:
        return route_execution(
            "send_email",
            payload
        )
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_market_watcher(payload):
    from agents.specialist.competitor_intel_agent import run_competitor_intel

    try:
        confirmed_goal = payload.get("confirmed_goal", "")
        idea_type = payload.get("idea_type", "saas")

        result = run_competitor_intel(
            confirmed_goal,
            idea_type
        )

        return {
            "success": True,
            "watched_at": datetime.utcnow().isoformat(),
            **result
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_content_poster(payload):
    from execution.execution_router import route_execution

    try:
        platforms = payload.get(
            "platforms",
            ["reddit", "twitter"]
        )

        results = []

        for platform in platforms:
            if platform == "reddit":
                r = route_execution(
                    "post_reddit",
                    payload
                )
            elif platform == "twitter":
                r = route_execution(
                    "post_twitter",
                    payload
                )
            else:
                r = {
                    "success": False,
                    "error": f"Unsupported platform: {platform}"
                }

            results.append(r)

        success_count = sum(
            1 for r in results
            if r.get("success")
        )

        return {
            "success": success_count > 0,
            "platforms_posted": success_count,
            "total_platforms": len(platforms),
            "results": results
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_seo_monitor(payload):
    from agents.search_agent import search_web, format_search_results

    try:
        keywords = payload.get("keywords", [])
        website_url = payload.get("website_url", "")

        rankings = []

        for keyword in keywords:
            results = search_web(
                f"{keyword} site:{website_url}"
            )

            rankings.append({
                "keyword": keyword,
                "found_in_results": len(results)
            })

        return {
            "success": True,
            "website": website_url,
            "keywords_checked": len(keywords),
            "rankings": rankings,
            "checked_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def build_notification_message(agent_type, result, job):
    run_count = job.get("run_count", 0)
    success = result.get("success", False)

    status = "✅ Success" if success else "❌ Failed"

    if agent_type == "reddit_poster":
        message = (
            f"{status} — Reddit Post #{run_count}\n\n"
            "Your marketing agent just posted to Reddit.\n"
            f"Post URL: {result.get('post_url', 'Check Reddit')}\n"
            f"Upvotes so far: {result.get('upvotes', 0)}\n\n"
            f"Next post scheduled in {job.get('interval_hours', 24)} hours.\n"
        )

    elif agent_type == "market_watcher":
        message = (
            f"{status} — Market Watch #{run_count}\n\n"
            "Your market watcher just ran.\n"
            f"Competitors monitored: {result.get('competitors', 0)}\n"
            f"New market gap found: {result.get('market_gap', 'No change')}\n\n"
            f"Next check in {job.get('interval_hours', 24)} hours."
        )

    elif agent_type == "health_monitor":
        message = (
            f"{status} — Health Check #{run_count}\n\n"
            "Your outcome health was checked.\n"
            f"Status: {result.get('status', 'Unknown')}"
        )

    elif agent_type == "email_sender":
        message = (
            f"{status} — Email Sequence #{run_count}\n\n"
            "Your email agent just ran.\n"
            f"Emails sent: {result.get('sent_count', 0)}\n\n"
            f"Next send in {job.get('interval_hours', 24)} hours."
        )

    else:
        message = (
            f"{status} — Agent {agent_type} ran. "
            f"Run #{run_count}."
        )

    return message


def send_notification(job, result):
    notify_via = job.get("notify_via", "none")
    notify_target = job.get("notify_target", "")

    if notify_via == "none":
        return

    agent_type = job.get("agent_type", "")
    message = build_notification_message(
        agent_type,
        result,
        job
    )

    if notify_via == "openclaw":
        return notify_via_openclaw(
            message,
            notify_target
        )

    if notify_via == "email":
        return notify_via_email(
            message,
            notify_target
        )


def notify_via_openclaw(message, channel):
    try:
        import httpx

        openclaw_url = os.getenv(
            "OPENCLAW_GATEWAY_URL",
            "http://localhost:18789"
        )

        with httpx.AsyncClient(timeout=5.0) as client:
            return asyncio.run(
                client.post(
                    f"{openclaw_url}/notify",
                    json={
                        "message": message,
                        "channel": channel
                    }
                )
            )

    except Exception:
        return None


def notify_via_email(message, to_email):
    from execution.email_executor import send_single_email

    try:
        return send_single_email(
            to_email,
            "Executa Agent Update",
            message
        )
    except Exception:
        return None


async def run_scheduler_tick():
    """
    Runs every hour. Checks for due jobs and executes them.
    Call this from the FastAPI startup event.
    """

    while True:
        try:
            due_jobs = get_due_jobs()

            if due_jobs:
                print(
                    f"🕐 Scheduler tick — "
                    f"{len(due_jobs)} jobs due"
                )

                for job in due_jobs:
                    print(
                        f"  ▶ Running: {job.get('agent_type')} "
                        f"for user {job.get('user_id')}"
                    )

                    await asyncio.to_thread(
                        execute_job,
                        job
                    )
            else:
                print("🕐 Scheduler tick — no jobs due")

        except Exception as e:
            print(f"Scheduler error: {e}")

        await asyncio.sleep(3600)
