"""Reference import, library, summary, and external access tests."""

from .common import *


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

    def test_imports_ris_like_txt_file_with_utf8_bom(self):
        ris_payload = (
            "\ufeffTY  - JOUR\n"
            "TI  - First RIS entry\n"
            "AU  - Morgan, Will\n"
            "PY  - 2024\n"
            "DO  - 10.1000/first\n"
            "ER  -\n\n"
            "TY  - JOUR\n"
            "TI  - Second RIS entry\n"
            "AU  - Thornton, Ann\n"
            "PY  - 2023\n"
            "DO  - 10.1000/second\n"
            "ER  -\n"
        )
        upload = SimpleUploadedFile(
            "references.txt",
            ris_payload.encode("utf-8"),
            content_type="text/plain",
        )

        response = self.client.post(
            self.url,
            {
                "label": "BOM library batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertRedirects(response, reverse("synopsis:reference_library"))
        self.assertEqual(LibraryReference.objects.count(), 2)
        titles = set(LibraryReference.objects.values_list("title", flat=True))
        self.assertEqual(titles, {"First RIS entry", "Second RIS entry"})
        batch = LibraryImportBatch.objects.get(label="BOM library batch")
        self.assertEqual(batch.record_count, 2)


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

    def test_imports_ris_like_txt_file_with_utf8_bom(self):
        ris_payload = (
            "\ufeffTY  - JOUR\n"
            "TI  - First RIS entry\n"
            "AU  - Morgan, Will\n"
            "PY  - 2024\n"
            "DO  - 10.1000/first\n"
            "ER  -\n\n"
            "TY  - JOUR\n"
            "TI  - Second RIS entry\n"
            "AU  - Thornton, Ann\n"
            "PY  - 2023\n"
            "DO  - 10.1000/second\n"
            "ER  -\n"
        )
        upload = SimpleUploadedFile(
            "references.txt",
            ris_payload.encode("utf-8"),
            content_type="text/plain",
        )

        response = self.client.post(
            self.url,
            {
                "label": "BOM batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:reference_batch_list", args=[self.project.id]),
        )
        refs = Reference.objects.filter(project=self.project).order_by("title")
        self.assertEqual(refs.count(), 2)
        self.assertEqual(
            list(refs.values_list("title", flat=True)),
            ["First RIS entry", "Second RIS entry"],
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project, label="BOM batch")
        self.assertEqual(batch.record_count, 2)

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

    def test_project_import_prefills_project_reference_from_shared_library_folders(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        existing_library_ref = LibraryReference.objects.create(
            hash_key=existing_hash,
            title="Existing canonical title",
            publication_year=2002,
            reference_folder=["2", "15"],
        )

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Reuse shared folders batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        project_ref = Reference.objects.get(
            project=self.project,
            hash_key=existing_hash,
        )
        self.assertEqual(project_ref.library_reference_id, existing_library_ref.id)
        self.assertEqual(project_ref.unlinked_reference_folder, [])
        self.assertEqual(project_ref.category_values, ["2", "15"])

    def test_project_reference_uses_shared_categories_as_effective_value(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        existing_library_ref = LibraryReference.objects.create(
            hash_key=existing_hash,
            title="Existing canonical title",
            publication_year=2002,
            reference_folder=["2", "15"],
        )

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Effective category batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        project_ref = Reference.objects.get(project=self.project, hash_key=existing_hash)
        project_ref.unlinked_reference_folder = ["3a"]
        project_ref.save(update_fields=["unlinked_reference_folder", "updated_at"])

        self.assertEqual(project_ref.unlinked_reference_folder, ["3a"])
        self.assertEqual(project_ref.category_values, ["2", "15"])
        self.assertEqual(project_ref.folder_labels(), ["2. Birds", "15. Forests/Woodland"])

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
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Bulk reference screening updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("References: 2", change.details)
        self.assertIn("Screening status: Include", change.details)

    def test_bulk_include_can_apply_selected_folders_at_same_time(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk include folders batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        include_ids = [str(ref.id) for ref in batch.references.order_by("id")[:2]]
        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )

        response = self.client.post(
            detail_url,
            {
                "bulk_action": "include",
                "selected_references": include_ids,
                "reference_folder": ["3a", "15"],
            },
            follow=True,
        )

        self.assertContains(
            response,
            "Applied the selected categories at the same time.",
        )
        for ref in Reference.objects.filter(pk__in=include_ids):
            self.assertEqual(ref.screening_status, "included")
            self.assertEqual(ref.unlinked_reference_folder, [])
            self.assertEqual(ref.category_values, ["3a", "15"])

        linked_library_refs = list(
            LibraryReference.objects.filter(project_references__id__in=include_ids).distinct()
        )
        self.assertTrue(linked_library_refs)
        for library_ref in linked_library_refs:
            self.assertEqual(library_ref.reference_folder, ["3a", "15"])
        self.assertTrue(
            LibraryReferenceFolderHistory.objects.filter(
                library_reference__in=linked_library_refs
            ).exists()
        )

    def test_screening_page_uses_resizable_folder_select_wrapper(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Folder width batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)

        response = self.client.get(
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "folder-select-shell")
        self.assertContains(response, "folder-select")
        self.assertContains(response, "screening-bulk-sticky")
        self.assertContains(response, "Save shared categories")
        self.assertContains(response, "Clear shared categories")
        self.assertContains(response, "Include in synopsis")
        self.assertContains(response, "Exclude from synopsis")
        self.assertContains(response, "Multiple categories are allowed.")
        self.assertContains(response, "data-collapse-toggle-label")
        self.assertContains(response, "screeningBulkPanelBody")
        self.assertContains(response, 'id="reference-batch-page"', html=False)
        self.assertContains(response, "cePreservePageState({", html=False)
        self.assertContains(
            response,
            f'"screening-batch-state-{self.project.id}-{batch.id}"',
            html=False,
        )
        self.assertContains(
            response,
            "Inclusion and exclusion here apply only to this synopsis. Category changes feed back into the shared CE reference library.",
        )
        self.assertContains(
            response,
            "This is the main category-classification step while screening.",
        )
        self.assertContains(
            response,
            "changing categories here updates the shared reference library record and is reflected in linked synopsis copies in other projects",
        )
        self.assertContains(
            response,
            "Save shared categories",
        )
        self.assertContains(
            response,
            "Clear shared categories",
        )
        self.assertContains(
            response,
            "remove all shared categories from those checked references.",
        )

    def test_screening_page_uses_shared_categories_when_local_fallback_exists(self):
        existing_hash = reference_hash(
            "In situ biofiltration: a means to limit the dispersal of effluents from marine finfish cage aquaculture.",
            "2002",
            "",
        )
        existing_library_ref = LibraryReference.objects.create(
            hash_key=existing_hash,
            title="Existing canonical title",
            publication_year=2002,
            reference_folder=["2", "15"],
        )

        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Shared screening category batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )

        batch = ReferenceSourceBatch.objects.get(project=self.project)
        ref = Reference.objects.get(project=self.project, hash_key=existing_hash)
        ref.unlinked_reference_folder = ["3a"]
        ref.save(update_fields=["unlinked_reference_folder", "updated_at"])

        response = self.client.get(
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            )
        )

        self.assertEqual(ref.library_reference_id, existing_library_ref.id)
        self.assertContains(response, 'option value="2" selected')
        self.assertContains(response, 'option value="15" selected')

    def test_focused_screening_shows_fixed_decision_bar_and_current_status(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Focused screening batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        ref = batch.references.order_by("id").first()
        ref.screening_status = "excluded"
        ref.screening_decision_at = timezone.now()
        ref.screened_by = self.user
        ref.save(
            update_fields=[
                "screening_status",
                "screening_decision_at",
                "screened_by",
                "updated_at",
            ]
        )

        response = self.client.get(
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            )
            + f"?focus=1&ref={ref.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "focus-screening-meta")
        self.assertContains(response, "focus-category-actions")
        self.assertContains(response, "focus-decision-bar")
        self.assertContains(response, "focus-decision-actions")
        self.assertContains(response, "Current synopsis status")
        self.assertNotContains(response, "Current status")
        self.assertContains(response, "Reference notes")
        self.assertContains(
            response,
            "These notes stay on this synopsis copy of the reference. They do not update the shared reference library, and excluding this reference here removes it only from this synopsis.",
        )
        self.assertContains(response, "Save notes")
        self.assertContains(
            response,
            f"Last screening update by {self.user.username} on",
        )
        self.assertNotContains(
            response,
            f'data-bs-target="#refCommentsModal-{ref.id}"',
            html=False,
        )
        self.assertContains(
            response,
            '<span class="focus-status-pill is-active">Excluded</span>',
            html=False,
        )

    def test_focused_save_categories_stays_on_same_reference(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Focused category save batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.order_by("id"))
        ref = references[0]
        next_ref = references[1]

        response = self.client.post(
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
            {
                "action": "save-categories",
                "focus": "1",
                "focus_ref": str(ref.id),
                "reference_id": str(ref.id),
                "screening_status": ref.screening_status,
                "reference_folder": ["3a"],
                "next_ref_id": str(next_ref.id),
            },
        )

        self.assertEqual(
            response["Location"],
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, batch.id])}?focus=1&ref={ref.id}",
        )
        ref.refresh_from_db()
        self.assertEqual(ref.category_values, ["3a"])

    def test_focused_save_notes_stays_on_same_reference(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Focused notes save batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.order_by("id"))
        ref = references[0]
        next_ref = references[1]
        ref.screening_status = "included"
        ref.save(update_fields=["screening_status", "updated_at"])

        response = self.client.post(
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
            {
                "action": "save-notes",
                "focus": "1",
                "focus_ref": str(ref.id),
                "reference_id": str(ref.id),
                "screening_status": "included",
                "screening_notes": "Keep for synopsis discussion.",
                "next_ref_id": str(next_ref.id),
            },
        )

        self.assertEqual(
            response["Location"],
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, batch.id])}?focus=1&ref={ref.id}",
        )
        ref.refresh_from_db()
        self.assertEqual(ref.screening_status, "included")
        self.assertEqual(ref.screening_notes, "Keep for synopsis discussion.")

    def test_bulk_apply_folders_to_selected_references(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk folder batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.order_by("id"))
        selected_ids = [str(ref.id) for ref in references[:2]]

        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )
        response = self.client.post(
            detail_url,
            {
                "bulk_action": "save-folders",
                "selected_references": selected_ids,
                "reference_folder": ["3a", "15"],
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "synopsis:reference_batch_detail",
                args=[self.project.id, batch.id],
            ),
        )

        for ref in Reference.objects.filter(pk__in=selected_ids):
            self.assertEqual(ref.unlinked_reference_folder, [])
            self.assertEqual(ref.category_values, ["3a", "15"])
            self.assertEqual(ref.screened_by, self.user)
            self.assertIsNotNone(ref.screening_decision_at)
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Bulk reference categories updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("References: 2", change.details)

    def test_bulk_clear_folders_from_selected_references(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Bulk clear folder batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        references = list(batch.references.select_related("library_reference").order_by("id"))
        selected_ids = [str(ref.id) for ref in references[:2]]
        for ref in references[:2]:
            ref.library_reference.reference_folder = ["3a", "15"]
            ref.library_reference.save(update_fields=["reference_folder", "updated_at"])

        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )
        response = self.client.post(
            detail_url,
            {
                "bulk_action": "clear-folders",
                "selected_references": selected_ids,
                "reference_folder": ["3a"],
            },
            follow=True,
        )

        self.assertContains(response, "Cleared shared categories for 2 reference(s).")
        for ref in Reference.objects.filter(pk__in=selected_ids).select_related("library_reference"):
            self.assertEqual(ref.unlinked_reference_folder, [])
            self.assertEqual(ref.category_values, [])
            self.assertEqual(ref.library_reference.reference_folder, [])
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Bulk reference categories cleared",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("References: 2", change.details)
        self.assertTrue(
            LibraryReferenceFolderHistory.objects.filter(
                library_reference__in=[ref.library_reference for ref in references[:2]],
                change_source="screening_bulk_clear_folders",
            ).exists()
        )

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

        self.assertEqual(
            response["Location"],
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, batch.id])}#ref-{ref.id}",
        )
        ref.refresh_from_db()
        self.assertEqual(ref.screening_status, "included")
        self.assertEqual(ref.unlinked_reference_folder, [])
        self.assertEqual(ref.category_values, ["3a"])
        self.assertEqual(ref.library_reference.reference_folder, ["3a"])
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Reference classification updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference:", change.details)
        self.assertIn("Notes: Relevant to the topic.", change.details)

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

        self.assertEqual(
            response["Location"],
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, batch.id])}#ref-{ref.id}",
        )
        ref.refresh_from_db()
        self.assertEqual(ref.unlinked_reference_folder, [])
        self.assertEqual(ref.category_values, ["15"])
        self.assertEqual(ref.screening_notes, "Keep these notes.")

    def test_single_reference_can_be_reset_to_pending(self):
        upload = SimpleUploadedFile(
            "references.txt",
            self._plaintext_payload().encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            self.url,
            {
                "label": "Pending reset batch",
                "source_type": "journal_search",
                "ris_file": upload,
            },
        )
        batch = ReferenceSourceBatch.objects.get(project=self.project)
        ref = batch.references.order_by("id").first()
        ref.screening_status = "included"
        ref.screening_decision_at = timezone.now()
        ref.screened_by = self.user
        ref.save(
            update_fields=["screening_status", "screening_decision_at", "screened_by", "updated_at"]
        )

        detail_url = reverse(
            "synopsis:reference_batch_detail",
            args=[self.project.id, batch.id],
        )
        response = self.client.post(
            detail_url,
            {
                "reference_id": ref.id,
                "screening_status": "pending",
            },
        )

        self.assertEqual(
            response["Location"],
            f"{reverse('synopsis:reference_batch_detail', args=[self.project.id, batch.id])}#ref-{ref.id}",
        )
        ref.refresh_from_db()
        self.assertEqual(ref.screening_status, "pending")

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

    def test_link_uses_existing_shared_library_folders_by_default(self):
        lib_ref = LibraryReference.objects.create(
            title="Shared folders default",
            publication_year=2024,
            doi="10.1000/shared-default",
            hash_key="lib-hash-shared-default",
            reference_folder=["2", "15"],
        )

        linked, reused, batch = _link_library_references_to_project(
            self.user,
            self.project,
            [lib_ref.id],
            [],
        )

        self.assertEqual((linked, reused), (1, 0))
        self.assertIsNotNone(batch)
        project_ref = Reference.objects.get(project=self.project, library_reference=lib_ref)
        self.assertEqual(project_ref.unlinked_reference_folder, [])
        self.assertEqual(project_ref.category_values, ["2", "15"])

    def test_link_folder_override_updates_shared_library_record(self):
        lib_ref = LibraryReference.objects.create(
            title="Shared folders override",
            publication_year=2024,
            doi="10.1000/shared-override",
            hash_key="lib-hash-shared-override",
            reference_folder=["2"],
        )

        linked, reused, _batch = _link_library_references_to_project(
            self.user,
            self.project,
            [lib_ref.id],
            ["15", "2"],
        )

        self.assertEqual((linked, reused), (1, 0))
        lib_ref.refresh_from_db()
        self.assertEqual(lib_ref.reference_folder, ["2", "15"])
        project_ref = Reference.objects.get(project=self.project, library_reference=lib_ref)
        self.assertEqual(project_ref.unlinked_reference_folder, [])
        self.assertEqual(project_ref.category_values, ["2", "15"])
        self.assertTrue(
            LibraryReferenceFolderHistory.objects.filter(
                library_reference=lib_ref,
                new_folders=["2", "15"],
            ).exists()
        )


class LibraryReferenceDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="libeditor", password="pw")
        self.project = Project.objects.create(title="Library Sync Project")
        UserRole.objects.create(user=self.user, project=self.project, role="author")
        self.library_reference = LibraryReference.objects.create(
            title="Library reference",
            publication_year=2024,
            doi="10.1000/library-detail",
            hash_key="lib-detail-hash",
            reference_folder=["2"],
        )
        self.batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Linked batch",
            source_type="library_link",
            uploaded_by=self.user,
        )
        self.project_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            library_reference=self.library_reference,
            hash_key="lib-detail-hash",
            title="Project copy",
        )
        self.client.force_login(self.user)

    def test_library_detail_updates_shared_folders_for_linked_project_copies(self):
        response = self.client.post(
            reverse(
                "synopsis:library_reference_detail",
                args=[self.library_reference.id],
            ),
            {
                "action": "edit",
                "title": "Library reference",
                "authors": "",
                "publication_year": 2024,
                "journal": "",
                "volume": "",
                "issue": "",
                "pages": "",
                "doi": "10.1000/library-detail",
                "url": "",
                "language": "",
                "abstract": "",
                "reference_folder": ["15", "2"],
            },
            follow=True,
        )

        self.library_reference.refresh_from_db()
        self.project_reference.refresh_from_db()
        self.assertEqual(self.library_reference.reference_folder, ["2", "15"])
        self.assertEqual(self.project_reference.unlinked_reference_folder, [])
        self.assertEqual(self.project_reference.category_values, ["2", "15"])
        self.assertContains(
            response,
            "Shared CE subject categories were updated.",
        )
        self.assertContains(
            response,
            "Linked synopsis copies now read those shared categories automatically.",
        )
        self.assertTrue(
            LibraryReferenceFolderHistory.objects.filter(
                library_reference=self.library_reference,
                new_folders=["2", "15"],
                change_source="library_detail",
            ).exists()
        )


class ReferenceSummaryFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(title="Summary form project")

    def test_update_form_requires_project(self):
        with self.assertRaises(TypeError):
            ReferenceSummaryUpdateForm()

    def test_habitat_tags_use_detailed_iucn_choices(self):
        values = [value for value, _label in IUCN_HABITAT_CHOICES]
        self.assertEqual(len(values), 93)
        self.assertIn("Forest & Woodland-Boreal Woodland/Forest", values)
        self.assertIn(
            "Wetlands-Permanent Freshwater Lakes",
            values,
        )
        self.assertIn(
            "Artificial Habitats-Dams and Reservoirs",
            values,
        )
        self.assertIn("Artificial Habitats-Marine Anthropogenic Structures", values)
        self.assertIn("Other-Continental Ice or Glaciers", values)
        self.assertIn("Wetlands-Marshes and Swamps", values)
        self.assertNotIn("Introduced Vegetation", values)
        self.assertNotIn("Coral Reefs", values)

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "habitat_tags": [
                    "Marine-Coral Reefs",
                    "Artificial Habitats-Dams and Reservoirs",
                ],
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["habitat_tags"],
            [
                "Marine-Coral Reefs",
                "Artificial Habitats-Dams and Reservoirs",
            ],
        )

    def test_habitat_tags_normalize_saved_legacy_values_when_editing(self):
        batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Legacy habitat batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=self.project,
            batch=batch,
            hash_key="h" * 40,
            title="Legacy habitat reference",
        )
        summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=reference,
            habitat_tags=["Marine Coral Reefs", "Artificial - Urban Areas"],
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form.initial["habitat_tags"],
            [
                "Marine-Coral Reefs",
                "Artificial Habitats-Built-up Areas",
            ],
        )

    def test_action_tags_use_detailed_iucn_choices(self):
        values = [value for value, _label in IUCN_ACTION_CHOICES]
        self.assertEqual(len(values), 31)
        self.assertIn("Land/water protection - 1.1 Site/area protection", values)
        self.assertIn(
            "Livelihood, economic & other incentives - 6.4 Conservation payments",
            values,
        )
        self.assertIn(
            "Law & policy - 5.4 Compliance and enforcement - 5.4.4 Scale unspecified",
            values,
        )
        self.assertNotIn("Research & monitoring-Other", values)

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "action_tags": [
                    "Land/water management - 2.1 Site/area management",
                    "Law & policy - 5.2 Policies and regulations",
                ],
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["action_tags"],
            [
                "Land/water management - 2.1 Site/area management",
                "Law & policy - 5.2 Policies and regulations",
            ],
        )

    def test_action_tags_normalize_and_preserve_legacy_saved_values_when_editing(self):
        batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Legacy action batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=self.project,
            batch=batch,
            hash_key="a" * 40,
            title="Legacy action reference",
        )
        summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=reference,
            action_tags=[
                "Land/water management-Site/area management",
                "Research & monitoring-Conservation planning",
            ],
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form.initial["action_tags"],
            [
                "Land/water management - 2.1 Site/area management",
                "Research & monitoring-Conservation planning",
            ],
        )
        choice_values = [value for value, _label in form.fields["action_tags"].choices]
        self.assertIn("Research & monitoring-Conservation planning", choice_values)

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
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["threat_tags"],
            [
                "Residential & commercial development-Housing/urban areas",
                "Climate change & severe weather-Storms/flooding",
            ],
        )

    def test_research_design_accepts_all_selected_tags(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "research_design": [
                    "Replicated",
                    "Randomized",
                    "Paired sites",
                    "Controlled*",
                    "Before-and-after",
                ],
            },
            project=self.project,
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["research_design"],
            "Replicated; Randomized; Paired sites; Controlled*; Before-and-after",
        )

    def test_research_design_initial_splits_saved_tags(self):
        summary = ReferenceSummary(research_design="Replicated; Controlled*")

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form["research_design"].value(),
            ["Replicated", "Controlled*"],
        )

    def test_blank_study_design_is_built_from_research_design_tags(self):
        project = Project.objects.create(title="Auto design")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="d" * 40,
            title="Auto design reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "study_design": "",
                "research_design": [
                    "Replicated",
                    "Randomized",
                    "Controlled*",
                ],
            },
            instance=summary,
            project=project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(
            saved.study_design,
            "replicated, randomized, controlled study",
        )

    def test_manual_study_design_overrides_research_design_tags(self):
        project = Project.objects.create(title="Manual design")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="e" * 40,
            title="Manual design reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            status=ReferenceSummary.STATUS_TODO,
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "study_design": "replicated, randomized, controlled, before-and-after study",
                "research_design": [
                    "Replicated",
                    "Randomized",
                    "Controlled*",
                ],
            },
            instance=summary,
            project=project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(
            saved.study_design,
            "replicated, randomized, controlled, before-and-after study",
        )

    def test_methods_and_design_initial_merges_existing_fields(self):
        summary = ReferenceSummary(
            action_methods="Used fenced plots and added seed.",
            experimental_design="Compared treated and untreated plots over two years.",
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form["methods_and_design"].value(),
            "Used fenced plots and added seed.\n\nCompared treated and untreated plots over two years.",
        )

    def test_action_dropdown_uses_project_interventions(self):
        project = Project.objects.create(title="Action choices")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="a" * 40,
            title="Action reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            action_description="Install nest boxes",
        )
        chapter = SynopsisChapter.objects.create(
            project=project,
            title="Evidence",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="General",
            position=1,
        )
        SynopsisIntervention.objects.create(
            subheading=subheading,
            title="Install nest boxes",
            position=1,
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=project)

        choice_values = [value for value, _label in form.fields["action_choice"].choices]
        self.assertIn("Install nest boxes", choice_values)
        self.assertEqual(form["action_choice"].value(), "Install nest boxes")
        self.assertEqual(form["action_custom"].value(), None)

    def test_action_dropdown_supports_custom_value_when_not_in_structure(self):
        project = Project.objects.create(title="Custom action choice")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="b" * 40,
            title="Custom action reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            action_description="Reduce ditch dredging",
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=project)

        self.assertEqual(
            form["action_choice"].value(),
            ReferenceSummaryUpdateForm.ACTION_CUSTOM_VALUE,
        )
        self.assertEqual(form["action_custom"].value(), "Reduce ditch dredging")

    def test_action_dropdown_save_uses_selected_intervention_title(self):
        project = Project.objects.create(title="Dropdown save")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="c" * 40,
            title="Save action reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            status=ReferenceSummary.STATUS_TODO,
        )
        chapter = SynopsisChapter.objects.create(
            project=project,
            title="Evidence",
            chapter_type=SynopsisChapter.TYPE_EVIDENCE,
            position=1,
        )
        subheading = SynopsisSubheading.objects.create(
            chapter=chapter,
            title="General",
            position=1,
        )
        SynopsisIntervention.objects.create(
            subheading=subheading,
            title="Install nest boxes",
            position=1,
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_DRAFT,
                "action_choice": "Install nest boxes",
                "action_custom": "",
            },
            instance=summary,
            project=project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.action_description, "Install nest boxes")

    def test_action_dropdown_includes_saved_project_action_names(self):
        project = Project.objects.create(
            title="Saved action names",
            saved_action_names="Install nest boxes\nReduce grazing",
        )
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="saved-action-hash",
            title="Saved action reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=project)

        choice_values = [value for value, _label in form.fields["action_choice"].choices]
        self.assertIn("Install nest boxes", choice_values)
        self.assertIn("Reduce grazing", choice_values)

    def test_methods_and_design_save_flattens_into_single_summary_field(self):
        project = Project.objects.create(title="Methods Merge")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="m" * 40,
            title="Methods reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            status=ReferenceSummary.STATUS_TODO,
            action_methods="Old methods",
            experimental_design="Old design",
        )

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_DRAFT,
                "methods_and_design": "Combined methods and design notes.",
            },
            instance=summary,
            project=project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()

        self.assertEqual(saved.action_methods, "Combined methods and design notes.")
        self.assertEqual(saved.experimental_design, "")

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

    def test_draft_form_prefills_saved_custom_paragraph_when_custom_mode_is_active(self):
        project = Project.objects.create(title="Saved custom paragraph")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="f" * 40,
            title="Custom paragraph reference",
        )
        summary = ReferenceSummary.objects.create(
            project=project,
            reference=reference,
            synopsis_draft="Author edited paragraph.",
            use_custom_synopsis_draft=True,
        )

        form = ReferenceSummaryDraftForm(
            instance=summary,
            generated_summary="Auto-generated paragraph.",
        )

        self.assertEqual(form["synopsis_draft"].value(), "Author edited paragraph.")

    def test_draft_form_rejects_invalid_supported_inline_markup(self):
        project = Project.objects.create(title="Invalid markup paragraph")
        batch = ReferenceSourceBatch.objects.create(
            project=project,
            label="Batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=project,
            batch=batch,
            hash_key="g" * 40,
            title="Invalid markup reference",
        )
        summary = ReferenceSummary.objects.create(project=project, reference=reference)

        form = ReferenceSummaryDraftForm(
            data={"synopsis_draft": "A replicated study found that CO<sup>2."},
            instance=summary,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("matching closing tag", form.errors["synopsis_draft"][0])

    def test_citation_field_prefills_with_shared_reference_citation_when_no_local_override_exists(self):
        batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Citation batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=self.project,
            batch=batch,
            hash_key="c" * 40,
            title="Corallivorous snail removal",
            authors="Miller M.",
            publication_year=2001,
            journal="Coral Reefs",
            volume="19",
            pages="293-295",
            doi="10.1007/PL00006963",
        )
        summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=reference,
            citation="Miller M. (2001) Corallivorous snail removal",
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form["citation"].value(),
            reference_summary_effective_citation(summary),
        )
        self.assertIn("Coral Reefs, 19, 293-295.", form["citation"].value())

    def test_citation_matching_shared_reference_is_not_saved_as_local_override(self):
        batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Citation save batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=self.project,
            batch=batch,
            hash_key="d" * 40,
            title="Corallivorous snail removal",
            authors="Miller M.",
            publication_year=2001,
            journal="Coral Reefs",
            volume="19",
            pages="293-295",
            doi="10.1007/PL00006963",
        )
        summary = ReferenceSummary.objects.create(project=self.project, reference=reference)
        shared_citation = reference_summary_effective_citation(summary)

        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "citation": shared_citation,
            },
            instance=summary,
            project=self.project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.citation, "")

    def test_location_tags_accepts_place_and_coords(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "location_tags": "London, UK - 51.50740, -0.12780",
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["location_tags"], ["London, UK - 51.50740, -0.12780"])

    def test_location_tags_rejects_out_of_range(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "location_tags": "Nowhere - 123.00000, 200.00000",
            },
            project=self.project,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Coordinates must be valid latitude", str(form.errors))

    def test_outcomes_raw_ignores_empty_rows(self):
        data = {
            "status": ReferenceSummary.STATUS_TODO,
            "outcomes_raw": "Outcome | 1 | treat | 2 | comp | unit | diff | stats | p | notes\n | | | | | | | | | ",
        }
        form = ReferenceSummaryUpdateForm(data=data, project=self.project)
        self.assertTrue(form.is_valid())
        cleaned = form.cleaned_data["outcomes_raw"]
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["outcome"], "Outcome")

    def test_outcomes_raw_accepts_free_text_sentence_lines(self):
        data = {
            "status": ReferenceSummary.STATUS_TODO,
            "outcomes_raw": "Species richness increased after scrub removal\nBreeding success stayed similar between treatments.",
        }
        form = ReferenceSummaryUpdateForm(data=data, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["outcomes_raw"]
        self.assertEqual(
            cleaned,
            [
                {"sentence": "Species richness increased after scrub removal"},
                {"sentence": "Breeding success stayed similar between treatments."},
            ],
        )

    def test_outcomes_raw_treats_escaped_pipes_as_free_text(self):
        data = {
            "status": ReferenceSummary.STATUS_TODO,
            "outcomes_raw": r"Species richness increased in Site A \| Site B comparison.",
        }
        form = ReferenceSummaryUpdateForm(data=data, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["outcomes_raw"],
            [
                {
                    "sentence": "Species richness increased in Site A | Site B comparison."
                }
            ],
        )

    def test_outcomes_raw_rejects_invalid_inline_markup(self):
        data = {
            "status": ReferenceSummary.STATUS_TODO,
            "outcomes_raw": "Species richness increased under CO<sup>2.",
        }
        form = ReferenceSummaryUpdateForm(data=data, project=self.project)

        self.assertFalse(form.is_valid())
        self.assertIn("Outcome notes has invalid inline formatting", str(form.errors))
        self.assertIn("matching closing tag", str(form.errors))

    def test_outcomes_raw_accepts_legacy_p_value_column_without_storing_it(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "outcomes_raw": "Abundance | 12 | Treatment | 4 | Control | pairs | Higher | t=2.3 | 0.04 | Significant increase",
            },
            project=self.project,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["outcomes_raw"],
            [
                {
                    "outcome": "Abundance",
                    "treatment_value": "12",
                    "treatment": "Treatment",
                    "comparator_value": "4",
                    "comparator": "Control",
                    "unit": "pairs",
                    "difference": "Higher",
                    "stats": "t=2.3",
                    "notes": "Significant increase",
                }
            ],
        )

    def test_outcomes_raw_initial_omits_legacy_p_value_column(self):
        batch = ReferenceSourceBatch.objects.create(
            project=self.project,
            label="Legacy outcomes batch",
            source_type="journal_search",
        )
        reference = Reference.objects.create(
            project=self.project,
            batch=batch,
            hash_key="p" * 40,
            title="Legacy outcomes reference",
        )
        summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=reference,
            outcome_rows=[
                {
                    "outcome": "Abundance",
                    "treatment_value": "12",
                    "treatment": "Treatment",
                    "comparator_value": "4",
                    "comparator": "Control",
                    "unit": "pairs",
                    "difference": "Higher",
                    "stats": "t=2.3",
                    "p_value": "0.04",
                    "notes": "Significant increase",
                }
            ]
        )

        form = ReferenceSummaryUpdateForm(instance=summary, project=self.project)

        self.assertEqual(
            form["outcomes_raw"].value(),
            "Abundance | 12 | Treatment | 4 | Control | pairs | Higher | t=2.3 | Significant increase",
        )

    def test_structured_summary_paragraph_uses_free_text_outcome_notes(self):
        summary = ReferenceSummary(
            study_design="replicated study",
            summary_of_results="brush cutting improved habitat condition.",
            outcome_rows=[
                {"sentence": "Species richness increased after scrub removal"},
                {"sentence": "Breeding success stayed similar between treatments."},
            ],
        )

        paragraph = _structured_summary_paragraph(summary)

        self.assertIn("Species richness increased after scrub removal.", paragraph)
        self.assertIn("Breeding success stayed similar between treatments.", paragraph)

    def test_structured_summary_paragraph_excludes_quality_scores_from_text(self):
        summary = ReferenceSummary(
            study_design="replicated study",
            summary_of_results="brush cutting improved habitat condition.",
            benefits_score=80,
            harms_score=5,
            reliability_score=0.7,
            relevance_score=0.9,
        )

        paragraph = _structured_summary_paragraph(summary)

        self.assertNotIn("Benefits:", paragraph)
        self.assertNotIn("Harms:", paragraph)
        self.assertNotIn("Reliability:", paragraph)
        self.assertNotIn("Relevance:", paragraph)

    def test_structured_summary_paragraph_places_reference_number_after_country(self):
        summary = ReferenceSummary(
            study_design="replicated study",
            year_range="2018",
            habitat_and_sites="wetland sites",
            country="UK",
            sites_replications="12 sites",
            summary_of_results="installing nest boxes increased occupancy.",
        )

        paragraph = _structured_summary_paragraph(
            summary, reference_identifier_override="3"
        )

        self.assertIn("in UK (3) (12 sites) found that", paragraph)

    def test_structured_summary_paragraph_omits_legacy_p_value_text(self):
        summary = ReferenceSummary(
            study_design="replicated study",
            outcome_rows=[
                {
                    "outcome": "Abundance",
                    "difference": "Higher",
                    "treatment": "treatment plots",
                    "comparator": "control plots",
                    "p_value": "0.04",
                    "notes": "Significant increase",
                }
            ],
        )

        paragraph = _structured_summary_paragraph(summary)

        self.assertNotIn("p=0.04", paragraph)
        self.assertIn("Significant increase.", paragraph)

    def test_quality_scores_accept_boundary_values(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "benefits_score": "0",
                "harms_score": "100",
                "reliability_score": "0.0",
                "relevance_score": "1.0",
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["benefits_score"], 0.0)
        self.assertEqual(form.cleaned_data["harms_score"], 100.0)
        self.assertEqual(form.cleaned_data["reliability_score"], 0.0)
        self.assertEqual(form.cleaned_data["relevance_score"], 1.0)

    def test_structured_summary_fields_reject_invalid_inline_markup(self):
        form = ReferenceSummaryUpdateForm(
            data={
                "status": ReferenceSummary.STATUS_TODO,
                "summary_of_results": "CO<sup>2 increased.",
            },
            project=self.project,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Summary of results has invalid inline formatting", str(form.errors))
        self.assertIn("matching closing tag", str(form.errors))

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
                    },
                    project=self.project,
                )
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)


class ReferenceSummaryDetailViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="author", password="pass123")
        self.viewer = User.objects.create_user(username="viewer", password="pass123")
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

    def test_detail_page_is_forbidden_for_non_project_editors(self):
        self.client.login(username="viewer", password="pass123")

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_duplicate_summary_tab_is_forbidden_for_non_project_editors(self):
        self.client.login(username="viewer", password="pass123")

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {"action": "duplicate-summary-tab"},
            follow=False,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            ReferenceSummary.objects.filter(
                project=self.project,
                reference=self.reference,
            ).count(),
            1,
        )

    def test_detail_page_explains_local_citation_override_behaviour(self):
        self.client.login(username="author", password="pass123")

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, "Citation for synopsis export")
        self.assertContains(response, "Shared reference citation in use")
        self.assertContains(
            response,
            "does not update the shared reference database",
        )
        self.assertContains(
            response,
            "&lt;i&gt;...&lt;/i&gt; or &lt;em&gt;...&lt;/em&gt; for italics.",
            html=False,
        )

    def test_detail_page_shows_project_action_dropdown_options(self):
        self.project.saved_action_names = "Install nest boxes"
        self.project.save(update_fields=["saved_action_names"])

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(
            response,
            "Choose a saved project action or an existing intervention title.",
        )
        self.assertContains(
            response,
            "Manage saved action names on the Action List page.",
        )
        self.assertContains(response, '<option value="Install nest boxes">Install nest boxes</option>', html=False)

    def test_detail_page_warns_when_another_author_is_active_in_summary(self):
        other_author = User.objects.create_user(
            username="coauthor",
            password="pass123",
            first_name="Co",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")

        self.client.login(username="coauthor", password="pass123")
        self.client.post(
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            )
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, "Active author")
        self.assertContains(response, "You + Co Author")
        self.assertContains(response, "Co Author")
        self.assertContains(response, 'name="summary_revision_token"', html=False)
        self.assertContains(
            response,
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            ),
            html=False,
        )

    def test_detail_page_does_not_show_removed_assignment_warning_text(self):
        other_author = User.objects.create_user(
            username="assigned-author",
            password="pass123",
            first_name="Assigned",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")
        self.summary.assigned_to = other_author
        self.summary.save(update_fields=["assigned_to", "updated_at"])

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertNotContains(
            response,
            "This summary is currently assigned to Assigned Author.",
        )

    def test_summary_presence_endpoint_returns_active_participants(self):
        other_author = User.objects.create_user(
            username="coauthor",
            password="pass123",
            first_name="Co",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")

        self.client.login(username="coauthor", password="pass123")
        self.client.post(
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            )
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["current_user_active"])
        self.assertIn("Co Author", payload["other_participants"])
        self.assertIn("author", payload["participant_names"])

    def test_summary_presence_endpoint_rejects_get_requests(self):
        self.client.login(username="author", password="pass123")

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertEqual(response.status_code, 400)

    def test_detail_page_explains_optional_fields_and_custom_paragraph_mode(self):
        self.summary.synopsis_draft = "Manual paragraph text."
        self.summary.use_custom_synopsis_draft = True
        self.summary.save(
            update_fields=["synopsis_draft", "use_custom_synopsis_draft", "updated_at"]
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, "These fields do different jobs.")
        self.assertContains(response, "Usually expected")
        self.assertContains(response, "Classification")
        self.assertContains(response, "Writing aid")
        self.assertContains(response, "Internal")
        self.assertContains(
            response,
            "The final compiled text always comes from the summary paragraph below.",
        )
        self.assertContains(response, "Custom paragraph mode is active.")
        self.assertContains(
            response,
            "The summary paragraph is currently the source of truth for compilation and export.",
        )
        self.assertContains(response, "Custom paragraph in use")
        self.assertContains(response, "Save custom paragraph")
        self.assertContains(response, "Switch back to auto-generated")
        self.assertContains(response, "Clear saved custom paragraph")
        self.assertContains(response, "Internal notes on this paragraph")
        self.assertContains(response, "Save paragraph notes")
        self.assertContains(response, "Word count:")
        self.assertContains(response, 'data-summary-word-count', html=False)
        self.assertContains(response, "Use these tags to organise, filter and group summaries across the synopsis.")
        self.assertContains(response, "Stored separately for internal use. These scores are not inserted into the generated summary paragraph.")
        self.assertContains(response, "Outcome notes")
        self.assertContains(response, "Main findings summary")
        self.assertContains(response, "More optional detail boxes")
        self.assertContains(response, "Select all study design terms that apply.")
        self.assertContains(response, "0 selected")
        self.assertNotContains(response, "up to four")
        self.assertNotContains(response, "0 of 4 selected")

    def test_detail_page_shows_inline_formatting_preview_and_editor_hook(self):
        self.summary.synopsis_draft = (
            "A replicated study found that <i>Festuca</i> increased in the 10<sup>th</sup> plot."
        )
        self.summary.use_custom_synopsis_draft = True
        self.summary.save(
            update_fields=["synopsis_draft", "use_custom_synopsis_draft", "updated_at"]
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, "Current compiled paragraph")
        self.assertContains(response, "<i>Festuca</i>", html=False)
        self.assertContains(response, "10<sup>th</sup> plot.", html=False)
        self.assertContains(response, 'data-inline-markup="true"', html=False)
        self.assertContains(
            response,
            "&lt;sub&gt;...&lt;/sub&gt; for subscript, and &lt;sup&gt;...&lt;/sup&gt; for superscript.",
            html=False,
        )

    def test_creating_summary_tab_invalidates_board_presence_summary_id_cache(self):
        self.client.login(username="author", password="pass123")
        initial_ids = _project_reference_summary_ids(self.project.id)

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {"action": "create-summary-tab"},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        new_summary = (
            ReferenceSummary.objects.filter(project=self.project, reference=self.reference)
            .exclude(pk=self.summary.id)
            .get()
        )
        self.assertNotIn(new_summary.id, initial_ids)
        self.assertIn(new_summary.id, _project_reference_summary_ids(self.project.id))

    def test_save_summary_persists_changes(self):
        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        response = self.client.get(url)
        revision_token = response.context["summary_revision_token"]
        resp = self.client.post(
            url,
            {
                "action": "save-summary",
                "summary_revision_token": revision_token,
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
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference: Test reference", change.details)
        self.assertIn("Status: In progress", change.details)

    def test_save_summary_auto_moves_todo_tab_to_in_progress_when_content_saved(self):
        self.client.login(username="author", password="pass123")
        url = reverse(
            "synopsis:reference_summary_detail", args=[self.project.id, self.summary.id]
        )
        response = self.client.get(url)
        revision_token = response.context["summary_revision_token"]
        response = self.client.post(
            url,
            {
                "action": "save-summary",
                "summary_revision_token": revision_token,
                "status": ReferenceSummary.STATUS_TODO,
                "habitat_and_sites": "New habitat info",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.status, ReferenceSummary.STATUS_DRAFT)
        self.assertContains(
            response,
            "Status moved to In progress automatically.",
        )
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Workflow: Auto-moved from To summarise to In progress", change.details)

    def test_save_summary_can_store_selected_project_action(self):
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
        SynopsisIntervention.objects.create(
            subheading=subheading,
            title="Install nest boxes",
            position=1,
        )

        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        response = self.client.get(url)
        revision_token = response.context["summary_revision_token"]
        self.client.post(
            url,
            {
                "action": "save-summary",
                "summary_revision_token": revision_token,
                "status": ReferenceSummary.STATUS_DRAFT,
                "action_choice": "Install nest boxes",
                "action_custom": "",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.action_description, "Install nest boxes")

    def test_save_summary_rejects_stale_page_after_another_author_saves(self):
        other_author = User.objects.create_user(
            username="coauthor",
            password="pass123",
            first_name="Co",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")

        self.client.login(username="author", password="pass123")
        url = reverse(
            "synopsis:reference_summary_detail",
            args=[self.project.id, self.summary.id],
        )
        initial_response = self.client.get(url)
        revision_token = initial_response.context["summary_revision_token"]

        self.summary.habitat_and_sites = "Other author's newer text"
        self.summary.assigned_to = other_author
        self.summary.save(update_fields=["habitat_and_sites", "assigned_to", "updated_at"])

        response = self.client.post(
            url,
            {
                "action": "save-summary",
                "summary_revision_token": revision_token,
                "status": ReferenceSummary.STATUS_DRAFT,
                "habitat_and_sites": "My conflicting text",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.habitat_and_sites, "Other author's newer text")
        self.assertEqual(response.context["summary_revision_token"], revision_token)
        self.assertContains(response, "This summary changed after you opened the page.")
        self.assertContains(
            response,
            "Reload the page before saving so you do not overwrite newer work.",
        )
        self.assertContains(response, "It is currently assigned to Co Author.")
        self.assertContains(response, "My conflicting text")

        second_response = self.client.post(
            url,
            {
                "action": "save-summary",
                "summary_revision_token": response.context["summary_revision_token"],
                "status": ReferenceSummary.STATUS_DRAFT,
                "habitat_and_sites": "Second conflicting text",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.habitat_and_sites, "Other author's newer text")
        self.assertEqual(second_response.context["summary_revision_token"], revision_token)
        self.assertContains(
            second_response,
            "Reload the page before saving so you do not overwrite newer work.",
        )
        self.assertContains(second_response, "Second conflicting text")

    def test_summary_status_choices_include_excluded_after_full_text(self):
        labels = dict(ReferenceSummary.STATUS_CHOICES)
        self.assertIn(ReferenceSummary.STATUS_EXCLUDED, labels)
        self.assertEqual(
            labels[ReferenceSummary.STATUS_EXCLUDED],
            "Excluded after full text",
        )

    def test_save_summary_does_not_clear_saved_paragraph_draft(self):
        self.summary.synopsis_draft = "Edited summary paragraph."
        self.summary.use_custom_synopsis_draft = True
        self.summary.save(
            update_fields=["synopsis_draft", "use_custom_synopsis_draft", "updated_at"]
        )

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
        self.assertTrue(self.summary.use_custom_synopsis_draft)

    def test_save_summary_keeps_auto_generated_mode_and_current_paragraph_updates(self):
        self.summary.study_design = "replicated, controlled study"
        self.summary.year_range = "2018-2020"
        self.summary.summary_of_results = "installing nest boxes increased occupancy."
        self.summary.habitat_and_sites = "woodland sites"
        self.summary.country = "UK"
        self.summary.save(
            update_fields=[
                "study_design",
                "year_range",
                "summary_of_results",
                "habitat_and_sites",
                "country",
                "updated_at",
            ]
        )

        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        self.client.post(
            url,
            {
                "action": "save-summary",
                "status": ReferenceSummary.STATUS_DRAFT,
                "study_design": "replicated, controlled study",
                "year_range": "2018-2020",
                "summary_of_results": "installing nest boxes increased occupancy.",
                "habitat_and_sites": "wetland sites",
                "country": "UK",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        generated_after = _structured_summary_paragraph(self.summary)
        self.assertFalse(self.summary.use_custom_synopsis_draft)
        self.assertEqual(_reference_summary_paragraph(self.summary), generated_after)

    def test_save_summary_paragraph_draft_persists_changes(self):
        self.client.login(username="author", password="pass123")
        url = reverse("synopsis:reference_summary_detail", args=[self.project.id, self.summary.id])
        self.client.post(
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
        self.assertTrue(self.summary.use_custom_synopsis_draft)
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Custom summary paragraph saved",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference: Test reference", change.details)
        self.assertIn("Summary ID:", change.details)

    def test_switching_back_to_auto_generated_clears_custom_paragraph_mode(self):
        self.summary.study_design = "replicated study"
        self.summary.summary_of_results = "occupancy increased."
        self.summary.synopsis_draft = "Custom paragraph text."
        self.summary.use_custom_synopsis_draft = True
        self.summary.save(
            update_fields=[
                "study_design",
                "summary_of_results",
                "synopsis_draft",
                "use_custom_synopsis_draft",
                "updated_at",
            ]
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "save-synopsis-draft",
                "draft_command": "use-generated",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertFalse(self.summary.use_custom_synopsis_draft)
        self.assertEqual(self.summary.synopsis_draft, "")
        self.assertEqual(
            _reference_summary_paragraph(self.summary),
            _structured_summary_paragraph(self.summary),
        )
        self.assertContains(
            response,
            "Auto-generated paragraph restored.",
        )
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Auto-generated summary paragraph restored",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference: Test reference", change.details)

    def test_save_summary_paragraph_draft_auto_moves_todo_tab_to_in_progress(self):
        self.client.login(username="author", password="pass123")
        url = reverse(
            "synopsis:reference_summary_detail", args=[self.project.id, self.summary.id]
        )
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
        self.assertEqual(self.summary.status, ReferenceSummary.STATUS_DRAFT)
        self.assertContains(
            response,
            "Custom paragraph saved and set as the version used for compilation. Status moved to In progress automatically.",
        )

    def test_save_internal_paragraph_notes_persists_and_logs_history(self):
        self.client.login(username="author", password="pass123")
        url = reverse(
            "synopsis:reference_summary_detail",
            args=[self.project.id, self.summary.id],
        )
        response = self.client.post(
            url,
            {
                "action": "save-paragraph-notes",
                "paragraph_notes": "Yes, this is 10 species not 11; see Fig. 4.",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(
            self.summary.paragraph_notes,
            "Yes, this is 10 species not 11; see Fig. 4.",
        )
        self.assertContains(response, "Internal paragraph notes saved.")
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary paragraph notes saved",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference: Test reference", change.details)
        self.assertIn("Notes: Yes, this is 10 species not 11; see Fig. 4.", change.details)

        response = self.client.post(
            url,
            {
                "action": "save-paragraph-notes",
                "paragraph_notes": "",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.paragraph_notes, "")
        self.assertContains(response, "Internal paragraph notes cleared.")
        cleared_change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary paragraph notes cleared",
        ).first()
        self.assertIsNotNone(cleared_change)
        self.assertIn(
            "Previous notes: Yes, this is 10 species not 11; see Fig. 4.",
            cleared_change.details,
        )

    def test_detail_status_update_requires_reason_for_summary_phase_exclusion(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        self.client.login(username="author", password="pass123")

        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-status",
                "status": ReferenceSummary.STATUS_EXCLUDED,
                "needs_help": "",
                "exclusion_reason": "",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.status, ReferenceSummary.STATUS_TODO)
        self.assertContains(
            response,
            "Provide a reason before excluding this summary after full-text review.",
        )

    def test_detail_status_exclusion_removes_only_that_summary_from_synopsis(self):
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
                "action": "update-status",
                "status": ReferenceSummary.STATUS_EXCLUDED,
                "needs_help": "",
                "exclusion_reason": "Full text shows this is not an intervention study.",
            },
            follow=True,
        )

        self.summary.refresh_from_db()
        key_message.refresh_from_db()
        self.assertEqual(self.summary.status, ReferenceSummary.STATUS_EXCLUDED)
        self.assertEqual(
            self.summary.exclusion_reason,
            "Full text shows this is not an intervention study.",
        )
        self.assertFalse(SynopsisAssignment.objects.filter(pk=assignment.id).exists())
        self.assertEqual(key_message.supporting_summaries.count(), 0)
        self.assertContains(
            response,
            "Summary excluded after full-text review.",
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(
            any("excluded after full-text review" in str(m).lower() for m in messages)
        )
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary excluded after full-text review",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Exclusion reason: Full text shows this is not an intervention study.", change.details)
        self.assertIn("Removed from intervention assignments: 1", change.details)

    def test_saved_summary_paragraph_draft_is_used_for_compilation(self):
        self.summary.reference_identifier = "CR1000"
        self.summary.synopsis_draft = "A revised paragraph (CR1000) with edited wording."
        self.summary.use_custom_synopsis_draft = True
        self.summary.save(
            update_fields=[
                "reference_identifier",
                "synopsis_draft",
                "use_custom_synopsis_draft",
                "updated_at",
            ]
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
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary tab created",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Source summary: manual-summary", change.details)

    def test_duplicate_summary_tab_copies_current_summary_content(self):
        self.summary.assigned_to = self.user
        self.summary.status = ReferenceSummary.STATUS_DONE
        self.summary.reference_identifier = "manual-ref"
        self.summary.summary_identifier = "manual-summary"
        self.summary.reference_label = "Test reference label"
        self.summary.action_description = "Install nest boxes"
        self.summary.study_design = "Replicated study"
        self.summary.summary_of_results = "Occupancy increased."
        self.summary.action_methods = "Installed wooden boxes."
        self.summary.outcome_rows = [{"outcome": "Occupancy", "notes": "Higher"}]
        self.summary.synopsis_draft = "Draft paragraph copied from the first tab."
        self.summary.use_custom_synopsis_draft = True
        self.summary.paragraph_notes = "Check whether this was really replicated."
        self.summary.summary_author = "Existing Author"
        self.summary.keywords = ["boxes", "occupancy"]
        self.summary.action_tags = ["Land/water protection-Area protection"]
        self.summary.habitat_tags = ["Marine Coral Reefs", "Artificial - Urban Areas"]
        self.summary.research_design = "Replicated; Controlled*"
        self.summary.citation = "Author (2024)"
        self.summary.save()

        self.client.login(username="author", password="pass123")
        url = reverse(
            "synopsis:reference_summary_detail", args=[self.project.id, self.summary.id]
        )
        resp = self.client.post(
            url,
            {"action": "duplicate-summary-tab"},
            follow=False,
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
        self.assertEqual(new_summary.assigned_to, self.user)
        self.assertEqual(new_summary.status, ReferenceSummary.STATUS_DRAFT)
        self.assertEqual(new_summary.reference_identifier, "manual-ref")
        self.assertEqual(new_summary.summary_identifier, "manual-ref.a")
        self.assertEqual(new_summary.reference_label, "Test reference label")
        self.assertEqual(new_summary.action_description, "Install nest boxes")
        self.assertEqual(new_summary.study_design, "Replicated study")
        self.assertEqual(new_summary.summary_of_results, "Occupancy increased.")
        self.assertEqual(new_summary.action_methods, "Installed wooden boxes.")
        self.assertEqual(new_summary.outcome_rows, [{"outcome": "Occupancy", "notes": "Higher"}])
        self.assertEqual(
            new_summary.synopsis_draft,
            "Draft paragraph copied from the first tab.",
        )
        self.assertTrue(new_summary.use_custom_synopsis_draft)
        self.assertEqual(
            new_summary.paragraph_notes,
            "Check whether this was really replicated.",
        )
        self.assertEqual(new_summary.summary_author, "Existing Author")
        self.assertEqual(new_summary.keywords, ["boxes", "occupancy"])
        self.assertEqual(
            new_summary.action_tags,
            ["Land/water protection - 1.1 Site/area protection"],
        )
        self.assertEqual(
            new_summary.habitat_tags,
            [
                "Marine-Coral Reefs",
                "Artificial Habitats-Built-up Areas",
            ],
        )
        self.assertEqual(new_summary.research_design, "Replicated; Controlled*")
        self.assertEqual(new_summary.citation, "Author (2024)")
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary tab duplicated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Copied from summary: manual-summary", change.details)

    def test_duplicate_summary_tab_does_not_copy_comments_assignments_or_exclusion_state(self):
        self.summary.status = ReferenceSummary.STATUS_EXCLUDED
        self.summary.needs_help = True
        self.summary.exclusion_reason = "Not really an intervention."
        self.summary.save(update_fields=["status", "needs_help", "exclusion_reason", "updated_at"])
        ReferenceSummaryComment.objects.create(
            summary=self.summary,
            author=self.user,
            body="Keep this note on the original tab only.",
        )
        ReferenceActionSummary.objects.create(
            reference_summary=self.summary,
            action_name="Install nest boxes",
            summary_text="Action-specific wording.",
            created_by=self.user,
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
        SynopsisAssignment.objects.create(
            intervention=intervention,
            reference_summary=self.summary,
            position=1,
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {"action": "duplicate-summary-tab"},
            follow=True,
        )

        duplicated = (
            ReferenceSummary.objects.filter(project=self.project, reference=self.reference)
            .exclude(pk=self.summary.id)
            .get()
        )
        self.assertEqual(duplicated.status, ReferenceSummary.STATUS_DRAFT)
        self.assertFalse(duplicated.needs_help)
        self.assertEqual(duplicated.exclusion_reason, "")
        self.assertEqual(duplicated.comments.count(), 0)
        self.assertEqual(duplicated.action_summaries.count(), 0)
        self.assertEqual(duplicated.synopsis_assignments.count(), 0)
        self.assertContains(
            response,
            "Summary tab duplicated. Review the copied text and adjust it for the new intervention or study summary.",
        )

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
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Summary tab deleted",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Next active summary: CR1000.a", change.details)

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
                "classification_command": "save",
                "screening_status": "included",
                "reference_folder": ["3a"],
                "screening_notes": "Freshwater fish evidence.",
            },
            follow=True,
        )

        self.reference.refresh_from_db()
        self.assertEqual(self.reference.screening_status, "included")
        self.assertEqual(self.reference.unlinked_reference_folder, ["3a"])
        self.assertEqual(self.reference.category_values, ["3a"])
        self.assertEqual(self.reference.screening_notes, "Freshwater fish evidence.")
        self.assertContains(response, "Reference classification updated.")
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Reference classification updated",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Reference: Test reference", change.details)
        self.assertIn("Summary ID:", change.details)
        self.assertIn("Notes: Freshwater fish evidence.", change.details)

    def test_summary_detail_folder_update_updates_shared_library_reference(self):
        canonical = LibraryReference.objects.create(
            title="Canonical library title",
            authors="Alhas, Ibrahim",
            publication_year=2024,
            hash_key="summary-shared-sync",
            reference_folder=["2"],
        )
        self.reference.library_reference = canonical
        self.reference.hash_key = "summary-shared-sync"
        self.reference.screening_status = "included"
        self.reference.save(
            update_fields=[
                "library_reference",
                "hash_key",
                "screening_status",
                "updated_at",
            ]
        )
        other_project = Project.objects.create(title="Other project")
        other_batch = ReferenceSourceBatch.objects.create(
            project=other_project,
            label="Other batch",
            source_type="library_link",
        )
        other_reference = Reference.objects.create(
            project=other_project,
            batch=other_batch,
            library_reference=canonical,
            hash_key="summary-shared-sync",
            title="Other project copy",
        )

        self.client.login(username="author", password="pass123")
        response = self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "update-classification",
                "classification_command": "save",
                "screening_status": "included",
                "reference_folder": ["15", "2"],
                "screening_notes": "Freshwater fish evidence.",
            },
            follow=True,
        )

        canonical.refresh_from_db()
        self.reference.refresh_from_db()
        other_reference.refresh_from_db()
        self.assertEqual(canonical.reference_folder, ["2", "15"])
        self.assertEqual(self.reference.unlinked_reference_folder, [])
        self.assertEqual(self.reference.category_values, ["2", "15"])
        self.assertEqual(other_reference.unlinked_reference_folder, [])
        self.assertEqual(other_reference.category_values, ["2", "15"])
        self.assertContains(
            response,
            "Shared CE subject categories were updated for all linked synopsis copies.",
        )
        self.assertTrue(
            LibraryReferenceFolderHistory.objects.filter(
                library_reference=canonical,
                new_folders=["2", "15"],
                source_project=self.project,
                source_reference=self.reference,
                change_source="summary_reference_management",
            ).exists()
        )

    def test_summary_detail_uses_shared_categories_when_local_fallback_exists(self):
        canonical = LibraryReference.objects.create(
            title="Canonical library title",
            authors="Alhas, Ibrahim",
            publication_year=2024,
            hash_key="summary-shared-read",
            reference_folder=["2", "15"],
        )
        self.reference.library_reference = canonical
        self.reference.hash_key = "summary-shared-read"
        self.reference.screening_status = "included"
        self.reference.unlinked_reference_folder = ["3a"]
        self.reference.save(
            update_fields=[
                "library_reference",
                "hash_key",
                "screening_status",
                "unlinked_reference_folder",
                "updated_at",
            ]
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        classification_form = response.context["classification_form"]
        self.assertEqual(
            classification_form.initial["reference_folder"],
            ["2", "15"],
        )
        self.assertContains(response, 'option value="2" selected')
        self.assertContains(response, 'option value="15" selected')

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
                "classification_command": "save",
                "screening_status": "included",
                "reference_folder": ["", "3a"],
                "screening_notes": "Freshwater fish evidence.",
            },
            follow=True,
        )

        self.reference.refresh_from_db()
        self.assertEqual(self.reference.unlinked_reference_folder, ["3a"])
        self.assertEqual(self.reference.category_values, ["3a"])
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
                "classification_command": "exclude",
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
                "classification_command": "exclude",
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
            f"{reverse('synopsis:reference_summary_detail', args=[self.project.id, self.summary.id])}?panel=management",
            fetch_redirect_response=False,
        )
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Reference excluded from synopsis",
        ).first()
        self.assertIsNotNone(change)
        self.assertIn("Removed from intervention assignments: 1", change.details)

    def test_summary_detail_reference_management_panel_reopens_after_classification_update(self):
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
                "classification_command": "exclude",
                "screening_status": "excluded",
                "reference_folder": ["3a"],
                "screening_notes": "Not relevant to this synopsis.",
            },
            follow=True,
        )

        self.assertContains(response, "Re-include this reference")
        self.assertTrue(response.context["open_management_panel"])
        self.assertContains(response, "Reference excluded from this synopsis.")

    def test_project_hub_shows_summary_audit_entries(self):
        self.client.login(username="author", password="pass123")
        self.client.post(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            ),
            {
                "action": "save-summary",
                "status": ReferenceSummary.STATUS_DRAFT,
                "habitat_and_sites": "New habitat info",
            },
            follow=True,
        )

        response = self.client.get(
            reverse("synopsis:project_hub", args=[self.project.id])
        )

        self.assertContains(response, "Summary saved")
        self.assertContains(response, "Reference: Test reference")

    def test_reference_management_explains_difference_between_summary_and_reference_exclusion(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status", "updated_at"])
        self.summary.status = ReferenceSummary.STATUS_EXCLUDED
        self.summary.exclusion_reason = "Full text exclusion reason."
        self.summary.save(update_fields=["status", "exclusion_reason", "updated_at"])
        self.client.login(username="author", password="pass123")

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(
            response,
            "All summary tabs for this reference are excluded after full-text review, but the whole reference is still marked as included for this synopsis.",
        )
        self.assertContains(response, "Exclude whole reference from synopsis too")
        self.assertContains(
            response,
            "Shared CE subject categories are stored on the reference, not on this individual summary tab.",
        )
        self.assertContains(
            response,
            "changing them here updates the shared reference record and is reflected everywhere it is linked",
        )

    def test_summary_detail_renders_restore_state_hooks(self):
        self.client.login(username="author", password="pass123")

        response = self.client.get(
            reverse(
                "synopsis:reference_summary_detail",
                args=[self.project.id, self.summary.id],
            )
        )

        self.assertContains(response, 'id="reference-summary-page"', html=False)
        self.assertContains(response, "cePreservePageState({", html=False)
        self.assertContains(
            response,
            f'"reference-summary-state-{self.project.id}-{self.summary.id}"',
            html=False,
        )
        self.assertContains(response, "managementPanelOpen", html=False)
        self.assertContains(response, "uploadForm.requestSubmit()", html=False)

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
                "excluded_after_full_text": row["excluded_after_full_text"],
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
                "excluded_after_full_text": 0,
            },
        )
        self.assertEqual(
            workload[other_author.id],
            {
                "assigned": 1,
                "summarised": 0,
                "summarised_percent": 0,
                "needs_help": 0,
                "excluded_after_full_text": 0,
            },
        )
        self.assertEqual(response.context["unassigned_count"], 0)
        self.assertEqual(response.context["needs_help_count"], 1)

    def test_summary_board_shows_active_editor_badge_for_active_summary(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status"])

        other_author = User.objects.create_user(
            username="coauthor",
            password="pass123",
            first_name="Co",
            last_name="Author",
        )
        UserRole.objects.create(user=other_author, project=self.project, role="author")

        self.client.login(username="coauthor", password="pass123")
        self.client.post(
            reverse(
                "synopsis:reference_summary_presence",
                args=[self.project.id, self.summary.id],
            )
        )

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse("synopsis:reference_summary_board", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active now")
        self.assertContains(response, "Co Author")
        self.assertContains(
            response,
            reverse("synopsis:reference_summary_board_presence", args=[self.project.id]),
            html=False,
        )

    def test_summary_board_shows_excluded_column_reason_and_progress_ignores_excluded(self):
        self.reference.screening_status = "included"
        self.reference.save(update_fields=["screening_status"])
        second_reference = Reference.objects.create(
            project=self.project,
            batch=self.batch,
            hash_key="d" * 40,
            title="Excluded summary reference",
            screening_status="included",
        )
        second_summary = ReferenceSummary.objects.create(
            project=self.project,
            reference=second_reference,
            assigned_to=self.user,
            status=ReferenceSummary.STATUS_EXCLUDED,
            exclusion_reason="Full text did not test a conservation intervention.",
        )
        self.summary.status = ReferenceSummary.STATUS_DONE
        self.summary.save(update_fields=["status", "updated_at"])

        self.client.login(username="author", password="pass123")
        response = self.client.get(
            reverse("synopsis:reference_summary_board", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excluded after full text")
        self.assertContains(response, 'class="summary-board-scroll pb-4"', html=False)
        self.assertContains(response, 'class="summary-board-row"', html=False)
        self.assertContains(response, 'class="summary-board-column"', html=False)
        self.assertNotContains(response, "Jump to excluded after full text")
        self.assertContains(
            response,
            "Full text did not test a conservation intervention.",
        )
        self.assertContains(response, "1 excluded after full text")
        self.assertEqual(response.context["excluded_after_full_text_count"], 1)
        self.assertEqual(response.context["summary_count"], 1)
        self.assertEqual(response.context["completed"], 1)
        workload = {row["author"].id: row for row in response.context["workload"]}
        self.assertEqual(workload[self.user.id]["excluded_after_full_text"], 1)


class GlobalReferenceLibraryAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="authorlib", password="pass123")
        self.project = Project.objects.create(title="Coral Project")
        self.other_project = Project.objects.create(title="Unassigned Project")
        UserRole.objects.create(user=self.user, project=self.project, role="author")

    @override_settings(APP_RELEASE_LABEL="v1.0.0")
    def test_author_sees_global_library_entry_points(self):
        self.client.login(username="authorlib", password="pass123")

        dashboard_response = self.client.get(reverse("synopsis:dashboard"))
        project_response = self.client.get(
            reverse("synopsis:project_hub", args=[self.project.id])
        )

        self.assertContains(dashboard_response, "Build")
        self.assertContains(
            dashboard_response,
            '<span class="ce-build-label">Build <code>v1.0.0</code></span>',
            html=False,
        )
        self.assertNotContains(
            dashboard_response,
            '<p class="small text-muted text-end mt-4 mb-0">Build:',
            html=False,
        )
        self.assertContains(dashboard_response, "Shared Reference Library")
        self.assertContains(dashboard_response, "Create New Synopsis")
        self.assertNotContains(dashboard_response, "How this works for authors")
        self.assertNotContains(
            dashboard_response,
            "This sits above individual synopses and can be used to link references into project batches.",
        )
        self.assertContains(dashboard_response, "Coral Project")
        self.assertContains(dashboard_response, "Unassigned Project")
        self.assertNotContains(project_response, "Create New Synopsis")
        self.assertContains(project_response, "Browse Shared Reference Library")
        self.assertContains(
            project_response,
            reverse("synopsis:reference_library") + f"?project={self.project.id}",
            html=False,
        )

    @override_settings(APP_RELEASE_LABEL="")
    def test_dashboard_hides_empty_release_label(self):
        self.client.login(username="authorlib", password="pass123")

        response = self.client.get(reverse("synopsis:dashboard"))

        self.assertNotContains(response, '<span class="ce-build-label">Build <code>')
        self.assertNotContains(response, "unlabelled build")

    def test_templates_without_nav_actions_also_hide_build_label(self):
        templates_dir = settings.BASE_DIR / "templates" / "synopsis"
        offenders = []
        for template_path in templates_dir.rglob("*.html"):
            template_source = template_path.read_text(encoding="utf-8")
            if (
                "{% block nav_actions %}{% endblock %}" in template_source
                and "{% block build_label %}{% endblock %}" not in template_source
            ):
                offenders.append(str(template_path.relative_to(templates_dir)))

        self.assertEqual(offenders, [])

    def test_author_can_open_unassigned_synopsis(self):
        self.client.login(username="authorlib", password="pass123")

        response = self.client.get(
            reverse("synopsis:project_hub", args=[self.other_project.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unassigned Project")

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


class ExternalAuthorAccessTests(TestCase):
    def setUp(self):
        ensure_global_groups()
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(
            username="external@example.com",
            email="external@example.com",
            password="pass123",
        )
        self.user.groups.add(Group.objects.get(name="external_collaborator"))
        self.assigned_project = Project.objects.create(title="Assigned Synopsis")
        self.unassigned_project = Project.objects.create(title="Hidden Synopsis")
        UserRole.objects.create(
            user=self.user, project=self.assigned_project, role="author"
        )

    def _docx_upload(self, name, content):
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_external_author_dashboard_only_shows_assigned_synopses(self):
        self.client.login(username="external@example.com", password="pass123")

        response = self.client.get(reverse("synopsis:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assigned Synopsis")
        self.assertNotContains(response, "Hidden Synopsis")
        self.assertNotContains(response, "Open Shared Reference Library")
        self.assertNotContains(response, "Shared Reference Library")
        self.assertNotContains(response, "Create New Synopsis")

    def test_external_author_cannot_create_synopsis_or_open_reference_library(self):
        self.client.login(username="external@example.com", password="pass123")

        create_response = self.client.get(reverse("synopsis:project_create"), follow=True)
        library_response = self.client.get(reverse("synopsis:reference_library"))

        self.assertRedirects(create_response, reverse("synopsis:dashboard"))
        self.assertContains(
            create_response,
            "External author accounts cannot create new synopses.",
        )
        self.assertEqual(library_response.status_code, 403)

    def test_external_author_can_open_assigned_synopsis_only(self):
        self.client.login(username="external@example.com", password="pass123")

        assigned_response = self.client.get(
            reverse("synopsis:project_hub", args=[self.assigned_project.id])
        )
        unassigned_response = self.client.get(
            reverse("synopsis:project_hub", args=[self.unassigned_project.id]),
            follow=True,
        )

        self.assertEqual(assigned_response.status_code, 200)
        self.assertNotContains(assigned_response, "Browse Shared Reference Library")
        self.assertNotContains(assigned_response, "Project settings")
        self.assertNotContains(assigned_response, "Manage phase tracker")
        self.assertNotContains(assigned_response, "Move to ")
        self.assertRedirects(unassigned_response, reverse("synopsis:dashboard"))
        self.assertContains(
            unassigned_response,
            "You do not have access to that synopsis.",
        )

    def test_external_author_cannot_open_project_settings(self):
        self.client.login(username="external@example.com", password="pass123")

        response = self.client.get(
            reverse("synopsis:project_settings", args=[self.assigned_project.id]),
            follow=True,
        )

        self.assertRedirects(
            response, reverse("synopsis:project_hub", args=[self.assigned_project.id])
        )
        self.assertContains(
            response,
            "You do not have permission to update project settings for this synopsis.",
        )

    def test_external_author_project_reference_page_hides_library_buttons(self):
        self.client.login(username="external@example.com", password="pass123")

        response = self.client.get(
            reverse("synopsis:reference_batch_list", args=[self.assigned_project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import RIS")
        self.assertNotContains(response, "Link from library")
        self.assertNotContains(response, "Browse library")

    def test_external_author_cannot_delete_protocol_or_action_list_documents(self):
        protocol = Protocol.objects.create(
            project=self.assigned_project,
            document=self._docx_upload("protocol.docx", b"protocol"),
        )
        action_list = ActionList.objects.create(
            project=self.assigned_project,
            document=self._docx_upload("action-list.docx", b"action-list"),
        )
        self.client.login(username="external@example.com", password="pass123")

        protocol_page = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.assigned_project.id])
        )
        action_list_page = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.assigned_project.id])
        )
        protocol_delete_response = self.client.post(
            reverse("synopsis:protocol_delete_file", args=[self.assigned_project.id]),
            follow=True,
        )
        action_delete_response = self.client.post(
            reverse(
                "synopsis:action_list_delete_file", args=[self.assigned_project.id]
            ),
            follow=True,
        )

        self.assertNotContains(protocol_page, "Danger zone")
        self.assertNotContains(action_list_page, "Danger zone")
        self.assertRedirects(
            protocol_delete_response,
            reverse("synopsis:protocol_detail", args=[self.assigned_project.id]),
        )
        self.assertContains(
            protocol_delete_response,
            "You do not have permission to delete protocol files for this synopsis.",
        )
        self.assertRedirects(
            action_delete_response,
            reverse("synopsis:action_list_detail", args=[self.assigned_project.id]),
        )
        self.assertContains(
            action_delete_response,
            "You do not have permission to delete action list files for this synopsis.",
        )
        protocol.refresh_from_db()
        action_list.refresh_from_db()
        self.assertTrue(protocol.document)
        self.assertTrue(action_list.document)

    def test_external_author_cannot_mark_completed_or_reactivate_completed_synopsis(self):
        self.assigned_project.status = "completed"
        self.assigned_project.save(update_fields=["status"])
        self.client.login(username="external@example.com", password="pass123")

        dashboard_response = self.client.get(reverse("synopsis:dashboard"))
        direct_post_response = self.client.post(
            reverse("synopsis:project_settings", args=[self.assigned_project.id]),
            {"status_action": "reactivate", "return_to": "dashboard"},
            follow=True,
        )

        self.assertContains(dashboard_response, "Assigned Synopsis")
        self.assertNotContains(dashboard_response, "Move to active")
        self.assertRedirects(
            direct_post_response,
            reverse("synopsis:project_hub", args=[self.assigned_project.id]),
        )
        self.assertContains(
            direct_post_response,
            "You do not have permission to update project settings for this synopsis.",
        )
        self.assigned_project.refresh_from_db()
        self.assertEqual(self.assigned_project.status, "completed")
