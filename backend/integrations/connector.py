from integrations.vault import get_credential, store_credential


def get_connected_apps(user_id, suggested_apps):
    connected = {}

    for app in suggested_apps:
        cred = get_credential(user_id, app)

        if cred is None:
            continue

        connected[app] = cred

    return connected


def connect_app(user_id, app_name, credential):
    success = store_credential(user_id, app_name, credential)

    if success:
        return {
            "success": True,
            "app": app_name,
            "message": "Connected successfully"
        }

    return {
        "success": False,
        "app": app_name,
        "message": "Failed to connect"
    }


def get_webhook_apps():
    return [
        "Webhooks",
        "Custom HTTP",
        "Zapier",
        "Make",
        "n8n"
    ]


def build_app_context(user_id, suggested_apps):
    context = {}

    for app_item in suggested_apps:

        if isinstance(app_item, dict):
            app_name = app_item.get("app", "")
        else:
            app_name = app_item

        if not app_name:
            continue

        credential = get_credential(user_id, app_name)

        if credential:
            context[app_name] = {
                "connected": True,
                "credential": credential
            }
        else:
            context[app_name] = {
                "connected": False
            }

    return context


def list_connected_apps(user_id):
    from integrations.vault import list_connected_apps as vault_list

    return vault_list(user_id)
