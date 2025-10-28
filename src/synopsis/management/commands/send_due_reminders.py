from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from synopsis.models import AdvisoryBoardMember
from django.core.mail import EmailMultiAlternatives
from synopsis.utils import email_subject, reply_to_list

# TODO: #26 Need to consider using a library for business days calculations if there are any for send_due_reminders.py. Also, need to handle holidays and abroad if applicable.


def minus_business_days(d, n):
    if hasattr(d, "date"):
        d = d.date()
    while n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Weekdays config but can be any.
            n -= 1
    return d


def format_deadline(dt_value):
    if not dt_value:
        return "—"
    try:
        aware = timezone.localtime(dt_value)
    except (ValueError, TypeError):
        aware = dt_value
    return aware.strftime("%d %b %Y %H:%M")


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
            response="Y",
        )
        proto_qs = proto_qs.filter(feedback_on_protocol_received__isnull=True)
        proto_to_remind = []
        for m in proto_qs:
            deadline = m.feedback_on_protocol_deadline
            if not deadline:
                continue
            if minus_business_days(deadline, 2) == today:
                proto_to_remind.append(m)
        for m in proto_to_remind:
            subj = email_subject(
                "protocol_reminder", m.project, m.feedback_on_protocol_deadline
            )
            body = (
                f"Dear {m.first_name or 'colleague'},\n\n"
                f"A reminder that protocol feedback for '{m.project.title}' is due by "
                f"{format_deadline(m.feedback_on_protocol_deadline)}.\n\nThank you."
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
        action_qs = AdvisoryBoardMember.objects.filter(
            sent_action_list_at__isnull=False,
            feedback_on_action_list_deadline__isnull=False,
            action_list_reminder_sent=False,
            response="Y",
        )
        action_qs = action_qs.filter(feedback_on_action_list_received__isnull=True)
        action_to_remind = []
        for m in action_qs:
            deadline = m.feedback_on_action_list_deadline
            if not deadline:
                continue
            if minus_business_days(deadline, 2) == today:
                action_to_remind.append(m)
        for m in action_to_remind:
            subj = email_subject(
                "action_list_reminder", m.project, m.feedback_on_action_list_deadline
            )
            body = (
                f"Dear {m.first_name or 'colleague'},\n\n"
                f"A reminder that action list feedback for '{m.project.title}' is due by "
                f"{format_deadline(m.feedback_on_action_list_deadline)}.\n\nThank you."
            )
            msg = EmailMultiAlternatives(
                subj, body, to=[m.email], reply_to=reply_to_list(None)
            )
            msg.send()
            m.action_list_reminder_sent = True
            m.action_list_reminder_sent_at = timezone.now()
            m.save(
                update_fields=[
                    "action_list_reminder_sent",
                    "action_list_reminder_sent_at",
                ]
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reminders sent: invites={len(to_remind)}, protocol={len(proto_to_remind)}, action_list={len(action_to_remind)}"
            )
        )
