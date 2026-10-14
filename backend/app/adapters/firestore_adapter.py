import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from google.cloud import firestore
from google.cloud.firestore import AsyncClient, AsyncTransaction
from google.cloud.firestore_v1.transforms import Increment

from app.config.firestore_db import get_firestore_client


def serialize_firestore_value(val: Any) -> Any:
    """Recursively converts Firestore types (Timestamp, Datetime, etc.) to JSON-friendly formats."""
    if val is None:
        return None
    if isinstance(val, (datetime,)):
        return val.isoformat()
    # Check for Firestore DatetimeWithNanoseconds or protobuf Timestamp
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: serialize_firestore_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [serialize_firestore_value(item) for item in val]
    return val


def serialize_firestore_doc(data: Optional[Dict[str, Any]], doc_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Format a Firestore document dictionary to include standard string `_id` and `id` fields.

    Maintains 100% compatibility with frontend and services expecting either `_id` or `id`.
    """
    if data is None:
        return None
    res = serialize_firestore_value(dict(data))
    if doc_id:
        res["_id"] = str(doc_id)
        res["id"] = str(doc_id)
    elif "_id" in res and "id" not in res:
        res["id"] = str(res["_id"])
    elif "id" in res and "_id" not in res:
        res["_id"] = str(res["id"])
    return res


class FirestoreAdapter:
    """Asynchronous adapter for Cloud Firestore operations.

    Provides a clean, uniform interface for collections, documents, queries,
    atomic transactions, and batch operations.
    """

    def __init__(self, client: Optional[AsyncClient] = None):
        self._client = client

    @property
    def client(self) -> AsyncClient:
        if self._client is not None:
            return self._client
        client = get_firestore_client()
        if client is None:
            raise RuntimeError("Firestore AsyncClient is not initialized. Call connect_firestore() first.")
        return client

    def collection(self, collection_name: str):
        return self.client.collection(collection_name)

    async def get_document(self, collection_name: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single document by ID."""
        if not doc_id:
            return None
        doc_ref = self.collection(collection_name).document(str(doc_id))
        snap = await doc_ref.get()
        if not snap.exists:
            return None
        return serialize_firestore_doc(snap.to_dict(), doc_id=snap.id)

    async def set_document(
        self,
        collection_name: str,
        doc_id: str,
        data: Dict[str, Any],
        merge: bool = True,
    ) -> Dict[str, Any]:
        """Create or overwrite a document with specified ID."""
        doc_ref = self.collection(collection_name).document(str(doc_id))
        payload = dict(data)
        await doc_ref.set(payload, merge=merge)
        return serialize_firestore_doc(payload, doc_id=str(doc_id))

    async def insert_document(
        self,
        collection_name: str,
        data: Dict[str, Any],
        doc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a document with auto-generated or specified ID."""
        payload = dict(data)
        if doc_id:
            doc_ref = self.collection(collection_name).document(str(doc_id))
            await doc_ref.set(payload)
            generated_id = str(doc_id)
        else:
            doc_ref = self.collection(collection_name).document()
            generated_id = doc_ref.id
            await doc_ref.set(payload)

        return serialize_firestore_doc(payload, doc_id=generated_id)

    async def update_document(
        self,
        collection_name: str,
        doc_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update existing document fields."""
        if not doc_id:
            return False
        doc_ref = self.collection(collection_name).document(str(doc_id))
        await doc_ref.update(dict(updates))
        return True

    async def delete_document(self, collection_name: str, doc_id: str) -> bool:
        """Delete a document by ID."""
        if not doc_id:
            return False
        doc_ref = self.collection(collection_name).document(str(doc_id))
        await doc_ref.delete()
        return True

    async def find_documents(
        self,
        collection_name: str,
        filters: Optional[List[Tuple[str, str, Any]]] = None,
        order_by: Optional[Union[str, List[Union[str, Tuple[str, str]]]]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query documents with filtering, ordering, and pagination.

        filters: list of (field_path, op_string, value) tuples e.g. [("companyId", "==", cid)]
        order_by: field name or list of (field, direction) tuples where direction is 'ASC' or 'DESC'
        """
        query = self.collection(collection_name)

        if filters:
            for field, op, val in filters:
                query = query.where(field, op, val)

        if order_by:
            if isinstance(order_by, str):
                order_by = [order_by]
            for order_item in order_by:
                if isinstance(order_item, tuple):
                    field, direction = order_item
                    dir_enum = (
                        firestore.Query.DESCENDING
                        if str(direction).upper() in ("DESC", "DESCENDING", "-1", -1)
                        else firestore.Query.ASCENDING
                    )
                    query = query.order_by(field, direction=dir_enum)
                else:
                    query = query.order_by(str(order_item))

        if offset and offset > 0:
            query = query.offset(offset)

        if limit and limit > 0:
            query = query.limit(limit)

        results = []
        async for doc in query.stream():
            results.append(serialize_firestore_doc(doc.to_dict(), doc_id=doc.id))

        return results

    async def count_documents(
        self,
        collection_name: str,
        filters: Optional[List[Tuple[str, str, Any]]] = None,
    ) -> int:
        """Count documents matching the given filter."""
        query = self.collection(collection_name)
        if filters:
            for field, op, val in filters:
                query = query.where(field, op, val)

        count_query = query.count()
        snapshot = await count_query.get()
        return int(snapshot[0][0].value)

    async def increment_field(
        self,
        collection_name: str,
        doc_id: str,
        field: str,
        amount: int = 1,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Atomically increment a numerical field (e.g. openCount, clickCount)."""
        if not doc_id:
            return
        doc_ref = self.collection(collection_name).document(str(doc_id))
        updates: Dict[str, Any] = {field: Increment(amount)}
        if extra_fields:
            updates.update(extra_fields)
        await doc_ref.update(updates)

    async def conditional_update(
        self,
        collection_name: str,
        doc_id: str,
        expected_statuses: List[str],
        updates: Dict[str, Any],
        status_field: str = "status",
    ) -> Optional[Dict[str, Any]]:
        """Atomically update a document only if its current status matches one of expected_statuses.

        Replaces MongoDB's `find_one_and_update({"_id": id, "status": {"$in": [...]}})` with
        a Firestore Transaction, preventing race conditions during scheduler dispatch.
        """
        doc_ref = self.collection(collection_name).document(str(doc_id))
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def _apply_update(txn: AsyncTransaction):
            snapshot = await doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            current_data = snapshot.to_dict()
            current_status = current_data.get(status_field)
            if current_status not in expected_statuses:
                return None

            merged_data = {**current_data, **updates}
            txn.update(doc_ref, updates)
            return serialize_firestore_doc(merged_data, doc_id=doc_ref.id)

        return await _apply_update(transaction)

    async def batch_delete(
        self,
        collection_name: str,
        doc_ids: List[str],
        chunk_size: int = 400,
    ) -> int:
        """Delete multiple documents by ID using chunked WriteBatch (max 500 ops per batch)."""
        if not doc_ids:
            return 0

        total_deleted = 0
        for i in range(0, len(doc_ids), chunk_size):
            chunk = doc_ids[i : i + chunk_size]
            batch = self.client.batch()
            for doc_id in chunk:
                ref = self.collection(collection_name).document(str(doc_id))
                batch.delete(ref)
            await batch.commit()
            total_deleted += len(chunk)

        return total_deleted

    async def clear_collection(
        self,
        collection_name: str,
        chunk_size: int = 400,
    ) -> int:
        """Safely delete all documents in a collection using chunked streaming batches."""
        total_deleted = 0
        while True:
            docs_to_delete = []
            async for doc in self.collection(collection_name).limit(chunk_size).stream():
                docs_to_delete.append(doc.id)

            if not docs_to_delete:
                break

            deleted = await self.batch_delete(collection_name, docs_to_delete, chunk_size=chunk_size)
            total_deleted += deleted

            if len(docs_to_delete) < chunk_size:
                break

        return total_deleted
