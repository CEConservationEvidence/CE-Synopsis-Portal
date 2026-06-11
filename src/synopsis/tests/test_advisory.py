"""Advisory board invitation and deadline workflow tests."""

from .common import *


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

    def test_edit_details_from_confirm_page_reopens_add_member_modal(self):
        response = self.client.post(
            self.url,
            {
                "action": "add_member_back",
                "title": "Dr",
                "first_name": "Amira",
                "middle_name": "",
                "last_name": "Shah",
                "organisation": "Conservation Lab",
                "email": "amira@example.com",
                "country": "UK",
                "continent": "Europe",
                "notes": "Review protocol section.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="addMemberModal"')
        self.assertContains(response, 'window.bootstrap.Modal.getOrCreateInstance')
        self.assertContains(response, 'value="Amira"')
        self.assertContains(response, 'value="amira@example.com"')
        self.assertTrue(response.context["open_add_member_modal"])


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


class MemberReminderUpdateTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

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

    def test_update_response_deadline_explains_no_email_is_sent(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Randy",
            email="randy@example.com",
        )
        target_date = timezone.localdate() + timedelta(days=7)
        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
            {"reminder_date": target_date.strftime("%Y-%m-%d")},
            follow=True,
        )

        self.assertRedirects(response, self.board_url)
        self.assertContains(
            response,
            "Response deadline updated. No email was sent automatically; future reminders now use the new date.",
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

    def test_board_page_shows_accepted_participation_note(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ness",
            email="ness@example.com",
            response="Y",
            participation_confirmed=True,
            participation_statement="Happy to help, but I may be slower next week.",
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View note")
        self.assertContains(response, f"accepted-message-{member.id}")
        self.assertContains(
            response,
            "Happy to help, but I may be slower next week.",
        )

    def test_board_page_greys_out_response_deadline_for_accepted_member(self):
        accepted_date = timezone.localdate() + timedelta(days=4)
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Amina",
            last_name="Accepted",
            email="amina@example.com",
            response="Y",
            participation_confirmed=True,
            response_date=accepted_date,
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{accepted_date.strftime("%Y-%m-%d")}"')
        self.assertContains(response, 'aria-label="Response deadline for Amina"')
        self.assertContains(response, "Locked")
        self.assertContains(response, "Accepted")
        self.assertNotContains(
            response,
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "invite"],
            ),
        )

    def test_board_page_shows_protocol_feedback_modal(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pat",
            last_name="Protocol",
            email="pat@example.com",
            response="Y",
            participation_confirmed=True,
            sent_protocol_at=timezone.now(),
        )
        feedback = ProtocolFeedback.objects.create(
            project=self.project,
            member=member,
            content="Please tighten the scope in the introduction.",
            submitted_at=timezone.now(),
            uploaded_document=SimpleUploadedFile(
                "pat-protocol-comments.docx",
                b"protocol comments",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View feedback")
        self.assertContains(response, "View document")
        self.assertContains(response, f'aria-label="View protocol feedback for {member.first_name} {member.last_name}"')
        self.assertContains(response, f"protocol-feedback-{member.id}")
        self.assertContains(response, f"protocol-feedback-document-{member.id}")
        self.assertContains(response, "Please tighten the scope in the introduction.")
        self.assertContains(response, feedback.latest_document_label())

    def test_board_page_shows_action_list_feedback_modal(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Will",
            last_name="Actions",
            email="will@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
        )
        feedback = ActionListFeedback.objects.create(
            project=self.project,
            member=member,
            content="I suggest splitting habitat creation and restoration.",
            submitted_at=timezone.now(),
            uploaded_document=SimpleUploadedFile(
                "will-action-comments.docx",
                b"action comments",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View feedback")
        self.assertContains(response, "View document")
        self.assertContains(response, f'aria-label="View action list feedback for {member.first_name} {member.last_name}"')
        self.assertContains(response, f"action-list-feedback-{member.id}")
        self.assertContains(response, f"action-list-feedback-document-{member.id}")
        self.assertContains(
            response,
            "I suggest splitting habitat creation and restoration.",
        )
        self.assertContains(response, feedback.latest_document_label())

    def test_board_page_shows_synopsis_feedback_modal(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sam",
            last_name="Synopsis",
            email="sam@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
        )
        feedback = SynopsisFeedback.objects.create(
            project=self.project,
            member=member,
            content="Please expand the key messages.",
            submitted_at=timezone.now(),
            uploaded_document=SimpleUploadedFile(
                "sam-synopsis-comments.pdf",
                b"synopsis comments",
                content_type="application/pdf",
            ),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View feedback")
        self.assertContains(response, "View document")
        self.assertContains(response, f"synopsis-feedback-{member.id}")
        self.assertContains(response, f"synopsis-feedback-document-{member.id}")
        self.assertContains(response, "Please expand the key messages.")
        self.assertContains(response, feedback.latest_document_label())

    def test_board_page_shows_action_list_feedback_deadline(self):
        deadline = timezone.now().replace(second=0, microsecond=0) + timedelta(days=5)
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="ibrahim",
            last_name="Deadline",
            email="ibrahim@hotmail.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
            feedback_on_action_list_deadline=deadline,
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            timezone.localtime(member.feedback_on_action_list_deadline).strftime(
                "%Y-%m-%d %H:%M"
            ),
        )

    def test_board_page_shows_updated_document_tracking_headers_without_guidance(self):
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Header",
            last_name="Check",
            email="header@example.com",
            response="Y",
            participation_confirmed=True,
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "GUIDANCE FEEDBACK")
        self.assertNotContains(response, "GUIDANCE SENT")
        self.assertContains(response, "FEEDBACK DOCUMENT", count=3)
        self.assertContains(response, "AUTHOR REPLIED", count=3)
        self.assertContains(response, "REMINDER SENT", count=4)
        self.assertContains(response, 'th class="ab-status-action text-start"', count=7)
        self.assertContains(response, 'td class="ab-status-action"', count=7)
        self.assertContains(response, 'th class="ab-status-protocol text-start"', count=7)
        self.assertContains(response, 'td class="ab-status-protocol"', count=7)
        self.assertContains(response, 'th class="ab-status-synopsis text-start"', count=7)
        self.assertContains(response, 'td class="ab-status-synopsis"', count=7)

    def test_can_toggle_action_list_author_replied_from_board(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Reyhan",
            last_name="Reply",
            email="reyhan@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
            feedback_on_action_list_received=timezone.localdate(),
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_action_list_flag",
                args=[self.project.id, member.id, "author-replied"],
            ),
            {"value": "1"},
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertTrue(member.wm_replied)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project,
                action="Updated action list tracking",
                details__contains="Marked author replied",
            ).exists()
        )

    def test_cannot_toggle_action_list_author_replied_before_feedback_received(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Early",
            last_name="Reply",
            email="early@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_action_list_flag",
                args=[self.project.id, member.id, "author-replied"],
            ),
            {"value": "1"},
            follow=True,
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertFalse(member.wm_replied)
        self.assertContains(
            response,
            "Action list tracking can only be updated after feedback has been received.",
        )

    def test_action_list_tracking_no_longer_exposes_guidance_feedback_flag(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Giad",
            last_name="Guidance",
            email="giad@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
            feedback_on_action_list_received=timezone.localdate(),
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_action_list_flag",
                args=[self.project.id, member.id, "guidance-feedback"],
            ),
            {"value": "1"},
        )

        self.assertEqual(response.status_code, 400)

    def test_board_page_shows_readable_action_list_tracking_controls(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Raed",
            last_name="Readable",
            email="raed@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
            feedback_on_action_list_received=timezone.localdate(),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not yet")
        self.assertContains(response, "Mark replied")
        self.assertContains(response, "Not added")
        self.assertContains(response, "Mark added")
        self.assertNotContains(response, "Not marked")
        self.assertNotContains(response, "Mark guidance")

    def test_can_toggle_protocol_tracking_flags_from_board(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pia",
            last_name="Protocol",
            email="pia@example.com",
            response="Y",
            participation_confirmed=True,
            sent_protocol_at=timezone.now(),
            feedback_on_protocol_received=timezone.localdate(),
        )

        author_response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_protocol_flag",
                args=[self.project.id, member.id, "author-replied"],
            ),
            {"value": "1"},
        )
        added_response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_protocol_flag",
                args=[self.project.id, member.id, "added-to-doc"],
            ),
            {"value": "1"},
        )
        self.assertRedirects(author_response, self.board_url)
        self.assertRedirects(added_response, self.board_url)
        member.refresh_from_db()
        self.assertTrue(member.protocol_author_replied)
        self.assertTrue(member.added_to_protocol_doc)

    def test_protocol_tracking_no_longer_exposes_guidance_feedback_flag(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pia",
            last_name="Protocol",
            email="pia@example.com",
            response="Y",
            participation_confirmed=True,
            sent_protocol_at=timezone.now(),
            feedback_on_protocol_received=timezone.localdate(),
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_protocol_flag",
                args=[self.project.id, member.id, "guidance-feedback"],
            ),
            {"value": "1"},
        )

        self.assertEqual(response.status_code, 400)

    def test_can_toggle_synopsis_tracking_flags_from_board(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sia",
            last_name="Synopsis",
            email="sia@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
            feedback_on_synopsis_received=timezone.localdate(),
        )

        author_response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_synopsis_flag",
                args=[self.project.id, member.id, "author-replied"],
            ),
            {"value": "1"},
        )
        added_response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_synopsis_flag",
                args=[self.project.id, member.id, "added-to-doc"],
            ),
            {"value": "1"},
        )

        self.assertRedirects(author_response, self.board_url)
        self.assertRedirects(added_response, self.board_url)
        member.refresh_from_db()
        self.assertTrue(member.synopsis_author_replied)
        self.assertTrue(member.added_to_synopsis_doc)

    def test_can_mark_synopsis_feedback_received_from_board(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sia",
            last_name="Feedback",
            email="sia-feedback@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_synopsis_flag",
                args=[self.project.id, member.id, "feedback-received"],
            ),
            {"value": "1"},
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertEqual(member.feedback_on_synopsis_received, timezone.localdate())

    def test_synopsis_feedback_link_accepts_comments_and_document(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sia",
            last_name="Reviewer",
            email="sia-reviewer@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
            feedback_on_synopsis_deadline=timezone.now() + timedelta(days=4),
        )
        feedback = SynopsisFeedback.objects.create(
            project=self.project,
            member=member,
            email=member.email,
            feedback_deadline_at=member.feedback_on_synopsis_deadline,
        )
        get_response = self.client.get(
            reverse("synopsis:synopsis_feedback", args=[str(feedback.token)])
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "How your information is used")
        self.assertContains(get_response, "authorised project authors and managers")
        uploaded_doc = SimpleUploadedFile(
            "synopsis-comments.pdf",
            b"annotated synopsis",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("synopsis:synopsis_feedback", args=[str(feedback.token)]),
            {
                "content": "Please clarify the evidence summary.",
                "uploaded_document": uploaded_doc,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Thank you")
        feedback.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(feedback.content, "Please clarify the evidence summary.")
        self.assertTrue(feedback.uploaded_document.name)
        self.assertEqual(member.feedback_on_synopsis_received, timezone.localdate())

    def test_board_page_shows_readable_protocol_and_synopsis_tracking_controls(self):
        protocol_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Paul",
            email="paul@example.com",
            response="Y",
            participation_confirmed=True,
            sent_protocol_at=timezone.now(),
            feedback_on_protocol_received=timezone.localdate(),
        )
        synopsis_member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sara",
            email="sara@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
            feedback_on_synopsis_received=timezone.localdate(),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "synopsis:advisory_member_set_protocol_flag",
                args=[self.project.id, protocol_member.id, "author-replied"],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "synopsis:advisory_member_set_synopsis_flag",
                args=[self.project.id, synopsis_member.id, "author-replied"],
            ),
        )
        self.assertNotContains(
            response,
            "synopsis:advisory_member_set_guidance_flag",
        )
        self.assertContains(response, "Mark replied", count=2)
        self.assertContains(response, "Not added", count=2)

    def test_board_page_shows_action_list_author_replied_as_awaiting_before_feedback(self):
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Wait",
            last_name="Feedback",
            email="wait@example.com",
            response="Y",
            participation_confirmed=True,
            sent_action_list_at=timezone.now(),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Awaiting feedback")

    def test_board_page_shows_synopsis_send_and_tracking_controls(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sian",
            email="sian@example.com",
            response="Y",
            participation_confirmed=True,
            sent_synopsis_at=timezone.now(),
        )

        response = self.client.get(self.board_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("synopsis:advisory_send_synopsis_compose_all", args=[self.project.id]),
        )
        self.assertContains(
            response,
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "synopsis"],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "synopsis:advisory_member_set_synopsis_flag",
                args=[self.project.id, member.id, "feedback-received"],
            ),
        )
        self.assertContains(response, "Mark received")

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

    def test_update_protocol_deadline_explains_no_email_is_sent(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Paula",
            email="paula@example.com",
            response="Y",
            sent_protocol_at=timezone.now(),
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
            follow=True,
        )

        self.assertRedirects(response, self.board_url)
        self.assertContains(
            response,
            "Protocol deadline updated. No email was sent automatically; future reminders and review links now use the new date.",
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

    def test_protocol_page_deadline_warns_before_protocol_is_sent(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Paula",
            email="paula@example.com",
            response="Y",
            participation_confirmed=True,
        )
        local_deadline = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
            second=0,
            microsecond=0,
        )

        response = self.client.post(
            reverse("synopsis:advisory_schedule_protocol_reminders", args=[self.project.id]),
            {"deadline": local_deadline.strftime("%Y-%m-%dT%H:%M")},
            follow=True,
        )

        self.assertRedirects(
            response, reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        member.refresh_from_db()
        self.assertIsNone(member.feedback_on_protocol_deadline)
        self.assertContains(
            response,
            "No protocol deadline was updated because no accepted advisory board member has been sent the protocol yet.",
        )

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

    def test_update_synopsis_deadline(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Sam",
            email="sam@example.com",
            response="Y",
            sent_synopsis_at=timezone.now(),
            synopsis_reminder_sent=True,
            synopsis_reminder_sent_at=timezone.now(),
        )
        deadline = timezone.now().replace(second=0, microsecond=0) + timedelta(days=5)
        local_deadline = timezone.localtime(deadline)

        response = self.client.post(
            reverse(
                "synopsis:advisory_member_set_deadline",
                args=[self.project.id, member.id, "synopsis"],
            ),
            {"deadline": local_deadline.strftime("%Y-%m-%dT%H:%M")},
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNotNone(member.feedback_on_synopsis_deadline)
        self.assertAlmostEqual(
            member.feedback_on_synopsis_deadline.timestamp(),
            deadline.timestamp(),
            delta=1,
        )
        self.assertFalse(member.synopsis_reminder_sent)
        self.assertIsNone(member.synopsis_reminder_sent_at)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project, action="Updated synopsis reminder"
            ).exists()
        )

    def test_action_list_page_deadline_warns_before_action_list_is_sent(self):
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"action list"),
        )
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Vanessa",
            email="vanessa@example.com",
            response="Y",
            participation_confirmed=True,
        )
        local_deadline = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
            second=0,
            microsecond=0,
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_schedule_action_list_reminders",
                args=[self.project.id],
            ),
            {"deadline": local_deadline.strftime("%Y-%m-%dT%H:%M")},
            follow=True,
        )

        self.assertRedirects(
            response, reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        member.refresh_from_db()
        self.assertIsNone(member.feedback_on_action_list_deadline)
        self.assertContains(
            response,
            "No action list deadline was updated because no accepted advisory board member has been sent the action list yet.",
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

    def test_edit_member_page_includes_delete_action(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            title="Dr",
            first_name="Rebecca",
            last_name="Smith",
            email="rebecca@example.com",
        )

        url = reverse(
            "synopsis:advisory_member_edit",
            args=[self.project.id, member.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delete advisory board member")
        self.assertContains(response, 'name="action" value="delete_member"')

    def test_delete_member_from_edit_page(self):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            title="Dr",
            first_name="Rebecca",
            last_name="Smith",
            email="rebecca@example.com",
        )
        custom_field = AdvisoryBoardCustomField.objects.create(
            project=self.project,
            name="Expertise",
            data_type=AdvisoryBoardCustomField.TYPE_TEXT,
        )
        custom_field.set_value_for_member(member, "Wetlands", changed_by=self.user)
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
            invited_by=self.user,
        )
        protocol_feedback = ProtocolFeedback.objects.create(
            project=self.project,
            member=member,
            email=member.email,
            content="Protocol notes",
        )
        action_list_feedback = ActionListFeedback.objects.create(
            project=self.project,
            member=member,
            email=member.email,
            content="Action list notes",
        )

        url = reverse(
            "synopsis:advisory_member_edit",
            args=[self.project.id, member.id],
        )
        response = self.client.post(url, data={"action": "delete_member"})

        self.assertRedirects(response, self.board_url)
        self.assertFalse(
            AdvisoryBoardMember.objects.filter(pk=member.id).exists()
        )
        self.assertFalse(
            AdvisoryBoardInvitation.objects.filter(pk=invitation.id).exists()
        )
        self.assertFalse(
            custom_field.values.filter(member_id=member.id).exists()
        )
        protocol_feedback.refresh_from_db()
        action_list_feedback.refresh_from_db()
        self.assertIsNone(protocol_feedback.member)
        self.assertIsNone(action_list_feedback.member)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project,
                action="Deleted advisory member",
                details__contains="Rebecca Smith",
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

    def assert_public_nav_actions_hidden(self, response):
        self.assertNotContains(response, ">Home</a>")
        self.assertNotContains(response, ">Login</a>")
        self.assertNotContains(response, ">Logout</button>")
        self.assertNotContains(response, ">Create New Synopsis</a>")

    def test_public_invitation_pages_hide_author_navigation_buttons(self):
        self.client.logout()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
        )

        response = self.client.get(
            reverse(
                "synopsis:advisory_invite_reply",
                args=[str(invitation.token), "yes"],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assert_public_nav_actions_hidden(response)

        response = self.client.post(
            reverse(
                "synopsis:advisory_invite_reply",
                args=[str(invitation.token), "yes"],
            ),
            {"confirm_participation": "on", "statement": "Happy to help."},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_public_nav_actions_hidden(response)

    def test_public_feedback_pages_hide_author_navigation_buttons(self):
        self.client.logout()
        protocol_feedback = ProtocolFeedback.objects.create(
            project=self.project,
            email="reviewer@example.com",
        )
        action_list_feedback = ActionListFeedback.objects.create(
            project=self.project,
            email="reviewer@example.com",
        )

        response = self.client.get(
            reverse(
                "synopsis:protocol_feedback",
                args=[str(protocol_feedback.token)],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assert_public_nav_actions_hidden(response)
        self.assertContains(response, "How your information is used")
        self.assertContains(response, "authorised project authors and managers")

        response = self.client.get(
            reverse(
                "synopsis:action_list_feedback",
                args=[str(action_list_feedback.token)],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assert_public_nav_actions_hidden(response)
        self.assertContains(response, "How your information is used")
        self.assertContains(response, "authorised project authors and managers")

    def test_legacy_accept_link_redirects_to_participation_confirmation(self):
        self.client.logout()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
        )

        response = self.client.get(
            reverse("synopsis:advisory_invite_accept", args=[str(invitation.token)])
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:advisory_invite_reply",
                args=[str(invitation.token), "yes"],
            )
            + "?source=legacy_accept",
        )
        invitation.refresh_from_db()
        member.refresh_from_db()
        self.assertIsNone(invitation.accepted)
        self.assertFalse(member.participation_confirmed)
        self.assertTrue(
            ProjectChangeLog.objects.filter(
                project=self.project,
                action="Opened advisory invite link",
                details__contains="Source: legacy accept link",
            ).exists()
        )

    def test_participation_confirmation_page_explains_two_step_flow(self):
        self.client.logout()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=member,
            email=member.email,
        )

        response = self.client.get(
            reverse(
                "synopsis:advisory_invite_reply",
                args=[str(invitation.token), "yes"],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Step 1 of 2")
        self.assertContains(
            response,
            "Your response is not recorded until you submit the form below.",
        )
        self.assertContains(
            response,
            "you will see a separate thank-you page confirming that your response has been recorded",
        )
        self.assertContains(response, "How your information is used")
        self.assertContains(response, "Lawful basis used by Conservation Evidence")

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

    @patch("synopsis.views._onlyoffice_enabled", return_value=True)
    def test_single_invite_form_explains_optional_action_list_resources(
        self, mock_onlyoffice
    ):
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
        )

        response = self.client.get(
            reverse(
                "synopsis:advisory_invite_create_for_member",
                args=[self.project.id, member.id],
            )
        )

        self.assertContains(response, "Optional action list resources")
        self.assertContains(
            response,
            "Choose the action list document, the action list collaborative editor link, or both.",
        )
        self.assertContains(
            response,
            "this member will be marked as having received the action list on the Advisory Board page",
        )
        self.assertContains(response, "Include action list collaborative editor link")

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

    @patch("synopsis.views._ensure_collaborative_invite_link", return_value="http://example.com/collab")
    @patch("synopsis.views._onlyoffice_enabled", return_value=True)
    @patch("synopsis.views.EmailMultiAlternatives")
    def test_single_invite_with_action_list_resources_marks_member_as_action_list_sent(
        self, mock_email, mock_onlyoffice, mock_collab
    ):
        mock_email.return_value = MagicMock()
        member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ibrahim",
            email="ibrahim@example.com",
        )
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
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
                "include_action_list": "on",
                "include_collaborative_link": "on",
            },
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNotNone(member.sent_action_list_at)
        self.assertFalse(member.action_list_reminder_sent)
        self.assertIsNone(member.action_list_reminder_sent_at)

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
    def test_bulk_invite_with_action_list_resource_marks_members_as_action_list_sent(
        self, mock_email
    ):
        mock_email.return_value = MagicMock()
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
        )
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
                "include_action_list": "on",
            },
        )

        self.assertRedirects(response, self.board_url)
        member.refresh_from_db()
        self.assertIsNotNone(member.sent_action_list_at)
        self.assertFalse(member.action_list_reminder_sent)
        self.assertIsNone(member.action_list_reminder_sent_at)

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


@override_settings(ASYNC_EMAIL_DELIVERY=False)
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
            last_name="Smith",
            email="rebecca@example.com",
            response="Y",
            participation_confirmed=True,
        )
        self.expected_due = timezone.localdate() + timedelta(
            days=settings.ADVISORY_DOCUMENT_FEEDBACK_WINDOW_DAYS
        )

    def test_document_send_pages_show_email_previews(self):
        pages = [
            (
                reverse(
                    "synopsis:advisory_send_protocol_compose_member",
                    args=[self.project.id, self.member.id],
                ),
                "Protocol email preview",
                "data-document-kind=\"protocol\"",
            ),
            (
                reverse(
                    "synopsis:advisory_send_action_list_compose_member",
                    args=[self.project.id, self.member.id],
                ),
                "Action list email preview",
                "data-document-kind=\"action list\"",
            ),
            (
                reverse(
                    "synopsis:advisory_send_synopsis_compose_member",
                    args=[self.project.id, self.member.id],
                ),
                "Synopsis email preview",
                "data-document-kind=\"synopsis\"",
            ),
        ]

        for url, heading, kind_attr in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, kind_attr)
                self.assertContains(response, "data-preview-subject")
                self.assertContains(response, "data-preview-body")
                self.assertContains(response, "Standard message")
                self.assertContains(response, "Rebecca Smith")

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
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear Rebecca Smith", email_body)
        self.assertIn(default_protocol_review_message(), email_body)

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_protocol_bulk_send_uses_generic_greeting(self, mock_email):
        mock_email.return_value = MagicMock()

        response = self.client.post(
            reverse(
                "synopsis:advisory_send_protocol_compose_all",
                args=[self.project.id],
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
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear advisory board member", email_body)
        self.assertNotIn("Dear Rebecca Smith", email_body)

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
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear Rebecca Smith", email_body)
        self.assertIn(default_action_list_review_message(), email_body)

    @patch("synopsis.views.EmailMultiAlternatives")
    def test_action_list_bulk_send_uses_generic_greeting(self, mock_email):
        mock_email.return_value = MagicMock()

        response = self.client.post(
            reverse(
                "synopsis:advisory_send_action_list_compose_all",
                args=[self.project.id],
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
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear advisory board member", email_body)
        self.assertNotIn("Dear Rebecca Smith", email_body)

    @patch("synopsis.views._generate_synopsis_docx", return_value=b"docx")
    @patch("synopsis.views.EmailMultiAlternatives")
    def test_synopsis_member_send_defaults_deadline_to_configured_window(
        self, mock_email, mock_generate
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance

        response = self.client.post(
            reverse(
                "synopsis:advisory_send_synopsis_compose_member",
                args=[self.project.id, self.member.id],
            ),
            {
                "due_date": "",
                "message": "",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.sent_synopsis_at)
        self.assertEqual(
            self.member.feedback_on_synopsis_deadline.date(), self.expected_due
        )
        self.assertEqual(self.member.feedback_on_synopsis_deadline.hour, 23)
        self.assertEqual(self.member.feedback_on_synopsis_deadline.minute, 59)
        feedback = SynopsisFeedback.objects.get(project=self.project, member=self.member)
        self.assertEqual(
            feedback.feedback_deadline_at,
            self.member.feedback_on_synopsis_deadline,
        )
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear Rebecca Smith", email_body)
        self.assertIn(default_synopsis_review_message(), email_body)
        self.assertIn(str(feedback.token), email_body)
        self.assertIn("Provide feedback:", email_body)
        mock_generate.assert_called_once_with(self.project)
        email_instance.attach.assert_called_once()

    @patch("synopsis.views._generate_synopsis_docx", return_value=b"docx")
    @patch("synopsis.views.EmailMultiAlternatives")
    def test_synopsis_bulk_send_uses_generic_greeting(
        self, mock_email, mock_generate
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance

        response = self.client.post(
            reverse(
                "synopsis:advisory_send_synopsis_compose_all",
                args=[self.project.id],
            ),
            {
                "due_date": "",
                "message": "",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        email_body = mock_email.call_args[0][1]
        self.assertIn("Dear advisory board member", email_body)
        self.assertNotIn("Dear Rebecca Smith", email_body)
        mock_generate.assert_called_once_with(self.project)
        email_instance.attach.assert_called_once()

    @patch("synopsis.views._generate_synopsis_docx", return_value=b"generated")
    @patch("synopsis.views.EmailMultiAlternatives")
    def test_synopsis_member_send_can_use_uploaded_attachment(
        self, mock_email, mock_generate
    ):
        email_instance = MagicMock()
        mock_email.return_value = email_instance
        uploaded_doc = SimpleUploadedFile(
            "review-draft.pdf",
            b"uploaded synopsis",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse(
                "synopsis:advisory_send_synopsis_compose_member",
                args=[self.project.id, self.member.id],
            ),
            {
                "due_date": "",
                "standard_message": "Please review this final draft.",
                "message": "Please review this version.",
                "synopsis_document": uploaded_doc,
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        mock_generate.assert_not_called()
        email_body = mock_email.call_args[0][1]
        self.assertIn("Please review this final draft.", email_body)
        self.assertIn("Please review this version.", email_body)
        email_instance.attach.assert_called_once_with(
            "review-draft.pdf",
            b"uploaded synopsis",
            "application/pdf",
        )

    @override_settings(
        ASYNC_EMAIL_DELIVERY=True,
        CELERY_BROKER_URL="redis://broker.example:6379/2",
    )
    @patch("synopsis.views.queue_or_send_email_message", return_value=(True, None))
    def test_protocol_bulk_send_reports_queued_delivery(self, mock_queue):
        response = self.client.post(
            reverse(
                "synopsis:advisory_send_protocol_compose_all",
                args=[self.project.id],
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
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Queued protocol delivery for 1 member(s).", messages)
        self.assertEqual(mock_queue.call_count, 1)

    @override_settings(
        ASYNC_EMAIL_DELIVERY=True,
        CELERY_BROKER_URL="redis://broker.example:6379/2",
    )
    @patch("synopsis.views.queue_or_send_email_message", return_value=(True, None))
    def test_action_list_member_send_reports_queued_delivery(self, mock_queue):
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
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn(
            f"Action list delivery queued for {self.member.email}.", messages
        )
        self.assertEqual(mock_queue.call_count, 1)

    @override_settings(
        ASYNC_EMAIL_DELIVERY=True,
        CELERY_BROKER_URL="redis://broker.example:6379/2",
    )
    @patch("synopsis.views._generate_synopsis_docx", return_value=b"docx")
    @patch("synopsis.views.queue_or_send_email_message", return_value=(True, None))
    def test_synopsis_member_send_reports_queued_delivery(
        self, mock_queue, mock_generate
    ):
        response = self.client.post(
            reverse(
                "synopsis:advisory_send_synopsis_compose_member",
                args=[self.project.id, self.member.id],
            ),
            {
                "due_date": "",
                "message": "",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn(
            f"Synopsis delivery queued for {self.member.email}.", messages
        )
        self.assertEqual(mock_queue.call_count, 1)
        mock_generate.assert_called_once_with(self.project)
