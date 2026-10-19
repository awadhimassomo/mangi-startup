import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .admin import UniqueEmailUserChangeForm, UniqueEmailUserCreationForm
from .forms import SignUpForm
from .models import PostedOpportunity, Startup, StartupMember


class SignUpFormTests(TestCase):
    def test_email_must_be_unique_case_insensitive(self):
        User = get_user_model()
        User.objects.create_user(username="existing", email="Founder@Example.com", password="pass12345")

        form = SignUpForm(
            data={
                "username": "newuser",
                "first_name": "New",
                "last_name": "Founder",
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
                "username": "newuser",
                "first_name": "New",
                "last_name": "Founder",
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
                "date_joined": user.date_joined,
            },
            instance=user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "founder@example.com")


class PwaAndPushNotificationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", email="tester@example.com", password="pass12345")
        self.client.login(username="tester", password="pass12345")

    def test_pwa_manifest_route_and_static_exists(self):
        from django.conf import settings
        import os
        manifest_path = settings.BASE_DIR / "static" / "workspace" / "manifest.json"
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("FundOS", content)
            self.assertIn("icon-192.png", content)

    def test_service_worker_is_served_from_root_scope(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("application/javascript", response["Content-Type"])

    def test_vapid_public_key_endpoint(self):
        response = self.client.get("/api/pwa/vapid-public-key/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("publicKey", data)
        self.assertTrue(len(data["publicKey"]) > 20)

    def test_vapid_public_key_endpoint_is_json_for_signed_out_visitors(self):
        self.client.logout()
        response = self.client.get("/api/pwa/vapid-public-key/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("publicKey", response.json())

    def test_subscribe_and_unsubscribe_endpoint(self):
        from .models import PushSubscription

        sub_data = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-token-12345",
            "keys": {
                "p256dh": "BL1234567890abcdef",
                "auth": "authSecret123"
            }
        }
        # Subscribe
        res = self.client.post("/api/pwa/subscribe/", data=json.dumps(sub_data), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 1)

        # Unsubscribe
        unsub_data = {"endpoint": "https://fcm.googleapis.com/fcm/send/test-token-12345"}
        res_unsub = self.client.post("/api/pwa/unsubscribe/", data=json.dumps(unsub_data), content_type="application/json")
        self.assertEqual(res_unsub.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 0)

    def test_startup_user_cannot_send_test_push(self):
        response = self.client.post("/api/pwa/test-notification/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Only operations admins can send test push notifications.")

    @patch("workspace.push_service.send_push_to_user", return_value=1)
    def test_operations_admin_can_send_test_push(self, send_push):
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="opsadmin", email="ops@example.com", password="pass12345"
        )
        self.client.force_login(admin)

        response = self.client.post("/api/pwa/test-notification/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        send_push.assert_called_once()


class ScrapedOpportunityReviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.startup_user = User.objects.create_user(
            username="founder", email="founder@example.com", password="pass12345"
        )
        startup = Startup.objects.create(name="Test Startup", country="Tanzania")
        StartupMember.objects.create(
            startup=startup,
            user=self.startup_user,
            role=StartupMember.Role.STARTUP_ADMIN,
            is_active=True,
        )
        self.admin = User.objects.create_superuser(
            username="reviewadmin", email="reviewadmin@example.com", password="pass12345"
        )
        self.opportunity = PostedOpportunity.objects.create(
            title="Scraped opportunity awaiting review",
            funder_name="Example Funder",
            posted_by=self.admin,
            review_status=PostedOpportunity.ReviewStatus.PENDING,
        )

    @patch("workspace.scraper_agent.PostedOpportunity.objects.create")
    def test_scraper_ingestion_defaults_to_pending_review(self, create_opportunity):
        from .scraper_agent import ingest_opportunity

        payload = {
            "title": "New scraped grant",
            "funder_name": "Example Funder",
            "application_link": "https://example.org/grant",
        }
        ingest_opportunity(payload, posted_by=self.admin)

        self.assertEqual(
            create_opportunity.call_args.kwargs["review_status"],
            PostedOpportunity.ReviewStatus.PENDING,
        )

    def test_pending_scraped_opportunity_is_hidden_from_startups(self):
        self.client.force_login(self.startup_user)

        response = self.client.get(reverse("posted_opportunity_list"))
        detail_response = self.client.get(
            reverse("posted_opportunity_detail", args=[self.opportunity.pk])
        )

        self.assertNotContains(response, self.opportunity.title)
        self.assertEqual(detail_response.status_code, 404)

    def test_admin_approval_makes_open_opportunity_public(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("ops_opportunity_toggle_status", args=[self.opportunity.pk]),
            {"review_status": PostedOpportunity.ReviewStatus.APPROVED},
        )

        self.assertRedirects(response, reverse("ops_dashboard"))
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.review_status, PostedOpportunity.ReviewStatus.APPROVED)

        self.client.force_login(self.startup_user)
        board_response = self.client.get(reverse("posted_opportunity_list"))
        self.assertContains(board_response, self.opportunity.title)

    def test_startup_user_cannot_approve_scraped_opportunity(self):
        self.client.force_login(self.startup_user)
        response = self.client.post(
            reverse("ops_opportunity_toggle_status", args=[self.opportunity.pk]),
            {"review_status": PostedOpportunity.ReviewStatus.APPROVED},
        )
        self.assertEqual(response.status_code, 403)

