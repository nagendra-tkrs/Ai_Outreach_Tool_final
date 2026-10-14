import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BACKEND = "mongodb"
DEFAULT_FIRESTORE_PROJECT = "ai-client-outreach-dev"
DEFAULT_FIRESTORE_DATABASE = "(default)"


def get_database_backend() -> str:
    """Return the configured database backend engine.

    Defaults to 'mongodb' to preserve existing behavior and ensure no unintended
    switch occurs unless explicitly requested via DATABASE_BACKEND environment variable.
    """
    backend = os.getenv("DATABASE_BACKEND", DEFAULT_BACKEND).strip().lower()
    if backend in ("firestore", "firebase"):
        return "firestore"
    return "mongodb"


def is_firestore_backend() -> bool:
    """Check if the active database backend is configured as Firestore."""
    return get_database_backend() == "firestore"


def is_mongodb_backend() -> bool:
    """Check if the active database backend is configured as MongoDB."""
    return get_database_backend() == "mongodb"


def get_firestore_settings() -> Dict[str, Any]:
    """Retrieve Firestore configuration from environment variables without exposing secrets."""
    project_id = os.getenv("FIRESTORE_PROJECT_ID", DEFAULT_FIRESTORE_PROJECT).strip()
    database_id = os.getenv("FIRESTORE_DATABASE_ID", DEFAULT_FIRESTORE_DATABASE).strip()
    emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if emulator_host:
        emulator_host = emulator_host.strip()

    if credentials_path:
        credentials_path = credentials_path.strip()

    return {
        "project_id": project_id,
        "database_id": database_id,
        "emulator_host": emulator_host,
        "credentials_path": credentials_path,
        "is_emulator": bool(emulator_host),
    }
