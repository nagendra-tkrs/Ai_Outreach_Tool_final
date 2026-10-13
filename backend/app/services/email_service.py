import os
import re
import uuid
import logging
from datetime import datetime, timezone
from email.message import EmailMessage
import aiosmtplib
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id
from app.services.outreach_tracking_service import record_email_dispatch

logger = logging.getLogger(__name__)


def is_masked_secret(value: str) -> bool:
    if not value:
        return False
    return value.startswith("*") or "..." in value


def sanitize_smtp_error(error_msg: str, secret: str = "") -> str:
    cleaned = str(error_msg)
    if secret and secret in cleaned:
        cleaned = cleaned.replace(secret, "********")
    return cleaned


def rewrite_tracking_links(body_html: str, message_id: str, base_url: str) -> str:
    """E7: Rewrite every http(s) <a href> in the outgoing HTML so clicks are
    recorded by GET /api/track/click/{message_id}?url=<original>. The original
    URL is preserved as a query parameter and validated (http/https only) by
    the tracking endpoint before the redirect, so no link clicking is lost and
    the tracking pixel route is the only place a click count is incremented.

    Only rewrites hrefs that are already absolute http(s) URLs; mailto:, #,
    relative links and the tracking pixel itself are left untouched.
    """
    import urllib.parse as _urlparse

    if not body_html or not message_id or not base_url:
        return body_html or ""

    def _rewrite(match: "re.Match") -> str:
        href = match.group(1)
        stripped = (href or "").strip()
        parsed = _urlparse.urlparse(stripped)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            tracked = f"{base_url.rstrip('/')}/api/track/click/{message_id}?url={_urlparse.quote(stripped, safe='')}"
            return f'href="{tracked}"'
        return f'href="{stripped}"'

    return re.sub(r'href="([^"]*)"', _rewrite, body_html)


async def get_smtp_config(custom_config: dict = None) -> dict:
    db = get_db()
    stored_smtp = {}
    if db is not None:
        setting = await db.settings.find_one({"key": "global_settings"})
        if setting and setting.get('smtp'):
            stored_smtp = setting['smtp']

    # Merge custom config over stored config if provided
    if custom_config is not None:
        host = custom_config.get('host') if ('host' in custom_config and custom_config['host'] is not None) else stored_smtp.get('host', '')
        user = custom_config.get('user') if ('user' in custom_config and custom_config['user'] is not None) else stored_smtp.get('user', '')
        raw_port = custom_config.get('port') if ('port' in custom_config and custom_config['port'] is not None) else stored_smtp.get('port', 587)
        secure_val = custom_config.get('secure') if ('secure' in custom_config and custom_config['secure'] is not None) else stored_smtp.get('secure', False)
        from_name = custom_config.get('fromName') if ('fromName' in custom_config and custom_config['fromName'] is not None) else stored_smtp.get('fromName', 'AI Outreach')
        from_email = custom_config.get('fromEmail') if ('fromEmail' in custom_config and custom_config['fromEmail'] is not None) else stored_smtp.get('fromEmail', user)
        incoming_pass = (custom_config.get('pass') or custom_config.get('pass_') or '')
    else:
        host = stored_smtp.get('host', '')
        user = stored_smtp.get('user', '')
        raw_port = stored_smtp.get('port', 587)
        secure_val = stored_smtp.get('secure', False)
        from_name = stored_smtp.get('fromName', 'AI Outreach')
        from_email = stored_smtp.get('fromEmail', user)
        incoming_pass = ''

    try:
        port = int(raw_port) if raw_port else 587
    except (ValueError, TypeError):
        port = 587

    secure = bool(secure_val)

    # Password resolution:
    # 1. If custom password is provided and is NOT masked: use custom password.
    # 2. If custom password is empty: retrieve real stored password from global_settings.
    # 3. If custom password is masked: retrieve real stored password from global_settings.
    # 4. Never replace a real password with a masked value.
    stored_pass = stored_smtp.get('pass') or stored_smtp.get('pass_') or ''

    if incoming_pass and not is_masked_secret(incoming_pass):
        resolved_pass = incoming_pass
    else:
        resolved_pass = stored_pass

    # Check for Ethereal only behind explicit development / test flag
    allow_ethereal = (
        os.getenv("ALLOW_ETHEREAL_TEST", "").lower() in ("true", "1") or
        os.getenv("ENABLE_ETHEREAL", "").lower() in ("true", "1")
    )

    # If real SMTP credentials are not configured:
    if not host or not user:
        if allow_ethereal:
            return {
                'host': 'smtp.ethereal.email',
                'port': 587,
                'user': 'sandbox_test_user@ethereal.email',
                'pass': 'sandbox_test_pass',
                'secure': False,
                'use_tls': False,
                'start_tls': True,
                'from': f'"{from_name}" <sandbox_test_user@ethereal.email>',
                'isTest': True
            }
        raise HTTPException(
            status_code=400,
            detail="SMTP credentials are not configured."
        )

    if not resolved_pass or not resolved_pass.strip():
        raise HTTPException(
            status_code=400,
            detail=f"SMTP password is missing for {user}. Please configure it in Settings."
        )

    if is_masked_secret(resolved_pass):
        raise HTTPException(
            status_code=400,
            detail="Valid SMTP password is required (masked password cannot be used for authentication)."
        )

    # Protocol determination:
    # Port 465 -> SSL/TLS connection (use_tls=True, start_tls=False)
    # Port 587 -> STARTTLS connection (use_tls=False, start_tls=True)
    is_ssl = (port == 465) or (secure and port != 587)
    use_tls = is_ssl
    start_tls = not is_ssl

    return {
        'host': host,
        'port': port,
        'user': user,
        'pass': resolved_pass,
        'secure': is_ssl,
        'use_tls': use_tls,
        'start_tls': start_tls,
        'from': f'"{from_name}" <{from_email or user}>',
        'isTest': False
    }


