"""Email, reminders, and shared utility tests."""

from .common import *


class EmailSubjectTests(TestCase):
    def setUp(self):
        self.project = SimpleNamespace(title="Coastal Restoration")

    def test_invite_subject_includes_due_date(self):
        due = timezone.make_aware(datetime(2025, 5, 1, 9, 30))
        expected_due = timezone.localtime(due).strftime("%d %b %Y %H:%M")
        subject = email_subject("invite", self.project, due)
        self.assertEqual(
            subject,
            f"[{BRAND}] Invitation to advise on {self.project.title} (reply by {expected_due})",
        )


class EmailSubjectFormattingTests(TestCase):
    def setUp(self):
        self.project = SimpleNamespace(title="Coastal Restoration")

    def test_invite_reminder_with_date(self):
        due = date(2025, 5, 10)
        subject = email_subject("invite_reminder", self.project, due)
        self.assertEqual(
            subject,
            f"[Reminder] {self.project.title} — please reply by {due.strftime('%d %b %Y')}",
        )

    def test_fallback_subject_for_unknown_kind(self):
        subject = email_subject("unknown", self.project)
        self.assertEqual(subject, f"[{BRAND}] {self.project.title}")

    def test_invite_without_due_date(self):
        subject = email_subject("invite", self.project)
        self.assertEqual(
            subject,
            f"[{BRAND}] Invitation to advise on {self.project.title}",
        )

    def test_protocol_reminder_subject(self):
        due = timezone.make_aware(datetime(2025, 6, 5, 18, 0))
        formatted = timezone.localtime(due).strftime("%d %b %Y %H:%M")
        subject = email_subject("protocol_reminder", self.project, due)
        self.assertEqual(
            subject,
            f"[Reminder] Protocol feedback due for {self.project.title} ({formatted})",
        )

    def test_protocol_review_subject(self):
        subject = email_subject("protocol_review", self.project)
        self.assertEqual(
            subject,
            f"[Action requested] Protocol for review — {self.project.title}",
        )

    def test_advisory_invitation_email_escapes_urls_in_html_hrefs(self):
        text, html_body = _build_advisory_invitation_email(
            project=self.project,
            recipient_name="Will",
            due_date=date(2025, 5, 10),
            yes_url="https://example.com/yes?x=1&y='two'",
            no_url='https://example.com/no?x=1&y="three"',
            attachment_lines=[
                ("Action list", "https://files.example.com/doc?version=1&lang='en'")
            ],
        )

        self.assertIn("https://example.com/yes?x=1&y='two'", text)
        self.assertIn('https://example.com/no?x=1&y="three"', text)
        self.assertIn(
            "href='https://example.com/yes?x=1&amp;y=&#x27;two&#x27;'",
            html_body,
        )
        self.assertIn(
            "href='https://example.com/no?x=1&amp;y=&quot;three&quot;'",
            html_body,
        )
        self.assertIn(
            "href='https://files.example.com/doc?version=1&amp;lang=&#x27;en&#x27;'",
            html_body,
        )
        self.assertIn("Privacy notice:", text)
        self.assertIn("Lawful basis:", text)
        self.assertIn("ICO:", text)
        self.assertIn("<strong>Privacy notice</strong>", html_body)


class ReplyToListTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
    def test_prefers_inviter_email(self):
        self.assertEqual(reply_to_list("inviter@example.com"), ["inviter@example.com"])

    @override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
    def test_uses_fallback_when_inviter_missing(self):
        self.assertEqual(reply_to_list(None), ["fallback@example.com"])


class EnsureGlobalGroupsTests(TestCase):
    def test_creates_all_expected_groups_once(self):
        ensure_global_groups()
        ensure_global_groups()
        names = set(Group.objects.values_list("name", flat=True))
        self.assertTrue(set(GLOBAL_GROUPS).issubset(names))
        self.assertEqual(
            Group.objects.filter(name__in=GLOBAL_GROUPS).count(),
            len(GLOBAL_GROUPS),
        )


