from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User, AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.urls import reverse

import shutil
import tempfile
import textwrap
from django.utils import timezone
from django.core.management import call_command

from .models import (
    AdvisoryBoardInvitation,
    AdvisoryBoardMember,
    AdvisoryBoardCustomField,
    AdvisoryBoardCustomFieldValueHistory,
    Funder,
    Project,
    ProjectChangeLog,
    ProtocolFeedback,
    Protocol,
    ProtocolRevision,
    ActionList,
    ActionListRevision,
    ActionListFeedback,
    CollaborativeSession,
    UserRole,
    ReferenceSourceBatch,
    ReferenceSourceBatchNoteHistory,
    Reference,
)
from .forms import (
    AdvisoryMemberCustomDataForm,
    FunderForm,
    ProjectDeleteForm,
    ProjectSettingsForm,
)
from .utils import (
    BRAND,
    GLOBAL_GROUPS,
    email_subject,
    ensure_global_groups,
    reply_to_list,
)
from .views import (
    _advisory_board_context,
    _create_protocol_feedback,
    _format_deadline,
    _format_value,
    _funder_contact_label,
    _log_project_change,
    _user_can_confirm_phase,
    _user_is_manager,
    _user_can_edit_project,
    protocol_delete_revision,
    action_list_delete_revision,
    _parse_plaintext_references,
)

# TODO: #25 Clean up tests.py and see if some tests can be split into separate files.


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


class ProjectPhaseTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Marine Study")

    def _create_protocol(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.txt", b"Test content"),
        )

    def test_defaults_to_draft_protocol_without_protocol(self):
        self.assertEqual(self.project.compute_phase(), "draft_protocol")

    def test_requires_invites_after_protocol(self):
        self._create_protocol()
        self.assertEqual(self.project.compute_phase(), "invite_advisory_board")

    def test_acceptance_moves_to_references_screening(self):
        self._create_protocol()
        AdvisoryBoardInvitation.objects.create(
            project=self.project,
            email="member@example.com",
            accepted=True,
        )
        self.assertEqual(self.project.compute_phase(), "references_screening")

    def test_manual_phase_does_not_regress(self):
        self._create_protocol()
        AdvisoryBoardInvitation.objects.create(
            project=self.project,
            email="member@example.com",
            accepted=True,
        )
        self.project.phase_manual = "draft_protocol"
        self.project.save(update_fields=["phase_manual"])
        self.assertEqual(self.project.phase, "references_screening")

    def test_manual_phase_can_advance(self):
        self._create_protocol()
        self.project.phase_manual = "summary_writing"
        self.project.save(update_fields=["phase_manual"])
        self.assertEqual(self.project.phase, "summary_writing")


class ProjectAuthorUsersTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Author Demo")
        self.author = User.objects.create_user(username="zoe")
        self.coauthor = User.objects.create_user(username="adam")
        self.manager = User.objects.create_user(username="manager")

        UserRole.objects.create(user=self.author, project=self.project, role="author")
        UserRole.objects.create(user=self.coauthor, project=self.project, role="author")
        UserRole.objects.create(user=self.manager, project=self.project, role="manager")

    def test_returns_authors_sorted_by_username(self):
        usernames = list(self.project.author_users.values_list("username", flat=True))
        self.assertEqual(usernames, ["adam", "zoe"])


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

    @patch("synopsis.management.commands.send_due_reminders.EmailMultiAlternatives")
    @patch("synopsis.management.commands.send_due_reminders.minus_business_days")
    @patch("synopsis.management.commands.send_due_reminders.timezone")
    def test_sends_due_reminders_for_all_streams(
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

        self.assertEqual(len(email_calls), 3)
        for _, _, instance in email_calls:
            instance.send.assert_called_once()

        self.invite_member.refresh_from_db()
        self.protocol_member.refresh_from_db()
        self.action_member.refresh_from_db()

        self.assertTrue(self.invite_member.reminder_sent)
        self.assertTrue(self.protocol_member.protocol_reminder_sent)
        self.assertTrue(self.action_member.action_list_reminder_sent)
        self.assertIsNotNone(self.invite_member.reminder_sent_at)
        self.assertIsNotNone(self.protocol_member.protocol_reminder_sent_at)
        self.assertIsNotNone(self.action_member.action_list_reminder_sent_at)

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


class MemberReminderUpdateTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Inline Reminders")
        self.user = User.objects.create_user(username="owner", password="pw")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.board_url = reverse("synopsis:advisory_board_list", args=[self.project.id])

    def test_update_response_deadline(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Randy",
            email="randy@example.com",
            reminder_sent=True,
            reminder_sent_at=timezone.now(),
        )
        target_date = date(2025, 2, 20)
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
            {"reminder_date": target_date.strftime("%Y-%m-%d")},
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertEqual(member.response_date, target_date)
        self.assertFalse(member.reminder_sent)
        self.assertIsNone(member.reminder_sent_at)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action="Updated invite reminder"
            ).exists()
        )

    def test_clear_response_deadline(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Clara",
            email="clara@example.com",
            response_date=date(2024, 12, 1),
            reminder_sent=True,
            reminder_sent_at=timezone.now(),
        )
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
            {"clear_deadline": "1"},
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNone(member.response_date)
        self.assertFalse(member.reminder_sent)
        self.assertIsNone(member.reminder_sent_at)

    def test_update_protocol_deadline(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Paula",
            email="paula@example.com",
            response="Y",
            sent_protocol_at=timezone.now(),
            protocol_reminder_sent=True,
            protocol_reminder_sent_at=timezone.now(),
        )
        ProtocolFeedback.objects.create(project=self.project, member=member)
        deadline = timezone.now().replace(second=0, microsecond=0) + timedelta(days=4)
        local_deadline = timezone.localtime(deadline)
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "protocol"],
            ),
            {"deadline": local_deadline.strftime("%Y-%m-%dT%H:%M")},
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNotNone(member.feedback_on_protocol_deadline)
        self.assertAlmostEqual(
            member.feedback_on_protocol_deadline.timestamp(), deadline.timestamp(), delta=1
        )
        self.assertFalse(member.protocol_reminder_sent)
        self.assertIsNone(member.protocol_reminder_sent_at)
        feedback = ProtocolFeedback.objects.get(project=self.project, member=member)
        self.assertIsNotNone(feedback.feedback_deadline_at)
        self.assertAlmostEqual(
            feedback.feedback_deadline_at.timestamp(), deadline.timestamp(), delta=1
        )
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action="Updated protocol reminder"
            ).exists()
        )

    def test_update_action_list_deadline(self):
        action_list = ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.txt", b"test"),
        )
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Alex",
            email="alex@example.com",
            response="Y",
            sent_action_list_at=timezone.now(),
            action_list_reminder_sent=True,
            action_list_reminder_sent_at=timezone.now(),
        )
        ActionListFeedback.objects.create(
            project=self.project, member=member, action_list=action_list
        )
        deadline = timezone.now().replace(second=0, microsecond=0) + timedelta(days=6)
        local_deadline = timezone.localtime(deadline)
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "action-list"],
            ),
            {"deadline": local_deadline.strftime("%Y-%m-%dT%H:%M")},
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNotNone(member.feedback_on_action_list_deadline)
        self.assertAlmostEqual(
            member.feedback_on_action_list_deadline.timestamp(),
            deadline.timestamp(),
            delta=1,
        )
        self.assertFalse(member.action_list_reminder_sent)
        self.assertIsNone(member.action_list_reminder_sent_at)
        feedback = ActionListFeedback.objects.get(project=self.project, member=member)
        self.assertIsNotNone(feedback.feedback_deadline_at)
        self.assertAlmostEqual(
            feedback.feedback_deadline_at.timestamp(),
            deadline.timestamp(),
            delta=1,
        )
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action="Updated action list reminder"
            ).exists()
        )

    def test_declined_member_cannot_schedule_invite(self):
        original_date = date(2024, 11, 15)
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Dana",
            email="dana@example.com",
            response="N",
            response_date=original_date,
            reminder_sent=True,
            reminder_sent_at=timezone.now(),
        )
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
            {"reminder_date": "2025-01-01"},
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertEqual(member.response_date, original_date)
        self.assertTrue(member.reminder_sent)

    def test_decline_captures_optional_reason(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Iggy",
            email="iggy@example.com",
        )
        inv = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
        )
        url = reverse("synopsis:advisory_invite_reply", args=[str(inv.token), "no"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        decline_reason = "Unavailable this cycle"
        response = self.client.post(url, data={"reason": decline_reason})
        self.assertEqual(response.status_code, 200)

        member.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(member.response, "N")
        self.assertEqual(member.participation_statement, decline_reason)
        self.assertFalse(inv.accepted)
        self.assertIsNotNone(inv.responded_at)
        self.assertFalse(inv.accepted)

    def test_edit_member_details(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            title="Dr",
            first_name="Casey",
            last_name="Smith",
            email="casey@example.com",
            organisation="Org",
        )

        payload = {
            "title": "Prof",
            "first_name": "Casey",
            "middle_name": "A",
            "last_name": "Jones",
            "organisation": "Updated Org",
            "email": "casey@example.com",
            "location": "London",
            "continent": "Europe",
            "notes": "Updated notes",
        }

        url = reverse(
            "synopsis:advisory_member_edit",
            args=[self.project.id, member.id],
        )
        response = self.client.post(url, data=payload)

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertEqual(member.title, "Prof")
        self.assertEqual(member.last_name, "Jones")
        self.assertEqual(member.organisation, "Updated Org")
        self.assertEqual(member.location, "London")
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project,
                action="Updated advisory member",
            ).exists()
        )

    def test_decline_reason_length_validation(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Lee",
            email="lee@example.com",
        )
        inv = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
        )
        url = reverse("synopsis:advisory_invite_reply", args=[str(inv.token), "no"])
        long_reason = "x" * 201
        response = self.client.post(url, data={"reason": long_reason})

        self.assertEqual(response.status_code, 200)
        form = response.context.get("form")
        self.assertIsNotNone(form)
        self.assertTrue(form.errors)
        self.assertIn("reason", form.errors)

        member.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(member.participation_statement, "")
        self.assertIsNone(inv.accepted)


class AdvisoryInviteFlowTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Invite Flow")
        self.user = User.objects.create_user(
            username="author", password="pw", email="author@example.com"
        )
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.board_url = reverse("synopsis:advisory_board_list", args=[self.project.id])

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_single_invite_sets_due_date_and_resets_flags(self, mock_email):
        mock_email.return_value = MagicMock()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Nova",
            email="nova@example.com",
            reminder_sent=True,
            reminder_sent_at=timezone.now(),
        )
        due = date(2025, 11, 30)
        url = reverse(
            "synopsis:advisory_invite_create_for_member",
            args=[self.project.id, member.id],
        )
        response = self.client.post(
            url,
            {
                "email": member.email,
                "due_date": due.strftime("%Y-%m-%d"),
                "message": "Welcome aboard",
            },
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertTrue(member.invite_sent)
        self.assertEqual(member.response_date, due)
        self.assertFalse(member.reminder_sent)
        self.assertIsNone(member.reminder_sent_at)
        self.assertEqual(
            AdvisoryBoardInvitation.objects.filter(member=member).count(), 1
        )
        self.assertEqual(mock_email.call_count, 1)

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_bulk_invite_skips_members_with_existing_invites(self, mock_email):
        mock_email.return_value = MagicMock()
        already_invited = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Iris",
            email="iris@example.com",
            invite_sent=True,
            invite_sent_at=timezone.now(),
            response_date=date(2025, 10, 1),
        )
        new_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Liam",
            email="liam@example.com",
        )
        due = date(2025, 12, 20)
        response = self.client.post(
            reverse("synopsis:advisory_send_invites_bulk", args=[self.project.id]),
            {
                "due_date": due.strftime("%Y-%m-%d"),
                "message": "Bulk kickoff",
            },
        )
        self.assertRedirects(response, self.board_url)
        new_member.refresh_from_db()
        already_invited.refresh_from_db()
        self.assertTrue(new_member.invite_sent)
        self.assertEqual(new_member.response_date, due)
        self.assertEqual(already_invited.response_date, date(2025, 10, 1))
        self.assertEqual(
            AdvisoryBoardInvitation.objects.filter(project=self.project).count(), 1
        )
        self.assertEqual(mock_email.call_count, 1)
        args, kwargs = mock_email.call_args
        self.assertEqual(kwargs["to"], [new_member.email])


