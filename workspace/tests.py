from django.contrib.auth import get_user_model
from django.test import TestCase

from .admin import UniqueEmailUserChangeForm, UniqueEmailUserCreationForm
from .forms import SignUpForm


class SignUpFormTests(TestCase):
    def test_email_must_be_unique_case_insensitive(self):
        User = get_user_model()
        User.objects.create_user(username="existing", email="Founder@Example.com", password="pass12345")

        form = SignUpForm(
            data={
                "company_name": "Acme",
                "email": "founder@example.com",
                "password1": "A-strong-passphrase-123",
                "password2": "A-strong-passphrase-123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["An account with this email already exists."])

    def test_email_is_saved_normalized(self):
        form = SignUpForm(
            data={
                "company_name": "Acme",
                "email": "  Founder@Example.com  ",
                "password1": "A-strong-passphrase-123",
                "password2": "A-strong-passphrase-123",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "founder@example.com")


class UserAdminEmailTests(TestCase):
    def test_admin_create_email_must_be_unique_case_insensitive(self):
        User = get_user_model()
        User.objects.create_user(username="existing", email="Founder@Example.com", password="pass12345")

        form = UniqueEmailUserCreationForm(
            data={
                "username": "newuser",
                "email": "founder@example.com",
                "password1": "A-strong-passphrase-123",
                "password2": "A-strong-passphrase-123",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["An account with this email already exists."])

    def test_admin_change_email_must_be_unique_case_insensitive(self):
        User = get_user_model()
        User.objects.create_user(username="existing", email="Founder@Example.com", password="pass12345")
        user = User.objects.create_user(username="newuser", email="new@example.com", password="pass12345")

        form = UniqueEmailUserChangeForm(
            data={
                "username": user.username,
                "email": "founder@example.com",
                "password": user.password,
            },
            instance=user,
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["An account with this email already exists."])

    def test_admin_change_allows_current_users_own_email(self):
        User = get_user_model()
        user = User.objects.create_user(username="existing", email="Founder@Example.com", password="pass12345")

        form = UniqueEmailUserChangeForm(
            data={
                "username": user.username,
                "email": "founder@example.com",
                "password": user.password,
            },
            instance=user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "founder@example.com")


class SourceWatchTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_superuser("staff", "s@x.com", "pw")
        self.client.force_login(self.user)

    def test_scan_finds_new_once_and_skips_expired(self):
        from unittest import mock
        from . import source_watch as sw
        from .models import DiscoveredOpportunity
        src = sw.register_source_from_link("https://funder.org/apply/1", self.user)
        self.assertEqual(src.url, "https://funder.org/")
        found = [
            {"title": "Grant A", "application_link": "https://funder.org/a", "deadline": "2999-01-01"},
            {"title": "Old", "deadline": "2000-01-01"},
        ]
        with mock.patch.object(sw, "fetch_page_text", side_effect=["v1", "v2"]), \
                mock.patch.object(sw, "_find_opportunities", return_value=found):
            self.assertEqual(len(sw.scan_source(src)), 1)
            self.assertEqual(len(sw.scan_source(src)), 0)
        self.assertEqual(DiscoveredOpportunity.objects.count(), 1)

    def test_pages_and_post_from_discovery(self):
        from .models import DiscoveredOpportunity, OpportunitySource, PostedOpportunity
        src = OpportunitySource.objects.create(url="https://funder.org/")
        d = DiscoveredOpportunity.objects.create(source=src, key="k", data={"title": "Grant A", "funder_name": "F"})
        self.assertEqual(self.client.get("/ops/sources/").status_code, 200)
        self.assertContains(self.client.get(f"/board/post/?discovered={d.pk}"), "Grant A")
        resp = self.client.post("/board/post/", {
            "discovered": d.pk, "title": "Grant A", "funder_name": "F", "opportunity_type": "grant",
            "status": "open", "currency": "USD", "application_link": "https://funder.org/a",
        })
        self.assertEqual(resp.status_code, 302)
        d.refresh_from_db()
        self.assertEqual(d.status, "posted")
        self.assertEqual(PostedOpportunity.objects.count(), 1)


class SimpleSignupTests(TestCase):
    def test_signup_creates_workspace_and_reminder_fires_once(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        from .models import Notification, Startup
        resp = self.client.post("/signup/", {
            "company_name": "Acme", "email": "a@acme.com", "password1": "Str0ngPass!word", "password2": "Str0ngPass!word",
        })
        self.assertEqual(resp.status_code, 302)
        startup = Startup.objects.get(name="Acme")
        self.assertEqual(startup.profile_completion, 0)
        self.assertEqual(self.client.get("/").status_code in (200, 302), True)
        call_command("send_profile_reminders")
        self.assertEqual(Notification.objects.count(), 0)  # too soon
        Startup.objects.filter(pk=startup.pk).update(created_at=timezone.now() - timedelta(days=4))
        call_command("send_profile_reminders")
        call_command("send_profile_reminders")
        self.assertEqual(Notification.objects.count(), 1)
