import json

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

    def test_vapid_public_key_endpoint(self):
        response = self.client.get("/api/pwa/vapid-public-key/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("publicKey", data)
        self.assertTrue(len(data["publicKey"]) > 20)

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