class FunderUtilityTests(TestCase):
    def test_build_display_name_prefers_organisation(self):
        name = Funder.build_display_name("Org Inc", "Dr", "Ann", "Lee")
        self.assertEqual(name, "Org Inc")

    def test_build_display_name_from_names(self):
        name = Funder.build_display_name(None, "Dr", "Ann", "Lee")
        self.assertEqual(name, "Dr Ann Lee")

    def test_build_display_name_default(self):
        self.assertEqual(Funder.build_display_name(None, None, None, None), "(Funder)")


class FunderFormTests(TestCase):
    def test_requires_identity_when_other_fields_provided(self):
        form = FunderForm(
            data={
                "organisation": "",
                "contact_title": "Dr",
                "contact_first_name": "",
                "contact_last_name": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Provide an organisation", form.errors.get("__all__")[0])

    def test_valid_with_only_organisation(self):
        form = FunderForm(data={"organisation": "Ocean Trust"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.has_identity_fields())
        self.assertTrue(form.has_meaningful_input())

    def test_empty_form_has_no_meaningful_input(self):
        form = FunderForm(data={})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.has_meaningful_input())

    def test_start_date_cannot_be_after_end_date(self):
        form = FunderForm(
            data={
                "organisation": "Ocean Trust",
                "fund_start_date": "2025-02-01",
                "fund_end_date": "2025-01-01",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Start date cannot be after the end date.",
            form.errors.get("fund_start_date", []),
        )
        self.assertIn(
            "Start date cannot be after the end date.",
            form.errors.get("fund_end_date", []),
        )

    def test_start_end_date_valid_when_ordered(self):
        form = FunderForm(
            data={
                "organisation": "Ocean Trust",
                "fund_start_date": "2025-01-01",
                "fund_end_date": "2025-02-01",
            }
        )
        self.assertTrue(form.is_valid())


class AdvisoryBoardCustomColumnsDynamicTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Dynamic Columns")
        self.editor = User.objects.create_user(username="editor")
        self.accepted = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ada",
            email="ada@example.com",
            response="Y",
        )
        self.pending = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ben",
            email="ben@example.com",
            response="",
        )
        self.general_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="General note",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        self.pending_only_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Follow-up date",
            data_type=AdvisoryBoardCustomField.TYPE_DATE,
            sections=[AdvisoryBoardCustomField.SECTION_PENDING],
        )
        self.general_field.set_value_for_member(self.accepted, "Confirmed")
        self.general_field.set_value_for_member(self.pending, "Need reply")
        self.pending_only_field.set_value_for_member(self.pending, date(2025, 5, 1))

    def test_section_fields_match_custom_field_configuration(self):
        context = _advisory_board_context(self.project)
        sections = {section["key"]: section for section in context["member_sections"]}

        accepted_field_ids = [
            field.id
            for field in sections[AdvisoryBoardCustomField.SECTION_ACCEPTED]["fields"]
        ]
        pending_field_ids = [
            field.id
            for field in sections[AdvisoryBoardCustomField.SECTION_PENDING]["fields"]
        ]

        self.assertEqual(accepted_field_ids, [self.general_field.id])
        self.assertEqual(
            pending_field_ids, [self.general_field.id, self.pending_only_field.id]
        )

    def test_member_rows_include_formatted_custom_values(self):
        context = _advisory_board_context(self.project)
        sections = {section["key"]: section for section in context["member_sections"]}

        accepted_member = sections[AdvisoryBoardCustomField.SECTION_ACCEPTED][
            "members"
        ][0]
        pending_member = sections[AdvisoryBoardCustomField.SECTION_PENDING]["members"][
            0
        ]

        self.assertEqual(
            accepted_member.custom_field_values[self.general_field.id], "Confirmed"
        )
        self.assertEqual(
            pending_member.custom_field_values[self.general_field.id], "Need reply"
        )
        self.assertEqual(
            pending_member.custom_field_values[self.pending_only_field.id], "2025-05-01"
        )
        self.assertNotIn(
            self.pending_only_field.id, accepted_member.custom_field_values
        )

    def test_custom_fields_list_exposes_all_configured_fields(self):
        context = _advisory_board_context(self.project)
        custom_field_ids = [field.id for field in context["custom_fields"]]
        self.assertEqual(
            custom_field_ids, [self.general_field.id, self.pending_only_field.id]
        )

    def test_custom_fields_can_target_specific_table_groups(self):
        invite_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Invite progress",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
            display_group=AdvisoryBoardCustomField.DISPLAY_GROUP_INVITATION,
        )
        synopsis_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Synopsis note",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
            sections=[AdvisoryBoardCustomField.SECTION_PENDING],
            display_group=AdvisoryBoardCustomField.DISPLAY_GROUP_SYNOPSIS,
        )

        context = _advisory_board_context(self.project)
        sections = {section["key"]: section for section in context["member_sections"]}
        pending_groups = sections[AdvisoryBoardCustomField.SECTION_PENDING][
            "fields_by_group"
        ]
        accepted_groups = sections[AdvisoryBoardCustomField.SECTION_ACCEPTED][
            "fields_by_group"
        ]

        self.assertIn(
            invite_field.id,
            [field.id for field in pending_groups[AdvisoryBoardCustomField.DISPLAY_GROUP_INVITATION]],
        )
        self.assertIn(
            invite_field.id,
            [field.id for field in accepted_groups[AdvisoryBoardCustomField.DISPLAY_GROUP_INVITATION]],
        )
        self.assertEqual(
            [field.id for field in pending_groups[AdvisoryBoardCustomField.DISPLAY_GROUP_SYNOPSIS]],
            [synopsis_field.id],
        )
        self.assertEqual(
            [field.id for field in pending_groups[AdvisoryBoardCustomField.DISPLAY_GROUP_CUSTOM]],
            [self.general_field.id, self.pending_only_field.id],
        )
        self.assertEqual(
            [field.id for field in accepted_groups[AdvisoryBoardCustomField.DISPLAY_GROUP_CUSTOM]],
            [self.general_field.id],
        )

    def test_move_custom_field_action_updates_display_group(self):
        self.client.force_login(self.editor)
        url = reverse("synopsis:advisory_board_list", args=[self.project.id])
        response = self.client.post(
            url,
            {
                "action": "custom_field_move",
                "field_id": self.general_field.id,
                "display_group": AdvisoryBoardCustomField.DISPLAY_GROUP_PROTOCOL,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.general_field.refresh_from_db()
        self.assertEqual(
            self.general_field.display_group,
            AdvisoryBoardCustomField.DISPLAY_GROUP_PROTOCOL,
        )

    def test_history_records_updates(self):
        base_count = AdvisoryBoardCustomFieldValueHistory.objects.filter(
            field=self.general_field, member=self.accepted
        ).count()

        self.general_field.set_value_for_member(
            self.accepted, "Updated note", changed_by=self.editor
        )
        self.general_field.set_value_for_member(
            self.accepted, "", changed_by=self.editor
        )

        history = AdvisoryBoardCustomFieldValueHistory.objects.filter(
            field=self.general_field, member=self.accepted
        ).order_by("-created_at")

        self.assertEqual(history.count(), base_count + 2)
        latest = history.first()
        self.assertTrue(latest.is_cleared)
        previous = history[1]
        self.assertEqual(previous.value, "Updated note")
        self.assertEqual(previous.changed_by, self.editor)

    def test_history_shows_current_value_first(self):
        self.general_field.set_value_for_member(
            self.accepted, "First", changed_by=self.editor
        )
        self.general_field.set_value_for_member(
            self.accepted, "Second", changed_by=self.editor
        )

        history = list(
            AdvisoryBoardCustomFieldValueHistory.objects.filter(
                field=self.general_field, member=self.accepted
            )
        )

        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[0].value, "Second")


class AdvisoryMemberCustomDataFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Form Columns")
        self.shared_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Notes",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        self.pending_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Reminder",
            data_type=AdvisoryBoardCustomField.TYPE_BOOLEAN,
            sections=[AdvisoryBoardCustomField.SECTION_PENDING],
        )

    def test_form_includes_only_fields_for_member_section(self):
        initial_values = {self.shared_field.id: "hello"}
        accepted_form = AdvisoryMemberCustomDataForm(
            [self.shared_field, self.pending_field],
            AdvisoryBoardCustomField.SECTION_ACCEPTED,
            initial_values,
        )
        accepted_field_ids = [field.id for field, _ in accepted_form.iter_fields()]
        self.assertEqual(accepted_field_ids, [self.shared_field.id])

        pending_form = AdvisoryMemberCustomDataForm(
            [self.shared_field, self.pending_field],
            AdvisoryBoardCustomField.SECTION_PENDING,
            initial_values,
        )
        pending_field_ids = [field.id for field, _ in pending_form.iter_fields()]
        self.assertEqual(
            pending_field_ids, [self.shared_field.id, self.pending_field.id]
        )

    def test_initial_values_are_parsed_for_form_fields(self):
        initial_values = {
            self.shared_field.id: "value",
            self.pending_field.id: "true",
        }
        form = AdvisoryMemberCustomDataForm(
            [self.shared_field, self.pending_field],
            AdvisoryBoardCustomField.SECTION_PENDING,
            initial_values,
        )
        key_shared = form._field_key(self.shared_field)
        key_pending = form._field_key(self.pending_field)
        self.assertEqual(form.initial[key_shared], "value")
        self.assertTrue(form.initial[key_pending])


class AdvisoryMemberCustomDataViewTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="View Columns")
        self.manager = User.objects.create_user(username="manager", password="x")
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        self.member = AdvisoryBoardMember.objects.create(
            project=self.project,
            email="member@example.com",
            first_name="Mia",
            response="Y",
        )
        self.field_one = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Engagement",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        self.field_two = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Notes",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        self.field_one.set_value_for_member(
            self.member, "Initial", changed_by=self.manager
        )
        self.field_two.set_value_for_member(
            self.member, "Aux", changed_by=self.manager
        )
        self.url = reverse(
            "synopsis:advisory_member_custom_data",
            args=[self.project.id, self.member.id],
        )
        self.client.force_login(self.manager)

    def test_focus_field_filters_form_and_history(self):
        response = self.client.get(self.url, {"field": self.field_one.id})
        self.assertEqual(response.status_code, 200)
        fields = response.context["fields"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].id, self.field_one.id)
        form_fields = list(response.context["form"].fields.keys())
        self.assertEqual(form_fields, [f"field_{self.field_one.id}"])
        history_map = response.context["history_map"]
        self.assertEqual(list(history_map.keys()), [self.field_one.id])

    def test_without_focus_shows_all_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        field_ids = [field.id for field in response.context["fields"]]
        self.assertCountEqual(field_ids, [self.field_one.id, self.field_two.id])


class OnlyOfficeDownloadTests(TestCase):
    def setUp(self):
        from . import views

        self.views = views
        self.original_settings = views.ONLYOFFICE_SETTINGS
        views.ONLYOFFICE_SETTINGS = {
            "base_url": "https://onlyoffice.example.com/office",
            "callback_timeout": 7,
        }
        self.addCleanup(self._restore_settings)

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    @patch("synopsis.views.requests.get")
    def test_download_allows_trusted_host(self, mock_get):
        mock_response = MagicMock()
        mock_response.content = b"doc"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        url = "https://onlyoffice.example.com/office/storage/doc.docx"
        content = self.views._download_onlyoffice_file(url)

        self.assertEqual(content, b"doc")
        mock_get.assert_called_once_with(url, timeout=7)

    @patch("synopsis.views.requests.get")
    def test_download_rejects_untrusted_host(self, mock_get):
        url = "https://files.example.com/storage/doc.docx"
        with self.assertRaisesMessage(ValueError, "Untrusted OnlyOffice download URL"):
            self.views._download_onlyoffice_file(url)
        mock_get.assert_not_called()

    @patch("synopsis.views.requests.get")
    def test_download_rejects_untrusted_path(self, mock_get):
        url = "https://onlyoffice.example.com/other/doc.docx"
        with self.assertRaisesMessage(ValueError, "Untrusted OnlyOffice download URL"):
            self.views._download_onlyoffice_file(url)
        mock_get.assert_not_called()


