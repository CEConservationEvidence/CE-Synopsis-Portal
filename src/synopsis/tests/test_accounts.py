"""Authentication, user management, and identity UI tests."""

from .common import *


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="author@example.com",
            email="author@example.com",
            password="StrongPass123!",
            first_name="Author",
        )
        self.manager = User.objects.create_user(
            username="manager@example.com",
            email="manager@example.com",
            password="StrongPass123!",
            is_staff=True,
        )
        self.project = Project.objects.create(title="Creation Assignment Project")

    def test_login_remember_me_controls_session_expiry(self):
        response = self.client.post(
            reverse("synopsis:login"),
            {"username": "author@example.com", "password": "StrongPass123!"},
        )
        self.assertRedirects(response, reverse("synopsis:dashboard"))
        self.assertTrue(self.client.session.get_expire_at_browser_close())

        self.client.post(reverse("synopsis:logout"))

        response = self.client.post(
            reverse("synopsis:login"),
            {
                "username": "author@example.com",
                "password": "StrongPass123!",
                "remember_me": "on",
            },
        )
        self.assertRedirects(response, reverse("synopsis:dashboard"))
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_login_allows_standard_django_username_for_superuser_style_accounts(self):
        root_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="RootPass123!",
            is_staff=True,
            is_superuser=True,
        )

        response = self.client.post(
            reverse("synopsis:login"),
            {"username": "admin", "password": "RootPass123!"},
        )

        self.assertRedirects(response, reverse("synopsis:dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), root_user.id)

    def test_logout_requires_post(self):
        self.client.login(username="author@example.com", password="StrongPass123!")
        response = self.client.get(reverse("synopsis:logout"))
        self.assertEqual(response.status_code, 405)

    def test_password_reset_request_sends_email(self):
        response = self.client.post(
            reverse("synopsis:password_reset"),
            {"email": "author@example.com"},
        )

        self.assertRedirects(response, reverse("synopsis:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["author@example.com"])

    def test_manager_create_user_sends_account_setup_email_and_allows_password_setup(self):
        self.client.login(username="manager@example.com", password="StrongPass123!")

        response = self.client.post(
            reverse("synopsis:user_create"),
            {
                "first_name": "New",
                "last_name": "Author",
                "email": "new.author@example.com",
                "global_role": "author",
            },
        )

        self.assertRedirects(response, reverse("synopsis:manager_dashboard"))
        created_user = User.objects.get(username="new.author@example.com")
        self.assertFalse(created_user.has_usable_password())
        self.assertEqual(created_user.email, "new.author@example.com")
        self.assertTrue(created_user.groups.filter(name="author").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.author@example.com"])
        self.assertIn("Set up your CE Synopsis Portal account", mail.outbox[0].subject)

        match = re.search(r"http://testserver(/accounts/reset/\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        reset_path = match.group(1)

        response = self.client.get(reset_path, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Set password")
        confirm_path = response.request["PATH_INFO"]

        response = self.client.post(
            confirm_path,
            {
                "new_password1": "EvenStrongerPass123!",
                "new_password2": "EvenStrongerPass123!",
            },
        )
        self.assertRedirects(response, reverse("synopsis:password_reset_complete"))

        created_user.refresh_from_db()
        self.assertTrue(created_user.has_usable_password())
        self.client.post(reverse("synopsis:logout"))
        self.assertTrue(
            self.client.login(
                username="new.author@example.com",
                password="EvenStrongerPass123!",
            )
        )

    def test_manager_can_create_external_author_with_assigned_synopsis(self):
        self.client.login(username="manager@example.com", password="StrongPass123!")

        response = self.client.post(
            reverse("synopsis:user_create"),
            {
                "first_name": "External",
                "last_name": "Author",
                "email": "external.author@example.com",
                "global_role": "external_collaborator",
                "assigned_projects": [str(self.project.id)],
            },
        )

        self.assertRedirects(response, reverse("synopsis:manager_dashboard"))
        created_user = User.objects.get(username="external.author@example.com")
        self.assertTrue(
            created_user.groups.filter(name="external_collaborator").exists()
        )
        self.assertTrue(
            UserRole.objects.filter(
                user=created_user, project=self.project, role="author"
            ).exists()
        )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ManagerUserManagementTests(TestCase):
    def setUp(self):
        ensure_global_groups()
        self.manager = User.objects.create_user(
            username="manager@example.com",
            email="manager@example.com",
            password="StrongPass123!",
            is_staff=True,
        )
        self.manager.groups.add(Group.objects.get(name="manager"))
        self.target = User.objects.create_user(
            username="target@example.com",
            email="target@example.com",
            password="StrongPass123!",
            first_name="Target",
            last_name="User",
        )
        self.target.groups.add(Group.objects.get(name="author"))
        self.pending_user = User.objects.create_user(
            username="pending@example.com",
            email="pending@example.com",
            first_name="Pending",
        )
        self.pending_user.set_unusable_password()
        self.pending_user.save(update_fields=["password"])
        self.pending_user.groups.add(Group.objects.get(name="external_collaborator"))
        self.project = Project.objects.create(title="Seagrass Pilot")
        self.superuser = User.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="StrongPass123!",
        )
        self.client.login(username="manager@example.com", password="StrongPass123!")

    def test_manager_dashboard_removes_staff_column_and_shows_manage_actions(self):
        response = self.client.get(reverse("synopsis:manager_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Staff?")
        self.assertContains(response, "Global role")
        self.assertContains(response, "Access")
        self.assertContains(response, "Manage user")
        self.assertContains(response, "Protected")

    def test_manager_can_update_global_role_and_account_status(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.target.id]),
            {
                "action": "update_user",
                "first_name": "Updated",
                "last_name": "User",
                "email": "updated.target@example.com",
                "global_role": "external_collaborator",
                "is_active": "",
            },
        )

        self.assertRedirects(
            response, reverse("synopsis:manager_user_edit", args=[self.target.id])
        )
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, "updated.target@example.com")
        self.assertEqual(self.target.email, "updated.target@example.com")
        self.assertFalse(self.target.is_active)
        self.assertFalse(self.target.is_staff)
        self.assertTrue(self.target.groups.filter(name="external_collaborator").exists())
        self.assertFalse(self.target.groups.filter(name="author").exists())

    def test_manager_can_send_password_reset_email_for_existing_account(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.target.id]),
            {"action": "send_access_email"},
        )

        self.assertRedirects(
            response, reverse("synopsis:manager_user_edit", args=[self.target.id])
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password reset", mail.outbox[0].subject.lower())
        self.assertEqual(mail.outbox[0].to, ["target@example.com"])

    def test_manager_can_resend_setup_email_for_pending_account(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.pending_user.id]),
            {"action": "send_access_email"},
        )

        self.assertRedirects(
            response,
            reverse("synopsis:manager_user_edit", args=[self.pending_user.id]),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("set up your ce synopsis portal account", mail.outbox[0].subject.lower())
        self.assertEqual(mail.outbox[0].to, ["pending@example.com"])

    def test_manager_can_assign_synopses_to_external_author(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.pending_user.id]),
            {
                "action": "update_user",
                "first_name": "Pending",
                "last_name": "",
                "email": "pending@example.com",
                "global_role": "external_collaborator",
                "is_active": "on",
                "assigned_projects": [str(self.project.id)],
            },
        )

        self.assertRedirects(
            response,
            reverse("synopsis:manager_user_edit", args=[self.pending_user.id]),
        )
        self.assertTrue(
            UserRole.objects.filter(
                user=self.pending_user, project=self.project, role="author"
            ).exists()
        )

    def test_manager_can_delete_user_with_email_confirmation(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.target.id]),
            {
                "action": "delete_user",
                "confirm_email": "target@example.com",
            },
        )

        self.assertRedirects(response, reverse("synopsis:manager_dashboard"))
        self.assertFalse(User.objects.filter(pk=self.target.id).exists())

    def test_manager_cannot_delete_own_account(self):
        response = self.client.post(
            reverse("synopsis:manager_user_edit", args=[self.manager.id]),
            {
                "action": "delete_user",
                "confirm_email": "manager@example.com",
            },
            follow=True,
        )

        self.assertRedirects(
            response, reverse("synopsis:manager_user_edit", args=[self.manager.id])
        )
        self.assertTrue(User.objects.filter(pk=self.manager.id).exists())
        self.assertContains(response, "You cannot delete your own account.")

    def test_superuser_accounts_are_protected_from_manager_edit_screen(self):
        response = self.client.get(
            reverse("synopsis:manager_user_edit", args=[self.superuser.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("synopsis:manager_dashboard"))
        self.assertContains(
            response,
            "System admin accounts are managed outside this screen.",
        )


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


class NavbarIdentityUiTests(TestCase):
    def setUp(self):
        ensure_global_groups()
        self.project = Project.objects.create(title="Navbar Synopsis")
        self.manager = User.objects.create_user(
            username="nav-manager",
            password="pass123",
            first_name="Mina",
            last_name="Manager",
            is_staff=True,
        )
        self.author = User.objects.create_user(
            username="nav-author",
            password="pass123",
        )
        self.external = User.objects.create_user(
            username="nav-external@example.com",
            email="nav-external@example.com",
            password="pass123",
            first_name="Eli",
            last_name="External",
        )
        self.external.groups.add(Group.objects.get(name="external_collaborator"))
        UserRole.objects.create(user=self.author, project=self.project, role="author")
        UserRole.objects.create(user=self.external, project=self.project, role="author")

    def test_manager_nav_shows_signed_in_name_and_manager_role(self):
        self.client.login(username="nav-manager", password="pass123")

        response = self.client.get(reverse("synopsis:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-user-summary"', html=False)
        self.assertContains(response, "Mina Manager")
        self.assertContains(response, "Manager")

    def test_project_author_nav_uses_project_role_label(self):
        self.client.login(username="nav-author", password="pass123")

        response = self.client.get(
            reverse("synopsis:project_hub", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-user-summary"', html=False)
        self.assertContains(response, "nav-author")
        self.assertContains(response, "Author")

    def test_external_author_nav_prefers_external_author_account_type(self):
        self.client.login(username="nav-external@example.com", password="pass123")

        response = self.client.get(
            reverse("synopsis:project_hub", args=[self.project.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-user-summary"', html=False)
        self.assertContains(response, "Eli External")
        self.assertContains(response, "External Author")
