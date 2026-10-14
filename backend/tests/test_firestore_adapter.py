import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import AsyncClient

from app.adapters.firestore_adapter import (
    FirestoreAdapter,
    serialize_firestore_doc,
    serialize_firestore_value,
)
from app.config.database import get_database_backend, is_firestore_backend, is_mongodb_backend
from app.config.firestore_config import get_firestore_settings
from app.config.firestore_db import close_firestore, connect_firestore, get_firestore_client


# ===========================================================================
# 1. Backend Selection & Configuration Tests
# ===========================================================================

def test_default_backend_is_mongodb():
    """Verify that when DATABASE_BACKEND is unset, MongoDB is the default."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DATABASE_BACKEND", None)
        assert get_database_backend() == "mongodb"
        assert is_mongodb_backend() is True
        assert is_firestore_backend() is False


def test_explicit_firestore_backend_selection():
    """Verify that setting DATABASE_BACKEND=firestore switches the selection."""
    with patch.dict(os.environ, {"DATABASE_BACKEND": "firestore"}):
        assert get_database_backend() == "firestore"
        assert is_firestore_backend() is True
        assert is_mongodb_backend() is False


def test_explicit_firebase_alias_selection():
    """Verify that setting DATABASE_BACKEND=firebase is recognized as firestore."""
    with patch.dict(os.environ, {"DATABASE_BACKEND": "firebase"}):
        assert get_database_backend() == "firestore"
        assert is_firestore_backend() is True


def test_unknown_backend_falls_back_to_mongodb():
    """Verify that any unrecognized backend setting safely defaults to mongodb."""
    with patch.dict(os.environ, {"DATABASE_BACKEND": "unknown_db_engine"}):
        assert get_database_backend() == "mongodb"
        assert is_mongodb_backend() is True


def test_firestore_settings_defaults():
    """Verify default Firestore settings when environment variables are omitted."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FIRESTORE_PROJECT_ID", None)
        os.environ.pop("FIRESTORE_DATABASE_ID", None)
        os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        settings = get_firestore_settings()
        assert settings["project_id"] == "ai-client-outreach-dev"
        assert settings["database_id"] == "(default)"
        assert settings["emulator_host"] is None
        assert settings["is_emulator"] is False


def test_firestore_settings_with_emulator():
    """Verify that FIRESTORE_EMULATOR_HOST is correctly detected."""
    with patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}):
        settings = get_firestore_settings()
        assert settings["emulator_host"] == "127.0.0.1:8080"
        assert settings["is_emulator"] is True


# ===========================================================================
# 2. Serialization & ID Mapping Tests
# ===========================================================================

def test_serialize_firestore_value():
    """Verify serialization of datetimes and nested data structures."""
    now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    raw = {
        "string": "value",
        "number": 42,
        "date": now,
        "nested": {"date": now, "list": [now, "plain"]},
    }
    serialized = serialize_firestore_value(raw)
    assert serialized["date"] == now.isoformat()
    assert serialized["nested"]["date"] == now.isoformat()
    assert serialized["nested"]["list"][0] == now.isoformat()
    assert serialized["nested"]["list"][1] == "plain"


def test_serialize_firestore_doc_id_mapping():
    """Verify that serialize_firestore_doc guarantees both _id and id fields."""
    doc = {"companyName": "Acme Corp", "website": "acme.com"}
    serialized = serialize_firestore_doc(doc, doc_id="company_12345")
    assert serialized["_id"] == "company_12345"
    assert serialized["id"] == "company_12345"
    assert serialized["companyName"] == "Acme Corp"


def test_serialize_firestore_doc_preserves_existing_id():
    """Verify that an existing _id or id is mirrored to the other field."""
    doc_with_underscore = {"_id": "doc_abc", "val": 1}
    serialized1 = serialize_firestore_doc(doc_with_underscore)
    assert serialized1["_id"] == "doc_abc"
    assert serialized1["id"] == "doc_abc"

    doc_with_plain = {"id": "doc_xyz", "val": 2}
    serialized2 = serialize_firestore_doc(doc_with_plain)
    assert serialized2["_id"] == "doc_xyz"
    assert serialized2["id"] == "doc_xyz"


# ===========================================================================
# 3. Client Initialization & Lifecycle Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_connect_and_close_firestore_with_emulator():
    """Verify connect_firestore initializes an AsyncClient in emulator mode without cloud calls."""
    with patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}):
        client = await connect_firestore(project_id="test-emulator-project")
        try:
            assert client is not None
            assert isinstance(client, AsyncClient)
            assert client.project == "test-emulator-project"
            assert get_firestore_client() is client
        finally:
            await close_firestore()
            assert get_firestore_client() is None


# ===========================================================================
# 4. FirestoreAdapter Operation & Mock Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_adapter_get_document_exists():
    """Verify adapter retrieves and serializes an existing document."""
    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_doc_ref = MagicMock()
    mock_snapshot = MagicMock()

    mock_snapshot.exists = True
    mock_snapshot.id = "comp_1"
    mock_snapshot.to_dict.return_value = {"companyName": "Test Co", "website": "test.com"}
    mock_doc_ref.get = AsyncMock(return_value=mock_snapshot)
    mock_col.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_col

    adapter = FirestoreAdapter(client=mock_client)
    result = await adapter.get_document("companies", "comp_1")

    assert result is not None
    assert result["_id"] == "comp_1"
    assert result["id"] == "comp_1"
    assert result["companyName"] == "Test Co"
    mock_col.document.assert_called_once_with("comp_1")


@pytest.mark.asyncio
async def test_adapter_get_document_not_found():
    """Verify adapter returns None for nonexistent documents."""
    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_doc_ref = MagicMock()
    mock_snapshot = MagicMock()

    mock_snapshot.exists = False
    mock_doc_ref.get = AsyncMock(return_value=mock_snapshot)
    mock_col.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_col

    adapter = FirestoreAdapter(client=mock_client)
    result = await adapter.get_document("companies", "missing_id")

    assert result is None


@pytest.mark.asyncio
async def test_adapter_set_document():
    """Verify adapter sets document with merge=True."""
    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_col.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_col

    adapter = FirestoreAdapter(client=mock_client)
    data = {"companyName": "New Corp", "industry": "AI"}
    saved = await adapter.set_document("companies", "comp_2", data, merge=True)

    assert saved["_id"] == "comp_2"
    assert saved["companyName"] == "New Corp"
    mock_doc_ref.set.assert_called_once_with(data, merge=True)


@pytest.mark.asyncio
async def test_adapter_delete_document():
    """Verify adapter deletes document by ID."""
    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_ref.delete = AsyncMock()
    mock_col.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_col

    adapter = FirestoreAdapter(client=mock_client)
    success = await adapter.delete_document("companies", "comp_delete")

    assert success is True
    mock_doc_ref.delete.assert_called_once()


@pytest.mark.asyncio
async def test_adapter_batch_delete():
    """Verify adapter processes chunked batch deletions within Firestore limits."""
    mock_client = MagicMock()
    mock_col = MagicMock()
    mock_batch = MagicMock()
    mock_batch.commit = AsyncMock()
    mock_client.batch.return_value = mock_batch
    mock_client.collection.return_value = mock_col

    adapter = FirestoreAdapter(client=mock_client)
    doc_ids = [f"doc_{i}" for i in range(10)]
    deleted_count = await adapter.batch_delete("companies", doc_ids, chunk_size=5)

    assert deleted_count == 10
    # Two chunks of 5 items should trigger two batch commits
    assert mock_batch.commit.await_count == 2
