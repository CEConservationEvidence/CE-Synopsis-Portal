"""Advisory custom field and dynamic column tests."""

from .common import *


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

    def test_custom_fields_are_grouped_by_display_area_in_board_context(self):
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
