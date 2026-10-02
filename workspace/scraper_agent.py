import datetime
import logging
import re
import urllib.parse
from decimal import Decimal
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from .models import PostedOpportunity

logger = logging.getLogger(__name__)

# User-Agent header for web requests
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 FundOS-Scraper/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Curated feeds for startup funding, innovation challenges, and NGO grants
DEFAULT_FEED_SOURCES = [
    {
        "name": "Opportunity Desk - Grants",
        "url": "https://opportunitydesk.org/category/grants/feed/",
        "default_type": PostedOpportunity.OpportunityType.GRANT,
    },
    {
        "name": "Opportunity Desk - Competitions",
        "url": "https://opportunitydesk.org/category/competitions/feed/",
        "default_type": PostedOpportunity.OpportunityType.COMPETITION,
    },
    {
        "name": "Opportunity Desk - Accelerators & Awards",
        "url": "https://opportunitydesk.org/category/awards/feed/",
        "default_type": PostedOpportunity.OpportunityType.ACCELERATOR,
    },
]

# Purely academic student terms that should be strictly excluded
EXCLUDED_ACADEMIC_TERMS = [
    "phd scholarship",
    "phd scholarships",
    "masters scholarship",
    "master's scholarship",
    "undergraduate fellowship",
    "undergraduate scholarship",
    "bachelor scholarship",
    "postdoctoral fellowship",
    "postdoctoral program",
    "faculty research grant",
    "visiting scholar",
    "student scholarship",
    "tuition grant",
    "high school",
    "travel grant for researcher",
    "scholarships and fellowships you can apply",
    "phd students",
    "postdoc",
    "early-career international researcher",
    "doctoral fellowship",
    "master's and phd",
    "university admission",
]

# Startup, Enterprise, Founder, and NGO target keywords
TARGET_STARTUP_NGO_TERMS = [
    "startup",
    "start-up",
    "startups",
    "founder",
    "founders",
    "entrepreneur",
    "entrepreneurs",
    "enterprise",
    "enterprises",
    "sme",
    "smes",
    "small business",
    "business",
    "businesses",
    "ngo",
    "ngos",
    "non-profit",
    "nonprofit",
    "non-profits",
    "nonprofits",
    "civil society",
    "cso",
    "csos",
    "community-based",
    "community organization",
    "social venture",
    "social enterprise",
    "social impact",
    "innovator",
    "innovators",
    "innovation challenge",
    "accelerator",
    "incubator",
    "venture",
    "cooperative",
    "grassroots",
    "consortium",
    "project grant",
    "implementation grant",
    "civic tech",
    "fintech",
    "agritech",
    "healthtech",
    "cleantech",
]

# Must be accessible to Tanzania / East Africa
TANZANIA_EAST_AFRICA_TERMS = [
    "tanzania",
    "dar es salaam",
    "arusha",
    "zanzibar",
    "east africa",
    "eastern africa",
    "eac",
    "sub-saharan africa",
    "sub saharan africa",
    "africa",
    "african",
    "developing countr",
    "low- and middle-income",
    "global",
    "worldwide",
    "all nationalities",
    "international",
    "commonwealth",
    "global south",
]

DISALLOWED_EXCLUSIVE_REGIONS = [
    "us citizens only",
    "us only",
    "uk residents only",
    "canada only",
    "australia only",
    "european union only",
    "latin america only",
    "india only",
]


def _clean_text(html_or_text):
    """Strips HTML tags and normalizes whitespace."""
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_relevant_for_startup_or_ngo(title, content):
    """
    Validates that the opportunity is meant for startups, founders, businesses, or NGOs,
    and NOT purely academic student scholarships/postdocs.
    """
    combined = (title + " " + content).lower()

    # 1. Check for strictly excluded academic terms
    for term in EXCLUDED_ACADEMIC_TERMS:
        if term in combined:
            return False, f"Excluded academic term found: '{term}'"

    # 2. Check for startup / founder / NGO relevance
    has_target_entity = any(term in combined for term in TARGET_STARTUP_NGO_TERMS)
    if not has_target_entity:
        return False, "Does not mention startups, SMEs, businesses, founders, or NGOs/civil society"

    return True, "Valid startup/NGO opportunity"


