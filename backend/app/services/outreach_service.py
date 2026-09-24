import re
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.services.ai_service import (
    get_ai_config,
    call_ai,
    can_use_ai,
    generate_fallback_outreach
)

async def generate_outreach_sequence(company_id: str, options: dict = None) -> list[dict]:
    if options is None:
        options = {}

    contact_id = options.get('contactId')
    angle = options.get('angle', 'pain_point')
    tone = options.get('tone', 'conversational')
    focus_service = options.get('focusService', 'AI Strategy Consulting')

    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contact = None
    if contact_id:
        contact = await db.contacts.find_one({"_id": to_object_id(contact_id)})
    if not contact:
        contact = await db.contacts.find_one({"companyId": cid}, sort=[("overallScore", -1)])

    research = await db.companyresearches.find_one({"companyId": cid})

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

    ai_config = await get_ai_config()
    generated_steps = []

    if can_use_ai(ai_config):
        contact_name = (contact.get('name') if contact else company.get('contactName')) or 'there'
        contact_title = (contact.get('title') if contact else 'Executive Leadership')
        company_name = company.get('companyName', '')

        system_prompt = f"""You are a world-class enterprise AI B2B copywriter representing "{sender['companyName']}".
You write short, punchy, professional, and evidence-based outreach emails to decision makers.
CRITICAL RULES:
- Focus on the SINGLE MOST RELEVANT problem for the prospect and explain how "{focus_service}" from {sender['companyName']} solves that specific challenge.
- DO NOT dump a bulleted laundry list of all services.
- Directly address the recipient by name ({contact_name}) and acknowledge their role as {contact_title} at {company_name}.
- Keep each email under 130 words.
- Tone: {tone}.
- Angle: {angle}.
- Output strict JSON with key "sequence"."""

        user_prompt = f"""Generate a 3-step cold outreach sequence from {sender['senderName']} ({sender['senderTitle']}, {sender['companyName']}) to:
Prospect: {contact_name}
Designation: {contact_title}
Company: {company_name} ({company.get('website')})
Industry: {company.get('industry') or 'B2B'}
Target Service Focus: {focus_service}

Company Research & AI Context:
{research.get('summary', '') if research else 'Growing technology company scaling operations.'}
Pain Points: {research.get('detectedPainPoints', []) if research else []}

Return a strict JSON object with this exact schema:
{{
  "sequence": [
    {{
      "step": 1,
      "stepLabel": "Step 1: Strategic AI Opportunity",
      "subject": "Concise compelling subject line (under 7 words)",
      "bodyText": "Plain text email under 130 words tailored specifically to {focus_service}",
      "bodyHtml": "<p>HTML email body with clean paragraph formatting</p>",
      "linkedinNote": "Short LinkedIn connection note under 280 characters",
      "linkedinInmail": "Direct InMail message copy"
    }},
    {{
      "step": 2,
      "stepLabel": "Step 2: Practical Value & Workflow Proof",
      "subject": "Re: Follow up subject line",
      "bodyText": "Follow-up email under 100 words",
      "bodyHtml": "<p>HTML email body for step 2</p>",
      "linkedinNote": "Follow-up connection note",
      "linkedinInmail": "Follow-up InMail copy"
    }},
    {{
      "step": 3,
      "stepLabel": "Step 3: Low-Friction Invitation",
      "subject": "Final check-in subject line",
      "bodyText": "Low-friction breakup/check-in email under 80 words",
      "bodyHtml": "<p>HTML email body for step 3</p>",
      "linkedinNote": "Final check-in note",
      "linkedinInmail": "Final check-in InMail copy"
    }}
  ]
}}"""

        try:
            res_data = None
            if ai_config.get('provider') == 'ollama':
                res_data = await call_ai(user_prompt, system_prompt, ai_config)

            if res_data and isinstance(res_data.get('sequence'), list) and res_data['sequence']:
                generated_steps = res_data['sequence']
        except Exception as e:
            print(f"AI sequence generation failed: {e}")
            generated_steps = generate_fallback_outreach(company, research or {}, contact or {}, sender, angle, tone, focus_service)

    if not generated_steps:
        generated_steps = generate_fallback_outreach(company, research or {}, contact or {}, sender, angle, tone, focus_service)

    # Preserve existing CC / BCC
    existing_meta_map = {}
    async for d in db.outreachmessages.find({"companyId": cid, "status": "draft"}):
        existing_meta_map[d.get('step')] = {
            'cc': d.get('ccRecipients', []),
            'bcc': d.get('bccRecipients', [])
        }

    saved_messages = []
    now = datetime.utcnow()

    for item in generated_steps:
        prev_meta = existing_meta_map.get(item['step'], {'cc': [], 'bcc': []})
        msg_doc = {
            'companyId': cid,
            'contactId': contact['_id'] if contact else None,
            'step': item['step'],
            'stepLabel': item.get('stepLabel') or f"Step {item['step']}",
            'subject': item.get('subject', ''),
            'bodyHtml': item.get('bodyHtml', ''),
            'bodyText': item.get('bodyText') or re.sub(r'<[^>]*>?', '', item.get('bodyHtml', '')),
            'focusService': focus_service or 'AI Strategy Consulting',
            'linkedinNote': item.get('linkedinNote', ''),
            'linkedinInmail': item.get('linkedinInmail', ''),
            'angle': item.get('angle', angle),
            'tone': item.get('tone', tone),
            'status': 'draft',
            'isManuallyEdited': False,
            'recipientEmail': contact.get('email', '') if contact else '',
            'recipientName': contact.get('name', '') if contact else (company.get('contactName') or 'Lead'),
            'ccRecipients': prev_meta['cc'],
            'bccRecipients': prev_meta['bcc'],
            'updatedAt': now
        }

        query = {"companyId": cid, "step": item['step'], "status": "draft"}
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
    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    message = await db.outreachmessages.find_one({"_id": mid})
    if not message:
        raise HTTPException(status_code=404, detail="Outreach message not found")

    if message.get('status') == 'sent':
        raise HTTPException(status_code=400, detail="Cannot edit an already sent message")

    allowed_fields = [
        'subject', 'bodyHtml', 'bodyText', 'recipientEmail', 'recipientName',
        'ccRecipients', 'bccRecipients', 'focusService', 'linkedinNote', 'linkedinInmail'
    ]
    set_fields = {'isManuallyEdited': True, 'updatedAt': datetime.utcnow()}
    for f in allowed_fields:
        if f in update_data:
            set_fields[f] = update_data[f]

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
