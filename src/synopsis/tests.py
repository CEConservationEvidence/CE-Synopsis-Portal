from datetime import date, datetime
from types import SimpleNamespace

from django.contrib.auth.models import Group, User, AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    AdvisoryBoardInvitation,
    AdvisoryBoardMember,
    Funder,
    Project,
    ProjectChangeLog,
    ProtocolFeedback,
    Protocol,
    UserRole,
)
from .forms import FunderForm, ProjectDeleteForm
from .utils import (
    BRAND,
    GLOBAL_GROUPS,
    email_subject,
    ensure_global_groups,
    reply_to_list,
)
from .views import (
    _create_protocol_feedback,
    _format_deadline,
    _format_value,
    _funder_contact_label,
    _log_project_change,
    _user_can_confirm_phase,
    _user_is_manager,
)


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
        usernames = list(
            self.project.author_users.values_list("username", flat=True)
        )
        self.assertEqual(usernames, ["adam", "zoe"])


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
        self.assertIn("This field is required.", form.errors["acknowledge_irreversible"][0])

    def test_valid_when_all_checks_pass(self):
        form = ProjectDeleteForm(
            data={
                "confirm_title": "Wetland Recovery",
                "acknowledge_irreversible": True,
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())


class ViewHelperTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Helper Project")

    def test_user_is_manager_for_staff(self):
        user = User.objects.create_user(username="staffer", password="pw", is_staff=True)
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
        entry = ProjectChangeLog.objects.filter(project=self.project).order_by("-id").first()
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
        self.assertEqual(formatted, timezone.localtime(aware).strftime("%d %b %Y %H:%M"))
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
        self.assertEqual(feedback.feedback_deadline_at, member.feedback_on_protocol_deadline)
        self.assertEqual(feedback.protocol_stage_snapshot, self.protocol.stage)
        self.assertEqual(feedback.protocol_document_last_updated, self.protocol.last_updated)
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
