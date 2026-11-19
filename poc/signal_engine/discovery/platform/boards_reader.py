"""Public project boards for the daily discovery task: fresh, open client projects from listing pages that robots.txt allows.

Sources (no login, no API key, no search endpoint, a handful of page requests per run, identifying User-Agent, delay):
  * freelancermap.de: project search (end customers only; recruiter postings are kept separately as staffing signals)
  * codeur.com: the public project list (French SMEs; budget, offer count and open/closed status shown)
  * peopleperhour.com: public job lists for technology and AI (UK-heavy buyers)
  * community.airtable.com: the community Jobs Board (businesses hiring Airtable/automation help)
Reading is limited to what the boards publish openly. Proposals happen in-platform, by a human. Output is candidates in the
agent_ingest format; nothing is stored here.

  python -m signal_engine.discovery.platform.boards_reader latest --days 7 [--out out/agent/boards-YYYYMMDD.json]
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

UA = {"User-Agent": "SolvantDiscovery/1.0 (low-volume lead research; respects robots.txt)", "Accept-Language": "en,de,fr"}
DELAY_S = 2.0

# Solvant-relevant work, in EN/DE/FR/ES/NL/IT (matched against title + description)
RELEVANT = re.compile(
    r"\b(automat\w*|automatis\w*|automatiz\w*|automatisier\w*|automazion\w*|n8n|make\.com|integromat|zapier|power automate|rpa|"
    r"workflow\w*|no-?code|low-?code|airtable|chatbot\w*|chat ?bot|voice ?bot|agent(e|s)? (ia|ki|ai)|ai agent\w*|ki-agent\w*|"
    r"\bki\b|\bia\b|\bai\b|llm|gpt|openai|claude|rag\b|künstliche intelligenz|intelligence artificielle|"
    r"api\b|apis\b|schnittstelle\w*|integrat\w*|intégr\w*|koppeling\w*|connect\w* (to|with)|webhook\w*|"
    r"crm|erp|odoo|hubspot|salesforce|pipedrive|zoho|xero|quickbooks|sage|datev|lexoffice|exact online|moneybird|shopify|woocommerce|"
    r"scrap\w*|extraction|data entry|saisie|dashboard\w*|reporting|google sheets|excel vba|macro\w*|bot\b|whatsapp|"
    r"prozess\w*optimier\w*|digitalisier\w*|mvp|saas|app (development|entwicklung)|application (web|mobile))\b", re.I)
NOT_FIT = re.compile(
    r"\b(cold ?call\w*|telefonakquise|vertriebspartner|setter|vermittler|sales (rep|agent)|commission only|provision|"
    r"co-?founder|mitgründer|equity only|unpaid|unbezahlt|bénévol\w*|volunteer|internship|praktikum|stage non|"
    r"seo|backlinks?|logo|video edit\w*|monteur vid\w*|youtube|tiktok|instagram reels|voice ?over|translation|traduction|"
    r"adult|erotic|onlyfans|casino|betting|crypto|token|nft|forex|trading bot|homework|assignment|essay|"
    r"open to work|for hire|i will|available for|commercial\w*|business developer|"
    r"site vitrine|landing page|website design|web design\w*|graphi\w+ design|3d (artist|model\w*)|illustrat\w*|animation|"
    r"matrimonial|dating app|game development|unity|unreal)\b", re.I)
TARGET_EU = {"DE", "AT", "CH", "FR", "BE", "LU", "NL", "IE", "GB", "UK", "ES", "PT", "IT", "DK", "SE", "NO", "FI", "PL", "CZ", "AE"}


class FetchError(RuntimeError):
    pass


def _get(url: str, timeout: int = 25) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from exc


def _text(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s or "", flags=re.I)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# core Solvant services: must appear in the title, or in the text when the title is not a non-fit role
STRONG = re.compile(
    r"\b(automat\w*|automatis\w*|automatiz\w*|automatisier\w*|automazion\w*|n8n|make\.com|integromat|zapier|power automate|rpa|"
    r"workflow\w*|no-?code|airtable|chatbot\w*|chat ?bot|voice ?bot|ai agent\w*|agent(e|s)? (ia|ki|ai)|ki-agent\w*|"
    r"\bki\b|\bia\b|\bai\b|llm|gpt|openai|claude|rag\b|"
    r"api\b|apis\b|schnittstelle\w*|integrat\w*|intégr\w*|igration|koppeling\w*|webhook\w*|odoo|crm|erp|scrap\w*|macro\w*|vba|apps script)\b", re.I)
ROLE_NOT_FIT = re.compile(
    r"\b(teacher|lehrer|dozent\w*|trainer\w*|formation|formateur|schulung|coach\w*|tutor|learn how|"
    r"manager\w*|managerin|projektmanager\w*|koordinator\w*|project (manager|coordinator)|account manager|"
    r"marketing\w*|sales|closer|vertrieb\w*|akquise|kaltakquise|recherche de client\w*|clientèle|"
    r"steuerberater\w*|buchhalter\w*|bauleiter\w*|montage\w*|kundensupport|customer support|support agent|"
    r"assistant\w*|virtual assistant|backoffice|participants? wanted|field trial|strategy|income|"
    r"qa engineer|tester|devops|cloud architect|systemadministrator|sysadmin|administrator|"
    r"ml engineer|data engineer\w*|(pakistan|india) only)\b", re.I)


def relevant(title: str, text: str) -> bool:
    if NOT_FIT.search(title or "") or ROLE_NOT_FIT.search(title or ""):
        return False
    return bool(STRONG.search(title or "")) or bool(STRONG.search((text or "")[:500]) and RELEVANT.search(title or ""))


# ------------------------------------------------------------------ relative dates ("3 hours ago", "Il y a 2 jours", "vor 2 Tagen")
_REL = [(re.compile(r"(\d+|an?|un|une)\s*(minute|min)\w*", re.I), "minutes"), (re.compile(r"(\d+|an?|un|une)\s*(hour|heure|stunde)\w*", re.I), "hours"),
        (re.compile(r"(\d+|an?|un|une)\s*(day|jour|tag)\w*", re.I), "days"), (re.compile(r"(\d+|an?|un|une)\s*(week|semaine|woche)\w*", re.I), "weeks"),
        (re.compile(r"(\d+|an?|un|une)\s*(month|mois|monat)\w*", re.I), "months"), (re.compile(r"(\d+|an?|un|une)\s*(year|an\b|ans\b|jahr)\w*", re.I), "years")]


def rel_date(s: str, now: datetime) -> Optional[str]:
    s = (s or "").strip()
    if re.search(r"\b(just now|today|aujourd'hui|heute|à l'instant)\b", s, re.I):
        return now.date().isoformat()
    if re.search(r"\b(yesterday|hier|gestern)\b", s, re.I):
        return (now - timedelta(days=1)).date().isoformat()
    for rx, unit in _REL:
        m = rx.search(s)
        if m:
            n = 1 if not m.group(1).isdigit() else int(m.group(1))
            days = {"minutes": 0, "hours": n / 24, "days": n, "weeks": 7 * n, "months": 30 * n, "years": 365 * n}[unit]
            return (now - timedelta(days=days)).date().isoformat()
    return None


def _age(d: Optional[str], now: datetime) -> Optional[int]:
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(d[:19]).replace(tzinfo=timezone.utc) if len(d) > 10 else datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - dt).days


def _cand(url, title, text, published, query, budget=None, country=None, facts=None, kind="marketplace", name=None) -> dict:
    return {"url": url, "title": title[:300], "evidence_quote": text[:700], "published_at": published, "page_read": True,
            "query": query, "kind": kind, "budget": budget, "business": {"type": "unknown", "country": country, "name": name},
            "facts": facts or {}, "board_listing": True}


# ------------------------------------------------------------------ freelancermap.de
FM_QUERIES = ["automatisierung", "n8n", "make", "zapier", "ki", "chatbot", "schnittstelle", "api integration", "crm", "workflow",
              "power automate", "airtable", "odoo"]


def parse_freelancermap(page: str, now: datetime, days: int, query: str) -> list[dict]:
    m = re.search(r'data-component-name="ProjectSearch"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    out = []
    for p in json.loads(m.group(1)).get("initialResults") or []:
        created = str(p.get("created") or "")[:10] or None
        age = _age(created, now)
        if age is None or age > days or p.get("applicationsPaused"):
            continue
        exp = p.get("expires")
        if isinstance(exp, (int, float)) and exp < now.timestamp():
            continue
        title, text = p.get("title") or "", _text(p.get("description") or "")
        if not relevant(title, text):
            continue
        end = bool(p.get("endcustomer"))
        country = ((p.get("country") or {}).get("nameEn")) or None
        budget = p.get("budget") if isinstance(p.get("budget"), str) and p.get("budget").strip() else None
        url = "https://www.freelancermap.de/projekt/" + str(p.get("slug"))
        out.append(_cand(url, title, text, created, f"freelancermap: {query}", budget, country,
                         {"end_customer": end, "contract": p.get("projectContractType") or p.get("contractType"),
                          "remote": (p.get("durationText") or ""), "poster_type": (p.get("poster") or {}).get("accountType")},
                         kind="marketplace" if end else "employment", name=(p.get("company") if end else None)))
    return out


def freelancermap(days: int, get: Callable[[str], str] = _get, now: Optional[datetime] = None, queries=FM_QUERIES) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for q in queries:
        url = "https://www.freelancermap.de/projekte?" + urllib.parse.urlencode({"query": q, "endcustomer": "true"})
        out += parse_freelancermap(get(url), now, days, q)
        time.sleep(DELAY_S)
    return out


# ------------------------------------------------------------------ codeur.com
_CD_CARD = re.compile(r'href="(/projects/\d+-[a-z0-9-]+)">\s*<div[^>]*>\s*<h3[^>]*>(.*?)</h3>\s*<span[^>]*>(.*?)</span>(.*?)'
                      r'<div class="text-blue-dark/70[^"]*"[^>]*>(.*?)</div>', re.S)


def parse_codeur(page: str, now: datetime, days: int) -> list[dict]:
    out = []
    for path, title, when, meta, desc in _CD_CARD.findall(page):
        title, desc = _text(title), _text(desc)
        if "Ouvert" not in meta:
            continue
        published = rel_date(_text(when), now)
        if _age(published, now) is None or _age(published, now) > days or not relevant(title, desc):
            continue
        b = re.search(r'title="Budget"[^>]*>.*?/>\s*([^<]+)</span>', meta, re.S)
        offers = re.search(r'title="Offres"[^>]*>\s*(\d+)', meta)
        out.append(_cand("https://www.codeur.com" + path, title, desc, published, "codeur: project list",
                         _text(b.group(1)) if b else None, "France",
                         {"bid_count": int(offers.group(1)) if offers else None, "language": "fr"}))
    return out


def codeur(days: int, get: Callable[[str], str] = _get, now: Optional[datetime] = None, pages: int = 4) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for n in range(1, pages + 1):
        out += parse_codeur(get("https://www.codeur.com/projects" + (f"?page={n}" if n > 1 else "")), now, days)
        time.sleep(DELAY_S)
    return out


# ------------------------------------------------------------------ peopleperhour.com
_PPH_CARD = re.compile(r'card__price[^>]*>.*?<span>([^<]*)</span>.*?<a class="item__url[^"]*" href="(https://www\.peopleperhour\.com/freelance-jobs/[^"]+)">'
                       r'(.*?)</a>.*?<p class="item__desc[^"]*">(.*?)</p>.*?card__footer-left[^>]*><span>([^<]*)</span>'
                       r'(?:<span class="u-mgl--1">(\d+)<!-- --> <!-- -->proposals</span>)?', re.S)
PPH_LISTS = ["https://www.peopleperhour.com/freelance-jobs/technology-programming",
             "https://www.peopleperhour.com/freelance-jobs/artificial-intelligence"]


def parse_pph(page: str, now: datetime, days: int) -> list[dict]:
    out = []
    for price, url, title, desc, when, proposals in _PPH_CARD.findall(page):
        title, desc = _text(title), _text(desc)
        published = rel_date(when, now)
        if _age(published, now) is None or _age(published, now) > days or not relevant(title, desc):
            continue
        out.append(_cand(url, title, desc, published, "peopleperhour: job list", _text(price) or None, None,
                         {"bid_count": int(proposals) if proposals else None}))
    return out


def peopleperhour(days: int, get: Callable[[str], str] = _get, now: Optional[datetime] = None, pages: int = 2) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for base in PPH_LISTS:
        for n in range(1, pages + 1):
            out += parse_pph(get(base + (f"?page={n}" if n > 1 else "")), now, days)
            time.sleep(DELAY_S)
    return out


# ------------------------------------------------------------------ community.airtable.com (Gainsight community: topic list embedded as JSON)
AIRTABLE_JOBS = "https://community.airtable.com/jobs-board-16"
_GS_TOPICS = '"topics":[{"categoryUrl"'


def parse_gainsight(page: str, now: datetime, days: int) -> list[dict]:
    out, seen, doc, dec, topics = [], set(), html.unescape(page), json.JSONDecoder(), []
    i = doc.find(_GS_TOPICS)
    while i >= 0:
        try:
            topics += dec.raw_decode(doc, i + len('"topics":'))[0]
        except ValueError:
            pass
        i = doc.find(_GS_TOPICS, i + 1)
    for t in topics:
        if not isinstance(t, dict):
            continue
        url = (t.get("topicUrl") or {}).get("destination") or ""
        published = str(t.get("publishedAt") or "")[:10] or None
        if not url.startswith("https://community.airtable.com/") or url in seen:
            continue
        seen.add(url)
        title, text = t.get("title") or "", _text(t.get("content") or "")
        if _age(published, now) is None or _age(published, now) > days or NOT_FIT.search(title):
            continue
        if re.search(r"\b(open to work|for hire|available|happy to help|maybe i can help|specialist here)\b", title, re.I):
            continue
        out.append(_cand(url, title, text, published, "airtable community: jobs board", None, None,
                         {"replies": t.get("replyCount")}, kind="customer"))
    return out


def airtable_jobs(days: int, get: Callable[[str], str] = _get, now: Optional[datetime] = None) -> list[dict]:
    return parse_gainsight(get(AIRTABLE_JOBS), now or datetime.now(timezone.utc), days)


# ------------------------------------------------------------------ verification (re-read one listing)
BOARD_HOSTS = {"www.freelancermap.de", "www.codeur.com", "www.peopleperhour.com", "community.airtable.com"}


def fetch_listing(url: str, get: Callable[[str], str] = _get) -> Optional[dict]:
    """Re-read a single listing page. Returns {"title", "closed"} or None when the listing no longer exists."""
    try:
        page = get(url)
    except FetchError as exc:
        if str(exc) in ("HTTP 404", "HTTP 410"):
            return None
        raise
    t = re.search(r'<meta property="og:title" content="([^"]+)"', page) or re.search(r"<title>([^<]+)</title>", page)
    closed = bool(re.search(r"(Projet (fermé|clôturé)|Ce projet est fermé|Projekt (ist )?(nicht mehr verfügbar|beendet|abgelaufen)|"
                            r"This job is (closed|no longer available)|Job (closed|expired))", page, re.I))
    return {"title": html.unescape(t.group(1)).strip() if t else None, "closed": closed}


SOURCES = {"freelancermap": freelancermap, "codeur": codeur, "peopleperhour": peopleperhour, "airtable": airtable_jobs}


def latest(days: int = 7, only: Optional[list[str]] = None) -> tuple[list[dict], dict]:
    cands, stats = [], {}
    for name, fn in SOURCES.items():
        if only and name not in only:
            continue
        try:
            got = fn(days)
            stats[name] = len(got)
            cands += got
        except Exception as exc:   # one board failing must not stop the others
            stats[name] = f"error: {type(exc).__name__}"
    uniq = list({c["url"]: c for c in cands}.values())
    return uniq, stats


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "latest":
        print(__doc__)
        return 2
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 7
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    cands, stats = latest(days, only)
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump(cands, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"boards": stats, "candidates": len(cands),
                      "by_kind": {k: sum(1 for c in cands if c["kind"] == k) for k in ("marketplace", "customer", "employment")}}))
    if "--out" not in argv:
        for c in cands:
            print(json.dumps({k: c[k] for k in ("url", "title", "published_at", "kind", "budget")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
