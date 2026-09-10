import uuid
import json
from datetime import datetime, timedelta

from llm.router import get_llm_response


class BotFactory:
    """Creates and manages autonomous bots."""

    def __init__(self):
        self._bots = {}

    def create_marketing_bot(
        self,
        goal: str,
        campaign_content: str,
        credentials: dict,
        user_id: str,
    ) -> dict:
        """
        Creates a Reddit marketing bot.
        Extracts posts from campaign content and queues them for posting.
        """

        bot_id = str(uuid.uuid4())
        posts = self._extract_reddit_posts(campaign_content)

        bot = {
            "bot_id": bot_id,
            "type": "reddit_marketing",
            "label": "Reddit Marketing Bot",
            "user_id": user_id,
            "goal": goal,
            "status": "active",
            "posts_queue": posts,
            "posts_sent": 0,
            "created_at": datetime.utcnow().isoformat(),
            "next_post_at": datetime.utcnow().isoformat(),
            "interval_hours": 48,
            "credentials": credentials,
            "performance": {
                "upvotes": 0,
                "comments": 0,
                "clicks": 0,
            },
        }

        self._bots[bot_id] = bot

        return {
            "success": True,
            "bot_id": bot_id,
            "type": "reddit_marketing",
            "posts_queued": len(posts),
            "message": f"Reddit bot created — {len(posts)} posts queued",
        }

    def create_seo_bot(
        self,
        goal: str,
        keywords: str,
        website_url: str,
        user_id: str,
    ) -> dict:
        """
        Creates an SEO monitoring bot.
        Tracks keyword rankings and surfaces optimization suggestions.
        """

        bot_id = str(uuid.uuid4())
        keyword_list = self._extract_keywords(keywords)

        bot = {
            "bot_id": bot_id,
            "type": "seo_monitor",
            "label": "SEO Monitor Bot",
            "user_id": user_id,
            "goal": goal,
            "status": "active",
            "keywords": keyword_list,
            "website_url": website_url,
            "created_at": datetime.utcnow().isoformat(),
            "next_check_at": (
                datetime.utcnow() + timedelta(hours=24)
            ).isoformat(),
            "interval_hours": 168,
            "rankings": {},
            "last_report": None,
        }

        self._bots[bot_id] = bot

        return {
            "success": True,
            "bot_id": bot_id,
            "type": "seo_monitor",
            "keywords_tracked": len(keyword_list),
            "message": f"SEO bot tracking {len(keyword_list)} keywords",
        }

    def create_email_bot(
        self,
        goal: str,
        campaign_content: str,
        sendgrid_key: str,
        user_id: str,
    ) -> dict:
        """
        Creates an email sequence bot.
        Extracts email sequences from campaign output and schedules them.
        """

        bot_id = str(uuid.uuid4())
        emails = self._extract_emails(campaign_content)

        bot = {
            "bot_id": bot_id,
            "type": "email_sequence",
            "label": "Email Sequence Bot",
            "user_id": user_id,
            "goal": goal,
            "status": "active",
            "email_queue": emails,
            "emails_sent": 0,
            "subscribers": [],
            "created_at": datetime.utcnow().isoformat(),
            "next_send_at": datetime.utcnow().isoformat(),
            "interval_hours": 72,
            "sendgrid_key": sendgrid_key,
            "performance": {
                "open_rate": 0,
                "click_rate": 0,
                "unsubscribes": 0,
            },
        }

        self._bots[bot_id] = bot

        return {
            "success": True,
            "bot_id": bot_id,
            "type": "email_sequence",
            "emails_queued": len(emails),
            "message": f"Email bot created — {len(emails)} emails in sequence",
        }

    def create_support_bot(
        self,
        goal: str,
        product_context: str,
        user_id: str,
    ) -> dict:
        """
        Creates a customer support bot.
        Generates FAQ responses using the product context via LLM.
        """

        bot_id = str(uuid.uuid4())
        faqs = self._generate_faqs(goal, product_context)

        bot = {
            "bot_id": bot_id,
            "type": "customer_support",
            "label": "Support Bot",
            "user_id": user_id,
            "goal": goal,
            "status": "active",
            "faqs": faqs,
            "conversations_handled": 0,
            "created_at": datetime.utcnow().isoformat(),
            "context": product_context[:1000],
        }

        self._bots[bot_id] = bot

        return {
            "success": True,
            "bot_id": bot_id,
            "type": "customer_support",
            "faqs_loaded": len(faqs),
            "message": f"Support bot ready — {len(faqs)} FAQ responses loaded",
        }

    def get_active_bots(self, user_id: str) -> list:
        """Returns all active bots for a user without credentials."""

        result = []

        for bot in self._bots.values():
            if bot["user_id"] != user_id:
                continue

            safe = {
                k: v
                for k, v in bot.items()
                if k not in ("credentials", "sendgrid_key")
            }

            result.append(safe)

        return result

    def get_bot(self, bot_id: str) -> dict:
        bot = self._bots.get(bot_id)

        if not bot:
            return None

        return {
            k: v
            for k, v in bot.items()
            if k not in ("credentials", "sendgrid_key")
        }

    def _extract_reddit_posts(self, content: str) -> list:
        posts = []
        current = {}
        in_post = False

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("REDDIT_POST"):
                if current:
                    posts.append(current)

                current = {}
                in_post = True
                continue

            if not in_post:
                continue

            if line.startswith("##"):
                continue

            if line.startswith("Subreddit:"):
                current["subreddit"] = (
                    line.replace("Subreddit:", "")
                    .replace("r/", "")
                    .strip()
                )

            elif line.startswith("Title:"):
                current["title"] = line.replace("Title:", "").strip()

            elif line.startswith("Body:"):
                current["body"] = line.replace("Body:", "").strip()

        if current:
            posts.append(current)

        return posts[:3]

    def _extract_keywords(self, content: str) -> list:
        keywords = []
        in_section = False

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("SEO_KEYWORDS"):
                in_section = True
                continue

            if not in_section:
                continue

            if line.startswith("##"):
                continue

            if ":" in line:
                line = line.split(":", 1)[1].strip()

            if line.startswith("-"):
                line = line.lstrip("-").strip()

            if line:
                keywords.append(line)

        return keywords[:10]

    def _extract_emails(self, content: str) -> list:
        emails = []
        current = {}
        in_email = False

        email_types = (
            "EMAIL_WELCOME",
            "EMAIL_FOLLOWUP",
            "EMAIL_CONVERSION",
        )

        for line in content.split("\n"):
            line = line.strip()

            if any(line.startswith(email_type) for email_type in email_types):
                if current:
                    emails.append(current)

                current = {}
                in_email = True
                continue

            if not in_email:
                continue

            if line.startswith("Subject:"):
                current["subject"] = (
                    line.replace("Subject:", "").strip()
                )

            elif line.startswith("Body:"):
                current["body"] = line.replace("Body:", "").strip()

            elif line.startswith("##"):
                continue

        if current:
            emails.append(current)

        return emails[:5]

    def _generate_faqs(self, goal: str, context: str) -> list:
        prompt = (
            "Generate 8 common customer support questions and answers for: "
            + goal
            + "\nContext: "
            + context[:300]
            + '\nReturn ONLY a JSON array: '
              '[{"question": "", "answer": ""}]'
        )

        try:
            raw = get_llm_response(
                task="json_extraction",
                system_prompt=(
                    "You generate customer support FAQs. "
                    "Return only a JSON array. No markdown."
                ),
                user_message=prompt,
                max_tokens=1000,
                temperature=0.3,
            )

            clean = raw.strip()

            if clean.startswith("```json"):
                clean = clean.replace("```json", "", 1)

            if clean.endswith("```"):
                clean = clean[:-3]

            parsed = json.loads(clean.strip())

            if isinstance(parsed, list):
                return parsed

        except Exception:
            pass

        return [
            {
                "question": "How does this work?",
                "answer": "How do I get started?",
            },
            {
                "question": "What does this cost?",
                "answer": "See our pricing page for details.",
            },
            {
                "question": "How do I contact support?",
                "answer": "Use the chat widget on our site.",
            },
        ]


# IMPORTANT: main_working.py imports THIS OBJECT.
bot_factory = BotFactory()
