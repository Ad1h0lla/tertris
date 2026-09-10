import os
import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from integrations.connectors.registry import check_credentials_for_connector


async def execute_google_sheets(action, params):
    api_key = os.getenv("GOOGLE_SHEETS_API_KEY")
    spreadsheet_id = params.get(
        "spreadsheet_id",
        os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    )
    range_name = params.get("range", "Sheet1!A1")

    if not spreadsheet_id:
        return {
            "error": "Missing spreadsheet_id parameter or GOOGLE_SHEETS_SPREADSHEET_ID in .env"
        }

    async with httpx.AsyncClient() as client:
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values/{range_name}"
        )

        if action == "append_row":
            row = params.get("row", [])

            payload = {
                "values": [row] if isinstance(row, list) else [[row]]
            }

            res = await client.post(
                url + ":append",
                params={
                    "valueInputOption": "USER_ENTERED",
                    "key": api_key,
                },
                json=payload,
            )

            res.raise_for_status()

            return {
                "success": True,
                "result": res.json(),
            }

        if action == "read_rows":
            res = await client.get(
                url,
                params={"key": api_key},
            )

            res.raise_for_status()

            return {
                "success": True,
                "result": res.json(),
            }

        return {
            "error": f"Unsupported action '{action}' for Google Sheets"
        }