def is_eligible_for_tanzania_and_east_africa(title, content):
    """
    Validates that Tanzania / East Africa is eligible for this opportunity.
    """
    combined = (title + " " + content).lower()

    # 1. Check if strictly limited to other exclusive regions
    for dis in DISALLOWED_EXCLUSIVE_REGIONS:
        if dis in combined and "tanzania" not in combined and "africa" not in combined:
            return False, f"Restricted to external region: '{dis}'"

    # 2. Check for Tanzania / East Africa / Africa / Global inclusion
    has_geo_match = any(term in combined for term in TANZANIA_EAST_AFRICA_TERMS)
    if not has_geo_match:
        return False, "Does not include Tanzania, East Africa, Sub-Saharan Africa, or Global eligibility"

    return True, "Valid Tanzania/East Africa eligibility"


def _extract_amount(text):
    """Detects min/max amounts and currency from text."""
    currency = "USD"
    if "€" in text or "EUR" in text.upper():
        currency = "EUR"
    elif "£" in text or "GBP" in text.upper():
        currency = "GBP"
    elif "TZS" in text.upper() or "SHILLING" in text.upper():
        currency = "TZS"
    elif "KES" in text.upper():
        currency = "KES"

    amounts = []
    for match in re.finditer(
        r"(?:[$€£]|USD\s*|EUR\s*|GBP\s*|TZS\s*|KES\s*)(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+)\s*(k|thousand|m|million)?",
        text,
        re.IGNORECASE,
    ):
        raw_val = match.group(1).replace(",", "")
        multiplier = match.group(2)
        try:
            val = float(raw_val)
            if multiplier:
                mul_lower = multiplier.lower()
                if "k" in mul_lower or "thousand" in mul_lower:
                    val *= 1000
                elif "m" in mul_lower or "million" in mul_lower:
                    val *= 1000000
            if 100 <= val <= 50000000:
                amounts.append(Decimal(str(val)))
        except (ValueError, ArithmeticError):
            pass

    if amounts:
        amount_min = min(amounts)
        amount_max = max(amounts)
        return amount_min, amount_max, currency
    return None, None, currency


def _extract_deadline(text):
    """Extracts deadline date from text."""
    months = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    patterns = [
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})\s+(\d{{4}})",
        rf"({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})",
        r"(\d{4})-(\d{2})-(\d{2})",
    ]

    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                if len(match.groups()) == 3:
                    g1, g2, g3 = match.groups()
                    if g1.isdigit() and not g2.isdigit():
                        date_str = f"{g1} {g2} {g3}"
                        for fmt in ("%d %B %Y", "%d %b %Y"):
                            try:
                                return datetime.datetime.strptime(date_str, fmt).date()
                            except ValueError:
                                pass
                    elif not g1.isdigit() and g2.isdigit():
                        date_str = f"{g1} {g2} {g3}"
                        for fmt in ("%B %d %Y", "%b %d %Y"):
                            try:
                                return datetime.datetime.strptime(date_str, fmt).date()
                            except ValueError:
                                pass
                    elif g1.isdigit() and g2.isdigit() and len(g1) == 4:
                        return datetime.date(int(g1), int(g2), int(g3))
            except Exception:
                pass

    return None


def _detect_opportunity_type(title, text):
    """Detects opportunity type enum from title and content."""
    combined = (title + " " + text).lower()
    if any(k in combined for k in ["accelerator", "incubator", "cohort", "venture builder"]):
        return PostedOpportunity.OpportunityType.ACCELERATOR
    if any(k in combined for k in ["competition", "challenge", "prize", "award", "hackathon"]):
        return PostedOpportunity.OpportunityType.COMPETITION
    if any(k in combined for k in ["fellowship", "residency"]):
        return PostedOpportunity.OpportunityType.FELLOWSHIP
    if any(k in combined for k in ["equity", "venture capital", "seed round", "angel investment"]):
        return PostedOpportunity.OpportunityType.EQUITY
    if any(k in combined for k in ["loan", "concessional debt", "credit line"]):
        return PostedOpportunity.OpportunityType.LOAN
    return PostedOpportunity.OpportunityType.GRANT


def _detect_geography(text):
    """Detects geographic scope from text."""
    combined = text.lower()
    geo = []
    if "tanzania" in combined:
        geo.append("Tanzania")
    if "kenya" in combined:
        geo.append("Kenya")
    if "uganda" in combined:
        geo.append("Uganda")
    if "rwanda" in combined:
        geo.append("Rwanda")
    if "east africa" in combined:
        geo.append("East Africa")
    if "sub-saharan" in combined or "africa" in combined:
        geo.append("Sub-Saharan Africa")
    if "commonwealth" in combined:
        geo.append("Commonwealth Nations (inc. Tanzania)")
    if "global" in combined or "worldwide" in combined or "all countries" in combined:
        geo.append("Global (open to Tanzania)")
    
    return ", ".join(geo) if geo else "East Africa / Tanzania"


