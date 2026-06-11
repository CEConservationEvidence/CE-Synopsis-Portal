"""Email backend helpers used by local development and test diagnostics."""

import sys

from django.core.mail.backends.base import BaseEmailBackend


class AttachmentSummaryConsoleEmailBackend(BaseEmailBackend):
    """Console email backend that does not dump attachment payloads."""

    def __init__(self, *args, stream=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = stream or sys.stdout

    def _write(self, text=""):
        self.stream.write(f"{text}\n")

    def _attachment_details(self, attachment):
        filename = getattr(attachment, "filename", None)
        content = getattr(attachment, "content", None)
        mimetype = getattr(attachment, "mimetype", None)

        if filename is None and isinstance(attachment, tuple):
            filename, content, mimetype = attachment
        elif filename is None and hasattr(attachment, "get_filename"):
            filename = attachment.get_filename()
            content = attachment.get_payload(decode=True)
            mimetype = attachment.get_content_type()

        if isinstance(content, str):
            size = len(content.encode("utf-8"))
        elif content is None:
            size = 0
        else:
            size = len(content)

        filename = filename or "unnamed attachment"
        mimetype = mimetype or "application/octet-stream"
        return filename, mimetype, size

    def write_message(self, message):
        self._write("=" * 79)
        self._write("Email preview")
        self._write("-" * 79)
        self._write(f"Subject: {message.subject}")
        self._write(f"From: {message.from_email}")
        self._write(f"To: {', '.join(message.to)}")
        if message.cc:
            self._write(f"Cc: {', '.join(message.cc)}")
        if message.bcc:
            self._write(f"Bcc: {', '.join(message.bcc)}")
        if message.reply_to:
            self._write(f"Reply-To: {', '.join(message.reply_to)}")
        self._write()
        self._write(message.body or "")

        alternatives = getattr(message, "alternatives", [])
        for alternative in alternatives:
            content = getattr(alternative, "content", None)
            mimetype = getattr(alternative, "mimetype", None)
            if content is None and isinstance(alternative, tuple):
                content, mimetype = alternative
            if content and mimetype == "text/plain":
                self._write()
                self._write("-- text alternative --")
                self._write(content)

        if message.attachments:
            self._write()
            self._write("Attachments:")
            for attachment in message.attachments:
                filename, mimetype, size = self._attachment_details(attachment)
                self._write(
                    f"- {filename} ({mimetype}, {size:,} bytes; content not printed)"
                )
        self._write("=" * 79)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent = 0
        for message in email_messages:
            self.write_message(message)
            sent += 1
        return sent
