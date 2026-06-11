"""OnlyOffice, collaborative editing, and document revision tests."""

from .common import *


class OnlyOfficeDownloadTests(TestCase):
    def setUp(self):
        from .. import views

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
        from .. import views

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
        from .. import views

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

    @patch("synopsis.views._download_onlyoffice_file", return_value=b"updated-doc")
    def test_collaborative_save_keeps_clean_filename_from_current_revision(self, mock_download):
        revision = ProtocolRevision.objects.create(
            protocol=self.protocol,
            file=SimpleUploadedFile(
                "protocol.docx",
                b"original-doc",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            stage="draft",
            original_name="protocol.docx",
            uploaded_by=self.manager,
            file_size=len(b"original-doc"),
        )
        self.protocol.current_revision = revision
        self.protocol.document.name = (
            f"protocols/{self.project.id}/"
            "11111111-1111-1111-1111-111111111111_"
            "22222222-2222-2222-2222-222222222222_protocol.docx"
        )
        self.protocol.save(update_fields=["current_revision", "document"])

        session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.manager,
            last_activity_at=timezone.now(),
            initial_protocol_revision=revision,
        )

        success = self.views._handle_collaborative_save(
            self.project,
            CollaborativeSession.DOCUMENT_PROTOCOL,
            self.protocol,
            session,
            {"url": "https://onlyoffice.example.com/office/storage/protocol.docx"},
            2,
        )

        self.assertTrue(success)
        self.protocol.refresh_from_db()
        self.assertEqual(self.protocol.current_revision.original_name, "protocol.docx")
        self.assertNotIn(
            "22222222-2222-2222-2222-222222222222_protocol.docx",
            self.protocol.current_revision.original_name,
        )
        self.assertTrue(self.protocol.document.name.endswith("_protocol.docx"))
        self.assertNotIn(
            "11111111-1111-1111-1111-111111111111_22222222-2222-2222-2222-222222222222_protocol.docx",
            self.protocol.document.name,
        )
        mock_download.assert_called_once()

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
        from .. import views

        self.views = views
        self.original_settings = views.ONLYOFFICE_SETTINGS
        views.ONLYOFFICE_SETTINGS = {
            "base_url": "https://onlyoffice.example.com/office",
            "callback_timeout": 7,
        }
        self.addCleanup(self._restore_settings)

        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

        self.project = Project.objects.create(title="Ibrahim Protocol Pilot")
        self.ibrahim = User.objects.create_user(username="ibrahim", password="pw")
        UserRole.objects.create(user=self.ibrahim, project=self.project, role="author")
        self.client.force_login(self.ibrahim)

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    def _docx_upload(self, name, content):
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_initial_protocol_upload_creates_revision_and_redirects(self):
        response = self.client.post(
            reverse("synopsis:protocol_detail", args=[self.project.id]),
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1.0",
                "document": self._docx_upload("ibrahim-protocol.docx", b"protocol"),
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

    def test_protocol_can_reupload_same_filename_after_delete_file(self):
        detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])

        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"first"),
            },
        )
        protocol = Protocol.objects.get(project=self.project)
        original_document_path = protocol.document.name
        original_revision_id = protocol.current_revision_id

        response = self.client.post(
            reverse("synopsis:protocol_delete_file", args=[self.project.id])
        )
        self.assertRedirects(response, detail_url)
        protocol.refresh_from_db()
        self.assertFalse(protocol.document)
        self.assertIsNone(protocol.current_revision)

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "Replacing deleted draft",
                "version_label": "v2",
                "document": self._docx_upload("draft-protocol.docx", b"second"),
            },
        )
        self.assertRedirects(response, detail_url)

        protocol.refresh_from_db()
        self.assertTrue(protocol.document)
        self.assertNotEqual(protocol.document.name, original_document_path)
        self.assertIsNotNone(protocol.current_revision)
        self.assertNotEqual(protocol.current_revision_id, original_revision_id)
        self.assertEqual(protocol.current_revision.original_name, "draft-protocol.docx")
        self.assertEqual(protocol.current_revision.version_label, "v2")
        self.assertEqual(ProtocolRevision.objects.filter(protocol=protocol).count(), 2)

    def test_protocol_missing_file_after_delete_shows_clear_error(self):
        detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"first"),
            },
        )
        self.client.post(reverse("synopsis:protocol_delete_file", args=[self.project.id]))

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Choose a protocol file to upload. You can reuse the same filename as a file you deleted.",
        )

    def test_action_list_can_reupload_same_filename_after_delete_file(self):
        detail_url = reverse("synopsis:action_list_detail", args=[self.project.id])

        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"first"),
            },
        )
        action_list = ActionList.objects.get(project=self.project)
        original_document_path = action_list.document.name
        original_revision_id = action_list.current_revision_id

        response = self.client.post(
            reverse("synopsis:action_list_delete_file", args=[self.project.id])
        )
        self.assertRedirects(response, detail_url)
        action_list.refresh_from_db()
        self.assertFalse(action_list.document)
        self.assertIsNone(action_list.current_revision)

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "Replacing deleted draft",
                "version_label": "v2",
                "document": self._docx_upload("draft-action-list.docx", b"second"),
            },
        )
        self.assertRedirects(response, detail_url)

        action_list.refresh_from_db()
        self.assertTrue(action_list.document)
        self.assertNotEqual(action_list.document.name, original_document_path)
        self.assertIsNotNone(action_list.current_revision)
        self.assertNotEqual(action_list.current_revision_id, original_revision_id)
        self.assertEqual(
            action_list.current_revision.original_name, "draft-action-list.docx"
        )
        self.assertEqual(action_list.current_revision.version_label, "v2")
        self.assertEqual(
            ActionListRevision.objects.filter(action_list=action_list).count(), 2
        )

    def test_action_list_missing_file_after_delete_shows_clear_error(self):
        detail_url = reverse("synopsis:action_list_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"first"),
            },
        )
        self.client.post(
            reverse("synopsis:action_list_delete_file", args=[self.project.id])
        )

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Choose an action list file to upload. You can reuse the same filename as a file you deleted.",
        )

    def test_current_document_links_use_download_current_document_labels(self):
        protocol_detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        action_list_detail_url = reverse(
            "synopsis:action_list_detail", args=[self.project.id]
        )
        project_hub_url = reverse("synopsis:project_hub", args=[self.project.id])

        self.client.post(
            protocol_detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"protocol"),
            },
        )
        self.client.post(
            action_list_detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"action"),
            },
        )

        project_hub_response = self.client.get(project_hub_url)
        protocol_detail_response = self.client.get(protocol_detail_url)
        action_list_detail_response = self.client.get(action_list_detail_url)

        protocol_view_url = reverse(
            "synopsis:document_view", args=[self.project.id, "protocol"]
        )
        action_list_view_url = reverse(
            "synopsis:document_view", args=[self.project.id, "action-list"]
        )

        self.assertContains(project_hub_response, protocol_view_url)
        self.assertContains(project_hub_response, action_list_view_url)
        self.assertContains(protocol_detail_response, protocol_view_url)
        self.assertContains(action_list_detail_response, action_list_view_url)
        self.assertContains(project_hub_response, "Download current document")
        self.assertContains(protocol_detail_response, "Download current document")
        self.assertContains(action_list_detail_response, "Download current document")
        self.assertNotContains(protocol_detail_response, "Open in new tab")
        self.assertNotContains(action_list_detail_response, "Open in new tab")

    def test_document_view_route_returns_latest_document_inline(self):
        protocol_detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        self.client.post(
            protocol_detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"protocol"),
            },
        )

        response = self.client.get(
            reverse("synopsis:document_view", args=[self.project.id, "protocol"])
        )
        protocol = Protocol.objects.get(project=self.project)
        expected_filename = protocol.document.name.rsplit("/", 1)[-1]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            f'inline; filename="{expected_filename}"',
        )
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(b"".join(response.streaming_content), b"protocol")

    def test_protocol_and_action_list_danger_zones_explain_permanent_deletion(self):
        protocol_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        action_list_url = reverse("synopsis:action_list_detail", args=[self.project.id])

        self.client.post(
            protocol_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"first"),
            },
        )
        self.client.post(
            action_list_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"first"),
            },
        )

        protocol_response = self.client.get(protocol_url)
        action_list_response = self.client.get(action_list_url)

        self.assertContains(protocol_response, "Danger zone: permanent deletion")
        self.assertContains(
            protocol_response,
            "These actions are final and destructive.",
        )
        self.assertContains(protocol_response, "Permanently delete file")
        self.assertContains(protocol_response, "Permanently delete protocol")
        self.assertContains(
            protocol_response,
            "This action is final and cannot be undone from the portal.",
        )

        self.assertContains(action_list_response, "Danger zone: permanent deletion")
        self.assertContains(
            action_list_response,
            "These actions are final and destructive.",
        )
        self.assertContains(action_list_response, "Permanently delete file")
        self.assertContains(action_list_response, "Permanently delete action list")
        self.assertContains(
            action_list_response,
            "This action is final and cannot be undone from the portal.",
        )

    def test_protocol_revision_history_uses_clear_current_and_earlier_sections(self):
        detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"first"),
            },
        )
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "Updated methods section",
                "version_label": "v2",
                "document": self._docx_upload("draft-protocol.docx", b"second"),
            },
        )

        response = self.client.get(detail_url)

        self.assertContains(response, "Current live version")
        self.assertContains(response, "Earlier saved versions")
        self.assertContains(response, "Working draft")
        self.assertContains(response, "Revision note:")
        self.assertContains(response, "Restore as current")
        self.assertContains(response, "Delete revision")

    def test_action_list_revision_history_uses_clear_current_and_earlier_sections(self):
        detail_url = reverse("synopsis:action_list_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"first"),
            },
        )
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "Added missing interventions",
                "version_label": "v2",
                "document": self._docx_upload("draft-action-list.docx", b"second"),
            },
        )

        response = self.client.get(detail_url)

        self.assertContains(response, "Current live version")
        self.assertContains(response, "Earlier saved versions")
        self.assertContains(response, "Working draft")
        self.assertContains(response, "Revision note:")
        self.assertContains(response, "Restore as current")
        self.assertContains(response, "Delete revision")

    def test_protocol_delete_closes_stale_collaborative_session_before_reupload(self):
        detail_url = reverse("synopsis:protocol_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-protocol.docx", b"first"),
            },
        )
        session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.ibrahim,
            last_activity_at=timezone.now(),
        )

        response = self.client.post(
            reverse("synopsis:protocol_delete", args=[self.project.id])
        )
        self.assertRedirects(
            response, reverse("synopsis:project_hub", args=[self.project.id])
        )
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertEqual(session.end_reason, "Protocol deleted")

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v2",
                "document": self._docx_upload("draft-protocol.docx", b"second"),
            },
        )
        self.assertRedirects(response, detail_url)

        response = self.client.get(detail_url)
        self.assertContains(response, "Open collaborative editor")
        self.assertNotContains(response, "Start collaborative edit")
        self.assertNotContains(response, '>Open editor<', html=False)

    def test_action_list_delete_closes_stale_collaborative_session_before_reupload(self):
        detail_url = reverse("synopsis:action_list_detail", args=[self.project.id])
        self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v1",
                "document": self._docx_upload("draft-action-list.docx", b"first"),
            },
        )
        session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_ACTION_LIST,
            started_by=self.ibrahim,
            last_activity_at=timezone.now(),
        )

        response = self.client.post(
            reverse("synopsis:action_list_delete", args=[self.project.id])
        )
        self.assertRedirects(
            response, reverse("synopsis:project_hub", args=[self.project.id])
        )
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertEqual(session.end_reason, "Action list deleted")

        response = self.client.post(
            detail_url,
            {
                "stage": "draft",
                "change_reason": "",
                "version_label": "v2",
                "document": self._docx_upload("draft-action-list.docx", b"second"),
            },
        )
        self.assertRedirects(response, detail_url)

        response = self.client.get(detail_url)
        self.assertContains(response, "Open collaborative editor")
        self.assertNotContains(response, "Start collaborative edit")
        self.assertNotContains(response, '>Open editor<', html=False)


