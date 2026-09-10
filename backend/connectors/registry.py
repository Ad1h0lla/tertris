import uuid
import httpx
from datetime import datetime, timezone


_connectors = {}


def register_connector(
    user_id: str,
    name: str,
    webhook_url: str,
    payload_schema: dict,
    trigger_phase: int,
    trigger_event: str
) -> dict:
    try:
        connector_id = str(uuid.uuid4())

        connector = {
            "id": connector_id,
            "user_id": user_id,
            "name": name,
            "webhook_url": webhook_url,
            "payload_schema": payload_schema,
            "trigger_phase": trigger_phase,
            "trigger_event": trigger_event,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        _connectors[connector_id] = connector

        return {
            "success": True,
            "connector_id": connector_id,
            "name": name,
            "webhook_url": webhook_url,
            "trigger_phase": trigger_phase
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_connectors(user_id: str) -> list:
    try:
        return [
            c
            for c in _connectors.values()
            if c.get("user_id") == user_id
        ]
    except Exception:
        return []


def fire_connectors(
    user_id: str,
    phase: int,
    event: str,
    payload: dict
) -> list:
    results = []

    try:
        matching_connectors = [
            c
            for c in _connectors.values()
            if (
                c.get("user_id") == user_id
                and c.get("trigger_phase") == phase
                and c.get("trigger_event") == event
                and c.get("active", True)
            )
        ]

        for c in matching_connectors:
            url = c.get("webhook_url")
            name = c.get("name")

            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=10.0
                )

                success = response.status_code in (
                    200,
                    201,
                    202,
                    204
                )

                results.append({
                    "connector_name": name,
                    "success": success,
                    "status_code": response.status_code
                })

            except Exception:
                results.append({
                    "connector_name": name,
                    "success": False,
                    "status_code": None
                })

        return results

    except Exception as e:
        return [{
            "connector_name": "unknown",
            "success": False,
            "error": str(e)
        }]


def test_connector(connector_id: str) -> dict:
    try:
        connector = _connectors.get(connector_id)

        if not connector:
            return {
                "success": False,
                "status_code": None,
                "connector_id": connector_id,
                "error": "Connector not found"
            }

        url = connector.get("webhook_url")

        test_payload = {
            "test": True,
            "message": "Test from Executa Engine"
        }

        try:
            response = httpx.post(
                url,
                json=test_payload,
                timeout=10.0
            )

            success = response.status_code in (
                200,
                201,
                202,
                204
            )

            return {
                "success": success,
                "status_code": response.status_code,
                "connector_id": connector_id
            }

        except Exception:
            return {
                "success": False,
                "status_code": None,
                "connector_id": connector_id
            }

    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "connector_id": connector_id,
            "error": str(e)
        }


def delete_connector(connector_id: str) -> dict:
    try:
        if connector_id in _connectors:
            del _connectors[connector_id]

            return {
                "success": True,
                "deleted_id": connector_id
            }

        return {
            "success": False,
            "error": "Connector not found"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