def _detect_sectors_and_tags(title, text):
    """Extracts relevant sector focus and tags."""
    combined = (title + " " + text).lower()
    sectors = []
    tags = []

    keyword_map = {
        "agritech": ("AgriTech", "agriculture, farming, food systems"),
        "agriculture": ("Agriculture", "agri, farming, food security"),
        "climate": ("ClimateTech & Environment", "climate, green, sustainability, energy"),
        "energy": ("Clean Energy", "renewable, solar, power"),
        "health": ("HealthTech", "healthcare, medical, biotech"),
        "fintech": ("FinTech", "financial inclusion, payments, banking"),
        "education": ("EdTech", "education, learning, skills"),
        "women": ("Women Founders", "female founders, gender lens, diversity"),
        "youth": ("Youth Innovation", "young founders, social innovation"),
        "ngo": ("Civil Society & NGO", "nonprofit, development, community impact"),
        "community": ("Community Development", "grassroots, social impact"),
        "tech": ("Technology & Digital", "software, ai, digital economy"),
    }

    for key, (sector_label, tag_string) in keyword_map.items():
        if key in combined:
            if sector_label not in sectors:
                sectors.append(sector_label)
            for t in tag_string.split(","):
                t_clean = t.strip()
                if t_clean and t_clean not in tags:
                    tags.append(t_clean)

    sector_str = ", ".join(sectors[:3]) if sectors else "Startups & NGOs"
    tags_str = ", ".join(tags[:6]) if tags else "startups, grants, ngos, tanzania"
    return sector_str, tags_str


def parse_opportunity_payload(raw_title, raw_content, source_url, funder_hint=""):
    """Parses raw content into structured PostedOpportunity fields."""
    title = _clean_text(raw_title)
    content = _clean_text(raw_content)

    # 1. Filter: Startup/NGO relevance
    is_startup_ngo, reason_entity = is_relevant_for_startup_or_ngo(title, content)
    if not is_startup_ngo:
        logger.info("Skipping '%s': %s", title, reason_entity)
        return None

    # 2. Filter: Tanzania & East Africa eligibility
    is_geo_valid, reason_geo = is_eligible_for_tanzania_and_east_africa(title, content)
    if not is_geo_valid:
        logger.info("Skipping '%s': %s", title, reason_geo)
        return None

    # Extract funder name if present in title or content
    funder = funder_hint or "Granting Body / Global Funder"
    if "by" in title.lower():
        parts = re.split(r"\s+by\s+", title, flags=re.IGNORECASE)
        if len(parts) > 1:
            funder = parts[1].split("-")[0].split("(")[0].strip()

    opp_type = _detect_opportunity_type(title, content)
    amount_min, amount_max, currency = _extract_amount(content)
    deadline = _extract_deadline(content)
    geographic_focus = _detect_geography(content)
    sector_focus, tags = _detect_sectors_and_tags(title, content)

    short_desc = content[:480] + ("..." if len(content) > 480 else "")
    
    # Extract eligibility excerpt
    eligibility = ""
    elig_match = re.search(r"(?:eligibility|who can apply|requirements)[:\s]+([^.\n]+(?:\.[^.\n]+){1,3})", content, re.IGNORECASE)
    if elig_match:
        eligibility = elig_match.group(1).strip()
    else:
        eligibility = "Open to registered startups, social enterprises, and NGOs in Tanzania and East Africa."

    return {
        "title": title[:255],
        "funder_name": funder[:255],
        "opportunity_type": opp_type,
        "status": PostedOpportunity.Status.OPEN,
        "short_description": short_desc,
        "eligibility": eligibility,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "currency": currency,
        "deadline": deadline,
        "application_link": source_url or "",
        "geographic_focus": geographic_focus[:255],
        "sector_focus": sector_focus[:255],
        "tags": tags[:255],
    }


