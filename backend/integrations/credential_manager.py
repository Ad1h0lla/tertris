import os
import base64

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from database.operations import (
    get_credential,
    store_credential,
    list_credentials,
    delete_credential,
)

load_dotenv()

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "default_secret_key_needs_to_be_32_characters_long"
)

fernet_key = base64.urlsafe_b64encode(
    SECRET_KEY.encode().ljust(32)[:32]
)

cipher = Fernet(fernet_key)


def encrypt_credential(raw: str) -> str:
    """Uses Fernet symmetric encryption to encrypt a string."""
    if not raw:
        return ""

    encrypted_bytes = cipher.encrypt(raw.encode())
    return encrypted_bytes.decode()


def decrypt_credential(encrypted: str) -> str:
    """Decrypts a Fernet encrypted string. Returns empty string on failure."""
    if not encrypted:
        return ""

    try:
        decrypted_bytes = cipher.decrypt(encrypted.encode())
        return decrypted_bytes.decode()
    except Exception:
        return ""


def connect_app(
    db,
    user_id: str,
    app_name: str,
    raw_credential: str,
    connection_type: str,
    display_name: str,
):
    """Encrypts credential and stores it in the database."""

    encrypted = encrypt_credential(raw_credential)

    store_credential(
        db=db,
        user_id=user_id,
        app_name=app_name.lower(),
        credential_encrypted=encrypted,
        connection_type=connection_type,
        display_name=display_name,
    )

    return {
        "success": True,
        "app_name": app_name,
        "message": "Connected successfully",
    }


def get_decrypted_credential(
    db,
    user_id: str,
    app_name: str,
) -> str | None:
    """Gets encrypted credential from database and decrypts it."""

    encrypted = get_credential(
        db,
        user_id,
        app_name.lower()
    )

    if not encrypted:
        return None

    return decrypt_credential(encrypted)


def get_connected_apps(
    db,
    user_id: str,
) -> list:
    """Returns list of all credentials/connected apps metadata."""

    return list_credentials(db, user_id)


def disconnect_app(
    db,
    user_id: str,
    app_name: str,
) -> dict:
    """Calls delete_credential to deactivate a credential."""

    delete_credential(
        db,
        user_id,
        app_name.lower()
    )

    return {
        "success": True,
        "message": f"{app_name} disconnected",
    }
