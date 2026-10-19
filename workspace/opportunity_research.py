"""Go beyond the picture: follow the website shown in it, or search the web by its keywords."""
import json
import logging
import os
import re
import urllib.parse

import requests

from .ai_pipeline import (
    EXTRACT_FIELDS,
    OPENAI_MODEL,
    PostedOpportunity,
    extract_opportunity_from_image,
    extract_opportunity_from_text,
)
from .scraper_agent import DEFAULT_HEADERS, _fetch_article

logger = logging.getLogger(__name__)

KEY_FIELDS = ("amount_max", "deadline", "eligibility", "application_link", "short_description")


def _missing(data):
    return [f for f in KEY_FIELDS if not data.get(f)]


def _merge(base, extra):
    """Fill blanks in `base` from `extra`; a researched official link beats a missing one."""
    for field in EXTRACT_FIELDS:
        if not base.get(field) and extra.get(field):
            base[field] = extra[field]
    if base.get("opportunity_type") in ("", "other") and extra.get("opportunity_type"):
        base["opportunity_type"] = extra["opportunity_type"]
    return base


def _from_website(url):
    text, links = _fetch_article(url)
    if not text:
        return None
    result = extract_opportunity_from_text(text, url, links)
    if result and not result.get("application_link"):
        result["application_link"] = url
    return result


def _web_search_openai(data):
    """Ask OpenAI (with its built-in web search) to find the official page and details."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    types = ", ".join(PostedOpportunity.OpportunityType.values)
    query = " ".join(filter(None, [data.get("title"), data.get("funder_name"), data.get("tags")]))
    prompt = (
        f"Search the web for this funding opportunity and find its official page: {query}\n"
        f"Reply with ONLY a JSON object with keys: {', '.join(EXTRACT_FIELDS)}. "
        f"opportunity_type must be one of: {types}. deadline is YYYY-MM-DD or empty. "
        "amount_min/amount_max are plain numbers per award or empty. application_link is the official "
        "application or call page you found. Only use facts from the official source; use empty strings otherwise."
    )
    response = OpenAI(api_key=api_key).responses.create(
        model=OPENAI_MODEL, tools=[{"type": "web_search_preview"}], input=prompt
    )
    match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
    if not match:
        return None
    raw = json.loads(match.group(0))
    return {k: ("" if raw.get(k) is None else str(raw.get(k))) for k in EXTRACT_FIELDS}


def _web_search_fallback(data):
    """Plain search-engine lookup: open the top results and read them."""
    query = " ".join(filter(None, [data.get("title"), data.get("funder_name"), "apply"]))
    resp = requests.get(
        "https://html.duckduckgo.com/html/", params={"q": query}, headers=DEFAULT_HEADERS, timeout=15
    )
    for href in re.findall(r'class="result__a" href="([^"]+)"', resp.text)[:3]:
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
        if href.startswith("//"):
            href = "https:" + href
        try:
            result = _from_website(href)
        except Exception:  # noqa: BLE001
            continue
        if result:
            return result
    return None


def research_opportunity(data):
    """Enrich the fields read from a picture. Never raises: the picture's own data is the floor."""
    url = (data.get("application_link") or "").strip()
    if url.startswith(("http://", "https://")):
        try:
            site = _from_website(url)
            if site:
                data = _merge(data, site)
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not read %s: %s", url, exc)

    if _missing(data) and (data.get("title") or data.get("funder_name")):
        found = None
        try:
            found = _web_search_openai(data)
        except Exception as exc:  # noqa: BLE001
            logger.info("OpenAI web search unavailable: %s", exc)
        if not found:
            try:
                found = _web_search_fallback(data)
            except Exception as exc:  # noqa: BLE001
                logger.info("Fallback web search failed: %s", exc)
        if found:
            data = _merge(data, found)
    return data


def read_screenshot(image_bytes, media_type):
    """Picture → fields, then follow its website / search its keywords for what the picture lacks."""
    data = extract_opportunity_from_image(image_bytes, media_type)
    return research_opportunity(data)
