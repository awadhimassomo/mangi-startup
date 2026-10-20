"""Watch external websites for new funding opportunities."""
import hashlib

import os
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from django.utils import timezone

from .ai_pipeline import EXTRACT_FIELDS, ask_openai_json
from .models import DiscoveredOpportunity, OpportunitySource, PostedOpportunity

MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 25_000


class _PageParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "mailto:", "javascript:")):
                self.parts.append(f" [link: {urljoin(self.base_url, href)}] ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def fetch_page_text(url):
    from .scraper_agent import http_get

    resp = http_get(url, headers={"User-Agent": "Mozilla/5.0 MangiOpportunityWatcher/1.0"})
    resp.raise_for_status()
    parser = _PageParser(url)
    parser.feed(resp.text)
    return " ".join(parser.parts)


def _find_opportunities(page_text, url):
    types = ", ".join(PostedOpportunity.OpportunityType.values)
    prompt = (
        f"Below is the text of the web page {url}, with links shown as [link: URL]. "
        "Find every funding opportunity for startups listed or announced on it (grants, loans, equity, "
        "accelerators, competitions, fellowships). Reply with ONLY a JSON object {'opportunities': [...]}; each item is an object with keys: "
        f"{', '.join(EXTRACT_FIELDS)}. opportunity_type must be one of: {types}. "
        "application_link must be the most specific link for that opportunity from the page. "
        "deadline is YYYY-MM-DD or empty; amounts are plain numbers or empty. "
        "Use empty strings for anything not stated; never invent details. "
        "Use an empty list if there are none.\n\n" + page_text[:MAX_TEXT_CHARS]
    )
    data = ask_openai_json(prompt, max_tokens=4000)
    items = data.get("opportunities", [])
    return items if isinstance(items, list) else []


def _key_for(item):
    return (item.get("application_link") or item.get("title") or "").strip().lower()[:500]


def scan_source(source):
    """Check one source. Returns the list of newly created DiscoveredOpportunity rows."""
    new = []
    source.last_checked_at = timezone.now()
    try:
        text = fetch_page_text(source.url)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != source.last_content_hash:
            today = timezone.localdate().isoformat()
            known_links = set(
                PostedOpportunity.objects.exclude(application_link="").values_list("application_link", flat=True)
            )
            known_titles = {t.lower() for t in PostedOpportunity.objects.values_list("title", flat=True)}
            for item in _find_opportunities(text, source.url):
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                item = {k: ("" if item.get(k) is None else str(item.get(k))) for k in EXTRACT_FIELDS}
                if item["deadline"] and item["deadline"] < today:
                    continue
                if item["application_link"] in known_links or item["title"].lower() in known_titles:
                    continue
                key = _key_for(item)
                if not key:
                    continue
                obj, created = DiscoveredOpportunity.objects.get_or_create(
                    source=source, key=key, defaults={"data": item}
                )
                if created:
                    new.append(obj)
            source.last_content_hash = digest
        source.last_error = ""
    except Exception as exc:  # noqa: BLE001
        source.last_error = str(exc)[:500]
    source.save()
    return new


def register_source_from_link(link, user=None):
    """Watch the website behind a posted opportunity's application link."""
    parsed = urlparse(link or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    root = f"{parsed.scheme}://{parsed.netloc}/"
    source, _ = OpportunitySource.objects.get_or_create(
        url=root, defaults={"name": parsed.netloc, "added_by": user}
    )
    return source