class OnlyOfficeConfigTests(TestCase):
    def setUp(self):
        from .. import views

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


class OnlyOfficeExternalAccessTests(TestCase):
    def setUp(self):
        from .. import views

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

        self.project = Project.objects.create(title="External Collaboration")
        self.author = User.objects.create_user(username="external-author", password="pw")
        UserRole.objects.create(user=self.author, project=self.project, role="author")
        self.member = AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Asha",
            last_name="Reviewer",
            organisation="CE",
            email="asha@example.com",
            response="Y",
            participation_confirmed=True,
            feedback_on_protocol_deadline=timezone.now() + timedelta(days=7),
        )
        self.protocol = Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile(
                "external-protocol.docx",
                b"protocol",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        self.session = CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.author,
            last_activity_at=timezone.now(),
        )

    def _restore_settings(self):
        self.views.ONLYOFFICE_SETTINGS = self.original_settings

    def _editor_url(self, query):
        return (
            reverse(
                "synopsis:collaborative_edit",
                args=[self.project.id, "protocol", self.session.token],
            )
            + query
        )

    def test_anonymous_reviewer_can_open_editor_with_feedback_token(self):
        feedback = ProtocolFeedback.objects.create(
            project=self.project,
            member=self.member,
            email=self.member.email,
            feedback_deadline_at=self.member.feedback_on_protocol_deadline,
        )

        response = self.client.get(self._editor_url(f"?feedback={feedback.token}"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["editor_config"]["editorConfig"]["user"]["id"],
            f"abm:{self.member.id}",
        )
        self.assertFalse(response.context["editor_config"]["document"]["permissions"]["edit"])
        self.assertTrue(response.context["editor_config"]["document"]["permissions"]["comment"])
        self.assertFalse(response.context["editor_config"]["document"]["permissions"]["review"])
        self.assertContains(response, "Reviewing as")
        self.assertContains(response, "Asha Reviewer")
        self.assertContains(
            response,
            "To comment, highlight text and use the comment button in the toolbar.",
        )
        self.assertContains(
            response,
            "Authors will review your comments and decide whether to apply them.",
        )
        self.assertContains(
            response,
            "Comments save automatically while you work.",
        )
        self.assertContains(
            response,
            "Comments accepted until",
        )
        self.assertContains(
            response,
            _format_deadline(self.member.feedback_on_protocol_deadline),
        )
        self.assertContains(
            response,
            "Comment-only access",
        )
        self.assertContains(response, "Leave review page")
        self.assertContains(response, "reviewer-tab-lock-key")
        self.assertContains(
            response,
            "This review page is already open in another tab. Return to that tab or close it before opening another one.",
        )
        self.assertNotContains(response, "How collaborative editing works")

    def test_anonymous_reviewer_can_open_editor_with_invitation_token(self):
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=self.member,
            email=self.member.email,
            invited_by=self.author,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        self.session.invitations.add(invitation)

        response = self.client.get(
            self._editor_url(f"?invite={invitation.token}&member={self.member.id}")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["editor_config"]["editorConfig"]["user"]["id"],
            f"abm:{self.member.id}",
        )
        self.assertFalse(response.context["editor_config"]["document"]["permissions"]["edit"])
        self.assertTrue(response.context["editor_config"]["document"]["permissions"]["comment"])
        self.assertFalse(response.context["editor_config"]["document"]["permissions"]["review"])
        self.assertContains(response, "Comments accepted until")
        self.assertContains(response, "Leave review page")
        self.assertNotContains(response, "How collaborative editing works")

    def test_anonymous_reviewer_invitation_link_restarts_when_session_is_closed(self):
        invitation = AdvisoryBoardInvitation.objects.create(
            project=self.project,
            member=self.member,
            email=self.member.email,
            invited_by=self.author,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        self.session.invitations.add(invitation)
        original_token = self.session.token
        self.session.mark_inactive(reason="Closed for restart test")

        response = self.client.get(
            self._editor_url(f"?invite={invitation.token}&member={self.member.id}")
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(invitation.token), response["Location"])
        self.assertNotIn(str(original_token), response["Location"])
        new_session = CollaborativeSession.objects.get(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            is_active=True,
        )
        self.assertNotEqual(new_session.token, original_token)
        self.assertTrue(new_session.invitations.filter(pk=invitation.pk).exists())

    def test_anonymous_reviewer_feedback_link_restarts_when_session_expires(self):
        feedback = ProtocolFeedback.objects.create(
            project=self.project,
            member=self.member,
            email=self.member.email,
            feedback_deadline_at=self.member.feedback_on_protocol_deadline,
        )
        original_token = self.session.token
        self.session.last_activity_at = timezone.now() - timedelta(hours=5)
        self.session.save(update_fields=["last_activity_at"])

        response = self.client.get(self._editor_url(f"?feedback={feedback.token}"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(feedback.token), response["Location"])
        self.assertNotIn(str(original_token), response["Location"])
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)
        new_session = CollaborativeSession.objects.get(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            is_active=True,
        )
        self.assertNotEqual(new_session.token, original_token)

    def test_member_id_only_link_is_blocked_for_anonymous_users(self):
        response = self.client.get(self._editor_url(f"?member={self.member.id}"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "This older collaborative link is missing its secure review token.",
            status_code=403,
        )

    def test_project_author_can_open_editor_without_external_token(self):
        self.client.force_login(self.author)

        response = self.client.get(self._editor_url(""))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["editor_config"]["editorConfig"]["user"]["id"],
            str(self.author.id),
        )
        self.assertTrue(response.context["editor_config"]["document"]["permissions"]["edit"])
        self.assertTrue(response.context["editor_config"]["document"]["permissions"]["comment"])
        self.assertTrue(response.context["editor_config"]["document"]["permissions"]["review"])
        self.assertContains(response, "Back to protocol page")
        self.assertContains(
            response,
            "Back to the protocol page only leaves your own browser tab.",
        )
        self.assertContains(
            response,
            "Save current version and close shared editor",
        )
        self.assertContains(response, "Active in this document:")
        self.assertContains(response, "visibilitychange")
        self.assertContains(response, "startPresencePolling")
        self.assertNotContains(response, "reviewer-tab-lock-key")
        self.assertNotContains(response, "How collaborative editing works")
        self.assertNotContains(
            response,
            reverse(
                "synopsis:collaborative_force_end",
                args=[self.project.id, "protocol", self.session.token],
            ),
        )

    @patch(
        "synopsis.views._collaborative_active_participant_names",
        return_value=["Asha Reviewer", "external-author"],
    )
    def test_author_can_fetch_active_collaborative_participants(
        self, mock_active_names
    ):
        self.client.force_login(self.author)

        response = self.client.get(
            reverse(
                "synopsis:collaborative_presence",
                args=[self.project.id, "protocol", self.session.token],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"participants": ["Asha Reviewer", "external-author"]},
        )
        mock_active_names.assert_called_once_with(
            self.project,
            CollaborativeSession.DOCUMENT_PROTOCOL,
            self.session,
        )

    def test_anonymous_reviewer_can_leave_editor_without_closing_shared_session(self):
        feedback = ProtocolFeedback.objects.create(
            project=self.project,
            member=self.member,
            email=self.member.email,
            feedback_deadline_at=self.member.feedback_on_protocol_deadline,
        )

        response = self.client.get(
            reverse(
                "synopsis:collaborative_leave",
                args=[self.project.id, "protocol", self.session.token],
            )
            + f"?feedback={feedback.token}"
        )

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_active)
        self.assertContains(
            response,
            "You left the review page. This did not close the shared session for other participants.",
        )
        self.assertContains(response, "Reviewing as")
        self.assertContains(response, "Asha Reviewer")
        self.assertContains(response, "Comment-only access")
        self.assertContains(response, "Comments accepted until")
        self.assertContains(
            response, _format_deadline(self.member.feedback_on_protocol_deadline)
        )
        self.assertContains(response, "Reopen review page")
        self.assertContains(response, "Close this tab")


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
            "Protocol current version was saved and the shared editor was closed for everyone.",
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
            "Protocol had no unsaved changes. The shared editor was closed for everyone.",
            messages_list,
        )
        change = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Protocol collaborative session closed",
        ).latest("id")
        self.assertEqual(
            change.details,
            "No unsaved changes were waiting in OnlyOffice. | Reason: Close from portal",
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
        self.assertContains(
            response,
            "Sending the protocol for review happens on the Advisory Board page.",
        )
        self.assertContains(
            response,
            "When you are ready to send it to advisory board members, go to the Advisory Board page",
        )
        self.assertContains(response, "Go to Advisory Board")
        self.assertContains(
            response,
            "Sending the protocol to advisory board members is done from the <strong>Advisory Board</strong> page.",
        )
        self.assertContains(response, "How collaborative editing works")
        self.assertContains(
            response,
            "Use this guide for the live OnlyOffice session itself.",
        )
        self.assertContains(
            response, "Upload the protocol before opening the collaborative editor."
        )
        self.assertContains(response, "Open collaborative editor")
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
            response, "Upload the protocol before opening the collaborative editor."
        )
        self.assertContains(response, "Open collaborative editor")
        self.assertContains(
            response,
            'target="_blank"',
            html=False,
        )
        self.assertContains(
            response,
            'rel="noopener"',
            html=False,
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
        self.assertContains(
            response,
            "Sending the action list for review happens on the Advisory Board page.",
        )
        self.assertContains(
            response,
            "When you are ready to send it to advisory board members, go to the Advisory Board page",
        )
        self.assertContains(response, "Go to Advisory Board")
        self.assertContains(
            response,
            "Sending the action list to advisory board members is done from the <strong>Advisory Board</strong> page.",
        )
        self.assertContains(response, "How collaborative editing works")
        self.assertContains(
            response,
            "Use this guide for the live OnlyOffice session itself.",
        )
        self.assertContains(
            response, "Upload the action list before opening the collaborative editor."
        )
        self.assertContains(response, "Open collaborative editor")
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
            response, "Upload the action list before opening the collaborative editor."
        )
        self.assertContains(response, "Open collaborative editor")
        self.assertContains(
            response,
            'target="_blank"',
            html=False,
        )
        self.assertContains(
            response,
            'rel="noopener"',
            html=False,
        )

    def test_action_list_page_shows_saved_action_names_editor(self):
        self.project.saved_action_names = "Install nest boxes\nReduce grazing"
        self.project.save(update_fields=["saved_action_names"])

        response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )

        self.assertContains(response, "Saved action names for this synopsis")
        self.assertContains(
            response,
            "Manage the action names once here, then reuse them in the summary action dropdown",
        )
        self.assertContains(response, "Install nest boxes")
        self.assertContains(response, "Save action names")

    def test_action_list_page_saves_project_action_names(self):
        response = self.client.post(
            reverse("synopsis:action_list_detail", args=[self.project.id]),
            {
                "action": "save-action-names",
                "action_names_text": "Install nest boxes\n\ninstall nest boxes\nReduce grazing",
            },
            follow=True,
        )

        self.project.refresh_from_db()
        self.assertEqual(
            self.project.saved_action_names,
            "Install nest boxes\nReduce grazing",
        )
        self.assertContains(response, "Saved action names updated.")
        log = ProjectChangeLog.objects.filter(
            project=self.project,
            action="Action list action names updated",
        ).first()
        self.assertIsNotNone(log)
        self.assertIn("Saved action names: 2", log.details)

    def test_protocol_panel_active_session_explains_global_close_scope(self):
        from .. import views

        original_settings = views.ONLYOFFICE_SETTINGS
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
        self.addCleanup(lambda: setattr(views, "ONLYOFFICE_SETTINGS", original_settings))

        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        CollaborativeSession.objects.create(
            project=self.project,
            document_type=CollaborativeSession.DOCUMENT_PROTOCOL,
            started_by=self.user,
            last_activity_at=timezone.now(),
        )

        response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )

        self.assertContains(response, "Collaborative editor is live")
        self.assertContains(response, "Open collaborative editor")
        self.assertNotContains(response, "Start collaborative edit")
        self.assertNotContains(response, '>Open editor<', html=False)
        self.assertContains(response, "Save current version and close shared editor")
        self.assertContains(
            response,
            "Going back to the protocol page only leaves your own browser tab.",
        )
        self.assertContains(
            response,
            "Advisory review deadlines do not close author editing automatically.",
        )

    def test_protocol_change_log_formats_collaborative_entries_for_authors(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        ProjectChangeLog.objects.create(
            project=self.project,
            changed_by=self.user,
            action="Protocol updated via collaborative edit",
            details=(
                "Session: 123e4567-e89b-12d3-a456-426614174000 | "
                "Status: 6 | File: protocol-v2.docx | Users: collab-author | "
                "Size: 24.0 KB | Reason: Updated citations"
            ),
        )
        ProjectChangeLog.objects.create(
            project=self.project,
            changed_by=self.user,
            action="Protocol collaborative session closed",
            details="Session 123e4567-e89b-12d3-a456-426614174000 closed (status 3).",
        )

        response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )

        self.assertContains(response, "Collaborative revision saved")
        self.assertContains(response, "Edited by collab-author")
        self.assertContains(response, "Saved file: protocol-v2.docx")
        self.assertContains(
            response,
            "OnlyOffice reported the shared session closed without new saved changes.",
        )
        self.assertNotContains(response, "123e4567-e89b-12d3-a456-426614174000")

    def test_advisory_board_shows_custom_columns_button_and_not_document_feedback_windows(self):
        response = self.client.get(
            reverse("synopsis:advisory_board_list", args=[self.project.id])
        )
        self.assertContains(response, "Custom columns")
        self.assertContains(response, "Invitation &amp; synopsis deadlines")
        self.assertContains(
            response,
            "Use this modal for invitation response deadlines and synopsis feedback deadlines only.",
        )
        self.assertContains(response, "Protocol")
        self.assertContains(response, "Action list")
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
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pia",
            email="pia@example.com",
            response="Y",
            sent_protocol_at=timezone.now(),
        )
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Ali",
            email="ali@example.com",
            response="Y",
            sent_action_list_at=timezone.now(),
        )

        protocol_response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        self.assertContains(protocol_response, "Protocol feedback window")
        self.assertContains(protocol_response, "Save deadline for sent members")
        self.assertContains(
            protocol_response,
            "Feedback links stay open until each member's own saved deadline, or until you close the whole feedback window manually.",
        )
        self.assertContains(
            protocol_response,
            "Saving here updates all already-sent accepted members and does not send a new email immediately.",
        )
        self.assertContains(
            protocol_response,
            "Members see this note only after the protocol feedback window has been closed. It is not used for reminder or deadline-change emails.",
        )
        self.assertContains(protocol_response, 'data-bs-target="#protocolFeedbackWindowCollapse"')
        self.assertContains(protocol_response, "data-collapse-toggle-label")
        self.assertContains(protocol_response, 'data-label-open="Hide"')
        self.assertContains(
            protocol_response,
            "Closing this feedback window will stop advisory members from submitting protocol feedback and will end collaborative editing for this protocol. Are you sure?",
        )

        action_list_response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertContains(action_list_response, "Action list feedback window")
        self.assertContains(action_list_response, "Save deadline for sent members")
        self.assertContains(
            action_list_response,
            "Feedback links stay open until each member's own saved deadline, or until you close the whole feedback window manually.",
        )
        self.assertContains(
            action_list_response,
            "Saving here updates all already-sent accepted members and does not send a new email immediately.",
        )
        self.assertContains(
            action_list_response,
            "Members see this note only after the action list feedback window has been closed. It is not used for reminder or deadline-change emails.",
        )
        self.assertContains(action_list_response, 'data-bs-target="#actionListFeedbackWindowCollapse"')
        self.assertContains(action_list_response, "data-collapse-toggle-label")
        self.assertContains(action_list_response, 'data-label-open="Hide"')
        self.assertContains(
            action_list_response,
            "Closing this feedback window will stop advisory members from submitting action list feedback and will end collaborative editing for this action list. Are you sure?",
        )

    def test_protocol_feedback_window_explains_member_specific_deadlines(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
        )
        now = timezone.now().replace(second=0, microsecond=0)
        early_deadline = now - timedelta(days=2)
        late_deadline = now + timedelta(days=5)
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Pia",
            email="pia@example.com",
            response="Y",
            sent_protocol_at=now - timedelta(days=10),
            feedback_on_protocol_deadline=early_deadline,
        )
        AdvisoryBoardMember.objects.create(
            project=self.project,
            first_name="Will",
            email="will@example.com",
            response="Y",
            sent_protocol_at=now - timedelta(days=2),
            feedback_on_protocol_deadline=late_deadline,
        )

        response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )

        self.assertContains(
            response,
            "Saved member deadlines: "
            f"{timezone.localtime(early_deadline).strftime('%Y-%m-%d %H:%M')} to "
            f"{timezone.localtime(late_deadline).strftime('%Y-%m-%d %H:%M')}",
        )
        self.assertContains(
            response,
            "Different advisory board members currently have different protocol deadlines.",
        )
        self.assertContains(
            response,
            "Some earlier member deadlines have already passed, but other members can still submit because their own saved deadline has not passed or because no protocol deadline is saved for them.",
        )
        self.assertContains(response, "Open for some members")

    def test_document_pages_explain_deadlines_require_sent_documents(self):
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
        self.assertContains(
            protocol_response,
            "Send the protocol from the Advisory Board page first.",
        )
        self.assertContains(
            protocol_response,
            "No protocol feedback deadline can be updated here yet because no accepted advisory board member has been sent the protocol.",
        )
        self.assertNotContains(protocol_response, "Set protocol deadline")

        action_list_response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertContains(
            action_list_response,
            "Send the action list from the Advisory Board page first.",
        )
        self.assertContains(
            action_list_response,
            "No action list feedback deadline can be updated here yet because no accepted advisory board member has been sent the action list.",
        )
        self.assertNotContains(action_list_response, "Set action list deadline")

    def test_document_pages_show_reopen_feedback_window_confirmations(self):
        Protocol.objects.create(
            project=self.project,
            document=SimpleUploadedFile("protocol.docx", b"protocol"),
            feedback_closed_at=timezone.now(),
        )
        ActionList.objects.create(
            project=self.project,
            document=SimpleUploadedFile("action-list.docx", b"alist"),
            feedback_closed_at=timezone.now(),
        )

        protocol_response = self.client.get(
            reverse("synopsis:protocol_detail", args=[self.project.id])
        )
        self.assertContains(protocol_response, "Reopen feedback")
        self.assertContains(
            protocol_response,
            "Reopening this feedback window will allow advisory members to submit protocol feedback again and can allow collaborative editing for this protocol again. Are you sure?",
        )

        action_list_response = self.client.get(
            reverse("synopsis:action_list_detail", args=[self.project.id])
        )
        self.assertContains(action_list_response, "Reopen feedback")
        self.assertContains(
            action_list_response,
            "Reopening this feedback window will allow advisory members to submit action list feedback again and can allow collaborative editing for this action list again. Are you sure?",
        )


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
