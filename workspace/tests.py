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
                "date_joined": user.date_joined,
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



class StaffDetailAndScraperTests(TestCase):
    def test_staff_without_startup_can_open_pending_opportunity(self):
        from .models import PostedOpportunity
        staff = get_user_model().objects.create_superuser("boss", "b@x.com", "pw")
        self.client.force_login(staff)
        opp = PostedOpportunity.objects.create(
            title="Pending Grant", funder_name="F", review_status="pending"
        )
        resp = self.client.get(f"/board/{opp.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pending Grant")

    def test_enrich_uses_real_apply_link_and_full_text_amounts(self):
        from unittest import mock
        from decimal import Decimal
        from . import scraper_agent as sa
        html = b"""<html><body><article><div class="entry-content">
        <p>Grants of up to $50,000 are available. Deadline: 30 November 2026.</p>
        <p>Visit <a href="https://grants.example.org/apply">Example Foundation Grant</a>.</p>
        <ins><a href="https://ads.example.com/car">Car ad</a></ins>
        <a href="https://twitter.com/x">tw</a></div></article></body></html>"""
        resp = mock.Mock(status_code=200, content=html)
        payload = {"title": "T", "application_link": "https://opportunitydesk.org/post/", "amount_min": None,
                   "amount_max": None, "currency": "USD", "deadline": None}
        with mock.patch.object(sa.requests, "get", return_value=resp), \
                mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            out = sa.enrich_payload(payload, "https://opportunitydesk.org/post/")
        self.assertEqual(out["application_link"], "https://grants.example.org/apply")
        self.assertEqual(out["amount_max"], Decimal("50000"))
        self.assertEqual(str(out["deadline"]), "2026-11-30")


class QuickPostTests(TestCase):
    def test_screenshot_creates_pending_draft_then_publishes(self):
        import io
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from .models import PostedOpportunity
        staff = get_user_model().objects.create_superuser("boss2", "b2@x.com", "pw")
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/board/quick-post/").status_code, 200)
        buf = io.BytesIO(); Image.new("RGB", (10, 10)).save(buf, "PNG")
        img = SimpleUploadedFile("shot.png", buf.getvalue(), content_type="image/png")
        data = {"title": "IG Grant", "funder_name": "Fund", "opportunity_type": "grant", "amount_max": "5,000",
                "currency": "USD", "deadline": "2999-01-01", "application_link": "https://f.org/apply",
                "short_description": "", "eligibility": "", "amount_min": "", "geographic_focus": "",
                "sector_focus": "", "tags": ""}
        with mock.patch("workspace.views.read_screenshot", return_value=data):
            resp = self.client.post("/board/quick-post/", {"images": img})
        opp = PostedOpportunity.objects.get()
        self.assertRedirects(resp, f"/board/{opp.pk}/edit/?from=quick")
        self.assertEqual(opp.review_status, "pending")
        self.assertEqual(str(opp.amount_max), "5000.00")
        self.assertTrue(opp.poster_image)
        resp = self.client.post(f"/board/{opp.pk}/edit/", {
            "publish": "1", "title": "IG Grant", "funder_name": "Fund", "opportunity_type": "grant",
            "status": "open", "currency": "USD"})
        opp.refresh_from_db()
        self.assertEqual(opp.review_status, "approved")


class QuickFlowRedirectTests(TestCase):
    def test_publish_from_quick_returns_to_upload_page(self):
        from .models import PostedOpportunity
        staff = get_user_model().objects.create_superuser("boss3", "b3@x.com", "pw")
        self.client.force_login(staff)
        opp = PostedOpportunity.objects.create(title="A", funder_name="F", review_status="pending")
        data = {"publish": "1", "title": "A", "funder_name": "F", "opportunity_type": "grant",
                "status": "open", "currency": "USD"}
        resp = self.client.post(f"/board/{opp.pk}/edit/?from=quick", data)
        self.assertRedirects(resp, "/board/quick-post/")
        resp = self.client.post(f"/board/{opp.pk}/edit/", data)
        self.assertRedirects(resp, "/ops/")
        self.assertContains(self.client.get(f"/board/{opp.pk}/"), "Back to manage")


