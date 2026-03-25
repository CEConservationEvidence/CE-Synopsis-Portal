from datetime import date, datetime, timedelta
import importlib
import io
import json
from urllib.parse import urlparse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
import jwt
from django.contrib.auth.models import Group, User, AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings, RequestFactory, SimpleTestCase
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
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
    IUCNCategory,
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
    LibraryReference,
    LibraryImportBatch,
    ReferenceSourceBatch,
    ReferenceSourceBatchNoteHistory,
    Reference,
    ReferenceSummary,
    SynopsisChapter,
    SynopsisSubheading,
    SynopsisIntervention,
    SynopsisInterventionKeyMessage,
    SynopsisAssignment,
)
from .forms import (
    ActionListReminderScheduleForm,
    ActionListSendForm,
    AdvisoryBulkInviteForm,
    AdvisoryBoardMemberForm,
    AdvisoryInviteForm,
    AdvisoryMemberCustomDataForm,
    FunderForm,
    FunderContactFormSet,
    ProtocolSendForm,
    ProtocolReminderScheduleForm,
    ProjectDeleteForm,
    ProjectSettingsForm,
    ReminderScheduleForm,
    IUCN_ACTION_CHOICES,
    IUCN_HABITAT_CHOICES,
    IUCN_THREAT_CHOICES,
    ReferenceSummaryDraftForm,
    ReferenceSummaryUpdateForm,
)
from .utils import (
    BRAND,
    GLOBAL_GROUPS,
    default_advisory_invitation_message,
    email_subject,
    ensure_global_groups,
    reference_hash,
    reply_to_list,
)
from .views import (
    _advisory_board_context,
    _apply_revision_to_action_list,
    _apply_revision_to_protocol,
    _build_advisory_invitation_email,
    _build_onlyoffice_config,
    _download_onlyoffice_file,
    _parse_onlyoffice_callback,
    _create_protocol_feedback,
    _format_deadline,
    _format_value,
    _funder_contact_label,
    _log_project_change,
    _normalise_import_record,
    _user_can_confirm_phase,
    _user_is_manager,
    _user_can_edit_project,
    protocol_delete_revision,
    action_list_delete_revision,
    _parse_plaintext_references,
    _parse_endnote_xml,
    project_synopsis_structure,
    _intervention_reference_numbering,
    _format_reference_number_ranges,
    _generate_synopsis_docx,
    _link_library_references_to_project,
    _reference_export_citation,
    _reference_summary_paragraph,
    _structured_summary_paragraph,
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


class AdvisoryBoardMemberFormTests(TestCase):
    def test_add_member_form_marks_core_fields_and_placeholders(self):
        form = AdvisoryBoardMemberForm()

        self.assertFalse(form.fields["title"].required)
        self.assertTrue(form.fields["first_name"].required)
        self.assertTrue(form.fields["last_name"].required)
        self.assertTrue(form.fields["email"].required)
        self.assertEqual(
            form.fields["first_name"].widget.attrs["placeholder"],
            "First name (required)",
        )
        self.assertEqual(
            form.fields["country"].widget.attrs["placeholder"],
            "Country (optional)",
        )
        self.assertEqual(
            form.fields["notes"].widget.attrs["placeholder"],
            "Notes for this member (optional)",
        )


class AdvisoryBoardMemberAddUiTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Advisory UX")
        self.user = User.objects.create_user(username="advisor-owner", password="pw")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.url = reverse("synopsis:advisory_board_list", args=[self.project.id])

    def test_board_page_explains_required_fields_and_review_step(self):
        response = self.client.get(self.url)

        self.assertContains(
            response,
            "Only first name, last name and email are required.",
        )
        self.assertContains(response, "Required to add member")
        self.assertContains(response, "Optional details")
        self.assertContains(response, "Review member details")

    def test_invalid_add_member_reopens_modal_with_error_guidance(self):
        response = self.client.post(
            self.url,
            {
                "action": "add_member",
                "title": "",
                "first_name": "",
                "middle_name": "",
                "last_name": "",
                "organisation": "",
                "email": "",
                "country": "",
                "continent": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="addMemberModal"')
        self.assertContains(response, 'window.bootstrap.Modal.getOrCreateInstance')
        self.assertContains(response, "This field is required.")


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


class SynopsisStructureTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Synopsis Demo")
        self.user = User.objects.create_user(username="manager", password="pw", is_staff=True)
        UserRole.objects.create(user=self.user, project=self.project, role="manager")
        self.client.force_login(self.user)
        # Attach a reference/summary for assignment flows
        self.batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Batch 1",
            source_type="manual_upload",
            uploaded_by=self.user,
        )
        self.reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Test ref",
            hash_key="hash-test-ref",
            screening_status="included",
        )
        self.summary = ReferenceSummary.objects.create(
            project=self.project, reference=self.reference
        )

    def test_apply_preset_creates_chapters_once(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        response = self.client.post(
            url,
            {"action": "apply-preset", "preset_key": "standard_ce_toc"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SynopsisChapter.objects.filter(project=self.project).exists())
        front_chapter = SynopsisChapter.objects.get(
            project=self.project, title="Advisory Board"
        )
        self.assertEqual(front_chapter.chapter_type, SynopsisChapter.TYPE_TEXT)
        evidence_chapter = SynopsisChapter.objects.get(
            project=self.project,
            title="2. Threat: Residential and commercial development",
        )
        self.assertEqual(
            evidence_chapter.chapter_type, SynopsisChapter.TYPE_EVIDENCE
        )
        count_after_first = SynopsisChapter.objects.filter(project=self.project).count()
        # Second apply should be blocked because outline is not empty
        response = self.client.post(
            url,
            {"action": "apply-preset", "preset_key": "standard_ce_toc"},
        )
        self.assertEqual(response.status_code, 302)
        count_after_second = SynopsisChapter.objects.filter(project=self.project).count()
        self.assertEqual(count_after_first, count_after_second)

    def test_reset_structure_clears_outline(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        SynopsisChapter.objects.create(project=self.project, title="Tmp", position=1)
        response = self.client.post(url, {"action": "reset-structure"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SynopsisChapter.objects.filter(project=self.project).exists())

    def test_create_intervention_without_subheading_creates_default(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(project=self.project, title="Ch", position=1)
        response = self.client.post(
            url,
            {
                "action": "create-intervention",
                "chapter_id": chapter.id,
                "title": "Intervention A",
            },
        )
        self.assertEqual(response.status_code, 302)
        subheadings = SynopsisSubheading.objects.filter(chapter=chapter)
        self.assertEqual(subheadings.count(), 1)
        intervention_titles = list(
            SynopsisIntervention.objects.filter(subheading__chapter=chapter).values_list("title", flat=True)
        )
        self.assertIn("Intervention A", intervention_titles)

    def test_text_chapter_blocks_subheading_and_intervention(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        text_chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="Advisory Board",
            chapter_type=SynopsisChapter.TYPE_TEXT,
            position=1,
        )
        response = self.client.post(
            url,
            {
                "action": "create-subheading",
                "chapter_id": text_chapter.id,
                "title": "Should fail",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SynopsisSubheading.objects.filter(chapter=text_chapter).exists())
        response = self.client.post(
            url,
            {
                "action": "create-intervention",
                "chapter_id": text_chapter.id,
                "title": "Should also fail",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            SynopsisIntervention.objects.filter(subheading__chapter=text_chapter).exists()
        )

    def test_update_intervention_synthesis_fields(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )

        response = self.client.post(
            url,
            {
                "action": "update-intervention-synthesis",
                "intervention_id": intervention.id,
                "ce_action_url": "https://www.conservationevidence.com/actions/4018",
                "evidence_status": SynopsisIntervention.EVIDENCE_STATUS_NO_STUDIES,
                "synthesis_text": "No direct studies were identified in the searched evidence base.",
            },
        )
        self.assertEqual(response.status_code, 302)
        intervention.refresh_from_db()
        self.assertEqual(
            intervention.ce_action_url,
            "https://www.conservationevidence.com/actions/4018",
        )
        self.assertEqual(
            intervention.evidence_status,
            SynopsisIntervention.EVIDENCE_STATUS_NO_STUDIES,
        )
        self.assertIn("No direct studies", intervention.synthesis_text)

    def test_add_and_update_key_message(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Second test ref",
            hash_key="hash-second-test-ref",
            screening_status="included",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project, reference=second_reference
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=second_summary,
            position=2,
        )

        response = self.client.post(
            url,
            {
                "action": "add-key-message",
                "intervention_id": intervention.id,
                "response_group": SynopsisInterventionKeyMessage.GROUP_POPULATION,
                "outcome_label": "Abundance/Cover",
                "study_count": 3,
                "statement": "Three studies found increased coral cover after intervention.",
                "supporting_summaries": [str(self.summary.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        key_message = intervention.key_messages.first()
        self.assertIsNotNone(key_message)
        self.assertEqual(key_message.study_count, 3)
        self.assertEqual(
            list(
                key_message.supporting_summaries.order_by("id").values_list("id", flat=True)
            ),
            [self.summary.id],
        )

        response = self.client.post(
            url,
            {
                "action": "update-key-message",
                "intervention_id": intervention.id,
                "key_message_id": key_message.id,
                "response_group": SynopsisInterventionKeyMessage.GROUP_COMMUNITY,
                "outcome_label": "Richness/diversity",
                "study_count": 5,
                "statement": "Five studies found no clear community-level change.",
                "supporting_summaries": [str(second_summary.id), str(self.summary.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        key_message.refresh_from_db()
        self.assertEqual(
            key_message.response_group,
            SynopsisInterventionKeyMessage.GROUP_COMMUNITY,
        )
        self.assertEqual(key_message.outcome_label, "Richness/diversity")
        self.assertEqual(key_message.study_count, 5)
        self.assertEqual(
            list(
                key_message.supporting_summaries.order_by("id").values_list("id", flat=True)
            ),
            sorted([self.summary.id, second_summary.id]),
        )

    def test_intervention_reference_numbering_uses_oldest_first_order(self):
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        older_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Older study",
            authors="Alpha A.",
            publication_year=2001,
            hash_key="hash-old-study",
            screening_status="included",
        )
        newer_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Newer study",
            authors="Beta B.",
            publication_year=2018,
            hash_key="hash-new-study",
            screening_status="included",
        )
        older_summary = ReferenceSummary.objects.create(
            project=self.project, reference=older_reference
        )
        newer_summary = ReferenceSummary.objects.create(
            project=self.project, reference=newer_reference
        )
        SynopsisAssignment.objects.create(
            intervention=intervention, reference_summary=newer_summary, position=1
        )
        SynopsisAssignment.objects.create(
            intervention=intervention, reference_summary=older_summary, position=2
        )

        assignments = list(intervention.assignments.all())
        ordered_assignments, summary_numbers, ordered_references = (
            _intervention_reference_numbering(assignments)
        )

        self.assertEqual(
            [assignment.reference_summary_id for assignment in ordered_assignments],
            [older_summary.id, newer_summary.id],
        )
        self.assertEqual(summary_numbers[older_summary.id], 1)
        self.assertEqual(summary_numbers[newer_summary.id], 2)
        self.assertEqual(
            [reference.id for _, reference in ordered_references],
            [older_reference.id, newer_reference.id],
        )
        self.assertEqual(
            [numbers for numbers, _ in ordered_references],
            [[1], [2]],
        )

    def test_intervention_reference_numbering_groups_duplicate_references(self):
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Group duplicate paper studies",
            position=2,
        )
        shared_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Shared study paper",
            authors="Gamma G.",
            publication_year=2009,
            hash_key="hash-shared-study-paper",
            screening_status="included",
        )
        first_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=shared_reference,
            action_description="Study A",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=shared_reference,
            action_description="Study B",
        )
        SynopsisAssignment.objects.create(
            intervention=intervention, reference_summary=first_summary, position=1
        )
        SynopsisAssignment.objects.create(
            intervention=intervention, reference_summary=second_summary, position=2
        )

        assignments = list(intervention.assignments.all())
        ordered_assignments, summary_numbers, ordered_references = (
            _intervention_reference_numbering(assignments)
        )

        self.assertEqual(
            [assignment.reference_summary_id for assignment in ordered_assignments],
            [first_summary.id, second_summary.id],
        )
        self.assertEqual(summary_numbers[first_summary.id], 1)
        self.assertEqual(summary_numbers[second_summary.id], 2)
        self.assertEqual(len(ordered_references), 1)
        self.assertEqual(ordered_references[0][1].id, shared_reference.id)
        self.assertEqual(ordered_references[0][0], [1, 2])
        self.assertEqual(_format_reference_number_ranges([1, 2]), "1-2")

    def test_key_message_rejects_unassigned_supporting_summary(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        outside_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Outside intervention summary",
            hash_key="hash-outside-summary",
            screening_status="included",
        )
        outside_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=outside_reference,
        )

        response = self.client.post(
            url,
            {
                "action": "add-key-message",
                "intervention_id": intervention.id,
                "response_group": SynopsisInterventionKeyMessage.GROUP_RESPONSE,
                "statement": "Message with invalid supporting study link.",
                "supporting_summaries": [str(outside_summary.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(intervention.key_messages.exists())

    def test_evidence_page_groups_summary_tabs_under_reference(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        self.reference.authors = "Rebecca Smith"
        self.reference.publication_year = 2024
        self.reference.save(update_fields=["authors", "publication_year", "updated_at"])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        alt_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            action_description="Study B",
        )
        self.summary.action_description = "Study A"
        self.summary.save(update_fields=["action_description"])
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=alt_summary,
            position=2,
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        grouped = response.context["reference_summary_groups"]
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["reference_heading"], "Rebecca Smith · 2024")
        self.assertEqual(grouped[0]["reference_context"], "Test ref")
        self.assertEqual(
            [item["summary_display"] for item in grouped[0]["summaries"]],
            ["D1000.a — Study A", "D1000.b — Study B"],
        )
        self.assertContains(response, "Assign summary tabs, not whole papers.")
        self.assertContains(response, "Grouped by reference author.")
        self.assertContains(
            response,
            "Choose a summary tab to preview its reference and tab label.",
        )
        self.assertContains(response, "Rebecca Smith · 2024")
        self.assertContains(response, "D1000.a — Study A")
        self.assertContains(response, "D1000.b — Study B")
        self.assertContains(response, "Same source paper")
        self.assertContains(response, "shared reference line (1-2)")
        self.assertContains(response, "Compilation preview")
        self.assertContains(response, "study paragraphs")
        self.assertContains(response, "source paper")
        self.assertContains(response, "2 summary tabs from the same paper")

    def test_evidence_workspace_uses_action_only_iucn_categories(self):
        response = self.client.get(
            reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        )

        context_categories = list(response.context["iucn_categories"])
        self.assertTrue(context_categories)
        self.assertTrue(
            all(category.kind == IUCNCategory.KIND_ACTION for category in context_categories)
        )
        self.assertIn(
            "Land/water protection-Area protection",
            [category.name for category in context_categories],
        )
        self.assertNotIn(
            "Residential & commercial development",
            [category.name for category in context_categories],
        )

        form_categories = list(
            response.context["intervention_form"].fields["iucn_category"].queryset
        )
        self.assertTrue(form_categories)
        self.assertTrue(
            all(category.kind == IUCNCategory.KIND_ACTION for category in form_categories)
        )

    def test_update_intervention_metadata_rejects_threat_category(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        threat_category = IUCNCategory.objects.filter(
            kind=IUCNCategory.KIND_THREAT,
            is_active=True,
        ).first()

        self.assertIsNotNone(threat_category)

        response = self.client.post(
            url,
            {
                "action": "update-intervention-metadata",
                "intervention_id": intervention.id,
                "iucn_category": str(threat_category.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        intervention.refresh_from_db()
        self.assertIsNone(intervention.iucn_category)

    def test_delete_assignment_removes_supporting_links_from_key_messages(self):
        url = reverse("synopsis:project_synopsis_structure", args=[self.project.id])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        assignment = SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        key_message = SynopsisInterventionKeyMessage.objects.create(
            intervention=intervention,
            response_group=SynopsisInterventionKeyMessage.GROUP_RESPONSE,
            statement="Linked message",
            position=1,
        )
        key_message.supporting_summaries.add(self.summary)

        response = self.client.post(
            url,
            {
                "action": "delete-assignment",
                "assignment_id": assignment.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        key_message.refresh_from_db()
        self.assertFalse(key_message.supporting_summaries.exists())

    def test_export_citation_and_reference_identifier_override(self):
        reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Corallivorous snail removal",
            authors="Miller M.",
            publication_year=2001,
            journal="Coral Reefs",
            volume="19",
            pages="293-295",
            doi="10.1007/PL00006963",
            hash_key="hash-citation-study",
            screening_status="included",
        )
        summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=reference,
            study_design="replicated, controlled study",
            year_range="1999",
            summary_of_results="snail removal reduced live tissue loss.",
            reference_identifier="X",
        )

        citation = _reference_export_citation(reference)
        self.assertIn("Miller M. (2001)", citation)
        self.assertIn("Corallivorous snail removal.", citation)
        self.assertIn("Coral Reefs, 19, 293-295.", citation)
        self.assertIn("https://doi.org/10.1007/PL00006963", citation)

        paragraph = _structured_summary_paragraph(
            summary, reference_identifier_override="3"
        )
        self.assertIn("(3)", paragraph)
        self.assertNotIn("(X)", paragraph)

    def test_generate_docx_collapses_duplicate_reference_lines_but_keeps_study_paragraphs(self):
        from docx import Document

        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="2. Threat: Demo",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="Interventions",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="2.1 Demo intervention",
            position=1,
        )
        shared_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            title="Shared study paper",
            authors="Gamma G.",
            publication_year=2009,
            hash_key="hash-docx-shared-paper",
            screening_status="included",
        )
        first_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=shared_reference,
            study_design="replicated, controlled study",
            year_range="2009",
            summary_of_results="first finding improved coral cover.",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=shared_reference,
            study_design="replicated, controlled study",
            year_range="2010",
            summary_of_results="second finding improved coral recruitment.",
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=first_summary,
            position=1,
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=second_summary,
            position=2,
        )

        payload = _generate_synopsis_docx(self.project)
        document = Document(io.BytesIO(payload))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]

        self.assertTrue(
            any("(1)" in paragraph and "first finding improved coral cover" in paragraph for paragraph in paragraphs)
        )
        self.assertTrue(
            any("(2)" in paragraph and "second finding improved coral recruitment" in paragraph for paragraph in paragraphs)
        )
        collapsed_reference_lines = [
            paragraph for paragraph in paragraphs if paragraph.startswith("(1-2) ")
        ]
        self.assertEqual(len(collapsed_reference_lines), 1)
        self.assertIn("Shared study paper.", collapsed_reference_lines[0])
        self.assertFalse(
            any(
                paragraph.startswith("(1) Gamma G. (2009) Shared study paper.")
                or paragraph.startswith("(2) Gamma G. (2009) Shared study paper.")
                for paragraph in paragraphs
            )
        )

    def test_workspace_routes_load(self):
        narrative_url = reverse(
            "synopsis:project_synopsis_narrative", args=[self.project.id]
        )
        evidence_url = reverse(
            "synopsis:project_synopsis_evidence", args=[self.project.id]
        )
        structure_url = reverse(
            "synopsis:project_synopsis_structure", args=[self.project.id]
        )
        self.assertEqual(self.client.get(narrative_url).status_code, 200)
        self.assertEqual(self.client.get(evidence_url).status_code, 200)
        self.assertEqual(self.client.get(structure_url).status_code, 200)

    def test_narrative_workspace_post_redirects_to_narrative_route(self):
        url = reverse("synopsis:project_synopsis_narrative", args=[self.project.id])
        response = self.client.post(
            url,
            {
                "action": "create-chapter",
                "title": "Advisory Board",
                "chapter_type": SynopsisChapter.TYPE_TEXT,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            urlparse(response["Location"]).path,
            urlparse(url).path,
        )


class AdvisoryDeadlineValidationTests(TestCase):
    def test_invite_due_date_rejects_today_and_past_dates(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        today_form = AdvisoryInviteForm(
            data={"email": "ibrahim@example.com", "due_date": today.isoformat()}
        )
        self.assertFalse(today_form.is_valid())
        self.assertIn("due_date", today_form.errors)

        yesterday_form = AdvisoryBulkInviteForm(
            data={"due_date": yesterday.isoformat()}
        )
        self.assertFalse(yesterday_form.is_valid())
        self.assertIn("due_date", yesterday_form.errors)

    def test_schedule_forms_expose_minimum_dates_in_widgets(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        expected_date_min = tomorrow.isoformat()
        expected_datetime_min = f"{expected_date_min}T00:00"

        self.assertEqual(
            AdvisoryInviteForm().fields["due_date"].widget.attrs.get("min"),
            expected_date_min,
        )
        self.assertEqual(
            ReminderScheduleForm().fields["reminder_date"].widget.attrs.get("min"),
            expected_date_min,
        )
        self.assertEqual(
            ProtocolReminderScheduleForm().fields["deadline"].widget.attrs.get("min"),
            expected_datetime_min,
        )
        self.assertEqual(
            ActionListReminderScheduleForm().fields["deadline"].widget.attrs.get("min"),
            expected_datetime_min,
        )

    @override_settings(
        ADVISORY_INVITE_RESPONSE_WINDOW_DAYS=14,
        ADVISORY_DOCUMENT_FEEDBACK_WINDOW_DAYS=21,
    )
    def test_advisory_help_text_uses_runtime_settings(self):
        self.assertIn(
            "Defaults to 14 days from today.",
            AdvisoryInviteForm().fields["due_date"].help_text,
        )
        self.assertIn(
            "Defaults to 14 days from today",
            AdvisoryBulkInviteForm().fields["due_date"].help_text,
        )
        self.assertIn(
            "Defaults to 14 days from today.",
            ReminderScheduleForm().fields["reminder_date"].help_text,
        )
        self.assertIn(
            "Defaults to 21 days from today",
            ProtocolSendForm().fields["due_date"].help_text,
        )
        self.assertIn(
            "Defaults to 21 days from today",
            ActionListSendForm().fields["due_date"].help_text,
        )
        self.assertIn(
            "Defaults to 21 days from today.",
            ProtocolReminderScheduleForm().fields["deadline"].help_text,
        )
        self.assertIn(
            "Defaults to 21 days from today.",
            ActionListReminderScheduleForm().fields["deadline"].help_text,
        )

    def test_protocol_deadline_rejects_same_day_datetime(self):
        same_day_value = f"{timezone.localdate().isoformat()}T12:00"
        form = ProtocolReminderScheduleForm(data={"deadline": same_day_value})
        self.assertFalse(form.is_valid())
        self.assertIn("deadline", form.errors)


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
        target_date = timezone.localdate() + timedelta(days=7)
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

    def test_board_page_sets_minimum_response_deadline_on_inline_input(self):
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Randy",
            email="randy@example.com",
        )
        tomorrow = timezone.localdate() + timedelta(days=1)
        response = self.client.get(self.board_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'min="{tomorrow.strftime("%Y-%m-%d")}"',
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

    def test_same_day_response_deadline_is_rejected(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Clara",
            email="clara@example.com",
        )
        today = timezone.localdate()
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
            {"reminder_date": today.strftime("%Y-%m-%d")},
            follow=True,
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNone(member.response_date)
        self.assertContains(response, "at least one day in the future")

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

    def test_same_day_protocol_deadline_is_rejected(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Paula",
            email="paula@example.com",
            response="Y",
            sent_protocol_at=timezone.now(),
        )
        ProtocolFeedback.objects.create(project=self.project, member=member)
        today_local = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "protocol"],
            ),
            {"deadline": today_local.strftime("%Y-%m-%dT%H:%M")},
            follow=True,
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNone(member.feedback_on_protocol_deadline)
        self.assertContains(response, "at least one day in the future")

    def test_update_action_list_deadline(self):
        action_list = ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.txt", b"test"),
        )
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Vanessa",
            email="vanessa@example.com",
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
            first_name="Rebecca",
            last_name="Smith",
            email="rebecca@example.com",
            organisation="Org",
        )

        payload = {
            "title": "Prof",
            "first_name": "Rebecca",
            "middle_name": "A",
            "last_name": "Thornton",
            "organisation": "Updated Org",
            "email": "rebecca@example.com",
            "country": "United Kingdom",
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
        self.assertEqual(member.last_name, "Thornton")
        self.assertEqual(member.organisation, "Updated Org")
        self.assertEqual(member.country, "United Kingdom")
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
            first_name="Ibrahim",
            email="ibrahim@example.com",
            reminder_sent=True,
            reminder_sent_at=timezone.now(),
        )
        due = timezone.localdate() + timedelta(days=14)
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
    def test_single_invite_defaults_due_date_to_configured_window_when_blank(self, mock_email):
        mock_email.return_value = MagicMock()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        url = reverse(
            "synopsis:advisory_invite_create_for_member",
            args=[self.project.id, member.id],
        )

        response = self.client.post(
            url,
            {
                "email": member.email,
                "due_date": "",
                "message": "Welcome aboard",
            },
        )

        expected_due = timezone.localdate() + timedelta(
            days=settings.ADVISORY_INVITE_RESPONSE_WINDOW_DAYS
        )
        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        invitation = AdvisoryBoardInvitation.objects.get(member=member)
        self.assertEqual(member.response_date, expected_due)
        self.assertEqual(invitation.due_date, expected_due)
        self.assertEqual(mock_email.call_count, 1)

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_single_invite_uses_default_standard_message_when_project_has_no_custom_message(
        self, mock_email
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        due = timezone.localdate() + timedelta(days=10)

        response = self.client.post(
            reverse(
                "synopsis:advisory_invite_create_for_member",
                args=[self.project.id, member.id],
            ),
            {
                "email": member.email,
                "due_date": due.strftime("%Y-%m-%d"),
                "message": "",
            },
        )

        self.assertRedirects(response, self.board_url)
        args, _kwargs = mock_email.call_args
        self.assertIn(default_advisory_invitation_message(), args[1])
        html_body = email_instance.attach_alternative.call_args[0][0]
        self.assertIn(default_advisory_invitation_message(), html_body)
        self.project.refresh_from_db()
        self.assertEqual(self.project.advisory_invitation_message, "")

    def test_single_invite_form_shows_preview_with_default_standard_message(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )

        response = self.client.get(
            reverse(
                "synopsis:advisory_invite_create_for_member",
                args=[self.project.id, member.id],
            )
        )

        self.assertContains(response, "Invitation preview")
        self.assertContains(response, default_advisory_invitation_message())

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_single_invite_missing_standard_message_field_keeps_saved_project_message(
        self, mock_email
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance
        self.project.advisory_invitation_message = "Saved standard message"
        self.project.save(update_fields=["advisory_invitation_message"])
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        due = timezone.localdate() + timedelta(days=14)

        response = self.client.post(
            reverse(
                "synopsis:advisory_invite_create_for_member",
                args=[self.project.id, member.id],
            ),
            {
                "email": member.email,
                "due_date": due.strftime("%Y-%m-%d"),
                "message": "Welcome aboard",
            },
        )

        self.assertRedirects(response, self.board_url)
        self.project.refresh_from_db()
        self.assertEqual(
            self.project.advisory_invitation_message, "Saved standard message"
        )
        args, _kwargs = mock_email.call_args
        self.assertIn("Saved standard message", args[1])
        html_body = email_instance.attach_alternative.call_args[0][0]
        self.assertIn("Saved standard message", html_body)

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
        due = timezone.localdate() + timedelta(days=21)
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

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_bulk_invite_saves_custom_standard_message_and_keeps_optional_message(
        self, mock_email
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Liam",
            email="liam@example.com",
        )
        due = timezone.localdate() + timedelta(days=21)

        response = self.client.post(
            reverse("synopsis:advisory_send_invites_bulk", args=[self.project.id]),
            {
                "due_date": due.strftime("%Y-%m-%d"),
                "standard_message": "This is the saved team invite message.",
                "message": "Bulk kickoff note",
            },
        )

        self.assertRedirects(response, self.board_url)
        self.project.refresh_from_db()
        self.assertEqual(
            self.project.advisory_invitation_message,
            "This is the saved team invite message.",
        )
        args, kwargs = mock_email.call_args
        self.assertEqual(kwargs["to"], [member.email])
        self.assertIn("This is the saved team invite message.", args[1])
        self.assertIn("Bulk kickoff note", args[1])
        html_body = email_instance.attach_alternative.call_args[0][0]
        self.assertIn("This is the saved team invite message.", html_body)
        self.assertIn("Bulk kickoff note", html_body)

    def test_bulk_invite_form_shows_preview_with_default_standard_message(self):
        response = self.client.get(
            reverse("synopsis:advisory_send_invites_bulk", args=[self.project.id])
        )

        self.assertContains(response, "Invitation preview")
        self.assertContains(response, default_advisory_invitation_message())

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_bulk_invite_missing_standard_message_field_keeps_saved_project_message(
        self, mock_email
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance
        self.project.advisory_invitation_message = "Saved standard message"
        self.project.save(update_fields=["advisory_invitation_message"])
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Liam",
            email="liam@example.com",
        )
        due = timezone.localdate() + timedelta(days=21)

        response = self.client.post(
            reverse("synopsis:advisory_send_invites_bulk", args=[self.project.id]),
            {
                "due_date": due.strftime("%Y-%m-%d"),
                "message": "Bulk kickoff",
            },
        )

        self.assertRedirects(response, self.board_url)
        self.project.refresh_from_db()
        self.assertEqual(
            self.project.advisory_invitation_message, "Saved standard message"
        )
        args, kwargs = mock_email.call_args
        self.assertEqual(kwargs["to"], [member.email])
        self.assertIn("Saved standard message", args[1])
        html_body = email_instance.attach_alternative.call_args[0][0]
        self.assertIn("Saved standard message", html_body)


class AdvisoryDocumentSendDefaultDeadlineTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Document Deadlines")
        self.user = User.objects.create_user(
            username="author", password="pw", email="author@example.com"
        )
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.txt", b"protocol"),
        )
        self.action_list = ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.txt", b"action list"),
        )
        self.member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Rebecca",
            email="rebecca@example.com",
            response="Y",
            participation_confirmed=True,
        )
        self.expected_due = timezone.localdate() + timedelta(
            days=settings.ADVISORY_DOCUMENT_FEEDBACK_WINDOW_DAYS
        )

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_protocol_member_send_defaults_deadline_to_configured_window(self, mock_email):
        mock_email.return_value = MagicMock()
        response = self.client.post(
            reverse(
                "synopsis:advisory_send_protocol_compose_member",
                args=[self.project.id, self.member.id],
            ),
            {
                "due_date": "",
                "message": "",
                "include_protocol_document": "on",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        self.member.refresh_from_db()
        self.assertEqual(self.member.feedback_on_protocol_deadline.date(), self.expected_due)
        self.assertEqual(self.member.feedback_on_protocol_deadline.hour, 23)
        self.assertEqual(self.member.feedback_on_protocol_deadline.minute, 59)
        feedback = ProtocolFeedback.objects.get(project=self.project, member=self.member)
        self.assertEqual(feedback.feedback_deadline_at, self.member.feedback_on_protocol_deadline)

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_action_list_member_send_defaults_deadline_to_configured_window(self, mock_email):
        mock_email.return_value = MagicMock()
        response = self.client.post(
            reverse(
                "synopsis:advisory_send_action_list_compose_member",
                args=[self.project.id, self.member.id],
            ),
            {
                "due_date": "",
                "message": "",
                "include_action_list_document": "on",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        self.member.refresh_from_db()
        self.assertEqual(
            self.member.feedback_on_action_list_deadline.date(), self.expected_due
        )
        self.assertEqual(self.member.feedback_on_action_list_deadline.hour, 23)
        self.assertEqual(self.member.feedback_on_action_list_deadline.minute, 59)
        feedback = ActionListFeedback.objects.get(project=self.project, member=self.member)
        self.assertEqual(
            feedback.feedback_deadline_at,
            self.member.feedback_on_action_list_deadline,
        )


class FunderUtilityTests(TestCase):
    def test_build_display_name_prefers_organisation(self):
        name = Funder.build_display_name("Org Inc", "Dr", "Ann", "Thornton")
        self.assertEqual(name, "Org Inc")

    def test_build_display_name_from_names(self):
        name = Funder.build_display_name(None, "Dr", "Ann", "Thornton")
        self.assertEqual(name, "Dr Ann Thornton")

    def test_build_display_name_default(self):
        self.assertEqual(Funder.build_display_name(None, None, None, None), "(Funder)")


class FunderFormTests(TestCase):
    def test_valid_with_only_organisation(self):
        form = FunderForm(data={"organisation": "Ocean Trust"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.has_identity_fields())
        self.assertTrue(form.has_meaningful_input())

    def test_empty_form_has_no_meaningful_input(self):
        form = FunderForm(data={})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.has_meaningful_input())

    def test_notes_count_as_meaningful_input(self):
        form = FunderForm(data={"organisation_details": "Focuses on wetlands"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.has_meaningful_input())

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


class FunderContactFormSetTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Project", start_date=date(2025, 1, 1))
        self.funder = Funder.objects.create(project=self.project, name="Seed")

    def _formset_payload(self, overrides=None):
        base = {
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-title": "",
            "contacts-0-first_name": "Will",
            "contacts-0-last_name": "Morgan",
            "contacts-0-email": "",
            "contacts-0-is_primary": "",
            "contacts-0-DELETE": "",
        }
        if overrides:
            base.update(overrides)
        return base

    def test_primary_auto_selected_when_missing(self):
        payload = self._formset_payload()
        formset = FunderContactFormSet(
            data=payload, instance=self.funder, prefix="contacts"
        )
        self.assertTrue(formset.is_valid())
        self.assertTrue(formset.forms[0].cleaned_data.get("is_primary"))

    def test_primary_contact_email_optional(self):
        payload = self._formset_payload({"contacts-0-is_primary": "on", "contacts-0-email": ""})
        formset = FunderContactFormSet(
            data=payload, instance=self.funder, prefix="contacts"
        )
        self.assertTrue(formset.is_valid())
        self.assertTrue(formset.forms[0].cleaned_data.get("is_primary"))

    def test_valid_primary_contact(self):
        payload = self._formset_payload(
            {"contacts-0-is_primary": "on", "contacts-0-email": "will@example.com"}
        )
        formset = FunderContactFormSet(
            data=payload, instance=self.funder, prefix="contacts"
        )
        self.assertTrue(formset.is_valid())


class AdvisoryBoardCustomColumnsDynamicTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Dynamic Columns")
        self.editor = User.objects.create_user(username="editor")
        self.accepted = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ann",
            email="ann@example.com",
            response="Y",
        )
        self.pending = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Vanessa",
            email="vanessa@example.com",
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

    @patch("synopsis.views.requests.get")
    def test_download_uses_internal_onlyoffice_url_when_base_is_browser_host(self, mock_get):
        self.views.ONLYOFFICE_SETTINGS = {
            "base_url": "http://localhost:8080",
            "internal_url": "http://onlyoffice",
            "callback_timeout": 7,
            "trusted_download_urls": ["http://onlyoffice"],
        }
        mock_response = MagicMock()
        mock_response.content = b"doc"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        content = _download_onlyoffice_file(
            "http://localhost:8080/cache/files/data/demo/output.docx?x=1"
        )

        self.assertEqual(content, b"doc")
        mock_get.assert_called_once_with(
            "http://onlyoffice/cache/files/data/demo/output.docx?x=1",
            timeout=7,
        )


class OnlyOfficeCallbackParsingTests(TestCase):
    def setUp(self):
        from . import views

        self.views = views
        self.original_settings = views.ONLYOFFICE_SETTINGS
        views.ONLYOFFICE_SETTINGS = {
            "jwt_secret": "change-me",
        }
        self.addCleanup(self._restore_settings)
        self.factory = RequestFactory()

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    def test_parse_callback_unwraps_nested_payload_from_jwt(self):
        payload = {
            "payload": {
                "status": 2,
                "url": "http://localhost:8080/cache/files/data/demo/output.docx",
            }
        }
        token = jwt.encode(payload, "change-me", algorithm="HS256")
        request = self.factory.post(
            "/",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        parsed = _parse_onlyoffice_callback(request)

        self.assertEqual(parsed["status"], 2)
        self.assertEqual(
            parsed["url"],
            "http://localhost:8080/cache/files/data/demo/output.docx",
        )


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
            reverse("synopsis:protocol_detail", args=[self.project.id]),
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
            reverse("synopsis:protocol_detail", args=[self.project.id]),
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


class ProtocolUploadFlowTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

        self.project = Project.objects.create(title="Ibrahim Protocol Pilot")
        self.ibrahim = User.objects.create_user(username="ibrahim", password="pw")
        UserRole.objects.create(user=self.ibrahim, project=self.project, role="author")
        self.client.force_login(self.ibrahim)

    def test_initial_protocol_upload_creates_revision_and_redirects(self):
        response = self.client.post(
            reverse("synopsis:protocol_detail", args=[self.project.id]),
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1.0",
                "document": SimpleUploadedFile(
                    "ibrahim-protocol.docx",
                    b"protocol",
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:protocol_detail", args=[self.project.id]),
        )
        protocol = Protocol.objects.get(project=self.project)
        self.assertTrue(protocol.document.name.endswith(".docx"))
        self.assertIsNotNone(protocol.current_revision)
        self.assertEqual(protocol.current_revision.version_label, "v1.0")


class OnlyOfficeConfigTests(TestCase):
    def setUp(self):
        from . import views

        self.views = views
        self.original_settings = views.ONLYOFFICE_SETTINGS
        views.ONLYOFFICE_SETTINGS = {
            "base_url": "http://localhost:8080",
            "internal_url": "http://onlyoffice",
            "app_base_url": "http://web:8000",
            "jwt_secret": "change-me",
            "callback_timeout": 10,
            "trusted_download_urls": [
                "http://localhost:8080",
                "http://onlyoffice",
            ],
        }
        self.addCleanup(self._restore_settings)

        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

        self.factory = RequestFactory()
        self.project = Project.objects.create(title="Will Collaboration Test")
        self.ibrahim = User.objects.create_user(username="ibrahim-editor", password="pw")
        UserRole.objects.create(user=self.ibrahim, project=self.project, role="author")
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile(
                "will-protocol.docx",
                b"protocol",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        self.session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.ibrahim,
            last_activity_at=timezone.now(),
        )

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    def test_config_uses_internal_app_base_for_document_and_callback_urls(self):
        request = self.factory.get("/", HTTP_HOST="localhost:8000")
        request.user = self.ibrahim

        config = _build_onlyoffice_config(
            request,
            self.project,
            self.protocol,
            self.session,
            CollaborativeSession.DOCUMENT_PROTOCOL,
        )

        document_url = urlparse(config["document"]["url"])
        callback_url = urlparse(config["editorConfig"]["callbackUrl"])

        self.assertEqual(document_url.scheme, "http")
        self.assertEqual(document_url.netloc, "web:8000")
        self.assertTrue(document_url.path.startswith("/media/"))
        self.assertEqual(callback_url.scheme, "http")
        self.assertEqual(callback_url.netloc, "web:8000")
        self.assertEqual(
            callback_url.path,
            reverse(
                "synopsis:collaborative_edit_callback",
                args=[self.project.id, "protocol", self.session.token],
            ),
        )


class CollaborativeForceSaveCloseTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Will Final Save")
        self.manager = User.objects.create_user(username="ibrahim-manager", password="pw")
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        UserRole.objects.create(user=self.manager, project=self.project, role="manager")
        self.client.force_login(self.manager)
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("will-protocol.docx", b"protocol"),
        )
        self.session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.manager,
            last_activity_at=timezone.now(),
        )
        self.url = reverse(
            "synopsis:collaborative_force_end",
            args=[self.project.id, "protocol", self.session.token],
        )

    @patch("synopsis.views._wait_for_collaborative_save", return_value=False)
    @patch(
        "synopsis.views._request_onlyoffice_forcesave",
        return_value=("failed", "Unable to request a final save from OnlyOffice."),
    )
    def test_force_end_keeps_session_open_when_save_request_fails(
        self, mock_request, mock_wait
    ):
        response = self.client.post(self.url, {"reason": "Close from portal"})

        self.assertRedirects(
            response,
            reverse("synopsis:protocol_detail", args=[self.project.id]),
        )
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_active)
        messages_list = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("session is still open" in message for message in messages_list),
            messages_list,
        )
        mock_request.assert_called_once()
        mock_wait.assert_not_called()

    @patch("synopsis.views._wait_for_collaborative_save", return_value=True)
    @patch(
        "synopsis.views._request_onlyoffice_forcesave",
        return_value=("requested", "Final save requested from OnlyOffice."),
    )
    def test_force_end_reports_success_after_final_save(
        self, mock_request, mock_wait
    ):
        response = self.client.post(self.url, {"reason": "Close from portal"})

        self.assertRedirects(
            response,
            reverse("synopsis:protocol_detail", args=[self.project.id]),
        )
        messages_list = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "Protocol saved and collaborative session closed.",
            messages_list,
        )
        mock_request.assert_called_once()
        mock_wait.assert_called_once()

    @patch("synopsis.views._wait_for_collaborative_save")
    @patch(
        "synopsis.views._request_onlyoffice_forcesave",
        return_value=("noop", "No unsaved changes were pending in OnlyOffice."),
    )
    def test_force_end_closes_session_when_no_unsaved_changes(
        self, mock_request, mock_wait
    ):
        response = self.client.post(self.url, {"reason": "Close from portal"})

        self.assertRedirects(
            response,
            reverse("synopsis:protocol_detail", args=[self.project.id]),
        )
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)
        self.assertEqual(self.session.ended_by, self.manager)
        self.assertEqual(self.session.end_reason, "Close from portal")
        self.assertEqual(self.session.change_summary, "Close from portal")
        messages_list = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "Protocol had no unsaved changes and the session was closed.",
            messages_list,
        )
        mock_request.assert_called_once()
        mock_wait.assert_not_called()


class MediaServingUrlTests(SimpleTestCase):
    def test_media_route_added_when_serve_media_enabled_without_debug(self):
        import ce_portal.urls as project_urls

        with override_settings(DEBUG=False, SERVE_MEDIA=True):
            reloaded = importlib.reload(project_urls)
            try:
                route_texts = [str(pattern.pattern) for pattern in reloaded.urlpatterns]
                self.assertTrue(
                    any(text.startswith("^media/") for text in route_texts),
                    route_texts,
                )
            finally:
                importlib.reload(project_urls)


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
        self.assertContains(response, "How this works")
        self.assertContains(
            response, "This page manages the current working protocol for the project."
        )
        self.assertContains(response, "How collaborative editing works")
        self.assertContains(
            response,
            "Use this guide for the live OnlyOffice session itself.",
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
        self.assertContains(response, "How this works")
        self.assertContains(
            response,
            "This page manages the current working action list for the project.",
        )
        self.assertContains(response, "How collaborative editing works")
        self.assertContains(
            response,
            "Use this guide for the live OnlyOffice session itself.",
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

    def test_advisory_board_shows_custom_columns_button_and_not_document_feedback_windows(self):
        response = self.client.get(
            reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        self.assertContains(response, "Custom columns")
        self.assertContains(response, "Deadlines &amp; reminders")
        self.assertNotContains(response, "Protocol feedback window")
        self.assertNotContains(response, "Action list feedback window")

    def test_document_pages_show_feedback_window_controls(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
        )

        protocol_response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        self.assertContains(protocol_response, "Protocol feedback window")
        self.assertContains(protocol_response, "Set protocol deadline")
        self.assertContains(protocol_response, 'data-bs-target="#protocolFeedbackWindowCollapse"')
        self.assertContains(protocol_response, "data-collapse-toggle-label")
        self.assertContains(protocol_response, 'data-label-open="Hide"')

        action_list_response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertContains(action_list_response, "Action list feedback window")
        self.assertContains(action_list_response, "Set action list deadline")
        self.assertContains(action_list_response, 'data-bs-target="#actionListFeedbackWindowCollapse"')
        self.assertContains(action_list_response, "data-collapse-toggle-label")
        self.assertContains(action_list_response, 'data-label-open="Hide"')


class AdvisoryBoardCustomColumnsTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Dynamic Columns")
        self.editor = User.objects.create_user(username="editor-secondary")
        self.accepted = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ann",
            email="ann@example.com",
            response="Y",
        )
        self.pending = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Vanessa",
            email="vanessa@example.com",
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

    def test_apply_protocol_revision_does_not_duplicate_upload_prefix(self):
        _apply_revision_to_protocol(self.protocol, self.rev1)
        self.protocol.refresh_from_db()
        self.assertTrue(self.protocol.document.name.startswith("protocols/"))
        self.assertNotIn("protocols/protocols/", self.protocol.document.name)

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

    def test_apply_action_list_revision_does_not_duplicate_upload_prefix(self):
        _apply_revision_to_action_list(self.action_list, self.al_rev1)
        self.action_list.refresh_from_db()
        self.assertTrue(self.action_list.document.name.startswith("action_lists/"))
        self.assertNotIn("action_lists/action_lists/", self.action_list.document.name)

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

    def test_updates_description(self):
        form = ProjectSettingsForm(
            data={
                "title": "Forest Recovery",
                "description": "  A pilot synopsis for forest restoration.  ",
            },
            instance=self.project,
        )
        self.assertTrue(form.is_valid())
        updated = form.save()
        self.assertEqual(updated.description, "A pilot synopsis for forest restoration.")


class ViewHelperTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Helper Project")

    def test_user_is_manager_for_staff(self):
        user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        self.assertTrue(_user_is_manager(user))

    def test_user_is_manager_for_group_member(self):
        group, _ = Group.objects.get_or_create(name="manager")
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
        self.assertEqual(_funder_contact_label("Ann", "Thornton"), "Ann Thornton")
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

            Morgan, W. and Thornton, A. (2018). Another example of parsing. Ecology Letters 11: 9-12.
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
        self.assertEqual(second["authors"], ["Morgan, W", "Thornton, A"])
        self.assertEqual(second["doi"], "10.5678/example")
        self.assertEqual(second["url"], "https://example.com/article")

    def test_returns_empty_list_for_blank_payload(self):
        self.assertEqual(_parse_plaintext_references(""), [])
        self.assertEqual(_parse_plaintext_references("   "), [])


class EndNoteXmlParserTests(TestCase):
    def test_parses_endnote_xml_record(self):
        payload = textwrap.dedent(
            """
            <xml>
              <records>
                <record>
                  <titles>
                    <title>Coral restoration methods</title>
                    <secondary-title>Marine Ecology</secondary-title>
                  </titles>
                  <contributors>
                    <authors>
                      <author>Alhas, Ibrahim</author>
                      <author>Morgan, Will</author>
                    </authors>
                  </contributors>
                  <dates>
                    <year>2023</year>
                  </dates>
                  <volume>12</volume>
                  <number>4</number>
                  <pages>101-110</pages>
                  <abstract>Summary text.</abstract>
                  <electronic-resource-num>10.1234/example</electronic-resource-num>
                  <urls>
                    <related-urls>
                      <url>https://example.com/article</url>
                    </related-urls>
                  </urls>
                </record>
              </records>
            </xml>
            """
        ).strip()

        parsed = _parse_endnote_xml(payload)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Coral restoration methods")
        self.assertEqual(parsed[0]["journal_name"], "Marine Ecology")
        self.assertEqual(parsed[0]["authors"], ["Alhas, Ibrahim", "Morgan, Will"])
        self.assertEqual(parsed[0]["publication_year"], "2023")
        self.assertEqual(parsed[0]["doi"], "10.1234/example")
        self.assertEqual(parsed[0]["url"], "https://example.com/article")

    def test_returns_empty_list_for_invalid_xml(self):
        self.assertEqual(_parse_endnote_xml("<xml><records>"), [])


class LibraryReferenceBatchUploadTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Library Upload Project")
        self.user = User.objects.create_user(username="libraryuploader", password="pw")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.client.force_login(self.user)
        self.url = reverse("synopsis:library_reference_batch_upload")

    def _plaintext_payload(self):
        return textwrap.dedent(
            """
            Angel, D. L.; et al. (2002). "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture." Hydrobiologia 469(1): 1-10.
            Net pen fish farms generally enrich the surrounding waters and the underlying sediments with nutrients and organic matter.

            Morgan, W. and Thornton, A. (2018). Another example of parsing. Ecology Letters 11: 9-12.
            Full abstract text including doi:10.5678/example and https://example.com/article for reference.
            """
        ).strip()

    def test_skips_existing_library_reference_hashes(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        existing = LibraryReference.objects.create(
            hash_key=existing_hash,
            title="In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            publication_year=2002,
        )

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        response = self.client.post(
            self.url,
            {
                "label": "Library batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
            follow=True,
        )

        self.assertEqual(LibraryReference.objects.count(), 2)
        self.assertTrue(LibraryReference.objects.filter(pk=existing.pk).exists())
        batch = LibraryImportBatch.objects.get(label="Library batch")
        self.assertEqual(batch.record_count, 1)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("Imported 1 reference(s) into 'Library batch'." in message for message in messages)
        )
        self.assertTrue(
            any("Skipped 1 reference(s) already in the library." in message for message in messages)
        )


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

            Morgan, W. and Thornton, A. (2018). Another example of parsing. Ecology Letters 11: 9-12.
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
        self.assertEqual(LibraryReference.objects.count(), 2)
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        self.assertEqual(batch.record_count, 2)
        self.assertFalse(
            Reference.objects.filter(project=self.project, library_reference__isnull=True).exists()
        )
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
            AU  - Thornton, Ann
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
        self.assertIsNotNone(ref.library_reference)
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

    def test_reports_invalid_rows_separately_from_duplicates(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        Reference.objects.create(
            project=self.project,
            batch=ReferenceSourceBatch.objects.create(
                project=self.project,
                label="Existing refs",
                source_type="manual_upload",
                uploaded_by=self.user,
            ),
            hash_key=existing_hash,
            title="In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            publication_year=2002,
        )

        original_normalise = _normalise_import_record

        def fake_normalise(record):
            if record.get("title") == "Another example of parsing":
                return None
            return original_normalise(record)

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )

        with patch("synopsis.views._normalise_import_record", side_effect=fake_normalise):
            response = self.client.post(
                self.url,
                {
                    "label": "Mixed skip batch",
                    "source_type": "journal_search",
                    "ris_file": upload,
                },
                follow=True,
            )

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("Imported 0 reference(s) into 'Mixed skip batch'." in message for message in messages)
        )
        self.assertTrue(
            any("Skipped 1 record(s) already present in this project." in message for message in messages)
        )
        self.assertTrue(
            any("Skipped 1 record(s) with no title." in message for message in messages)
        )

    def test_reuses_existing_library_reference_by_hash(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        existing_library_ref = LibraryReference.objects.create(
            hash_key=existing_hash,
            title="Existing canonical title",
            publication_year=2002,
        )

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        response = self.client.post(
            self.url,
            {
                "label": "Reuse library ref batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )
        self.assertEqual(LibraryReference.objects.count(), 2)
        project_ref = Reference.objects.get(
            project=self.project,
            hash_key=existing_hash,
        )
        self.assertEqual(project_ref.library_reference_id, existing_library_ref.id)

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

    def test_single_screening_update_filters_blank_reference_folder_values(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Single screening batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        ref = batch.references.order_by("id").first()
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(
            detail_url,
            {
                "reference_id": ref.id,
                "screening_status": "included",
                "screening_notes": "Relevant to the topic.",
                "reference_folder": ["", "3a"],
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )
        ref.refresh_from_db()
        self.assertEqual(ref.screening_status, "included")
        self.assertEqual(ref.reference_folder, ["3a"])

    def test_save_folders_preserves_existing_screening_notes(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Folder notes batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        ref = batch.references.order_by("id").first()
        ref.screening_notes = "Keep these notes."
        ref.save(update_fields=["screening_notes", "updated_at"])
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(
            detail_url,
            {
                "reference_id": ref.id,
                "screening_status": ref.screening_status,
                "reference_folder": ["15"],
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )
        ref.refresh_from_db()
        self.assertEqual(ref.reference_folder, ["15"])
        self.assertEqual(ref.screening_notes, "Keep these notes.")

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


class LibraryLinkBatchTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Library Link Project")
        self.user = User.objects.create_user(username="linker", password="pw")

    def test_linking_on_separate_operations_creates_distinct_library_batches(self):
        first_lib_ref = LibraryReference.objects.create(
            title="Library reference one",
            publication_year=2020,
            doi="10.1000/one",
            hash_key="lib-hash-one",
        )
        second_lib_ref = LibraryReference.objects.create(
            title="Library reference two",
            publication_year=2021,
            doi="10.1000/two",
            hash_key="lib-hash-two",
        )

        linked_one, reused_one, batch_one = _link_library_references_to_project(
            self.user,
            self.project,
            [first_lib_ref.id],
            ["15"],
        )
        linked_two, reused_two, batch_two = _link_library_references_to_project(
            self.user,
            self.project,
            [second_lib_ref.id],
            ["15"],
        )

        self.assertEqual((linked_one, reused_one), (1, 0))
        self.assertEqual((linked_two, reused_two), (1, 0))
        self.assertIsNotNone(batch_one)
        self.assertIsNotNone(batch_two)
        self.assertNotEqual(batch_one.id, batch_two.id)
        self.assertNotEqual(batch_one.label, batch_two.label)
        self.assertEqual(batch_one.source_type, "library_link")
        self.assertEqual(batch_two.source_type, "library_link")
        self.assertEqual(batch_one.record_count, 1)
        self.assertEqual(batch_two.record_count, 1)
        self.assertEqual(
            Reference.objects.filter(project=self.project, batch=batch_one).count(), 1
        )
        self.assertEqual(
            Reference.objects.filter(project=self.project, batch=batch_two).count(), 1
        )

    def test_duplicate_only_link_does_not_create_empty_library_batch(self):
        lib_ref = LibraryReference.objects.create(
            title="Duplicate library reference",
            publication_year=2022,
            doi="10.1000/duplicate",
            hash_key="lib-hash-duplicate",
        )
        linked, reused, initial_batch = _link_library_references_to_project(
            self.user,
            self.project,
            [lib_ref.id],
            ["15"],
        )
        self.assertEqual((linked, reused), (1, 0))
        self.assertIsNotNone(initial_batch)

        batch_count_before = ReferenceSourceBatch.objects.filter(
            project=self.project,
            source_type="library_link",
        ).count()

        linked_again, reused_again, duplicate_batch = _link_library_references_to_project(
            self.user,
            self.project,
            [lib_ref.id],
            ["15"],
        )

        self.assertEqual((linked_again, reused_again), (0, 1))
        self.assertIsNone(duplicate_batch)
        self.assertEqual(
            ReferenceSourceBatch.objects.filter(
                project=self.project,
                source_type="library_link",
            ).count(),
            batch_count_before,
        )


class ReferenceSummaryFormTests(TestCase):
    def test_habitat_tags_use_detailed_iucn_choices(self):
        values = [value for value, _label in IUCN_HABITAT_CHOICES]
        self.assertEqual(len(values), 63)
        self.assertIn("Marine Coral Reefs", values)
        self.assertIn(
            "Wetlands (inland) - Permanent Freshwater Lakes",
            values,
        )
        self.assertIn(
            "Artificial - Subtropical/Tropical Heavily Degraded Former Forest",
            values,
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "habitat_tags": [
                    "Marine Coral Reefs",
                    "Forest - Temperate",
                ],
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["habitat_tags"],
            [
                "Marine Coral Reefs",
                "Forest - Temperate",
            ],
        )

    def test_action_tags_use_detailed_iucn_choices(self):
        values = [value for value, _label in IUCN_ACTION_CHOICES]
        self.assertEqual(len(values), 37)
        self.assertIn("Land/water protection-Area protection", values)
        self.assertIn(
            "Livelihood, economic & other incentives-Conservation payments", values
        )
        self.assertIn("Research & monitoring-Other", values)

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "action_tags": [
                    "Land/water management-Site/area management",
                    "Research & monitoring-Conservation planning",
                ],
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["action_tags"],
            [
                "Land/water management-Site/area management",
                "Research & monitoring-Conservation planning",
            ],
        )

    def test_threat_tags_use_detailed_iucn_choices(self):
        values = [value for value, _label in IUCN_THREAT_CHOICES]
        self.assertEqual(len(values), 41)
        self.assertIn(
            "Residential & commercial development-Housing/urban areas", values
        )
        self.assertIn("Invasive & other problematic species & genes", values)
        self.assertIn(
            "Climate change & severe weather-Other impacts", values
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "threat_tags": [
                    "Residential & commercial development-Housing/urban areas",
                    "Climate change & severe weather-Storms/flooding",
                ],
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["threat_tags"],
            [
                "Residential & commercial development-Housing/urban areas",
                "Climate change & severe weather-Storms/flooding",
            ],
        )

    def test_draft_form_prefills_generated_summary_when_no_saved_draft_exists(self):
        project = Project.objects.create(title="Coral Reefs Synopsis")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="c" * 40,
            title="Test reference",
        )
        summary = ReferenceSummary.objects.create(project=project, reference=reference)

        form = ReferenceSummaryDraftForm(
            instance=summary,
            generated_summary="Auto-generated paragraph.",
        )

        self.assertEqual(form["synopsis_draft"].value(), "Auto-generated paragraph.")

    def test_location_tags_accepts_place_and_coords(self):
        form = ReferenceSummaryUpdateForm(
            data={"status": ReferenceSummary.STATUS_TODO, "location_tags": "London, UK - 51.50740, -0.12780"}
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["location_tags"], ["London, UK - 51.50740, -0.12780"])

    def test_location_tags_rejects_out_of_range(self):
        form = ReferenceSummaryUpdateForm(
            data={"status": ReferenceSummary.STATUS_TODO, "location_tags": "Nowhere - 123.00000, 200.00000"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Coordinates must be valid latitude", str(form.errors))

    def test_outcomes_raw_ignores_empty_rows(self):
        data = {
            "status": ReferenceSummary.STATUS_TODO,
            "outcomes_raw": "Outcome | 1 | treat | 2 | comp | unit | diff | stats | p | notes\n | | | | | | | | | ",
        }
        form = ReferenceSummaryUpdateForm(data=data)
        self.assertTrue(form.is_valid())
        cleaned = form.cleaned_data["outcomes_raw"]
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["outcome"], "Outcome")

    def test_quality_scores_accept_boundary_values(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "benefits_score": "0",
                "harms_score": "100",
                "reliability_score": "0.0",
                "relevance_score": "1.0",
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["benefits_score"], 0.0)
        self.assertEqual(form.cleaned_data["harms_score"], 100.0)
        self.assertEqual(form.cleaned_data["reliability_score"], 0.0)
        self.assertEqual(form.cleaned_data["relevance_score"], 1.0)

    def test_quality_scores_reject_values_outside_ranges(self):
        invalid_cases = [
            ("benefits_score", "-0.1"),
            ("benefits_score", "100.1"),
            ("harms_score", "-1"),
            ("harms_score", "101"),
            ("reliability_score", "-0.01"),
            ("reliability_score", "1.01"),
            ("relevance_score", "-0.5"),
            ("relevance_score", "2"),
        ]
        for field_name, value in invalid_cases:
            with self.subTest(field_name=field_name, value=value):
                form = ReferenceSummaryUpdateForm(
                    data={
                        "status": ReferenceSummary.STATUS_TODO,
                        field_name: value,
                    }
                )
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)


class ReferenceSummaryDetailViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="author", password="pass123")
        self.project = Project.objects.create(title="Coral Reefs Synopsis")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Batch",
            source_type="journal_search",
        )
        self.reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="a" * 40,
            title="Test reference",
        )
        self.summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            status=ReferenceSummary.STATUS_TODO,
        )

    def test_save_summary_persists_changes(self):
        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        resp = self.client.post(
            url,
            {
                "action": "save-summary",
                "status": ReferenceSummary.STATUS_DRAFT,
                "habitat_and_sites": "New habitat info",
            },
            follow=True,
        )
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.status, ReferenceSummary.STATUS_DRAFT)
        self.assertEqual(self.summary.habitat_and_sites, "New habitat info")
        messages = list(get_messages(resp.wsgi_request))
        self.assertTrue(any("Summary updated" in str(m) for m in messages))

    def test_save_summary_does_not_clear_saved_paragraph_draft(self):
        self.summary.synopsis_draft = "Edited summary paragraph."
        self.summary.save(update_fields=["synopsis_draft", "updated_at"])

        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        self.client.post(
            url,
            {
                "action": "save-summary",
                "status": ReferenceSummary.STATUS_DRAFT,
                "habitat_and_sites": "Updated habitat info",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.synopsis_draft, "Edited summary paragraph.")

    def test_save_summary_paragraph_draft_persists_changes(self):
        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        response = self.client.post(
            url,
            {
                "action": "save-synopsis-draft",
                "draft_command": "save",
                "synopsis_draft": "A revised summary paragraph written by the author.",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(
            self.summary.synopsis_draft,
            "A revised summary paragraph written by the author.",
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("paragraph draft saved" in str(m).lower() for m in messages))

    def test_saved_summary_paragraph_draft_is_used_for_compilation(self):
        self.summary.reference_identifier = "CR1000"
        self.summary.synopsis_draft = "A revised paragraph (CR1000) with edited wording."
        self.summary.save(
            update_fields=["reference_identifier", "synopsis_draft", "updated_at"]
        )

        compiled = _reference_summary_paragraph(
            self.summary, reference_identifier_override="2"
        )

        self.assertEqual(
            compiled,
            "A revised paragraph (2) with edited wording.",
        )

    def test_create_summary_tab_adds_second_summary_for_same_reference(self):
        self.summary.assigned_to = self.user
        self.summary.reference_identifier = "manual-ref"
        self.summary.summary_identifier = "manual-summary"
        self.summary.reference_label = "Test reference label"
        self.summary.summary_author = "Existing Author"
        self.summary.citation = "Author (2024)"
        self.summary.save()

        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        resp = self.client.post(
            url,
            {"action": "create-summary-tab"},
            follow=False,
        )

        self.assertEqual(
            ReferenceSummary.objects.filter(
                project=self.project,
                reference=self.reference,
            ).count(),
            2,
        )
        new_summary = (
            ReferenceSummary.objects.filter(
                project=self.project,
                reference=self.reference,
            )
            .exclude(pk=self.summary.id)
            .get()
        )
        self.assertRedirects(
            resp,
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, new_summary.id],
            ),
            fetch_redirect_response=False,
        )
        self.summary.refresh_from_db()
        self.assertEqual(new_summary.assigned_to, self.user)
        self.assertEqual(self.summary.reference_identifier, "manual-ref")
        self.assertEqual(self.summary.summary_identifier, "manual-summary")
        self.assertEqual(new_summary.reference_identifier, "manual-ref")
        self.assertEqual(new_summary.summary_identifier, "manual-ref.a")
        self.assertEqual(new_summary.summary_author, "Existing Author")
        self.assertEqual(new_summary.citation, "Author (2024)")

    def test_delete_summary_tab_removes_extra_tab_and_redirects_to_remaining_tab(self):
        extra_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            status=ReferenceSummary.STATUS_DRAFT,
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, extra_summary.id],
            ),
            {"action": "delete-summary-tab"},
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            ReferenceSummary.objects.filter(pk=extra_summary.id).exists()
        )
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.summary_identifier, "CR1000.a")

    def test_delete_summary_tab_resequences_intervention_assignments(self):
        extra_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            status=ReferenceSummary.STATUS_DRAFT,
        )
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="Evidence",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="General",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="Intervention",
            position=1,
        )
        retained_assignment = SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=extra_summary,
            position=2,
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, extra_summary.id],
            ),
            {"action": "delete-summary-tab"},
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            fetch_redirect_response=False,
        )
        retained_assignment.refresh_from_db()
        self.assertEqual(retained_assignment.position, 1)

    def test_delete_summary_tab_is_blocked_for_only_summary(self):
        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {"action": "delete-summary-tab"},
            follow=True,
        )

        self.assertEqual(
            ReferenceSummary.objects.filter(
                project=self.project,
                reference=self.reference,
            ).count(),
            1,
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(
            any("only summary tab" in str(message) for message in messages)
        )

    def test_detail_page_shows_generated_identifiers_and_reference_title(self):
        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, 'value="CR1000"')
        self.assertContains(response, 'value="CR1000.a"')
        self.assertContains(response, 'value="Test reference"')

    def test_single_summary_tab_defaults_to_generated_summary_identifier_label(self):
        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        tabs = response.context["summary_tabs"]
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["label"], "CR1000.a")

    def test_second_reference_in_project_gets_next_generated_reference_id(self):
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="b" * 40,
            title="Second reference",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, second_summary.id],
            )
        )

        second_summary.refresh_from_db()
        self.assertEqual(second_summary.reference_identifier, "CR1001")
        self.assertEqual(second_summary.summary_identifier, "CR1001.a")
        self.assertContains(response, 'value="CR1001"')
        self.assertContains(response, 'value="CR1001.a"')

    def test_project_title_change_does_not_rewrite_existing_identifiers(self):
        self.client.login(username="author", password="pass123")
        detail_url = reverse(
            "synopsis:reference_summary_detail",
            args=[self.project.id, self.summary.id],
        )

        self.client.get(detail_url)
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.reference_identifier, "CR1000")
        self.assertEqual(self.summary.summary_identifier, "CR1000.a")

        self.project.title = "Marine Restoration Handbook"
        self.project.save(update_fields=["title"])

        self.client.get(detail_url)
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.reference_identifier, "CR1000")
        self.assertEqual(self.summary.summary_identifier, "CR1000.a")

    def test_deleting_earlier_reference_does_not_rewrite_later_reference_identifier(self):
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="b" * 40,
            title="Second reference",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        self.client.login(username="author", password="pass123")
        second_detail_url = reverse(
            "synopsis:reference_summary_detail",
            args=[self.project.id, second_summary.id],
        )

        self.client.get(second_detail_url)
        second_summary.refresh_from_db()
        self.assertEqual(second_summary.reference_identifier, "CR1001")
        self.assertEqual(second_summary.summary_identifier, "CR1001.a")

        self.reference.delete()

        self.client.get(second_detail_url)
        second_summary.refresh_from_db()
        self.assertEqual(second_summary.reference_identifier, "CR1001")
        self.assertEqual(second_summary.summary_identifier, "CR1001.a")

    def test_new_reference_after_deleting_earlier_reference_gets_next_unused_id(self):
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="b" * 40,
            title="Second reference",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        self.client.login(username="author", password="pass123")
        self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, second_summary.id],
            )
        )
        second_summary.refresh_from_db()
        self.assertEqual(second_summary.reference_identifier, "CR1001")

        self.reference.delete()

        third_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="c" * 40,
            title="Third reference",
        )
        third_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=third_reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, third_summary.id],
            )
        )

        third_summary.refresh_from_db()
        self.assertEqual(third_summary.reference_identifier, "CR1002")
        self.assertEqual(third_summary.summary_identifier, "CR1002.a")
        self.assertContains(response, 'value="CR1002"')
        self.assertContains(response, 'value="CR1002.a"')

    def test_new_reference_after_project_rename_keeps_established_prefix(self):
        self.client.login(username="author", password="pass123")
        self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.reference_identifier, "CR1000")

        self.project.title = "Marine Restoration Handbook"
        self.project.save(update_fields=["title"])

        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="b" * 40,
            title="Second reference",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, second_summary.id],
            )
        )

        second_summary.refresh_from_db()
        self.assertEqual(second_summary.reference_identifier, "CR1001")
        self.assertEqual(second_summary.summary_identifier, "CR1001.a")
        self.assertContains(response, 'value="CR1001"')
        self.assertContains(response, 'value="CR1001.a"')

    def test_board_still_creates_only_one_default_summary_per_included_reference(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status"])
        self.client.login(username="author", password="pass123")
        extra_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            citation="Alt citation",
        )

        resp = self.client.get(
            reverse("synopsis:reference_summary_board", args=[self.project.id])
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            ReferenceSummary.objects.filter(
                project=self.project,
                reference=self.reference,
            ).count(),
            2,
        )
        self.assertContains(resp, "of 2 summary tabs for this reference", status_code=200)
        self.assertContains(resp, "CR1000.b")

    def test_board_and_detail_use_library_reference_metadata(self):
        canonical = LibraryReference.objects.create(
            title="Canonical library title",
            authors="Alhas, Ibrahim",
            publication_year=2024,
        )
        self.reference.library_reference = canonical
        self.reference.title = "Project-local title"
        self.reference.screening_status = "included"
        self.reference.save(
            update_fields=["library_reference", "title", "screening_status", "updated_at"]
        )

        self.client.login(username="author", password="pass123")

        board_response = self.client.get(
            reverse("synopsis:reference_summary_board", args=[self.project.id])
        )
        detail_response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(board_response, "Canonical library title")
        self.assertContains(board_response, "Alhas, Ibrahim")
        self.assertContains(detail_response, "Canonical library title")
        self.assertContains(detail_response, "Alhas, Ibrahim")

    def test_summary_detail_can_update_reference_classification(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        self.client.login(username="author", password="pass123")

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-classification",
                "screening_status": "included",
                "reference_folder": ["3a"],
                "screening_notes": "Freshwater fish evidence.",
            },
            follow=True,
        )

        self.reference.refresh_from_db()
        self.assertEqual(self.reference.screening_status, "included")
        self.assertEqual(self.reference.reference_folder, ["3a"])
        self.assertEqual(self.reference.screening_notes, "Freshwater fish evidence.")
        self.assertContains(response, "Reference classification updated.")

    def test_summary_detail_filters_blank_reference_folder_values(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        self.client.login(username="author", password="pass123")

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-classification",
                "screening_status": "included",
                "reference_folder": ["", "3a"],
                "screening_notes": "Freshwater fish evidence.",
            },
            follow=True,
        )

        self.reference.refresh_from_db()
        self.assertEqual(self.reference.reference_folder, ["3a"])
        self.assertContains(response, "Reference classification updated.")

    def test_excluding_reference_requires_reason_on_summary_page(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        self.client.login(username="author", password="pass123")

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-classification",
                "screening_status": "excluded",
                "reference_folder": [],
                "screening_notes": "",
            },
        )

        self.reference.refresh_from_db()
        self.assertEqual(self.reference.screening_status, "included")
        self.assertContains(
            response,
            "Provide a reason before excluding this reference from the synopsis.",
        )

    def test_excluding_reference_from_summary_removes_synopsis_assignments(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        chapter = SynopsisChapter.objects.create(
            project=self.project,
            title="Evidence",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="General",
            position=1,
        )
        intervention = SynopsisIntervention.objects.create(
            subheading=subheading,
            title="Intervention",
            position=1,
        )
        assignment = SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )
        key_message = SynopsisInterventionKeyMessage.objects.create(
            intervention=intervention,
            response_group=SynopsisInterventionKeyMessage.GROUP_POPULATION,
            statement="Supported by this study.",
            position=1,
        )
        key_message.supporting_summaries.set([self.summary])

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-classification",
                "screening_status": "excluded",
                "reference_folder": ["3a"],
                "screening_notes": "Not relevant to this synopsis.",
            },
            follow=False,
        )

        self.reference.refresh_from_db()
        key_message.refresh_from_db()
        self.assertEqual(self.reference.screening_status, "excluded")
        self.assertEqual(self.reference.screening_notes, "Not relevant to this synopsis.")
        self.assertFalse(SynopsisAssignment.objects.filter(pk=assignment.id).exists())
        self.assertEqual(key_message.supporting_summaries.count(), 0)
        self.assertRedirects(
            response,
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, self.batch.id])}?focus=1&ref={self.reference.id}",
            fetch_redirect_response=False,
        )

    def test_board_context_workload_counts_are_aggregated_correctly(self):
        other_author = User.objects.create_user(
            username="coauthor",
            password="pass123",
            first_name="Co",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")

        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status"])
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="b" * 40,
            title="Second reference",
            screening_status="included",
        )
        third_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="c" * 40,
            title="Third reference",
            screening_status="included",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            assigned_to=self.user,
            needs_help=True,
            status=ReferenceSummary.STATUS_DONE,
        )
        third_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=third_reference,
            assigned_to=other_author,
            needs_help=False,
            status=ReferenceSummary.STATUS_DRAFT,
        )
        self.summary.assigned_to = self.user
        self.summary.needs_help = False
        self.summary.status = ReferenceSummary.STATUS_DONE
        self.summary.save(
            update_fields=["assigned_to", "needs_help", "status", "updated_at"]
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse("synopsis:reference_summary_board", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        workload = {
            row["author"].id: {
                "assigned": row["assigned"],
                "summarised": row["summarised"],
                "summarised_percent": row["summarised_percent"],
                "needs_help": row["needs_help"],
            }
            for row in response.context["workload"]
        }
        self.assertEqual(
            workload[self.user.id],
            {
                "assigned": 2,
                "summarised": 2,
                "summarised_percent": 100,
                "needs_help": 1,
            },
        )
        self.assertEqual(
            workload[other_author.id],
            {
                "assigned": 1,
                "summarised": 0,
                "summarised_percent": 0,
                "needs_help": 0,
            },
        )
        self.assertEqual(response.context["unassigned_count"], 0)
        self.assertEqual(response.context["needs_help_count"], 1)


class GlobalReferenceLibraryAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="authorlib", password="pass123")
        self.project = Project.objects.create(title="Coral Project")
        UserRole.objects.create(user=self.user, project=self.project, role="author")

    def test_author_sees_global_library_entry_points(self):
        self.client.login(username="authorlib", password="pass123")

        dashboard_response = self.client.get(reverse("synopsis:dashboard"))
        project_response = self.client.get(
            reverse("synopsis:project_hub", args=[self.project.id])
        )

        self.assertContains(dashboard_response, "Open Reference Database")
        self.assertContains(dashboard_response, "Reference Database")
        self.assertContains(dashboard_response, "How this works for authors")
        self.assertContains(
            dashboard_response,
            "The portal is meant to support the main Conservation Evidence synopsis workflow in one place",
        )
        self.assertContains(
            dashboard_response,
            "This pilot is here to test how well the portal supports the real CE synopsis workflow from start to finish",
        )
        self.assertContains(project_response, "Browse Reference Database")
        self.assertContains(
            project_response,
            reverse("synopsis:reference_library") + f"?project={self.project.id}",
            html=False,
        )

    def test_library_pages_show_global_workflow_help(self):
        self.client.login(username="authorlib", password="pass123")
        batch = LibraryImportBatch.objects.create(
            label="Library import",
            source_type="journal_search",
            uploaded_by=self.user,
        )

        library_response = self.client.get(reverse("synopsis:reference_library"))
        batch_list_response = self.client.get(reverse("synopsis:library_batch_list"))
        batch_detail_response = self.client.get(
            reverse("synopsis:library_batch_detail", args=[batch.id])
        )

        for response in (library_response, batch_list_response, batch_detail_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "How this works")
            self.assertContains(response, "How the shared reference library works")
            self.assertContains(response, "shared library of references")
            self.assertContains(response, "It is not yet a full EndNote replacement")


class ProjectReferenceWorkflowHelpUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="refauthor", password="pass123")
        self.project = Project.objects.create(title="Reference Help Project")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Search batch",
            source_type="journal_search",
            uploaded_by=self.user,
        )
        self.reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="ref-help-1",
            title="Shared library behaviour",
            screening_status="included",
        )
        self.summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=self.reference,
            citation="Shared library behaviour",
        )

    def test_project_reference_pages_show_workflow_help(self):
        self.client.login(username="refauthor", password="pass123")

        responses = [
            self.client.get(reverse("synopsis:reference_batch_list", args=[self.project.id])),
            self.client.get(
                reverse(
                    "synopsis:reference_batch_detail",
                    args=[self.project.id, self.batch.id],
                )
            ),
            self.client.get(
                reverse("synopsis:reference_summary_board", args=[self.project.id])
            ),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "How this works")
            self.assertContains(response, "How project references work")
            self.assertContains(response, "Two ways to add references")
            self.assertContains(
                response,
                "It does not copy the current team workflow exactly",
            )


class ProjectAuthorSelectionUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="pass123")
        self.other_user = User.objects.create_user(
            username="ibrahim",
            password="pass123",
            first_name="Ibrahim",
            last_name="Alhas",
        )
        self.third_user = User.objects.create_user(
            username="will",
            password="pass123",
            first_name="Will",
            last_name="Morgan",
        )

    def test_project_create_uses_readable_author_picker(self):
        self.client.login(username="creator", password="pass123")

        response = self.client.get(reverse("synopsis:project_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Description (optional)")
        self.assertContains(response, "Filter authors by name or username")
        self.assertNotContains(response, "Ctrl/Cmd multi-select", html=False)
        self.assertContains(response, "Ibrahim Alhas (ibrahim)")
        self.assertContains(response, "Will Morgan (will)")


class ProjectDescriptionUiTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="manager",
            password="pass123",
            is_staff=True,
        )
        self.project = Project.objects.create(
            title="Forest Restoration",
            description="A pilot synopsis for forest restoration.",
        )

    def test_project_hub_shows_description_when_present(self):
        self.client.login(username="manager", password="pass123")

        response = self.client.get(reverse("synopsis:project_hub", args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Description")
        self.assertContains(response, "A pilot synopsis for forest restoration.")

    def test_project_settings_shows_description_field(self):
        self.client.login(username="manager", password="pass123")

        response = self.client.get(
            reverse("synopsis:project_settings", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "optional description")
        self.assertContains(response, "A pilot synopsis for forest restoration.")
        self.assertContains(response, 'value="Forest Restoration"', html=False)