def ingest_opportunity(payload, posted_by=None):
    """
    Creates a PostedOpportunity record if valid and not already existing.
    Returns (instance, created).
    """
    if not payload:
        return None, False

    link = payload.get("application_link", "").strip()
    title = payload.get("title", "").strip()

    if link and PostedOpportunity.objects.filter(application_link=link).exists():
        return None, False

    if PostedOpportunity.objects.filter(title__iexact=title).exists():
        return None, False

    opp = PostedOpportunity.objects.create(
        title=payload["title"],
        funder_name=payload.get("funder_name", "Global Funder"),
        opportunity_type=payload.get("opportunity_type", PostedOpportunity.OpportunityType.GRANT),
        status=payload.get("status", PostedOpportunity.Status.OPEN),
        short_description=payload.get("short_description", ""),
        eligibility=payload.get("eligibility", ""),
        amount_min=payload.get("amount_min"),
        amount_max=payload.get("amount_max"),
        currency=payload.get("currency", "USD"),
        deadline=payload.get("deadline"),
        application_link=payload.get("application_link", ""),
        geographic_focus=payload.get("geographic_focus", "Tanzania & East Africa"),
        sector_focus=payload.get("sector_focus", "Startups & NGOs"),
        tags=payload.get("tags", "startups, grants, ngos, tanzania"),
        posted_by=posted_by,
        is_featured=False,
    )
    return opp, True


def fetch_rss_feed(feed_url, default_type=None):
    """Fetches an RSS/Atom feed and yields parsed raw items."""
    try:
        response = requests.get(feed_url, headers=DEFAULT_HEADERS, timeout=15)
        if response.status_code != 200:
            logger.warning("Feed fetch failed (%s): %s", response.status_code, feed_url)
            return []

        root = ET.fromstring(response.content)
        items = []

        for item in root.findall(".//item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            content_encoded = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            full_text = content_encoded or description

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "content": full_text,
                    "default_type": default_type,
                })

        return items
    except Exception as e:
        logger.error("Error parsing RSS feed %s: %s", feed_url, e)
        return []


def scrape_webpage_opportunity(url):
    """Scrapes a single opportunity webpage/article directly."""
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        title_el = soup.find("h1") or soup.find("title")
        title = title_el.get_text().strip() if title_el else "Funding Opportunity"

        article = soup.find("article") or soup.find("main") or soup.body
        paragraphs = [p.get_text() for p in article.find_all("p")] if article else []
        content = " ".join(paragraphs)

        return parse_opportunity_payload(title, content, url)
    except Exception as e:
        logger.error("Error scraping webpage %s: %s", url, e)
        return None


def run_opportunity_scraper(acting_user=None, custom_urls=None, max_items_per_feed=15):
    """
    Main entry point for running the Opportunity Scraper Agent with strict
    Tanzania/East Africa and Startup/NGO filters.
    """
    stats = {
        "scraped": 0,
        "created": 0,
        "skipped_duplicates": 0,
        "skipped_not_target": 0,
        "errors": [],
        "created_opportunities": [],
    }

    # 1. Process custom URLs if provided
    if custom_urls:
        for url in custom_urls:
            url = url.strip()
            if not url:
                continue
            try:
                payload = scrape_webpage_opportunity(url)
                if payload:
                    stats["scraped"] += 1
                    opp, created = ingest_opportunity(payload, posted_by=acting_user)
                    if created:
                        stats["created"] += 1
                        stats["created_opportunities"].append(opp.title)
                    else:
                        stats["skipped_duplicates"] += 1
                else:
                    stats["skipped_not_target"] += 1
            except Exception as e:
                stats["errors"].append(f"Error scraping {url}: {str(e)}")

    # 2. Process curated feed sources
    for source in DEFAULT_FEED_SOURCES:
        try:
            items = fetch_rss_feed(source["url"], default_type=source.get("default_type"))
            for item in items[:max_items_per_feed]:
                stats["scraped"] += 1
                payload = parse_opportunity_payload(
                    raw_title=item["title"],
                    raw_content=item["content"],
                    source_url=item["link"],
                    funder_hint=source["name"],
                )
                if not payload:
                    stats["skipped_not_target"] += 1
                    continue

                if source.get("default_type"):
                    payload["opportunity_type"] = source["default_type"]

                opp, created = ingest_opportunity(payload, posted_by=acting_user)
                if created:
                    stats["created"] += 1
                    stats["created_opportunities"].append(opp.title)
                else:
                    stats["skipped_duplicates"] += 1
        except Exception as e:
            stats["errors"].append(f"Error reading feed {source['name']}: {str(e)}")

    return stats