async def send_test_email(custom_config: dict = None, recipient_email: str = 'test@example.com'):
    smtp_cfg = await get_smtp_config(custom_config)

    message_id = f"<{uuid.uuid4()}@{smtp_cfg['host'] or 'local'}>"

    msg = EmailMessage()
    msg['Message-ID'] = message_id
    msg['From'] = smtp_cfg['from']
    msg['To'] = recipient_email
    msg['Subject'] = 'AI Client Outreach - SMTP Test Verification'
    msg.set_content('This is a test verification email from your AI Client Outreach platform.')
    now_utc = datetime.now(timezone.utc).isoformat()
    msg.add_alternative(f"""
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px;">
        <h2 style="color: #2563eb;">AI Client Outreach</h2>
        <p>This is a verification test email from your AI Client Outreach platform.</p>
        <div style="background-color: #f3f4f6; padding: 15px; border-radius: 6px; margin: 15px 0;">
          <p style="margin: 0; color: #16a34a; font-weight: bold;">✓ SMTP connection is active and verified!</p>
          <p style="margin: 5px 0 0 0; color: #6b7280; font-size: 13px;">Timestamp: {now_utc}</p>
        </div>
        <p style="color: #4b5563; font-size: 14px;">You can now dispatch personalized AI email sequences directly to prospects.</p>
      </div>
    """, subtype='html')

    if not smtp_cfg.get('isTest', False):
        try:
            await aiosmtplib.send(
                msg,
                hostname=smtp_cfg['host'],
                port=smtp_cfg['port'],
                username=smtp_cfg['user'],
                password=smtp_cfg['pass'],
                start_tls=smtp_cfg['start_tls'],
                use_tls=smtp_cfg['use_tls'],
            )
        except Exception as e:
            clean_err = sanitize_smtp_error(str(e), smtp_cfg.get('pass', ''))
            raise HTTPException(status_code=400, detail=f"SMTP test failed: {clean_err}")

    return {
        'success': True,
        'isTest': smtp_cfg.get('isTest', False),
        'recipient': recipient_email,
        'messageId': message_id
    }