async def execute_notion(action, params):
    key = os.getenv("NOTION_API_KEY")

    headers = {
        "Authorization": f"Bearer {key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:

        if action == "create_page":
            body = {
                "parent": {
                    "database_id": params.get("database_id")
                },
                "properties": params.get("properties", {}),
            }

            res = await client.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=body,
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "page_url": res_json.get("url"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Notion"
        }


async def execute_github(action, params):
    token = os.getenv("GITHUB_TOKEN")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "FastAPI-Connector-Executor",
    }

    async with httpx.AsyncClient() as client:

        if action == "create_issue":
            owner = params.get("owner")
            repo = params.get("repo")
            title = params.get("title")
            body = params.get("body", "")

            if not owner or not repo or not title:
                return {
                    "error": "Missing required parameters: owner, repo, and title"
                }

            url = (
                f"https://api.github.com/repos/"
                f"{owner}/{repo}/issues"
            )

            res = await client.post(
                url,
                headers=headers,
                json={
                    "title": title,
                    "body": body,
                },
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "issue_url": res_json.get("html_url"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for GitHub"
        }


async def execute_airtable(action, params):
    key = os.getenv("AIRTABLE_API_KEY")

    base_id = params.get(
        "base_id",
        os.getenv("AIRTABLE_BASE_ID")
    )

    table_name = params.get("table_name", "Table 1")

    if not base_id:
        return {
            "error": "Missing base_id parameter or AIRTABLE_BASE_ID in .env"
        }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:

        if action == "create_record":
            fields = params.get("fields", {})

            url = (
                f"https://api.airtable.com/v0/"
                f"{base_id}/{table_name}"
            )

            res = await client.post(
                url,
                headers=headers,
                json={"fields": fields},
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "record_id": res_json.get("id"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Airtable"
        }


async def execute_discord(action, params):
    token = os.getenv("DISCORD_BOT_TOKEN")

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:

        if action == "send_message":
            channel_id = params.get("channel_id")
            content = params.get("content")

            if not channel_id or not content:
                return {
                    "error": "Missing required parameters: channel_id and content"
                }

            url = (
                f"https://discord.com/api/v10/channels/"
                f"{channel_id}/messages"
            )

            res = await client.post(
                url,
                headers=headers,
                json={"content": content},
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "message_id": res_json.get("id"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Discord"
        }


async def execute_slack(action, params):
    token = os.getenv("SLACK_BOT_TOKEN")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:

        if action == "send_message":
            channel = params.get("channel")
            text = params.get("text")

            if not channel or not text:
                return {
                    "error": "Missing required parameters: channel and text"
                }

            url = "https://slack.com/api/chat.postMessage"

            res = await client.post(
                url,
                headers=headers,
                json={
                    "channel": channel,
                    "text": text,
                },
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "ts": res_json.get("ts"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Slack"
        }


async def execute_stripe(action, params):
    key = os.getenv("STRIPE_SECRET_KEY", "")

    auth = (key, "")

    async with httpx.AsyncClient() as client:

        if action == "create_product":
            res = await client.post(
                "https://api.stripe.com/v1/products",
                auth=auth,
                data={
                    "name": params.get("name"),
                    "description": params.get("description", ""),
                },
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "product_id": res_json.get("id"),
                "response": res_json,
            }

        if action == "create_price":
            res = await client.post(
                "https://api.stripe.com/v1/prices",
                auth=auth,
                data={
                    "product": params.get("product"),
                    "unit_amount": params.get("unit_amount"),
                    "currency": params.get("currency", "usd"),
                    "recurring[interval]": params.get(
                        "interval",
                        "month"
                    ),
                },
            )

            res.raise_for_status()

            res_json = res.json()

            return {
                "success": True,
                "price_id": res_json.get("id"),
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Stripe"
        }


async def execute_telegram(action, params):
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    async with httpx.AsyncClient() as client:

        if action == "send_message":
            chat_id = params.get("chat_id")
            text = params.get("text")

            if not chat_id or not text:
                return {
                    "error": "Missing required parameters: chat_id and text"
                }

            url = (
                f"https://api.telegram.org/bot"
                f"{token}/sendMessage"
            )

            res = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                },
            )

            res.raise_for_status()

            res_json = res.json()

            message = res_json.get("result", {})
            message_id = message.get("message_id")

            return {
                "success": True,
                "message_id": message_id,
                "response": res_json,
            }

        return {
            "error": f"Unsupported action '{action}' for Telegram"
        }


async def execute_supabase(action, params):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    table = params.get("table")

    if not table:
        return {
            "error": "Missing table parameter"
        }

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    async with httpx.AsyncClient() as client:

        endpoint = (
            url.rstrip("/")
            + "/rest/v1/"
            + table
        )

        if action == "insert_row":
            row = params.get("row", {})

            res = await client.post(
                endpoint,
                headers=headers,
                json=row,
            )

            res.raise_for_status()

            return {
                "success": True,
                "record": res.json(),
            }

        if action == "select_rows":
            query_params = params.get("query_params", {})

            res = await client.get(
                endpoint,
                headers=headers,
                params=query_params,
            )

            res.raise_for_status()

            return {
                "success": True,
                "result": res.json(),
            }

        return {
            "error": f"Unsupported action '{action}' for Supabase"
        }


async def execute_webhook(action, params):
    webhook_url = params.get(
        "webhook_url",
        os.getenv("WEBHOOK_URL")
    )

    if not webhook_url:
        return {
            "error": "webhook_url parameter or WEBHOOK_URL env is missing"
        }

    body = params.get("body", params)

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                webhook_url,
                json=body,
            )

            res.raise_for_status()

            return {
                "success": True,
                "status_code": res.status_code,
                "body": res.json(),
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def execute_http_request(action, params):
    method = params.get("method", "GET").upper()

    url = params.get(
        "url",
        os.getenv("API_URL")
    )

    if not url:
        return {
            "error": "url parameter or API_URL env is missing"
        }

    headers = params.get("headers", {})
    body = params.get("body")

    try:
        async with httpx.AsyncClient() as client:

            if method == "GET":
                res = await client.get(
                    url,
                    headers=headers,
                    params=params.get("query_params", {}),
                )

            elif method == "POST":
                res = await client.post(
                    url,
                    headers=headers,
                    json=body,
                )

            elif method == "PUT":
                res = await client.put(
                    url,
                    headers=headers,
                    json=body,
                )

            elif method == "DELETE":
                res = await client.delete(
                    url,
                    headers=headers,
                )

            elif method == "PATCH":
                res = await client.patch(
                    url,
                    headers=headers,
                    json=body,
                )

            else:
                return {
                    "error": f"Unsupported HTTP method: {method}"
                }

            res.raise_for_status()

            try:
                response_body = res.json()
            except Exception:
                response_body = res.text

            return {
                "success": True,
                "status_code": res.status_code,
                "body": response_body,
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def execute_connector_action(
    connector_id: str,
    action: str,
    params: dict
) -> dict:

    status = check_credentials_for_connector(connector_id)

    if status.get("error"):
        return status

    if not status.get("ready"):
        missing_cred = status.get("missing", [])

        return {
            "success": False,
            "error": f"{connector_id} not configured",
            "action_required": f"Add {', '.join(missing_cred)} to .env",
        }

    try:

        if connector_id == "google_sheets":
            result = await execute_google_sheets(action, params)

        elif connector_id == "notion":
            result = await execute_notion(action, params)

        elif connector_id == "github":
            result = await execute_github(action, params)

        elif connector_id == "airtable":
            result = await execute_airtable(action, params)

        elif connector_id == "discord":
            result = await execute_discord(action, params)

        elif connector_id == "slack":
            result = await execute_slack(action, params)

        elif connector_id == "stripe":
            result = await execute_stripe(action, params)

        elif connector_id == "telegram":
            result = await execute_telegram(action, params)

        elif connector_id == "supabase":
            result = await execute_supabase(action, params)

        elif connector_id == "webhook":
            result = await execute_webhook(action, params)

        elif connector_id == "http_request":
            result = await execute_http_request(action, params)

        else:
            return {
                "success": False,
                "error": (
                    f"Connector execution for "
                    f"'{connector_id}' is not yet implemented"
                ),
            }

        return {
            "success": True,
            "connector": connector_id,
            "action": action,
            "result": result,
        }

    except Exception as e:
        return {
            "success": False,
            "connector": connector_id,
            "action": action,
            "error": str(e),
        }
