import os
import base64
import hashlib
from cryptography.fernet import Fernet


_vault = {}


def _get_fernet():
    secret_key = os.environ.get("SECRET_KEY")

    if not secret_key:
        raise ValueError(
            "SECRET_KEY not found in environment variables."
        )

    digest = hashlib.sha256(
        secret_key.encode("utf-8")
    ).digest()

    fernet_key = base64.urlsafe_b64encode(digest)

    return Fernet(fernet_key)


def store_credential(user_id: str, app_name: str, credential: str) -> bool:
    try:
        f = _get_fernet()

        encrypted_cred = f.encrypt(
            credential.encode("utf-8")
        )

        key = f"{user_id}:{app_name}"

        _vault[key] = encrypted_cred

        return True

    except Exception as e:
        print(f"Error storing credential: {e}")
        return False


def get_credential(user_id: str, app_name: str) -> str | None:
    try:
        f = _get_fernet()

        key = f"{user_id}:{app_name}"

        encrypted_cred = _vault.get(key)

        if encrypted_cred is None:
            return None

        decrypted_cred = (
            f.decrypt(encrypted_cred)
            .decode("utf-8")
        )

        return decrypted_cred

    except Exception as e:
        print(f"Error retrieving credential: {e}")
        return None


def list_connected_apps(user_id: str) -> list:
    connected_apps = []

    prefix = f"{user_id}:"

    for key in _vault.keys():
        if key.startswith(prefix):
            app_name = key[len(prefix):]
            connected_apps.append(app_name)

    return connected_apps