class AttachmentSummaryConsoleEmailBackendTests(SimpleTestCase):
    def test_prints_body_and_attachment_summary_without_payload(self):
        stream = io.StringIO()
        backend = AttachmentSummaryConsoleEmailBackend(stream=stream)
        message = EmailMessage(
            "Demo link",
            "Open this link: http://example.com/demo-token",
            "from@example.com",
            ["to@example.com"],
        )
        message.attach(
            "synopsis.docx",
            b"raw document bytes that should not be printed",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        sent = backend.send_messages([message])

        output = stream.getvalue()
        self.assertEqual(sent, 1)
        self.assertIn("Open this link: http://example.com/demo-token", output)
        self.assertIn("synopsis.docx", output)
        self.assertIn("content not printed", output)
        self.assertNotIn("raw document bytes", output)


class CeleryReminderTaskTests(SimpleTestCase):
    @patch("synopsis.tasks.call_command")
    def test_send_due_reminders_task_runs_management_command(self, mock_call_command):
        from ..tasks import send_due_reminders_task

        send_due_reminders_task()

        mock_call_command.assert_called_once_with("send_due_reminders")


class AsyncEmailDeliveryTests(SimpleTestCase):
    @override_settings(
        ASYNC_EMAIL_DELIVERY=True,
        CELERY_BROKER_URL="redis://broker.example:6379/2",
    )
    @patch("synopsis.tasks.send_email_message_task.delay")
    def test_queue_or_send_email_message_queues_serialized_payload(self, mock_delay):
        from ..tasks import queue_or_send_email_message

        message = EmailMultiAlternatives(
            subject="Queued subject",
            body="Queued body",
            from_email="from@example.com",
            to=["to@example.com"],
            reply_to=["reply@example.com"],
        )
        message.attach_alternative("<p>Queued body</p>", "text/html")
        message.attach("notes.txt", "hello", "text/plain")

        queued, sent = queue_or_send_email_message(message)

        self.assertTrue(queued)
        self.assertIsNone(sent)
        mock_delay.assert_called_once()
        payload = mock_delay.call_args.args[0]
        self.assertEqual(payload["subject"], "Queued subject")
        self.assertEqual(payload["to"], ["to@example.com"])
        self.assertEqual(payload["reply_to"], ["reply@example.com"])
        self.assertEqual(payload["alternatives"][0]["mimetype"], "text/html")
        self.assertEqual(payload["attachments"][0]["filename"], "notes.txt")


@override_settings(DEFAULT_FROM_EMAIL="reminders@example.com")
class SendDueRemindersTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Reminder Project")
        self.invite_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ina",
            email="invite@example.com",
            invite_sent=True,
            response_date=date(2025, 1, 10),
        )
        aware_now = timezone.now()
        self.protocol_deadline = aware_now + timedelta(days=5)
        self.protocol_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Proto",
            email="proto@example.com",
            invite_sent=True,
            response="Y",
            sent_protocol_at=aware_now,
            feedback_on_protocol_deadline=self.protocol_deadline,
        )
        self.action_list_deadline = aware_now + timedelta(days=6)
        self.action_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Al",
            email="action@example.com",
            invite_sent=True,
            response="Y",
            sent_action_list_at=aware_now,
            feedback_on_action_list_deadline=self.action_list_deadline,
        )
        self.synopsis_deadline = aware_now + timedelta(days=7)
        self.synopsis_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Syn",
            email="synopsis@example.com",
            invite_sent=True,
            response="Y",
            sent_synopsis_at=aware_now,
            feedback_on_synopsis_deadline=self.synopsis_deadline,
        )

    @patch("synopsis.management.commands.send_due_reminders.EmailMultiAlternatives")
    @patch("synopsis.management.commands.send_due_reminders.minus_business_days")
    @patch("synopsis.management.commands.send_due_reminders.timezone")
    def test_sends_due_reminders_for_active_streams(
        self, mock_timezone, mock_minus, mock_email
    ):
        today = date(2025, 1, 8)
        real_now = timezone.now()
        mock_timezone.localdate.return_value = today
        mock_timezone.now.return_value = real_now
        mock_timezone.localtime.side_effect = lambda value: value

        def minus_side_effect(deadline, offset):
            self.assertEqual(offset, 2)
            return today

        mock_minus.side_effect = minus_side_effect

        email_calls = []

        def build_email(*args, **kwargs):
            instance = MagicMock()
            email_calls.append((args, kwargs, instance))
            return instance

        mock_email.side_effect = build_email

        call_command("send_due_reminders")

        self.assertEqual(len(email_calls), 4)
        for _, _, instance in email_calls:
            instance.send.assert_called_once()

        self.invite_member.refresh_from_db()
        self.protocol_member.refresh_from_db()
        self.action_member.refresh_from_db()
        self.synopsis_member.refresh_from_db()

        self.assertTrue(self.invite_member.reminder_sent)
        self.assertTrue(self.protocol_member.protocol_reminder_sent)
        self.assertTrue(self.action_member.action_list_reminder_sent)
        self.assertTrue(self.synopsis_member.synopsis_reminder_sent)
        self.assertIsNotNone(self.invite_member.reminder_sent_at)
        self.assertIsNotNone(self.protocol_member.protocol_reminder_sent_at)
        self.assertIsNotNone(self.action_member.action_list_reminder_sent_at)
        self.assertIsNotNone(self.synopsis_member.synopsis_reminder_sent_at)

        subjects = [args[0] for args, _, _ in email_calls]
        self.assertIn(
            email_subject("invite_reminder", self.project, self.invite_member.response_date),
            subjects,
        )
        self.assertIn(
            email_subject("protocol_reminder", self.project, self.protocol_deadline),
            subjects,
        )
        self.assertIn(
            email_subject(
                "action_list_reminder", self.project, self.action_list_deadline
            ),
            subjects,
        )
        self.assertIn(
            email_subject("synopsis_reminder", self.project, self.synopsis_deadline),
            subjects,
        )

    @override_settings(ADVISORY_REMINDER_LEAD_BUSINESS_DAYS=-1)
    def test_rejects_negative_reminder_lead_business_days(self):
        with self.assertRaisesMessage(
            CommandError,
            "ADVISORY_REMINDER_LEAD_BUSINESS_DAYS must be a non-negative integer",
        ):
            call_command("send_due_reminders")

    @override_settings(ADVISORY_REMINDER_LEAD_BUSINESS_DAYS="tomorrow")
    def test_rejects_non_integer_reminder_lead_business_days(self):
        with self.assertRaisesMessage(
            CommandError,
            "ADVISORY_REMINDER_LEAD_BUSINESS_DAYS must be an integer",
        ):
            call_command("send_due_reminders")
