import os
import hmac
import logging
from datetime import datetime, timezone
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from app.config.database import get_db
from app.utils.bson_utils import serialize_doc, to_object_id

logger = logging.getLogger(__name__)

ADMIN_RELEASE_KEY_ENV = "ADMIN_RELEASE_KEY"


class QuarantineReleaseRequest(BaseModel):
    confirmMessageId: str = Field(..., description="Exact message ID confirmation")
    expectedBatch: str = Field(..., description="Expected quarantine batch identifier")
    reason: str = Field(..., min_length=5, description="Audited business reason for release")
    actor: str = Field(default="admin", description="Operator identity label (for audit log)")


def verify_admin_release_key(x_admin_key: str = Header(None, alias="X-Admin-Key")) -> str:
    """Validate X-Admin-Key header against server-side ADMIN_RELEASE_KEY environment variable.

    Security guarantees:
    - Fails closed: if ADMIN_RELEASE_KEY is unset or empty, release is strictly disabled.
    - Constant-time comparison via hmac.compare_digest prevents timing attacks.
    - Never logs or exposes submitted or expected tokens.
    """
    configured_key = os.getenv(ADMIN_RELEASE_KEY_ENV, "").strip()
    if not configured_key:
        logger.warning("[Security] Quarantine release attempt rejected: ADMIN_RELEASE_KEY is not configured on server.")
        raise HTTPException(
            status_code=503,
            detail="Quarantine release is disabled: server administrator has not configured ADMIN_RELEASE_KEY."
        )

    if not x_admin_key:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: X-Admin-Key header is missing."
        )

    # Secure constant-time comparison
    if not hmac.compare_digest(x_admin_key.strip(), configured_key):
        logger.warning("[Security] Quarantine release attempt rejected: invalid X-Admin-Key provided.")
        raise HTTPException(
            status_code=403,
            detail="Forbidden: invalid X-Admin-Key."
        )

    return configured_key


async def check_transactions_supported(db) -> bool:
    """Check if the connected MongoDB server supports multi-document transactions.

    Transactions require a replica set (setName present) or sharded cluster.
    Standalone MongoDB instances do not support multi-document transactions.
    """
    try:
        client = getattr(db, "client", None)
        if not client:
            return False
        hello = await client.admin.command("hello")
        return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
    except Exception:
        return False


async def reconcile_missing_quarantine_audit_logs(db=None) -> dict:
    """Detect and repair any incomplete secondary quarantine audit records.

    Idempotent recovery strategy:
    - Scans messages that were released (quarantined=False, quarantineReleased exists).
    - Checks whether a corresponding document exists in `quarantine_audit_logs`.
    - If missing, idempotently inserts the record derived from the primary embedded
      `quarantineReleased` metadata on the message document.
    - Marks `quarantineReleased.auditLogged = True`.
    - INVARIANT: Never unquarantines, modifies status, or triggers sending/scheduling.
    """
    if db is None:
        db = get_db()

    now = datetime.now(timezone.utc)
    cursor = db.outreachmessages.find({
        "quarantined": False,
        "quarantineReleased": {"$exists": True},
    })

    scanned = 0
    repaired = 0
    errors = []

    async for msg in cursor:
        scanned += 1
        mid_str = str(msg["_id"])
        existing_log = await db.quarantine_audit_logs.find_one({"messageId": mid_str})
        if not existing_log:
            rel = msg.get("quarantineReleased") or {}
            audit_entry = {
                "messageId": mid_str,
                "companyId": str(msg.get("companyId")),
                "step": msg.get("step"),
                "recipientEmail": msg.get("recipientEmail"),
                "batch": rel.get("previousBatch") or (msg.get("quarantine") or {}).get("batch") or "unknown",
                "action": "RELEASE_QUARANTINE_RECONCILED",
                "actor": rel.get("releasedBy", "unknown"),
                "reason": rel.get("releaseReason", "Reconciled from primary embedded message metadata"),
                "timestamp": rel.get("releasedAt") or now,
                "messageStatus": msg.get("status"),
                "authMethod": "X-Admin-Key",
                "reconciledAt": now,
            }
            try:
                await db.quarantine_audit_logs.insert_one(audit_entry)
                await db.outreachmessages.update_one(
                    {"_id": msg["_id"]},
                    {"$set": {"quarantineReleased.auditLogged": True}}
                )
                repaired += 1
                logger.info(f"[Quarantine Audit Repair] Successfully backfilled missing audit log for message {mid_str}.")
            except Exception as e:
                errors.append(f"Failed to repair log for message {mid_str}: {e}")
                logger.error(f"[Quarantine Audit Repair Error] Message {mid_str}: {e}")

    return {
        "success": True,
        "scanned": scanned,
        "repaired": repaired,
        "errors": errors,
        "timestamp": now.isoformat(),
    }