class ResearchTests(TestCase):
    def test_fills_blanks_from_website_then_search(self):
        from unittest import mock
        from . import opportunity_research as r
        image_data = {k: "" for k in r.EXTRACT_FIELDS}
        image_data.update({"title": "Big Grant", "funder_name": "Fund", "opportunity_type": "other",
                           "application_link": "https://fund.org/grant"})
        site = {k: "" for k in r.EXTRACT_FIELDS}
        site.update({"amount_max": "20000", "deadline": "2999-05-01", "opportunity_type": "grant",
                     "title": "SHOULD NOT OVERRIDE"})
        searched = {k: "" for k in r.EXTRACT_FIELDS}
        searched.update({"eligibility": "Startups in Africa", "short_description": "A grant."})
        with mock.patch.object(r, "_from_website", return_value=site), \
                mock.patch.object(r, "_web_search_openai", return_value=searched) as search:
            out = r.research_opportunity(image_data)
        self.assertEqual(out["title"], "Big Grant")
        self.assertEqual(out["amount_max"], "20000")
        self.assertEqual(out["opportunity_type"], "grant")
        self.assertEqual(out["eligibility"], "Startups in Africa")
        self.assertTrue(search.called)

    def test_never_raises_when_everything_fails(self):
        from unittest import mock
        from . import opportunity_research as r
        d = {k: "" for k in r.EXTRACT_FIELDS}
        d.update({"title": "X", "application_link": "https://x.org"})
        with mock.patch.object(r, "_from_website", side_effect=RuntimeError("boom")), \
                mock.patch.object(r, "_web_search_openai", side_effect=RuntimeError("no")), \
                mock.patch.object(r, "_web_search_fallback", side_effect=RuntimeError("no")):
            self.assertEqual(r.research_opportunity(d)["title"], "X")


class PosterLightboxTests(TestCase):
    def test_poster_is_zoomable_for_admin_and_includes_lightbox(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import PostedOpportunity
        import io
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (4, 4)).save(buf, "PNG")
        staff = get_user_model().objects.create_superuser("boss4", "b4@x.com", "pw")
        self.client.force_login(staff)
        opp = PostedOpportunity.objects.create(
            title="P", funder_name="F",
            poster_image=SimpleUploadedFile("p.png", buf.getvalue(), content_type="image/png"))
        resp = self.client.get(f"/board/{opp.pk}/")
        self.assertContains(resp, 'class="zoomable"')
        self.assertContains(resp, 'id="lb"')
        opp.poster_image.delete(save=False)


class ListingScrapeTests(TestCase):
    def test_listing_page_creates_pending_posts_and_watches_url(self):
        from unittest import mock
        from . import scraper_agent as sa
        from .models import OpportunitySource, PostedOpportunity
        items = [
            {"title": "Grant One", "funder_name": "FAO", "application_link": "https://x.org/1", "deadline": "2999-01-01"},
            {"title": "Grant Two", "funder_name": "UNDP", "application_link": "https://x.org/2", "deadline": ""},
            {"title": "Old One", "deadline": "2000-01-01"},
        ]
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "x"}), \
                mock.patch("workspace.source_watch.fetch_page_text", return_value="text [link: https://x.org/1]"), \
                mock.patch("workspace.source_watch._find_opportunities", return_value=items), \
                mock.patch("workspace.opportunity_research.research_opportunity", side_effect=lambda d: d):
            stats = sa.run_opportunity_scraper(custom_urls=["https://x.org/funding"])
        self.assertEqual(stats["created"], 2)
        self.assertEqual(PostedOpportunity.objects.filter(review_status="pending").count(), 2)
        self.assertTrue(OpportunitySource.objects.filter(url="https://x.org/funding").exists())
