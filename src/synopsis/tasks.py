"""Celery tasks for asynchronous email delivery and scheduled reminder jobs."""

import logging
import base64

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from celery import shared_task
from django.core.management import call_command


logger = logging.getLogger(__name__)


def _serialize_email_message(message: EmailMultiAlternatives) -> dict:
    payload = {
        "subject": message.subject,
        "body": message.body,
        "from_email": message.from_email,
        "to": list(message.to or []),
        "cc": list(message.cc or []),
        "bcc": list(message.bcc or []),
        "reply_to": list(message.reply_to or []),
        "headers": dict(message.extra_headers or {}),
        "alternatives": [],
        "attachments": [],
    }

    for alternative in getattr(message, "alternatives", []) or []:
        if hasattr(alternative, "content") and hasattr(alternative, "mimetype"):
            content = alternative.content
            mimetype = alternative.mimetype
        else:
            content, mimetype = alternative
        payload["alternatives"].append(
            {
                "content": content,
                "mimetype": mimetype,
            }
        )

    for attachment in getattr(message, "attachments", []) or []:
        if hasattr(attachment, "filename"):
            filename = attachment.filename
            content = attachment.content
            mimetype = attachment.mimetype
        else:
            filename, content, mimetype = attachment
        charset = None
        if isinstance(content, str):
            charset = "utf-8"
            content_bytes = content.encode(charset)
        else:
            content_bytes = bytes(content)
        payload["attachments"].append(
            {
                "filename": filename,
                "content_b64": base64.b64encode(content_bytes).decode("ascii"),
                "mimetype": mimetype,
                "charset": charset,
            }
        )

    return payload


def _build_email_message_from_payload(payload: dict) -> EmailMultiAlternatives:
    message = EmailMultiAlternatives(
        subject=payload.get("subject", ""),
        body=payload.get("body", ""),
        from_email=payload.get("from_email"),
        to=payload.get("to") or None,
        cc=payload.get("cc") or None,
        bcc=payload.get("bcc") or None,
        reply_to=payload.get("reply_to") or None,
        headers=payload.get("headers") or None,
    )
    for alternative in payload.get("alternatives", []):
        message.attach_alternative(
            alternative.get("content", ""),
            alternative.get("mimetype", "text/html"),
        )
    for attachment in payload.get("attachments", []):
        content = base64.b64decode(attachment.get("content_b64", ""))
        charset = attachment.get("charset")
        if charset:
            content = content.decode(charset)
        message.attach(
            attachment.get("filename"),
            content,
            attachment.get("mimetype") or "application/octet-stream",
        )
    return message


def queue_or_send_email_message(message: EmailMultiAlternatives) -> tuple[bool, int | None]:
    if getattr(settings, "ASYNC_EMAIL_DELIVERY", False) and getattr(
        settings, "CELERY_BROKER_URL", ""
    ):
        send_email_message_task.delay(_serialize_email_message(message))
        return True, None
    return False, message.send()


@shared_task(ignore_result=True)
def send_email_message_task(payload: dict):
    logger.info("Sending queued portal email to %s", payload.get("to") or [])
    message = _build_email_message_from_payload(payload)
    message.send()


@shared_task(ignore_result=True)
def send_due_reminders_task():
    logger.info("Running scheduled due-reminder task.")
    call_command("send_due_reminders")