async def release_quarantined_message_service(
    message_id: str,
    payload: QuarantineReleaseRequest,
    authenticated_actor_token: str
) -> dict:
    """Atomically release exactly one specified quarantined draft message.

    Invariants enforced:
    - confirmMessageId must exactly match the URL message_id.
    - Message must exist, belong to expectedBatch, have status='draft' and quarantined=True.
    - State transition: sets quarantined=False, records quarantineReleased metadata.
    - Status strictly remains 'draft'.
    - Does NOT schedule or send any email.
    - Transaction-aware & Recoverable Audit:
      * If MongoDB deployment supports transactions (replica set), executes in an atomic transaction.
      * If standalone (non-replica set), uses a two-tier recoverable audit model:
        1. Primary embedded audit metadata is recorded atomically in the message document.
        2. Secondary audit record is written to `quarantine_audit_logs`.
        3. If secondary insert fails, records `auditLogged=False` with error details, returning
           a clear audit warning. An operator can safely run `reconcile_missing_quarantine_audit_logs`.
    """
    if message_id != payload.confirmMessageId:
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation mismatch: message ID in path '{message_id}' does not match confirmMessageId '{payload.confirmMessageId}'."
        )

    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID format.")

    db = get_db()
    now = datetime.now(timezone.utc)

    # 1. Inspect current state to provide precise rejection messages if ineligible
    current = await db.outreachmessages.find_one({"_id": mid})
    if not current:
        raise HTTPException(status_code=404, detail="Outreach message not found.")

    if current.get("quarantined") is not True:
        raise HTTPException(
            status_code=409,
            detail="Message is not quarantined (already released or not in quarantine)."
        )

    if current.get("status") != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot release message in status '{current.get('status')}'. Only draft messages may be released."
        )

    current_batch = (current.get("quarantine") or {}).get("batch")
    if current_batch != payload.expectedBatch:
        raise HTTPException(
            status_code=409,
            detail=f"Batch mismatch: message belongs to batch '{current_batch}', expected '{payload.expectedBatch}'."
        )

    # 2. Release metadata definition
    supports_tx = await check_transactions_supported(db)
    client = getattr(db, "client", None)

    release_metadata = {
        "releasedAt": now,
        "releasedBy": payload.actor,
        "releaseReason": payload.reason,
        "previousBatch": current_batch,
        "auditLogged": False,
        "transactionsSupported": supports_tx,
    }

    audit_entry = {
        "messageId": str(mid),
        "companyId": str(current.get("companyId")),
        "step": current.get("step"),
        "recipientEmail": current.get("recipientEmail"),
        "batch": payload.expectedBatch,
        "action": "RELEASE_QUARANTINE",
        "actor": payload.actor,
        "reason": payload.reason,
        "timestamp": now,
        "messageStatus": "draft",
        "authMethod": "X-Admin-Key",
    }

    # 3. Transactional execution path (replica set / mongos)
    if supports_tx and client:
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    release_metadata["auditLogged"] = True
                    updated = await db.outreachmessages.find_one_and_update(
                        {
                            "_id": mid,
                            "status": "draft",
                            "quarantined": True,
                            "quarantine.batch": payload.expectedBatch,
                        },
                        {
                            "$set": {
                                "quarantined": False,
                                "quarantine.active": False,
                                "quarantineReleased": release_metadata,
                                "updatedAt": now,
                            }
                        },
                        return_document=True,
                        session=session,
                    )
                    if not updated:
                        raise HTTPException(
                            status_code=409,
                            detail="Conflict: message could not be released. It may have been concurrently modified or released."
                        )

                    await db.quarantine_audit_logs.insert_one(audit_entry, session=session)
        except HTTPException:
            raise
        except Exception as tx_err:
            logger.error(f"[Quarantine Transaction Error] Message {mid} release failed: {tx_err}")
            raise HTTPException(
                status_code=500,
                detail=f"Transaction failed during quarantine release: {tx_err}"
            )

        logger.info(
            f"[Quarantine] Message {mid} for {updated.get('recipientEmail')} atomically released via transaction."
        )
        return {
            "success": True,
            "message": f"Message {mid} successfully released from quarantine. It remains a draft and can now be scheduled or edited.",
            "data": serialize_doc(updated),
            "audit": {
                "releasedAt": now.isoformat(),
                "actor": payload.actor,
                "batch": payload.expectedBatch,
                "auditLogged": True,
                "transactional": True,
            }
        }

    # 4. Non-transactional recoverable path (standalone MongoDB)
    # Step 4a: Atomic conditional update of the message document with embedded primary audit trail
    updated = await db.outreachmessages.find_one_and_update(
        {
            "_id": mid,
            "status": "draft",
            "quarantined": True,
            "quarantine.batch": payload.expectedBatch,
        },
        {
            "$set": {
                "quarantined": False,
                "quarantine.active": False,
                "quarantineReleased": release_metadata,
                "updatedAt": now,
            }
        },
        return_document=True,
    )

    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Conflict: message could not be released. It may have been concurrently modified or released."
        )

    # Step 4b: Secondary audit log insertion with graceful failure tracking
    audit_warning = None
    try:
        await db.quarantine_audit_logs.insert_one(audit_entry)
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {"quarantineReleased.auditLogged": True}}
        )
        audit_logged = True
    except Exception as audit_err:
        audit_logged = False
        audit_warning = str(audit_err)
        logger.critical(
            f"[Quarantine Audit Warning] Secondary audit log insert failed for message {mid}: {audit_err}. "
            "Primary audit trail is safely embedded in outreach message. Run reconcile_missing_quarantine_audit_logs to backfill."
        )
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {
                "quarantineReleased.auditLogged": False,
                "quarantineReleased.auditError": audit_warning,
            }}
        )

    logger.info(
        f"[Quarantine] Message {mid} for {updated.get('recipientEmail')} released from batch '{payload.expectedBatch}' by actor '{payload.actor}' (auditLogged={audit_logged})."
    )

    response_payload = {
        "success": True,
        "message": f"Message {mid} successfully released from quarantine. It remains a draft and can now be scheduled or edited.",
        "data": serialize_doc(updated),
        "audit": {
            "releasedAt": now.isoformat(),
            "actor": payload.actor,
            "batch": payload.expectedBatch,
            "auditLogged": audit_logged,
            "transactional": False,
        }
    }
    if audit_warning:
        response_payload["auditWarning"] = audit_warning

    return response_payload

