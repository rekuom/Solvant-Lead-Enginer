"""Web-search provider adapters and RSS/Atom feeds.

Findings (2026-11-06, see docs/source-registry.md): Google Custom Search JSON API is closed to new
customers (shuts down 1 Jan 2027); Bing Web Search API was retired (Aug 2025); Brave Search API needs a
card and is metered (~$5/month credit reported). No no-cost, credential-free open-web search route
exists, so adapters are built and tested with fixtures and stay DISABLED until a key is supplied.

A search hit is NEVER a verified lead: hits become RawRecords with verification
"search_snippet_only" and route to H_RESEARCH_UNVERIFIED until the page is verified.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from ...collectors.http import FetchBlocked, PoliteClient
from .. import registry
from ..models import RawRecord
from ..privacy import clean_text
from ..querylib import PROVIDER_COST, PlannedQuery
from . import RunLog


class ProviderDisabled(RuntimeError):
    pass


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str
    age: Optional[str] = None
    lang: Optional[str] = None


class SearchProvider:
    name = "base"
    registry_key = ""

    def search(self, q: PlannedQuery) -> list[SearchHit]:  # pragma: no cover - interface
        raise NotImplementedError


class BraveProvider(SearchProvider):
    """Brave Web Search API — GET https://api.search.brave.com/res/v1/web/search, header X-Subscription-Token.
    Parameters used (per Brave's API reference, checked 2026-11-06): q (≤400 chars/50 words), country (documented subset or ALL),
    search_lang (Brave codes, e.g. en-gb, pt-pt, nb), count (max 20), freshness (pd/pw/pm/py), spellcheck=0 (keep the exact phrase).
    Response: web.results[].url/title/description/page_age/age.

    TERMS: Brave "Data for Search"/"Data for AI" plans do NOT permit retaining any part of the API output; only a
    "storage rights" plan does. Results are therefore processed within the run and, by default, only aggregate counts are
    published (see run.report). Brave grants no rights to third-party pages it links to."""
    name = "brave"
    registry_key = "web_search_brave"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: Optional[str] = None, client: Optional[PoliteClient] = None, freshness: str = "pm") -> None:
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise ProviderDisabled("Brave Search API key not configured (paid/metered; not purchased)")
        self.client = client or PoliteClient(min_interval_s=1.1, check_robots=False)
        self.freshness = freshness

    def search(self, q: PlannedQuery) -> list[SearchHit]:
        country = q.country or "ALL"
        lang = q.search_lang or q.lang
        url = (f"{self.URL}?q={quote(q.query)}&count=20&freshness={self.freshness}&country={country}"
               f"&search_lang={lang}&spellcheck=0&safesearch=moderate")
        data = self.client.get_json(url, check_robots=False, headers={"X-Subscription-Token": self.api_key})
        return [SearchHit(r.get("url", ""), r.get("title", ""), r.get("description", ""), r.get("age"), q.lang)
                for r in ((data.get("web") or {}).get("results") or [])]


class FixtureProvider(SearchProvider):
    """Replays recorded/hand-made provider responses. Records are tagged 'fixture' — never leads."""
    name = "fixture"
    registry_key = "web_search_brave"

    def __init__(self, path: Path) -> None:
        self.data = json.loads(Path(path).read_text())

    def search(self, q: PlannedQuery) -> list[SearchHit]:
        return [SearchHit(**h) for h in self.data.get(q.text, [])]


def run_search(provider: SearchProvider, queries: list[PlannedQuery], max_requests: int = 10, dry_run: bool = False,
               fixture: bool = False) -> tuple[list[RawRecord], RunLog]:
    log = RunLog(f"search:{provider.name}")
    now = datetime.now(timezone.utc).isoformat()
    out: dict[str, RawRecord] = {}
    for q in queries:
        if log.requests >= max_requests or dry_run:
            log.skipped += 1
            log.event(kind="dry_run" if dry_run else "budget", query_id=q.query_id, est_cost_usd=PROVIDER_COST.get(provider.name, 0))
            continue
        log.requests += 1
        log.est_cost_usd += PROVIDER_COST.get(provider.name, 0.0)
        try:
            hits = provider.search(q)
        except FetchBlocked as exc:
            log.failed += 1
            log.event(kind="error", query_id=q.query_id, error_kind=exc.kind)
            continue
        log.ok += 1
        for h in hits:
            if not h.url.startswith("https://") or h.url in out:
                continue
            landing = landing_source(h.url)
            out[h.url] = RawRecord(source_key="web_search_brave", source_id=h.url, url=h.url, title=h.title,
                                   body=clean_text(h.snippet, limit=300),
                                   verification="fixture" if fixture else "search_snippet_only",
                                   created_at=None, state="unknown", fetched_at=now, query_id=q.query_id, language=h.lang,
                                   meta={"kind": "search_hit", "age_text": h.age, "query_category": q.category, "market": q.market,
                                         "landing_source": landing, "provider": provider.name})
        log.event(kind="ok", query_id=q.query_id, returned=len(hits))
    log.records = len(out)
    return list(out.values()), log


FEEDS = Path(__file__).resolve().parent.parent / "data" / "feeds.json"


def read_feed(xml_text: str, source_key: str, feed_id: str) -> list[RawRecord]:
    """Parse RSS 2.0 or Atom. Feed items are verified API content of that feed (title/summary as published)."""
    now = datetime.now(timezone.utc).isoformat()
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    items = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in items:
        title = (it.findtext("title") or it.findtext("a:title", namespaces=ns) or "").strip()
        link = it.findtext("link") or ""
        if not link:
            le = it.find("a:link", ns)
            link = le.get("href") if le is not None else ""
        body = it.findtext("description") or it.findtext("a:summary", namespaces=ns) or it.findtext("a:content", namespaces=ns) or ""
        date = it.findtext("pubDate") or it.findtext("a:updated", namespaces=ns) or it.findtext("a:published", namespaces=ns)
        if link.startswith("https://"):
            out.append(RawRecord(source_key=source_key, source_id=link, url=link, title=title, body=clean_text(body),
                                 verification="api_verified", created_at=_iso(date), state="unknown", fetched_at=now,
                                 query_id=f"feed:{feed_id}", meta={"kind": "feed_item"}))
    return out


def _iso(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(d).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None


def run_feeds(client: Optional[PoliteClient] = None) -> tuple[list[RawRecord], RunLog]:
    """Only feeds registered in data/feeds.json with a registry key whose status permits collection are read."""
    log = RunLog("rss_atom")
    feeds = json.loads(FEEDS.read_text()).get("feeds", []) if FEEDS.exists() else []
    if not feeds:
        log.skipped = 1
        log.event(kind="config", detail="no feeds registered (each feed needs its own verified terms)")
    client = client or PoliteClient(min_interval_s=2.0)
    out: list[RawRecord] = []
    import urllib.request
    for f in feeds:
        ok, why = registry.may_collect(f["registry_key"])
        if not ok:
            log.skipped += 1
            log.event(kind="permission", feed=f["id"], detail=why)
            continue
        log.requests += 1
        try:
            req = urllib.request.Request(f["url"], headers={"User-Agent": client.user_agent})
            with urllib.request.urlopen(req, timeout=30) as r:
                out += read_feed(r.read().decode("utf-8", "replace"), f["registry_key"], f["id"])
            log.ok += 1
        except Exception as exc:
            log.failed += 1
            log.event(kind="error", feed=f["id"], detail=str(exc)[:200])
    log.records = len(out)
    return out, log


# ----------------------------------------------------------------------------- landing-page verification
# Map result domains to registry sources. A landing page is fetched ONLY through that source's permitted API;
# no generic page scraping. Everything else stays search_snippet_only (Pipeline H) with the reason recorded.
LANDING = [
    ("github.com", "github_issues"), ("news.ycombinator.com", "hn_algolia"), ("reddit.com", "reddit"), ("linkedin.com", "linkedin"),
    ("facebook.com", "facebook_groups"), ("upwork.com", "upwork"), ("peopleperhour.com", "peopleperhour"), ("freelancer.", "freelancer_com"),
    ("malt.", "malt"), ("fiverr.com", "fiverr_briefs"), ("community.n8n.io", "n8n_community"), ("community.make.com", "make_community"),
    ("community.zapier.com", "zapier_community"), ("stackoverflow.com", "stack_exchange"), ("stackexchange.com", "stack_exchange"),
    ("indiehackers.com", "indie_hackers"), ("ukbusinessforums.co.uk", "uk_business_forums"), ("bark.com", "bark"), ("sortlist.", "sortlist"),
    ("contractsfinder.service.gov.uk", "contracts_finder"), ("find-tender.service.gov.uk", "find_a_tender"), ("ted.europa.eu", "ted"),
]
_GH_ISSUE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)")


def landing_source(url: str) -> Optional[str]:
    host = url.split("/")[2].lower() if url.count("/") >= 2 else ""
    for dom, key in LANDING:
        if dom in host:
            return key
    return None


def verify_landing(records: list[RawRecord], client: Optional[PoliteClient] = None, token: Optional[str] = None,
                   max_requests: int = 20) -> tuple[list[RawRecord], RunLog]:
    """Replace a snippet with source-verified content where the landing source offers a PERMITTED API (today: GitHub
    issues). The verified record is the source's own data (provenance keeps the search query id). Others are annotated."""
    from .github import API, _headers, item_to_record
    log = RunLog("landing_verification")
    client = client or PoliteClient(min_interval_s=2.2 if token else 6.5, check_robots=False)
    out: list[RawRecord] = []
    for r in records:
        key = r.meta.get("landing_source")
        m = _GH_ISSUE.match(r.url)
        if key == "github_issues" and m and log.requests < max_requests and registry.may_collect("github_issues")[0]:
            log.requests += 1
            try:
                it = client.get_json(f"{API}/repos/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}", check_robots=False, headers=_headers(token))
                v = item_to_record(it, None, r.fetched_at or "")
                if v:
                    v.query_id = r.query_id
                    v.meta["discovered_via"] = r.meta.get("provider", "search")
                    v.meta["query_category"] = r.meta.get("query_category")
                    out.append(v)
                    log.ok += 1
                    continue
            except FetchBlocked as exc:
                log.failed += 1
                log.event(kind="error", url_source=key, error_kind=exc.kind)
        r.meta["landing_verification"] = ("not attempted: " + (registry.policy(key)["status"] if key else "unknown source; no permitted API")
                                          if key != "github_issues" else "not attempted: budget")
        out.append(r)
    log.records = sum(1 for r in out if r.verification == "api_verified")
    return out, log