class CollaborativeClosureTests(TestCase):
    def setUp(self):
        from . import views

        self.views = views
        self.original_settings = views.ONLYOFFICE_SETTINGS
        views.ONLYOFFICE_SETTINGS = {
            "base_url": "https://onlyoffice.example.com/office",
            "callback_timeout": 5,
        }
        self.addCleanup(self._restore_settings)

        self.factory = RequestFactory()
        self.project = Project.objects.create(title="Collaborative Close")
        self.manager = User.objects.create_user(username="manager", password="pw")
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        UserRole.objects.create(user=self.manager, project=self.project, role="manager")
        self.client.force_login(self.manager)
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile(
                "protocol.docx",
                b"test-protocol",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    def _build_request(self):
        request = self.factory.get("/", HTTP_HOST="testserver")
        request.user = self.manager
        return request

    def test_closing_protocol_disables_collaborative_session(self):
        request = self._build_request()
        url = self.views._ensure_collaborative_invite_link(
            request,
            self.project,
            CollaborativeSession.DOCUMENT_PROTOCOL,
            None,
        )
        self.assertTrue(url)
        session = CollaborativeSession.objects.get(
            project=self.project, document_type=CollaborativeSession.DOCUMENT_PROTOCOL
        )
        self.assertTrue(session.is_active)

        close_url = reverse(
            "synopsis:advisory_protocol_feedback_close", args=[self.project.id]
        )
        response = self.client.post(close_url, {"message": "Window closed"})
        self.assertRedirects(
            response,
            reverse("synopsis:advisory_board_list", args=[self.project.id]),
        )

        self.project = Project.objects.get(id=self.project.id)
        self.protocol = self.project.protocol

        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.ended_at)

        request = self._build_request()
        disabled_url = self.views._ensure_collaborative_invite_link(
            request,
            self.project,
            CollaborativeSession.DOCUMENT_PROTOCOL,
            None,
        )
        self.assertEqual(disabled_url, "")
        self.assertEqual(
            CollaborativeSession.objects.filter(
                project=self.project,
                document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
                is_active=True,
            ).count(),
            0,
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Window closed")
        self.assertTemplateUsed(response, "synopsis/collaborative_editor.html")

        start_url = reverse(
            "synopsis:collaborative_start",
            args=[self.project.id, "protocol"],
        )
        response = self.client.post(start_url)
        self.assertRedirects(
            response,
            reverse("synopsis:protocol_detail", args=[self.project.id]),
        )
        self.assertEqual(
            CollaborativeSession.objects.filter(
                project=self.project,
                document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
                is_active=True,
            ).count(),
            0,
        )

        reopen_response = self.client.post(close_url, {"action": "reopen"})
        self.assertRedirects(
            reopen_response,
            reverse("synopsis:advisory_board_list", args=[self.project.id]),
        )
        self.project.refresh_from_db()
        self.assertIsNone(self.project.protocol.feedback_closed_at)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response["Location"], url)
        parsed = urlparse(response["Location"])
        new_token = parsed.path.rstrip("/").split("/")[-1]
        new_session = CollaborativeSession.objects.get(token=new_token)
        self.assertTrue(new_session.is_active)


class CollaborativePanelViewTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Collaborative Panel")
        self.user = User.objects.create_user(username="collab-author", password="pw")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)

    def test_protocol_panel_disabled_without_document(self):
        response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        self.assertContains(
            response, "Upload the protocol before starting a collaborative session."
        )
        self.assertIn('aria-disabled="true"', response.content.decode())

    def test_protocol_panel_enabled_with_document(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        self.assertNotContains(
            response, "Upload the protocol before starting a collaborative session."
        )

    def test_action_list_panel_disabled_without_document(self):
        response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertContains(
            response, "Upload the action list before starting a collaborative session."
        )
        self.assertIn('aria-disabled="true"', response.content.decode())

    def test_action_list_panel_enabled_with_document(self):
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
        )
        response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertNotContains(
            response, "Upload the action list before starting a collaborative session."
        )


class AdvisoryBoardCustomColumnsTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Dynamic Columns")
        self.editor = User.objects.create_user(username="editor-secondary")
        self.accepted = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ada",
            email="ada@example.com",
            response="Y",
        )
        self.pending = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ben",
            email="ben@example.com",
            response="",
        )
        self.general_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="General note",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        self.pending_only_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Follow-up date",
            data_type=AdvisoryBoardCustomField.TYPE_DATE,
            sections=[AdvisoryBoardCustomField.SECTION_PENDING],
        )
        self.general_field.set_value_for_member(self.accepted, "Confirmed")
        self.general_field.set_value_for_member(self.pending, "Need reply")
        self.pending_only_field.set_value_for_member(self.pending, date(2025, 5, 1))

    def test_section_fields_match_custom_field_configuration(self):
        context = _advisory_board_context(self.project)
        sections = {section["key"]: section for section in context["member_sections"]}

        accepted_field_ids = [
            field.id
            for field in sections[AdvisoryBoardCustomField.SECTION_ACCEPTED]["fields"]
        ]
        pending_field_ids = [
            field.id
            for field in sections[AdvisoryBoardCustomField.SECTION_PENDING]["fields"]
        ]

        self.assertEqual(accepted_field_ids, [self.general_field.id])
        self.assertEqual(
            pending_field_ids, [self.general_field.id, self.pending_only_field.id]
        )

    def test_member_rows_include_formatted_custom_values(self):
        context = _advisory_board_context(self.project)
        sections = {section["key"]: section for section in context["member_sections"]}

        accepted_member = sections[AdvisoryBoardCustomField.SECTION_ACCEPTED][
            "members"
        ][0]
        pending_member = sections[AdvisoryBoardCustomField.SECTION_PENDING]["members"][
            0
        ]

        self.assertEqual(
            accepted_member.custom_field_values[self.general_field.id], "Confirmed"
        )
        self.assertEqual(
            pending_member.custom_field_values[self.general_field.id], "Need reply"
        )
        self.assertEqual(
            pending_member.custom_field_values[self.pending_only_field.id], "2025-05-01"
        )
        self.assertNotIn(
            self.pending_only_field.id, accepted_member.custom_field_values
        )

    def test_custom_fields_list_exposes_all_configured_fields(self):
        context = _advisory_board_context(self.project)
        custom_field_ids = [field.id for field in context["custom_fields"]]
        self.assertEqual(
            custom_field_ids, [self.general_field.id, self.pending_only_field.id]
        )

    def test_history_records_updates(self):
        base_count = AdvisoryBoardCustomFieldValueHistory.objects.filter(
            field=self.general_field, member=self.accepted
        ).count()

        self.general_field.set_value_for_member(
            self.accepted, "Updated note", changed_by=self.editor
        )
        self.general_field.set_value_for_member(
            self.accepted, "", changed_by=self.editor
        )

        history = AdvisoryBoardCustomFieldValueHistory.objects.filter(
            field=self.general_field, member=self.accepted
        ).order_by("-created_at")

        self.assertEqual(history.count(), base_count + 2)
        latest = history.first()
        self.assertTrue(latest.is_cleared)
        previous = history[1]
        self.assertEqual(previous.value, "Updated note")
        self.assertEqual(previous.changed_by, self.editor)




class UserEditPermissionTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Permissions Project")
        self.manager = User.objects.create_user(username="manager_user")
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        self.author = User.objects.create_user(username="author_user")
        UserRole.objects.create(user=self.author, project=self.project, role="author")
        self.viewer = User.objects.create_user(username="viewer_user")

    def test_manager_can_edit_project(self):
        self.assertTrue(_user_can_edit_project(self.manager, self.project))

    def test_author_can_edit_project(self):
        self.assertTrue(_user_can_edit_project(self.author, self.project))

    def test_other_user_cannot_edit_project(self):
        self.assertFalse(_user_can_edit_project(self.viewer, self.project))


class RevisionDeleteViewTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

        ensure_global_groups()

        self.factory = RequestFactory()
        self.project = Project.objects.create(title="Revision Project")
        self.author = User.objects.create_user(username="author", password="pwd")
        UserRole.objects.create(user=self.author, project=self.project, role="author")
        self.other_user = User.objects.create_user(username="other", password="pwd")

        # Protocol setup
        base_file = SimpleUploadedFile("protocol_base.docx", b"base")
        self.protocol = Protocol.objects.create(
            project=self.project, document=base_file
        )
        self.rev1 = ProtocolRevision.objects.create(
            protocol=self.protocol,
            file=SimpleUploadedFile("protocol_rev1.docx", b"rev1"),
            stage="draft",
            change_reason="Initial",
        )
        self.protocol.current_revision = self.rev1
        self.protocol.save(update_fields=["current_revision"])
        self.rev2 = ProtocolRevision.objects.create(
            protocol=self.protocol,
            file=SimpleUploadedFile("protocol_rev2.docx", b"rev2"),
            stage="draft",
            change_reason="Second",
        )
        self.protocol.current_revision = self.rev2
        self.protocol.save(update_fields=["current_revision"])

        # Action list setup
        action_file = SimpleUploadedFile("action_base.docx", b"alist")
        self.action_list = ActionList.objects.create(
            project=self.project,
            document=action_file,
        )
        self.al_rev1 = ActionListRevision.objects.create(
            action_list=self.action_list,
            file=SimpleUploadedFile("action_rev1.docx", b"rev1"),
            stage="draft",
            change_reason="Initial",
        )
        self.action_list.current_revision = self.al_rev1
        self.action_list.save(update_fields=["current_revision"])
        self.al_rev2 = ActionListRevision.objects.create(
            action_list=self.action_list,
            file=SimpleUploadedFile("action_rev2.docx", b"rev2"),
            stage="draft",
            change_reason="Second",
        )
        self.action_list.current_revision = self.al_rev2
        self.action_list.save(update_fields=["current_revision"])

    def _add_session_and_messages(self, request):
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)

    def test_author_can_delete_protocol_revision(self):
        request = self.factory.post(
            f"/project/{self.project.id}/protocol/revision/{self.rev2.id}/delete/"
        )
        request.user = self.author
        self._add_session_and_messages(request)

        response = protocol_delete_revision(request, self.project.id, self.rev2.id)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProtocolRevision.objects.filter(pk=self.rev2.pk).exists())
        self.protocol.refresh_from_db()
        self.assertEqual(self.protocol.current_revision_id, self.rev1.id)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action__icontains="Protocol revision deleted"
            ).exists()
        )

    def test_non_editor_cannot_delete_protocol_revision(self):
        request = self.factory.post(
            f"/project/{self.project.id}/protocol/revision/{self.rev1.id}/delete/"
        )
        request.user = self.other_user
        self._add_session_and_messages(request)

        response = protocol_delete_revision(request, self.project.id, self.rev1.id)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProtocolRevision.objects.filter(pk=self.rev1.pk).exists())

    def test_author_can_delete_action_list_revision(self):
        request = self.factory.post(
            f"/project/{self.project.id}/action-list/revision/{self.al_rev2.id}/delete/"
        )
        request.user = self.author
        self._add_session_and_messages(request)

        response = action_list_delete_revision(
            request, self.project.id, self.al_rev2.id
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ActionListRevision.objects.filter(pk=self.al_rev2.pk).exists())
        self.action_list.refresh_from_db()
        self.assertEqual(self.action_list.current_revision_id, self.al_rev1.id)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action__icontains="Action list revision deleted"
            ).exists()
        )

    def test_non_editor_cannot_delete_action_list_revision(self):
        request = self.factory.post(
            f"/project/{self.project.id}/action-list/revision/{self.al_rev1.id}/delete/"
        )
        request.user = self.other_user
        self._add_session_and_messages(request)

        response = action_list_delete_revision(
            request, self.project.id, self.al_rev1.id
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ActionListRevision.objects.filter(pk=self.al_rev1.pk).exists())


class ProjectDeleteFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Wetland Recovery")

    def test_requires_matching_title(self):
        form = ProjectDeleteForm(
            data={
                "confirm_title": "Wrong title",
                "acknowledge_irreversible": True,
            },
            project=self.project,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Title does not match", form.errors["confirm_title"][0])

    def test_requires_acknowledgement(self):
        form = ProjectDeleteForm(
            data={"confirm_title": "Wetland Recovery"}, project=self.project
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "This field is required.", form.errors["acknowledge_irreversible"][0]
        )

    def test_valid_when_all_checks_pass(self):
        form = ProjectDeleteForm(
            data={
                "confirm_title": "Wetland Recovery",
                "acknowledge_irreversible": True,
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())


class ProjectSettingsFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Forest Restoration")

    def test_requires_title(self):
        form = ProjectSettingsForm(data={"title": ""}, instance=self.project)
        self.assertFalse(form.is_valid())
        self.assertIn("Enter a title", form.errors["title"][0])

    def test_updates_title(self):
        form = ProjectSettingsForm(
            data={"title": "Forest Recovery"}, instance=self.project
        )
        self.assertTrue(form.is_valid())
        updated = form.save()
        self.assertEqual(updated.title, "Forest Recovery")


class ViewHelperTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Helper Project")

    def test_user_is_manager_for_staff(self):
        user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        self.assertTrue(_user_is_manager(user))

    def test_user_is_manager_for_group_member(self):
        group = Group.objects.create(name="manager")
        user = User.objects.create_user(username="manager_user")
        user.groups.add(group)
        self.assertTrue(_user_is_manager(user))

    def test_user_is_manager_false_for_others(self):
        user = User.objects.create_user(username="regular")
        self.assertFalse(_user_is_manager(user))

    def test_log_project_change_records_entry(self):
        user = User.objects.create_user(username="logger")
        _log_project_change(self.project, user, "Edited", "Updated title")
        entry = ProjectChangeLog.objects.get(project=self.project)
        self.assertEqual(entry.action, "Edited")
        self.assertEqual(entry.details, "Updated title")
        self.assertEqual(entry.changed_by, user)

    def test_log_project_change_anonymous(self):
        anonymous = AnonymousUser()
        _log_project_change(self.project, anonymous, "Edited", "Updated title")
        entry = (
            ProjectChangeLog.objects.filter(project=self.project)
            .order_by("-id")
            .first()
        )
        self.assertIsNone(entry.changed_by)

    def test_format_value_handles_none_and_date(self):
        self.assertEqual(_format_value(None), "—")
        today = date(2025, 1, 2)
        self.assertEqual(_format_value(today), "2025-01-02")
        self.assertEqual(_format_value(42), "42")

    def test_funder_contact_label(self):
        self.assertEqual(_funder_contact_label("Ann", "Lee"), "Ann Lee")
        self.assertEqual(_funder_contact_label("", ""), "—")

    def test_format_deadline_formats_timezone(self):
        aware = timezone.make_aware(datetime(2025, 7, 1, 15, 0))
        formatted = _format_deadline(aware)
        self.assertEqual(
            formatted, timezone.localtime(aware).strftime("%d %b %Y %H:%M")
        )
        self.assertEqual(_format_deadline(None), "—")

    def test_user_can_confirm_phase(self):
        staff = User.objects.create_user(username="staff", is_staff=True)
        self.assertTrue(_user_can_confirm_phase(staff, self.project))
        author = User.objects.create_user(username="author")
        UserRole.objects.create(user=author, project=self.project, role="author")
        self.assertTrue(_user_can_confirm_phase(author, self.project))
        outsider = User.objects.create_user(username="outsider")
        self.assertFalse(_user_can_confirm_phase(outsider, self.project))
        self.assertFalse(_user_can_confirm_phase(AnonymousUser(), self.project))


class CreateProtocolFeedbackTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Protocol Feedback")
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.txt", b"content"),
        )

    def test_feedback_from_member_uses_member_deadline(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pat",
            email="pat@example.com",
            response="Y",
            feedback_on_protocol_deadline=timezone.now(),
        )
        feedback = _create_protocol_feedback(self.project, member=member)
        self.assertEqual(feedback.project, self.project)
        self.assertEqual(feedback.member, member)
        self.assertEqual(
            feedback.feedback_deadline_at, member.feedback_on_protocol_deadline
        )
        self.assertEqual(feedback.protocol_stage_snapshot, self.protocol.stage)
        self.assertEqual(
            feedback.protocol_document_last_updated, self.protocol.last_updated
        )
        self.assertEqual(
            feedback.protocol_document_name,
            self.protocol.document.name,
        )

    def test_feedback_from_invitation_sets_end_of_day_deadline(self):
        due = date(2025, 8, 15)
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            email="invitee@example.com",
            due_date=due,
        )
        feedback = _create_protocol_feedback(self.project, invitation=invitation)
        self.assertEqual(feedback.invitation, invitation)
        self.assertEqual(feedback.feedback_deadline_at.date(), due)
        self.assertEqual(feedback.feedback_deadline_at.hour, 23)
        self.assertEqual(feedback.feedback_deadline_at.minute, 59)
        self.assertEqual(feedback.protocol_stage_snapshot, self.protocol.stage)


class PlainTextReferenceParserTests(TestCase):
    def test_parses_references_and_extracts_metadata(self):
        payload = textwrap.dedent(
            """
            Angel, D. L.; et al. (2002). "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture." Hydrobiologia 469(1): 1-10.
            Net pen fish farms generally enrich the surrounding waters and the underlying sediments with nutrients and organic matter.

            This entry is invalid and should be skipped.

            Sample, S. and Example, E. (2018). Another example of parsing. Ecology Letters 11: 9-12.
            Full abstract text including doi:10.5678/example and https://example.com/article for reference.
            """
        ).strip()

        parsed = _parse_plaintext_references(payload)

        self.assertEqual(len(parsed), 2)

        first = parsed[0]
        self.assertEqual(
            first["title"],
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
        )
        self.assertEqual(first["journal_name"], "Hydrobiologia")
        self.assertEqual(first["volume"], "469")
        self.assertEqual(first["issue"], "1")
        self.assertEqual(first["pages"], "1-10")
        self.assertEqual(first["year"], "2002")
        self.assertEqual(first["publication_year"], "2002")
        self.assertEqual(first["authors"], ["Angel, D. L", "et al"])
        self.assertTrue(first["abstract"].startswith("Net pen fish farms"))

        second = parsed[1]
        self.assertEqual(second["title"], "Another example of parsing")
        self.assertEqual(second["journal_name"], "Ecology Letters")
        self.assertEqual(second["volume"], "11")
        self.assertFalse(second["issue"])
        self.assertEqual(second["pages"], "9-12")
        self.assertEqual(second["authors"], ["Sample, S", "Example, E"])
        self.assertEqual(second["doi"], "10.5678/example")
        self.assertEqual(second["url"], "https://example.com/article")

    def test_returns_empty_list_for_blank_payload(self):
        self.assertEqual(_parse_plaintext_references(""), [])
        self.assertEqual(_parse_plaintext_references("   "), [])


class ReferenceBatchUploadParsingTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Reference Upload Project")
        self.user = User.objects.create_user(username="uploader", password="pw")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.url = reverse(
            "synopsis:reference_batch_upload", args=[self.project.id]
        )

    def _plaintext_payload(self):
        return textwrap.dedent(
            """
            Angel, D. L.; et al. (2002). "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture." Hydrobiologia 469(1): 1-10.
            Net pen fish farms generally enrich the surrounding waters and the underlying sediments with nutrients and organic matter.

            Sample, S. and Example, E. (2018). Another example of parsing. Ecology Letters 11: 9-12.
            Full abstract text including doi:10.5678/example and https://example.com/article for reference.
            """
        ).strip()

    def test_imports_plaintext_file(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )

        response = self.client.post(
            self.url,
            {
                "label": "Plain text batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )

        self.assertEqual(Reference.objects.filter(project=self.project).count(), 2)
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        self.assertEqual(batch.record_count, 2)
        titles = set(
            Reference.objects.filter(project=self.project).values_list(
                "title", flat=True
            )
        )
        self.assertIn(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            titles,
        )
        self.assertIn("Another example of parsing", titles)

    def test_rejects_unparseable_plaintext(self):
        upload = SimpleUploadedFile(
            "bad.txt",
            b"not a valid ris record and no parsable citation",
            content_type="text/plain",
        )

        response = self.client.post(
            self.url,
            {
                "label": "Invalid batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("ris_file", form.errors)
        self.assertIn("No references were detected", form.errors["ris_file"][0])
        self.assertEqual(Reference.objects.count(), 0)

    def test_imports_ris_file(self):
        ris_payload = textwrap.dedent(
            """
            TY  - JOUR
            TI  - Example Title
            AU  - Doe, Jane
            PY  - 2021
            JO  - Marine Science Quarterly
            VL  - 12
            IS  - 3
            SP  - 101
            EP  - 110
            DO  - 10.1000/example
            ER  -
            """
        ).strip()
        upload = SimpleUploadedFile(
            "references.ris",
            ris_payload.encode("utf-8"),
            content_type="application/x-research-info-systems",
        )

        response = self.client.post(
            self.url,
            {
                "label": "RIS batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )

        refs = Reference.objects.filter(project=self.project)
        self.assertEqual(refs.count(), 1)
        ref = refs.first()
        self.assertEqual(ref.title, "Example Title")
        self.assertEqual(ref.publication_year, 2021)
        self.assertEqual(ref.journal, "Marine Science Quarterly")
        self.assertEqual(ref.pages, "101-110")
        self.assertEqual(ref.doi, "10.1000/example")

    def test_skips_duplicates_within_project(self):
        first_upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Initial batch",
                "source_type": "journal_search",
                "ris_file": first_upload,
            },
        )
        self.assertEqual(Reference.objects.filter(project=self.project).count(), 2)

        duplicate_upload = SimpleUploadedFile(
            "references_again.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        response = self.client.post(
            self.url,
            {
                "label": "Duplicate batch",
                "source_type": "journal_search",
                "ris_file": duplicate_upload,
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )
        self.assertEqual(Reference.objects.filter(project=self.project).count(), 2)
        latest_batch = (
            ReferenceSourceBatch.objects.filter(project=self.project)
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(latest_batch)
        self.assertEqual(latest_batch.record_count, 0)

    def test_can_delete_reference_from_batch(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Delete test batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        self.assertEqual(batch.references.count(), 2)
        ref_to_delete = batch.references.order_by("id").first()

        delete_url = reverse(
            "synopsis:reference_delete",
            args=[self.project.id, ref_to_delete.id],
        )
        response = self.client.post(delete_url, follow=False)
        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )

        self.assertFalse(
            Reference.objects.filter(pk=ref_to_delete.id).exists()
        )
        batch.refresh_from_db()
        self.assertEqual(batch.record_count, batch.references.count())

    def test_delete_reference_requires_edit_permission(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Permission batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        target = batch.references.first()
        viewer = User.objects.create_user(username="viewer", password="pw")
        delete_url = reverse(
            "synopsis:reference_delete",
            args=[self.project.id, target.id],
        )
        self.client.logout()
        self.client.force_login(viewer)
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Reference.objects.filter(pk=target.id).exists())

    def test_can_delete_batch(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Batch to delete",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        self.assertEqual(batch.references.count(), 2)
        delete_url = reverse(
            "synopsis:reference_batch_delete",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(delete_url, follow=False)
        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )
        self.assertFalse(
            ReferenceSourceBatch.objects.filter(pk=batch.id).exists()
        )
        self.assertEqual(Reference.objects.filter(project=self.project).count(), 0)

    def test_bulk_include_selected_references(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.order_by("id"))
        include_ids = [str(ref.id) for ref in references[:2]]

        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )
        response = self.client.post(
            detail_url,
            {
                "bulk_action": "include",
                "selected_references": include_ids,
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )

        refreshed = Reference.objects.filter(pk__in=include_ids)
        self.assertTrue(refreshed.exists())
        for ref in refreshed:
            self.assertEqual(ref.screening_status, "included")
            self.assertEqual(ref.screened_by, self.user)
            self.assertIsNotNone(ref.screening_decision_at)

    def test_bulk_action_requires_selection(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk batch empty",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(
            detail_url,
            {
                "bulk_action": "exclude",
            },
            follow=True,
        )

        self.assertContains(
            response,
            "Select at least one reference before applying a bulk update.",
        )
        self.assertTrue(
            Reference.objects.filter(project=self.project, screening_status="pending").exists()
        )

    def test_bulk_reset_to_pending(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk reset batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.order_by("id"))
        include_ids = [str(ref.id) for ref in references[:2]]
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        self.client.post(
            detail_url,
            {
                "bulk_action": "include",
                "selected_references": include_ids,
            },
        )
        response = self.client.post(
            detail_url,
            {
                "bulk_action": "pending",
                "selected_references": include_ids,
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )
        for ref in Reference.objects.filter(pk__in=include_ids):
            self.assertEqual(ref.screening_status, "pending")

    def test_update_notes_creates_history(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Notes batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(
            detail_url,
            {
                "action": "update_notes",
                "notes": "Initial notes",
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )
        batch.refresh_from_db()
        self.assertEqual(batch.notes, "Initial notes")
        history = ReferenceSourceBatchNoteHistory.objects.filter(batch=batch)
        self.assertEqual(history.count(), 1)
        first_entry = history.first()
        self.assertEqual(first_entry.previous_notes, "")
        self.assertEqual(first_entry.new_notes, "Initial notes")
        self.assertEqual(first_entry.changed_by, self.user)

        response = self.client.post(
            detail_url,
            {
                "action": "update_notes",
                "notes": "Updated notes",
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )
        batch.refresh_from_db()
        self.assertEqual(batch.notes, "Updated notes")
        history = ReferenceSourceBatchNoteHistory.objects.filter(batch=batch).order_by(
            "-changed_at"
        )
        self.assertEqual(history.count(), 2)
        latest = history.first()
        self.assertEqual(latest.previous_notes, "Initial notes")
        self.assertEqual(latest.new_notes, "Updated notes")