async def send_outreach_email(message_id: str, send_options: dict = None):
    if send_options is None:
        send_options = {}

    from app.services.send_guard import (
        assert_not_suppressed,
        assert_send_limits,
        validate_recipient_email,
        assert_domain_match_if_enforced,
    )

    db = get_db()
    mid = to_object_id(message_id)
    if not mid:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    message = await db.outreachmessages.find_one({"_id": mid})
    if not message:
        raise HTTPException(status_code=404, detail="Outreach message not found")

    # E3: Duplicate-send protection — a message that already went out must
    # never be re-sent, even if the scheduler or the UI triggers it again.
    if message.get('status') == 'sent':
        raise HTTPException(
            status_code=409,
            detail="This message has already been sent. Duplicate sends are blocked."
        )

    target_email = send_options.get('recipientEmail') or message.get('recipientEmail')
    if not target_email:
        raise HTTPException(status_code=400, detail="Recipient email address is required")

    # Domain mismatch check if ENFORCE_RECIPIENT_DOMAIN_MATCH is enabled
    company = await db.companies.find_one({"_id": message.get("companyId")}) if message.get("companyId") else None
    if company:
        assert_domain_match_if_enforced(target_email, company.get("website", ""))

    # E8: recipient email syntax validation before any dispatch attempt
    if not validate_recipient_email(target_email):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid recipient email address format: {target_email}"
        )

    cc_list = send_options.get('ccRecipients', message.get('ccRecipients', []))
    bcc_list = send_options.get('bccRecipients', message.get('bccRecipients', []))
    if isinstance(cc_list, str):
        cc_list = [x for x in cc_list.split(',') if x.strip()]
    if isinstance(bcc_list, str):
        bcc_list = [x for x in bcc_list.split(',') if x.strip()]

    # E4: Suppression / opt-out — block before any dispatch, and reject CC/BCC
    # as well so a suppressed recipient cannot receive outreach via cc.
    await assert_not_suppressed(target_email, cc_list)

    smtp_cfg = await get_smtp_config()

    # E3: daily + per-domain limits (test/sandbox sends are exempt by design,
    # so an automated test suite can never consume production quota).
    await assert_send_limits(target_email, is_test=smtp_cfg.get('isTest', False))

    await db.outreachmessages.update_one({"_id": mid}, {"$set": {"status": "sending", "error": ""}})

    try:
        base_url = os.getenv('API_BASE_URL', f"http://localhost:{os.getenv('PORT', 5000)}")
        tracking_pixel = f'<img src="{base_url}/api/track/open/{message_id}.png" width="1" height="1" style="display:none !important;" alt="" />'
        unsubscribe_url = f"{base_url}/api/track/unsubscribe/{message_id}"
        # E7: rewrite outbound links through the click-tracking endpoint so
        # candidate clicks are recorded; non-http(s) links untouched.
        outgoing_html = rewrite_tracking_links(message.get('bodyHtml', ''), message_id, base_url)

        email_message_id = f"<{uuid.uuid4()}@{smtp_cfg['host'] or 'local'}>"
        msg = EmailMessage()
        msg['Message-ID'] = email_message_id
        msg['From'] = smtp_cfg['from']
        msg['To'] = target_email
        if cc_list:
            msg['Cc'] = ", ".join(cc_list) if isinstance(cc_list, list) else cc_list
        if bcc_list:
            msg['Bcc'] = ", ".join(bcc_list) if isinstance(bcc_list, list) else bcc_list
        msg['Subject'] = message.get('subject', '')
        # E4: one-click List-Unsubscribe header pointing to the app's own
        # unsubscribe endpoint (registered suppression applies globally).
        msg['List-Unsubscribe'] = f"<{unsubscribe_url}>"
        msg['List-Unsubscribe-Post'] = "List-Unsubscribe=One-Click"
        msg.set_content(message.get('bodyText', ''))
        msg.add_alternative(f"""
          <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #1f2937;">
            {outgoing_html}
            {tracking_pixel}
          </div>
        """, subtype='html')

        if not smtp_cfg.get('isTest', False):
            await aiosmtplib.send(
                msg,
                hostname=smtp_cfg['host'],
                port=smtp_cfg['port'],
                username=smtp_cfg['user'],
                password=smtp_cfg['pass'],
                start_tls=smtp_cfg['start_tls'],
                use_tls=smtp_cfg['use_tls'],
            )

        now = datetime.now(timezone.utc)
        is_test_send = bool(smtp_cfg.get('isTest', False))
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {
                "status": "sent",
                "sentAt": now,
                "recipientEmail": target_email,
                "ccRecipients": cc_list,
                "bccRecipients": bcc_list,
                "messageId": email_message_id,
                "isTestSend": is_test_send,
                "updatedAt": now
            }}
        )

        dispatch_result = {
            'success': True,
            'sentAt': now,
            'recipientEmail': target_email,
            'ccRecipients': cc_list,
            'bccRecipients': bcc_list,
            'messageId': email_message_id,
            'isTestSend': is_test_send
        }
        await record_email_dispatch(message, dispatch_result)

        return {'success': True, 'message': 'Email dispatched successfully', 'messageId': email_message_id}
    except Exception as e:
        now = datetime.now(timezone.utc)
        secret_to_clean = smtp_cfg.get('pass', '') if 'smtp_cfg' in locals() else ''
        clean_err = sanitize_smtp_error(str(e), secret_to_clean)
        await db.outreachmessages.update_one(
            {"_id": mid},
            {"$set": {"status": "failed", "error": clean_err, "updatedAt": now}}
        )
        dispatch_result = {
            'success': False,
            'error': clean_err,
            'sentAt': now,
            'recipientEmail': target_email,
            'ccRecipients': cc_list,
            'bccRecipients': bcc_list,
            'isTestSend': bool(smtp_cfg.get('isTest', False))
        }
        await record_email_dispatch(message, dispatch_result)
        raise e

