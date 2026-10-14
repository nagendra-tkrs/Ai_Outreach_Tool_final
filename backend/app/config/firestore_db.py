import logging
from typing import Optional, Any
from google.cloud.firestore import AsyncClient
from google.auth.credentials import AnonymousCredentials
from app.config.firestore_config import get_firestore_settings

logger = logging.getLogger("firestore_db")

firestore_client: Optional[AsyncClient] = None


async def connect_firestore(
    project_id: Optional[str] = None,
    database_id: Optional[str] = None,
    emulator_host: Optional[str] = None,
    credentials: Optional[Any] = None,
) -> AsyncClient:
    """Initialize and return an asynchronous Firestore client.

    If emulator_host is configured (via parameter or FIRESTORE_EMULATOR_HOST env var),
    the client runs strictly in offline emulator mode using AnonymousCredentials if
    no credentials are provided, guaranteeing zero cloud requests.
    """
    global firestore_client

    settings = get_firestore_settings()
    proj = project_id or settings["project_id"]
    db_id = database_id or settings["database_id"]
    emu_host = emulator_host or settings["emulator_host"]

    try:
        # Determine credentials
        creds = credentials
        if emu_host and creds is None:
            # Use AnonymousCredentials to prevent SDK from attempting metadata lookup
            creds = AnonymousCredentials()

        kwargs = {"project": proj}
        if db_id and db_id != "(default)":
            kwargs["database"] = db_id
        if creds is not None:
            kwargs["credentials"] = creds

        firestore_client = AsyncClient(**kwargs)

        if emu_host:
            logger.info(f"Connected to Firestore Emulator at {emu_host} (project={proj})")
        else:
            logger.info(f"Initialized Firestore AsyncClient for project={proj}")

        return firestore_client
    except Exception as e:
        logger.error(f"Error initializing Firestore AsyncClient: {e}", exc_info=True)
        raise


async def close_firestore() -> None:
    """Gracefully close the Firestore AsyncClient session."""
    global firestore_client
    if firestore_client is not None:
        try:
            firestore_client.close()
            logger.info("Firestore AsyncClient connection closed.")
        except Exception as e:
            logger.warning(f"Error while closing Firestore client: {e}")
        finally:
            firestore_client = None


def get_firestore_client() -> Optional[AsyncClient]:
    """Retrieve the currently initialized Firestore AsyncClient instance."""
    global firestore_client
    return firestore_client
