from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from synopsis.models import AdvisoryBoardMember
from django.core.mail import EmailMultiAlternatives
from synopsis.utils import email_subject, reply_to_list


def minus_business_days(d, n):
    while n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Weekdays config but can be any.
            n -= 1
    return d


class Command(BaseCommand):
    help = "Email reminders 2 working days before a member's response_date."

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        qs = AdvisoryBoardMember.objects.filter(
            invite_sent=True,
            response_date__isnull=False,
            reminder_sent=False,
        ).exclude(response="N")
        to_remind = [m for m in qs if minus_business_days(m.response_date, 2) == today]
        for m in to_remind:
            subj = email_subject("invite_reminder", m.project, m.response_date)
            body = (
                f"Dear {m.first_name or 'colleague'},\n\n"
                f"This is a reminder that your response for '{m.project.title}' is due by "
                f"{m.response_date.strftime('%d %b %Y')}.\n\nThank you."
            )
            msg = EmailMultiAlternatives(
                subj, body, to=[m.email], reply_to=reply_to_list(None)
            )
            msg.send()
            m.reminder_sent = True
            m.reminder_sent_at = timezone.now()
            m.save(update_fields=["reminder_sent", "reminder_sent_at"])
        proto_qs = AdvisoryBoardMember.objects.filter(
            sent_protocol_at__isnull=False,
            feedback_on_protocol_deadline__isnull=False,
            protocol_reminder_sent=False,
        ).exclude(response="N")
        proto_qs = proto_qs.filter(feedback_on_protocol_received__isnull=True)
        proto_to_remind = [
            m
            for m in proto_qs
            if minus_business_days(m.feedback_on_protocol_deadline, 2) == today
        ]
        for m in proto_to_remind:
            subj = email_subject(
                "protocol_reminder", m.project, m.feedback_on_protocol_deadline
            )
            body = (
                f"Dear {m.first_name or 'colleague'},\n\n"
                f"A reminder that protocol feedback for '{m.project.title}' is due by "
                f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y')}.\n\nThank you."
            )
            msg = EmailMultiAlternatives(
                subj, body, to=[m.email], reply_to=reply_to_list(None)
            )
            msg.send()
            m.protocol_reminder_sent = True
            m.protocol_reminder_sent_at = timezone.now()
            m.save(
                update_fields=["protocol_reminder_sent", "protocol_reminder_sent_at"]
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reminders sent: invites={len(to_remind)}, protocol={len(proto_to_remind)}"
            )
        )
