import os
from datetime import datetime
from email.message import EmailMessage
import aiosmtplib
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id
from app.services.outreach_tracking_service import record_email_dispatch

async def get_smtp_config(custom_config: dict = None) -> dict:
    smtp = custom_config
    if not smtp:
        db = get_db()
        if db is not None:
            setting = await db.settings.find_one({"key": "global_settings"})
            if setting and setting.get('smtp'):
                smtp = setting['smtp']

    host = smtp.get('host') if smtp else ''
    user = smtp.get('user') if smtp else ''
    pass_ = smtp.get('pass') or smtp.get('pass_') if smtp else ''
    port = int(smtp.get('port', 587)) if smtp else 587
    secure = bool(smtp.get('secure', False)) if smtp else False
    from_name = smtp.get('fromName') or 'AI Outreach' if smtp else 'AI Outreach'
    from_email = smtp.get('fromEmail') or user if smtp else user

    if host and user:
        if not pass_ or not pass_.strip():
            raise HTTPException(
                status_code=400,
                detail=f"SMTP password is missing for {user}. Please configure it in Settings."
            )
        return {
            'host': host,
            'port': port,
            'user': user,
            'pass': pass_,
            'secure': secure,
            'from': f'"{from_name}" <{from_email}>',
            'isTest': False
        }

    return {
        'host': 'smtp.ethereal.email',
        'port': 587,
        'user': 'sandbox_test_user@ethereal.email',
        'pass': 'sandbox_test_pass',
        'secure': False,
        'from': f'"{from_name}" <sandbox_test_user@ethereal.email>',
        'isTest': True
    }

async def send_test_email(custom_config: dict = None, recipient_email: str = 'test@example.com'):
    smtp_cfg = await get_smtp_config(custom_config)

    msg = EmailMessage()
    msg['From'] = smtp_cfg['from']
    msg['To'] = recipient_email
    msg['Subject'] = 'AI Client Outreach - SMTP Test Verification'
    msg.set_content('This is a test verification email from your AI Client Outreach platform.')
    msg.add_alternative(f"""
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px;">
        <h2 style="color: #2563eb;">AI Client Outreach</h2>
        <p>This is a verification test email from your AI Client Outreach platform.</p>
        <div style="background-color: #f3f4f6; padding: 15px; border-radius: 6px; margin: 15px 0;">
          <p style="margin: 0; color: #16a34a; font-weight: bold;">✓ SMTP connection is active and verified!</p>
          <p style="margin: 5px 0 0 0; color: #6b7280; font-size: 13px;">Timestamp: {datetime.utcnow().isoformat()}</p>
        </div>
        <p style="color: #4b5563; font-size: 14px;">You can now dispatch personalized AI email sequences directly to prospects.</p>
      </div>
    """, subtype='html')

    if not smtp_cfg['isTest']:
        await aiosmtplib.send(
            msg,
            hostname=smtp_cfg['host'],
            port=smtp_cfg['port'],
            username=smtp_cfg['user'],
            password=smtp_cfg['pass'],
            start_tls=not smtp_cfg['secure'],
            use_tls=smtp_cfg['secure']
        )
    return {'success': True, 'isTest': smtp_cfg['isTest'], 'recipient': recipient_email}

async def send_outreach_email(message_id: str, send_options: dict = None):
    if send_options is None:
        send_options = {}

    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    message = await db.outreachmessages.find_one({"_id": mid})
    if not message:
        raise HTTPException(status_code=404, detail="Outreach message not found")

    target_email = send_options.get('recipientEmail') or message.get('recipientEmail')
    if not target_email:
        raise HTTPException(status_code=400, detail="Recipient email address is required")

    cc_list = send_options.get('ccRecipients', message.get('ccRecipients', []))
    bcc_list = send_options.get('bccRecipients', message.get('bccRecipients', []))

    await db.outreachmessages.update_one({"_id": mid}, {"$set": {"status": "sending", "error": ""}})

    try:
        smtp_cfg = await get_smtp_config()
        base_url = os.getenv('API_BASE_URL', f"http://localhost:{os.getenv('PORT', 5000)}")
        tracking_pixel = f'<img src="{base_url}/api/track/open/{message_id}.png" width="1" height="1" style="display:none !important;" alt="" />'

        msg = EmailMessage()
        msg['From'] = smtp_cfg['from']
        msg['To'] = target_email
        if cc_list:
            msg['Cc'] = ", ".join(cc_list) if isinstance(cc_list, list) else cc_list
        if bcc_list:
            msg['Bcc'] = ", ".join(bcc_list) if isinstance(bcc_list, list) else bcc_list
        msg['Subject'] = message.get('subject', '')
        msg.set_content(message.get('bodyText', ''))
        msg.add_alternative(f"""
          <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #1f2937;">
            {message.get('bodyHtml', '')}
            {tracking_pixel}
          </div>
        """, subtype='html')

        if not smtp_cfg['isTest']:
            await aiosmtplib.send(
                msg,
                hostname=smtp_cfg['host'],
                port=smtp_cfg['port'],
                username=smtp_cfg['user'],
                password=smtp_cfg['pass'],
                start_tls=not smtp_cfg['secure'],
                use_tls=smtp_cfg['secure']
            )

        now = datetime.utcnow()
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {
                "status": "sent",
                "sentAt": now,
                "recipientEmail": target_email,
                "ccRecipients": cc_list,
                "bccRecipients": bcc_list,
                "updatedAt": now
            }}
        )

        dispatch_result = {
            'success': True,
            'sentAt': now,
            'recipientEmail': target_email,
            'ccRecipients': cc_list,
            'bccRecipients': bcc_list
        }
        await record_email_dispatch(message, dispatch_result)

        return {'success': True, 'message': 'Email dispatched successfully'}
    except Exception as e:
        now = datetime.utcnow()
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {"status": "failed", "error": str(e), "updatedAt": now}}
        )
        dispatch_result = {
            'success': False,
            'error': str(e),
            'sentAt': now,
            'recipientEmail': target_email,
            'ccRecipients': cc_list,
            'bccRecipients': bcc_list
        }
        await record_email_dispatch(message, dispatch_result)
        raise e
