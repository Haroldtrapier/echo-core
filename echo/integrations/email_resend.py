"""Email integration — send transactional / newsletter email via Resend.

Matches the connector contract used by ``publisher._live_publish``: ``send()``
performs the live call and returns a short identifier (the Resend message id),
raising when unconfigured so the publisher records a clean failure. It never
sends unless real credentials are present, and the publish gate
(``ECHO_ALLOW_LIVE_PUBLISH``) upstream keeps everything dry-run by default.

Env:
    RESEND_API_KEY — Resend API key (required to send)
    EMAIL_FROM     — verified sender, e.g. "Echo <noreply@yourdomain.com>"
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import EMAIL_FROM, RESEND_API_KEY
from echo.core.logger import get_logger

log = get_logger("echo.integrations.email_resend")

API_URL = "https://api.resend.com/emails"


def configured() -> bool:
    """True when Resend can actually send (key + sender present)."""
    return bool(RESEND_API_KEY and EMAIL_FROM)


def send(content: dict[str, Any]) -> str:
    """Send an email via Resend. Returns the Resend message id.

    content keys:
        to (str | list[str]): recipient address(es); comma-separated string ok
        subject (str): email subject
        html (str, optional): HTML body
        text | body (str, optional): plain-text body (``body`` is accepted as an
            alias so approval drafts can be sent as-is)
    """
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")
    if not EMAIL_FROM:
        raise RuntimeError("EMAIL_FROM not configured (e.g. 'Echo <noreply@you.com>')")

    to = content.get("to")
    if isinstance(to, str):
        recipients = [a.strip() for a in to.split(",") if a.strip()]
    elif isinstance(to, (list, tuple)):
        recipients = [str(a).strip() for a in to if str(a).strip()]
    else:
        recipients = []
    if not recipients:
        raise ValueError("email 'to' is required")

    subject = content.get("subject") or "(no subject)"
    html = content.get("html")
    text = content.get("text") or content.get("body")
    if not html and not text:
        raise ValueError("provide at least one of 'html' or 'text'/'body'")

    payload: dict[str, Any] = {"from": EMAIL_FROM, "to": recipients, "subject": subject}
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    message_id = result.get("id", "")
    log.info("Resend email sent id=%s to=%d recipient(s)", message_id, len(recipients))
    return message_id
