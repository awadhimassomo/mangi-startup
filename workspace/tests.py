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
            },
            instance=user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "founder@example.com")
