"""Funder form and contact workflow tests."""

from .common import *


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
