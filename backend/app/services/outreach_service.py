import re
import logging
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.services.ai_service import (
    apply_tksr_signature,
    build_followup_email,
    build_primary_email,
    call_ai,
    can_use_ai,
    generate_fallback_outreach,
    get_ai_config,
    sanitize_evidence,
)
from app.services.send_guard import (
    validate_recipient_email,
    check_recipient_domain_alignment,
    check_contact_and_greeting_consistency,
)

logger = logging.getLogger(__name__)


def _normalize_email(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _recipient_match(email: str) -> dict:
    """Case-insensitive, anchored email match.

    Emails are stored as typed by the operator, so an exact-case Mongo equality
    filter would miss `None`/`NONE`/`Prospect@X.com` style values. This keeps
    recipient synchronization reliable without ever matching a partial address.
    """
    return {"$regex": f"^{re.escape(email)}$", "$options": "i"}


async def _load_sender(db) -> dict:
    sender = {
        'senderName': 'Nagendra',
        'senderTitle': 'Business Analyst',
        'companyName': 'TKSR Product Services',
        'senderEmail': 'nagendra@tksrproductservices.com'
    }
    try:
        setting = await db.settings.find_one({"key": "global_settings"})
        if setting and setting.get('senderProfile'):
            sp = setting['senderProfile']
            sender['senderName'] = sp.get('senderName') or sender['senderName']
            sender['senderTitle'] = sp.get('senderTitle') or sender['senderTitle']
            sender['companyName'] = sp.get('companyName') or sender['companyName']
    except Exception as e:
        print(f"Could not fetch sender profile: {e}")
    return sender


# Statuses that mean a follow-up is already (or being) dispatched: recipient
# synchronization must never touch them.
_FOLLOWUP_LOCKED_STATUSES = ("sent", "sending")


def _usable_recipient(value) -> bool:
    """True only for a syntactically valid address.

    Blank strings and legacy placeholders ("None", "Not publicly available",
    "N/A", ...) are all invalid and therefore safe to repair via synchronization.
    """
    return validate_recipient_email(_normalize_email(value))


async def _eligible_followups(db, company_oid) -> list:
    """Unsent Step 2/3 messages for a company.

    Identified by the stable company + sequence-step relationship (never by the
    previous recipient alone), excluding sent/sending history so a parked
    sequence can never be edited by synchronization.
    """
    cursor = (
        db.outreachmessages.find(
            {
                "companyId": company_oid,
                "step": {"$in": [2, 3]},
                "status": {"$nin": list(_FOLLOWUP_LOCKED_STATUSES)},
            }
        )
        .sort("step", 1)
    )
    return await cursor.to_list(length=50)


async def _sync_followup_recipients(company_oid, old_email: str, new_email: str, now, recipient_name=None) -> dict:
    """Propagate a Step-1 recipient edit to eligible unsent follow-up messages.

    Follow-ups are found by the stable company + sequence-step relationship, so a
    blank/placeholder follow-up recipient is repaired too (matching solely on the
    old recipient missed exactly those broken rows).

    Per follow-up:
      * eligible -> recipient is blank/placeholder/invalid OR already equals the
                    old Step-1 recipient: recipient (+ name) are updated.
      * conflict -> recipient is a *different valid* address: never overwritten;
                    flagged (and paused if armed) for manual review.
      * sent / sending -> never touched.

    CC/BCC, subject, body, status, delayDays and scheduledAt are preserved.
    """
    db = get_db()
    old_norm = _normalize_email(old_email)
    updated = 0
    conflicts = []

    for m in await _eligible_followups(db, company_oid):
        existing = _normalize_email(m.get("recipientEmail"))
        if _usable_recipient(existing) and existing != old_norm:
            # A different, still-deliverable address — do NOT silently redirect it.
            set_fields = {
                "requiresReview": True,
                "recipientConflict": True,
                "previousRecipient": m.get("recipientEmail"),
                "updatedAt": now,
            }
            # An armed/in-review follow-up must not auto-dispatch while it
            # conflicts with the freshly edited Step 1 recipient.
            if m.get("status") in ("scheduled", "approved"):
                set_fields["status"] = "draft"
            await db.outreachmessages.update_one({"_id": m["_id"]}, {"$set": set_fields})
            conflicts.append({
                "messageId": str(m["_id"]),
                "step": m.get("step"),
                "recipientEmail": m.get("recipientEmail"),
                "status": m.get("status"),
            })
            continue

        set_fields = {
            "recipientEmail": new_email,
            "recipientSyncedFromStep1": True,
            "updatedAt": now,
        }
        if recipient_name:
            set_fields["recipientName"] = recipient_name
        await db.outreachmessages.update_one(
            {"_id": m["_id"]},
            {
                "$set": set_fields,
                "$unset": {
                    "recipientChangedAfterSend": "",
                    "requiresReview": "",
                    "previousRecipient": "",
                    "recipientConflict": "",
                },
            },
        )
        updated += 1

    return {"updated": updated, "paused": 0, "skippedInvalid": False, "conflicts": conflicts}


def _normalize_cc_list(value) -> list:
    """Normalize a CC list the way the editor builds one (CompanyDetail
    `handleAddCcEmail`): split on commas/semicolons/whitespace, trim, lowercase,
    drop blanks and anything that is not a syntactically valid address, and
    de-duplicate case-insensitively (first occurrence wins).

    BCC is deliberately NOT handled here — BCC is never synchronized.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if isinstance(item, str) and re.search(r"[,;\s]+", item):
                parts.extend(re.split(r"[,;\s]+", item))
            else:
                parts.append(item)
    else:
        return []
    normalized, seen = [], set()
    for part in parts:
        if not isinstance(part, str):
            continue
        addr = part.strip().lower()
        if not addr or "@" not in addr or not validate_recipient_email(addr):
            continue
        if addr in seen:
            continue
        seen.add(addr)
        normalized.append(addr)
    return normalized


def _cc_differs(current, incoming) -> bool:
    """Case-insensitive CC comparison so a legacy mixed-case address that is
    merely re-saved never counts as a change (no needless follow-up writes)."""
    return _normalize_cc_list(current) != _normalize_cc_list(incoming)


async def _sync_followup_cc(company_oid, cc_list, now) -> dict:
    """Mirror Step 1's CC list onto eligible unsent Step 2/3 messages.

    Only `ccRecipients` (and `updatedAt`) is written: subject, HTML/plain-text
    body, primary recipient, recipient name, BCC, status, delays and dates are
    left exactly as they are. Sent messages are excluded by
    `_eligible_followups`, so a parked sequence can never be reactivated here.
    A follow-up that already carries this CC list is skipped so an unchanged
    save produces no write churn.
    """
    db = get_db()
    target = _normalize_cc_list(cc_list)
    cc_updated = 0
    for m in await _eligible_followups(db, company_oid):
        if _normalize_cc_list(m.get("ccRecipients")) == target:
            continue
        await db.outreachmessages.update_one(
            {"_id": m["_id"]},
            {"$set": {"ccRecipients": target, "updatedAt": now}},
        )
        cc_updated += 1
    return {"ccUpdated": cc_updated}


async def _pause_followups_for_recipient_change(company_oid, old_email: str, new_email: str, now) -> dict:
    """Step 1 was already sent and its recipient changed.

    Never silently redirect the sequence: every unsent Step 2/3 message is put
    back to `draft` and flagged for manual review, and the matching record's
    pending follow-ups become REVIEW so neither worker can dispatch to the old
    recipient. Sent messages / historical records are untouched.
    """
    db = get_db()
    paused_msgs = 0
    for m in await _eligible_followups(db, company_oid):
        await db.outreachmessages.update_one(
            {"_id": m["_id"]},
            {
                "$set": {
                    "status": "draft",
                    "recipientChangedAfterSend": True,
                    "requiresReview": True,
                    "previousRecipient": old_email or m.get("recipientEmail"),
                    "updatedAt": now,
                }
            },
        )
        paused_msgs += 1

    record_paused = 0
    record = None
    if old_email:
        record = await db.outreachrecords.find_one(
            {"companyId": company_oid, "recipientEmail": _recipient_match(old_email)}
        )
    if record:
        updates = {}
        for key in ("followUp1", "followUp2"):
            if record.get(key, {}).get("status") == "PENDING":
                updates[f"{key}.status"] = "REVIEW"
                updates[f"{key}.reason"] = "recipient_changed_after_send"
        if updates:
            updates["updatedAt"] = now
            await db.outreachrecords.update_one({"_id": record["_id"]}, {"$set": updates})
            record_paused = len([k for k in updates if k.endswith(".status")])
    return {
        "updated": 0,
        "paused": paused_msgs + record_paused,
        "skippedInvalid": False,
        "conflicts": [],
    }

async def generate_outreach_sequence(company_id: str, options: dict = None) -> list[dict]:
    if options is None:
        options = {}

    contact_id = options.get('contactId')
    angle = options.get('angle', 'pain_point')
    tone = options.get('tone', 'conversational')

    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Authoritative Validation (Phase 2):
    # Both Evidence and Recommended Service must exist on the company record
    company_evidence = (company.get('evidence') or '').strip()
    company_rec_service = (company.get('recommendedService') or '').strip()

    if not company_evidence:
        raise HTTPException(
            status_code=400,
            detail="Missing required Evidence for outreach generation. Please configure Evidence in the company record or re-import."
        )

    if not company_rec_service:
        raise HTTPException(
            status_code=400,
            detail="Missing required Recommended Service for outreach generation. Please configure Recommended Service in the company record or re-import."
        )

    # Core Rule: company.recommendedService is strictly authoritative.
    # Frontend focusService must NOT override company.recommendedService.
    focus_service = company_rec_service

    contact = None
    if contact_id:
        contact = await db.contacts.find_one({"_id": to_object_id(contact_id)})
    if not contact:
        contact = await db.contacts.find_one({"companyId": cid}, sort=[("overallScore", -1)])

    sender = await _load_sender(db)

    ai_config = await get_ai_config()
    generated_steps = []

    if can_use_ai(ai_config):
        contact_name = (contact.get('name') if contact else company.get('contactName')) or 'there'
        contact_title = (contact.get('title') if contact else 'Executive Leadership')
        company_name = company.get('companyName', '')

        system_prompt = f"""You are a world-class enterprise B2B outreach copywriter representing "{sender['companyName']}".
You write short, punchy, professional, and strictly evidence-backed outreach emails to decision makers.

AUTHORITATIVE CORE RULES:
1. PRIMARY EVIDENCE IS THE ONLY PERSONALIZATION SOURCE:
   - Ground ALL personalization strictly in the supplied PRIMARY EVIDENCE (a factual note about the company).
   - STRICT ANTI-HALLUCINATION: Do NOT invent unmentioned company initiatives, AI projects, automation projects, digital transformation claims, technology adoption, partnerships, customers, statistics, revenue, employee numbers, ROI metrics, future plans, internal problems, or technology stacks.
   - Do NOT use AI/LLM hype, buzzwords, or generic phrases like "revolutionize", "game-changing", "cutting-edge", or "supercharge".
   - If the evidence does not state that the company uses AI or has an AI initiative, DO NOT claim or imply they do.
   - Subject lines must be company-specific, evidence-grounded, and under 8 words.
2. RECOMMENDED SERVICE IS AUTHORITATIVE:
   - The RECOMMENDED TKSR SERVICE "{focus_service}" is strictly authoritative.
   - You MUST use the exact service name "{focus_service}" in ALL 3 steps of the sequence.
   - Do NOT replace, alter, rename, or substitute this service under any circumstances.
3. THREE-STEP SEQUENCE STRUCTURE:
   - Step 1 (Initial Outreach): Observation from PRIMARY EVIDENCE -> Business opportunity connected to that evidence -> Introduce "{focus_service}" -> One clear value proposition -> One specific, low-pressure CTA (e.g. "would a short discussion be useful?") (< 130 words).
   - Step 2 (Follow-up): Reference the original evidence -> Practical value -> Same "{focus_service}" -> Simple low-friction CTA (< 100 words).
   - Step 3 (Final Follow-up): Brief reference -> Same business opportunity -> Same "{focus_service}" -> Low-pressure closing CTA (< 80 words).
   - Each step's copy must be purpose-specific. NEVER copy the Step 1 body into Steps 2 or 3.
4. RECIPIENT:
   - Address the recipient by name ({contact_name}) and acknowledge their role as {contact_title} at {company_name}.
5. TONE: {tone}. Keep it concise, professional, and never flattering or salesy.
6. NO SIGNATURE: do not add any sign-off, signature, or contact details — the platform appends the TKSR signature automatically.
7. STRICT JSON OUTPUT: Return a valid JSON object with key "sequence" containing exactly 3 step objects."""

        user_prompt = f"""Generate a 3-step cold outreach sequence from {sender['senderName']} ({sender['senderTitle']}, {sender['companyName']}) to:

Company Name: {company_name}
Website: {company.get('website', '')}
Industry: {company.get('industry') or 'B2B'}
Decision Maker Name: {contact_name}
Decision Maker Role: {contact_title}
Decision Maker Email: {contact.get('email', '') if contact else ''}

PRIMARY EVIDENCE:
{company_evidence}

RECOMMENDED TKSR SERVICE:
{focus_service}

CRITICAL MANDATES:
- The PRIMARY EVIDENCE is the only authoritative source for company-specific personalization.
- The RECOMMENDED TKSR SERVICE is authoritative.
- Do not change or substitute the Recommended Service. Every email must use "{focus_service}".
- Do NOT invent company facts, projects, or statistics outside the PRIMARY EVIDENCE.

Return a strict JSON object with this exact schema:
{{
  "sequence": [
    {{
      "step": 1,
      "stepLabel": "Step 1: Strategic AI Opportunity",
      "subject": "Company-specific subject line under 8 words, grounded in PRIMARY EVIDENCE",
      "bodyText": "Plain text email under 130 words grounded in PRIMARY EVIDENCE and featuring {focus_service}",
      "bodyHtml": "<p>HTML email body with clean paragraph formatting</p>",
      "linkedinNote": "Short LinkedIn connection note under 280 characters",
      "linkedinInmail": "Direct InMail message copy"
    }},
    {{
      "step": 2,
      "stepLabel": "Step 2: Practical Value & Workflow Proof",
      "subject": "Re: Follow up subject line",
      "bodyText": "Follow-up email under 100 words referencing the same evidence and {focus_service}",
      "bodyHtml": "<p>HTML email body for step 2</p>",
      "linkedinNote": "Follow-up connection note",
      "linkedinInmail": "Follow-up InMail copy"
    }},
    {{
      "step": 3,
      "stepLabel": "Step 3: Low-Friction Invitation",
      "subject": "Final check-in subject line",
      "bodyText": "Low-friction check-in email under 80 words referencing the same opportunity and {focus_service}",
      "bodyHtml": "<p>HTML email body for step 3</p>",
      "linkedinNote": "Final check-in note",
      "linkedinInmail": "Final check-in InMail copy"
    }}
  ]
}}"""

        try:
            res_data = None
            if ai_config.get('provider') == 'ollama':
                logger.info(f"[Ollama Prompt] Dispatched with PRIMARY EVIDENCE: '{company_evidence}' | RECOMMENDED SERVICE: '{focus_service}'")
                res_data = await call_ai(user_prompt, system_prompt, ai_config)

            if res_data and isinstance(res_data.get('sequence'), list) and res_data['sequence']:
                generated_steps = res_data['sequence']
        except Exception as e:
            print(f"AI sequence generation failed: {e}")
            generated_steps = generate_fallback_outreach(company, {}, contact or {}, sender, angle, tone, focus_service)

    if not generated_steps:
        generated_steps = generate_fallback_outreach(company, {}, contact or {}, sender, angle, tone, focus_service)

    # Preserve existing CC / BCC and any manually-edited content for drafts.
    existing_meta_map = {}
    async for d in db.outreachmessages.find({"companyId": cid, "status": "draft"}):
        existing_meta_map[d.get('step')] = d

    saved_messages = []
    now = datetime.now(timezone.utc)

    for item in generated_steps:
        step = int(item.get('step') or 1)

        # Deterministic defaults guarantee complete, signed copy when the LLM
        # omitted or malformed content.
        if step == 1:
            base = build_primary_email(company, contact or None, sender, focus_service, tone)
        else:
            base = build_followup_email(step, company, contact or None, sender, focus_service, company_evidence, tone)

        subject = (item.get('subject') or '').strip() or base['subject']
        body_html, body_text = apply_tksr_signature(
            item.get('bodyHtml') or base['bodyHtml'],
            item.get('bodyText') or base['bodyText'],
        )

        prev = existing_meta_map.get(step)
        prev_cc = (prev or {}).get('ccRecipients', [])
        prev_bcc = (prev or {}).get('bccRecipients', [])

        # FIX (manual edits preserved): an explicitly edited draft is never
        # silently overwritten by re-generation. The operator can deliberately
        # regenerate via POST /outreach/{message_id}/regenerate.
        preserve_content = bool(prev and prev.get('isManuallyEdited'))
        if preserve_content:
            subject = (prev.get('subject') or subject)
            body_html = (prev.get('bodyHtml') or body_html)
            body_text = (prev.get('bodyText') or body_text)

        msg_doc = {
            'companyId': cid,
            'contactId': contact['_id'] if contact else None,
            'step': step,
            'stepLabel': item.get('stepLabel') or (prev or {}).get('stepLabel') or f"Step {step}",
            'subject': subject,
            'bodyHtml': body_html,
            'bodyText': body_text or re.sub(r'<[^>]*>?', '', body_html),
            'focusService': focus_service,
            'evidenceUsed': company_evidence,
            'recommendedServiceUsed': focus_service,
            'linkedinNote': (prev.get('linkedinNote') if preserve_content
                             else (item.get('linkedinNote') or base.get('linkedinNote', ''))),
            'linkedinInmail': (prev.get('linkedinInmail') if preserve_content
                               else (item.get('linkedinInmail') or base.get('linkedinInmail', ''))),
            'angle': item.get('angle', angle),
            'tone': item.get('tone', tone),
            'status': 'draft',
            'isManuallyEdited': preserve_content,
            'recipientEmail': (prev.get('recipientEmail') if preserve_content
                               else (contact.get('email', '') if contact else '')),
            'recipientName': (prev.get('recipientName') if preserve_content
                              else (contact.get('name', '') if contact else (company.get('contactName') or 'Lead'))),
            'ccRecipients': prev_cc,
            'bccRecipients': prev_bcc,
            'updatedAt': now
        }

        # Validation safeguards (Phase 4): Domain & Greeting / Contact consistency checks
        domain_check = check_recipient_domain_alignment(msg_doc.get('recipientEmail'), company.get('website', ''))
        greeting_line = (msg_doc.get('bodyText') or '').strip().split('\n')[0].strip() if msg_doc.get('bodyText') else ''
        step1_prev = existing_meta_map.get(1)
        step1_greeting = (step1_prev.get('bodyText') or '').strip().split('\n')[0].strip() if step1_prev and step1_prev.get('bodyText') else None
        contact_check = check_contact_and_greeting_consistency(
            msg_doc.get('recipientName'),
            greeting_line,
            step1_greeting if step in (2, 3) else None
        )

        review_reasons = []
        if not domain_check.get('aligned'):
            review_reasons.append(domain_check.get('reason'))
        if not contact_check.get('valid'):
            review_reasons.extend(contact_check.get('findings', []))

        if review_reasons:
            msg_doc['requiresReview'] = True
            msg_doc['reviewReasons'] = review_reasons

        query = {"companyId": cid, "step": step, "status": "draft"}
        await db.outreachmessages.update_one(query, {"$set": msg_doc, "$setOnInsert": {"createdAt": now}}, upsert=True)
        saved = await db.outreachmessages.find_one(query)
        saved_messages.append(saved)

    await db.companies.update_one({"_id": cid}, {"$set": {"outreachStatus": "generated", "updatedAt": now}})
    return serialize_doc(saved_messages)

async def get_company_outreach(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    cursor = db.outreachmessages.find({"companyId": cid}).sort("step", 1)
    messages = await cursor.to_list(length=50)

    # Populate contactId details
    results = []
    for m in messages:
        doc = dict(m)
        if doc.get('contactId'):
            cont = await db.contacts.find_one({"_id": doc['contactId']})
            doc['contactId'] = cont
        results.append(doc)

    return serialize_doc(results)

async def get_all_outreach(query_params: dict = None):
    if query_params is None:
        query_params = {}

    db = get_db()
    query = {}
    if query_params.get('status'):
        query['status'] = query_params['status']
    if query_params.get('companyId'):
        cid = to_object_id(query_params['companyId'])
        if cid:
            query['companyId'] = cid

    cursor = db.outreachmessages.find(query).sort("createdAt", -1)
    messages = await cursor.to_list(length=200)

    results = []
    for m in messages:
        doc = dict(m)
        if doc.get('companyId'):
            comp = await db.companies.find_one({"_id": doc['companyId']})
            doc['companyId'] = comp
        if doc.get('contactId'):
            cont = await db.contacts.find_one({"_id": doc['contactId']})
            doc['contactId'] = cont
        results.append(doc)

    return serialize_doc(results)

async def update_outreach_message(message_id: str, update_data: dict):
    """Update one outreach message.

    * Sent messages are immutable history: only a recipient-only correction is
      permitted (never content/CC/BCC), and that correction pauses Step 2/3 for
      manual review instead of silently redirecting the sequence.
    * Editing the recipient of an unsent Step 1 synchronizes the new recipient
      to eligible unsent Step 2/3 messages (CC/BCC, content, status, delays and
      dates preserved).
    * Editing Step 1's CC list synchronizes that CC list to the same eligible
      unsent Step 2/3 messages. Only `ccRecipients` moves: each follow-up keeps
      its own subject/bodies, primary recipient, recipient name and BCC, and no
      BCC is ever synchronized.
    * Draft manual edit: To/CC/BCC, recipient name, subject and bodies may be
      corrected. The save never changes `status` (stays `draft`) and never
      sends, schedules, approves or activates anything. Each message keeps its
      own subject/bodies — edits never rewrite another step's content.

    Returns (serialized_message, sync_info) — the router surfaces sync_info to
    the caller so the UI can explain what happened. `sync_info` reports
    `ccUpdated` (follow-ups whose CC actually changed) alongside the recipient
    counters.
    """
    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    message = await db.outreachmessages.find_one({"_id": mid})
    if not message:
        raise HTTPException(status_code=404, detail="Outreach message not found")

    # An explicit null CC list means "not provided": never interpret it as a
    # request to wipe CC on this message or its follow-ups.
    if 'ccRecipients' in update_data and update_data.get('ccRecipients') is None:
        update_data = {k: v for k, v in update_data.items() if k != 'ccRecipients'}

    now = datetime.now(timezone.utc)
    step = int(message.get('step') or 1)
    is_sent = message.get('status') == 'sent'
    old_recipient = _normalize_email(message.get('recipientEmail'))
    new_recipient_raw = update_data.get('recipientEmail')
    recipient_changed = (
        new_recipient_raw is not None
        and _normalize_email(new_recipient_raw) != old_recipient
        and _normalize_email(new_recipient_raw) != ''
    )

    if is_sent:
        # Sent emails are history — never rewrite subject/body/CC/BCC/etc.
        immutable_fields = {
            'subject', 'bodyHtml', 'bodyText', 'ccRecipients', 'bccRecipients',
            'focusService', 'evidenceUsed', 'recommendedServiceUsed',
            'recipientName', 'linkedinNote', 'linkedinInmail'
        }
        blocked = set(update_data.keys()) & immutable_fields
        if blocked:
            raise HTTPException(
                status_code=400,
                detail="Cannot edit the content of an already sent message. You may update the recipient only; "
                       "changing it pauses affected follow-ups for manual review."
            )
        if 'recipientEmail' not in update_data:
            raise HTTPException(status_code=400, detail="Cannot edit an already sent message")

        set_fields = {'updatedAt': now}
        if 'recipientEmail' in update_data:
            set_fields['recipientEmail'] = update_data['recipientEmail']
        await db.outreachmessages.update_one({"_id": mid}, {"$set": set_fields})
        updated = await db.outreachmessages.find_one({"_id": mid})

        sync_info = {'updated': 0, 'paused': 0, 'skippedInvalid': False, 'conflicts': []}
        if step == 1 and recipient_changed:
            sync_info = await _pause_followups_for_recipient_change(
                message.get('companyId'), old_recipient, update_data['recipientEmail'], now
            )
        return serialize_doc(updated), sync_info

    allowed_fields = [
        'subject', 'bodyHtml', 'bodyText', 'recipientEmail', 'recipientName',
        'ccRecipients', 'bccRecipients', 'focusService', 'evidenceUsed', 'recommendedServiceUsed',
        'linkedinNote', 'linkedinInmail'
    ]
    set_fields = {'isManuallyEdited': True, 'updatedAt': now}
    for f in allowed_fields:
        if f in update_data:
            set_fields[f] = update_data[f]
    if 'ccRecipients' in update_data:
        # Store Step 1's CC normalized (trimmed, lower-cased, de-duplicated) so
        # Step 1 and its follow-ups always hold the same representation and a
        # case-only difference never registers as a change.
        set_fields['ccRecipients'] = _normalize_cc_list(update_data['ccRecipients'])

    await db.outreachmessages.update_one({"_id": mid}, {"$set": set_fields})
    updated = await db.outreachmessages.find_one({"_id": mid})

    sync_info = {'updated': 0, 'paused': 0, 'skippedInvalid': False, 'conflicts': [], 'ccUpdated': 0}
    if step == 1 and recipient_changed:
        new_recipient = _normalize_email(update_data['recipientEmail'])
        if new_recipient and validate_recipient_email(new_recipient):
            sync_info = await _sync_followup_recipients(
                message.get('companyId'), old_recipient, new_recipient, now,
                recipient_name=set_fields.get('recipientName'),
            )
            sync_info.setdefault('ccUpdated', 0)
        else:
            # An empty / invalid / "None"-style recipient is saved on the message
            # but is never propagated to follow-ups (they would only be broken).
            sync_info = {'updated': 0, 'paused': 0, 'skippedInvalid': True, 'conflicts': [], 'ccUpdated': 0}

    # CC is synchronized independently of the primary recipient: a CC-only edit
    # must reach the follow-ups too, and it never touches recipient/content/BCC.
    if step == 1 and 'ccRecipients' in update_data and _cc_differs(message.get('ccRecipients'), set_fields['ccRecipients']):
        sync_info.update(
            await _sync_followup_cc(message.get('companyId'), set_fields['ccRecipients'], now)
        )
    return serialize_doc(updated), sync_info


async def regenerate_outreach_message(message_id: str, options: dict = None):
    """Deliberately regenerate Step 1 (primary) content for review.

    Only ever acts on an UNSENT Step 1 message. Sent messages and historical
    records are never rewritten. Manual edits are replaced (this IS the explicit
    "regenerate" action); the operator reviews the new copy before use.
    """
    if options is None:
        options = {}
    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    msg = await db.outreachmessages.find_one({"_id": mid})
    if not msg:
        raise HTTPException(status_code=404, detail="Outreach message not found")

    if msg.get('status') == 'sent':
        raise HTTPException(status_code=400, detail="Cannot regenerate a sent message; historical emails are never rewritten")
    if int(msg.get('step') or 1) != 1:
        raise HTTPException(status_code=400, detail="Only Step 1 (primary) messages can be regenerated")

    company = await db.companies.find_one({"_id": msg.get('companyId')})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contact = None
    if msg.get('contactId'):
        contact = await db.contacts.find_one({"_id": msg['contactId']})
    if not contact:
        contact = await db.contacts.find_one({"companyId": msg.get('companyId')}, sort=[("overallScore", -1)])

    sender = await _load_sender(db)
    evidence = sanitize_evidence(company.get('evidence'))
    rec_service = (company.get('recommendedService') or '').strip() or msg.get('focusService') or 'AI Strategy Consulting'
    tone = (company or {}).get('tone') or msg.get('tone') or 'conversational'

    subject, body_text, body_html = None, None, None
    linkedin_note = linkedin_inmail = None
    use_ai = bool(options.get('useAi'))

    if use_ai:
        ai_config = await get_ai_config()
        if can_use_ai(ai_config):
            try:
                company_name = company.get('companyName', '')
                contact_name = (contact.get('name') if contact else company.get('contactName')) or 'there'
                contact_title = (contact.get('title') if contact else 'Executive Leadership')
                system_prompt = (
                    "You are a world-class enterprise B2B outreach copywriter. You write short, "
                    "professional, strictly evidence-backed emails. STRICT ANTI-HALLUCINATION: never invent "
                    "company initiatives, facts, metrics, contacts, achievements, or AI adoption claims. "
                    "The PRIMARY EVIDENCE is the only personalization source. "
                    f"The RECOMMENDED TKSR SERVICE '{rec_service}' is authoritative; use its exact name. "
                    "Do NOT add a signature or sign-off (the platform appends it). "
                    "Reply with strict JSON only."
                )
                user_prompt = (
                    f"Write ONE primary outreach email (no signature) to {contact_name} "
                    f"({contact_title}) at {company_name}.\n\n"
                    f"PRIMARY EVIDENCE:\n{evidence}\n\n"
                    f"RECOMMENDED TKSR SERVICE:\n{rec_service}\n\n"
                    "Requirements: company-specific subject under 8 words grounded in the evidence; "
                    "personalized opening using the recipient's name; one observation from the evidence; "
                    "one business opportunity logically connected to it; one clear value proposition for "
                    f"'{rec_service}'; one low-pressure CTA; under 130 words; no hype; no invented facts.\n\n"
                    'Return strict JSON: {"subject": "...", "bodyText": "...", "bodyHtml": "<p>...</p>", '
                    '"linkedinNote": "...", "linkedinInmail": "..."}'
                )
                res_data = await call_ai(user_prompt, system_prompt, ai_config)
                if res_data and res_data.get('subject') and res_data.get('bodyText'):
                    subject = res_data.get('subject')
                    body_text = res_data.get('bodyText')
                    body_html = res_data.get('bodyHtml') or body_text
                    linkedin_note = res_data.get('linkedinNote') or msg.get('linkedinNote') or ''
                    linkedin_inmail = res_data.get('linkedinInmail') or msg.get('linkedinInmail') or ''
            except Exception as e:
                logger.info(f"Regeneration via LLM failed ({e}); using deterministic builder.")
                subject = body_text = body_html = linkedin_note = linkedin_inmail = None

    base = build_primary_email(company, contact or None, sender, rec_service, tone)
    subject = subject or base['subject']
    body_html, body_text = apply_tksr_signature(
        body_html or base['bodyHtml'],
        body_text or base['bodyText'],
    )
    linkedin_note = linkedin_note or base.get('linkedinNote', '')
    linkedin_inmail = linkedin_inmail or base.get('linkedinInmail', '')

    now = datetime.now(timezone.utc)
    set_fields = {
        'subject': subject,
        'bodyHtml': body_html,
        'bodyText': body_text,
        'linkedinNote': linkedin_note,
        'linkedinInmail': linkedin_inmail,
        'evidenceUsed': evidence,
        'recommendedServiceUsed': rec_service,
        'isManuallyEdited': False,
        'regeneratedAt': now,
        'updatedAt': now,
    }
    await db.outreachmessages.update_one({"_id": mid}, {"$set": set_fields})
    updated = await db.outreachmessages.find_one({"_id": mid})
    return serialize_doc(updated)

async def delete_outreach_message(message_id: str):
    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    res = await db.outreachmessages.delete_one({"_id": mid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": "Message deleted"}

async def bulk_generate_outreach(company_ids: list[str], options: dict = None):
    results = []
    for cid in company_ids:
        try:
            messages = await generate_outreach_sequence(cid, options)
            results.append({"companyId": cid, "success": True, "count": len(messages)})
        except Exception as e:
            results.append({"companyId": cid, "success": False, "error": str(e)})

    return {
        "total": len(company_ids),
        "successful": len([r for r in results if r.get('success')]),
        "results": results
    }
