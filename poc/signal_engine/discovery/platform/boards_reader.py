"""Public project boards for the daily discovery task: fresh, open client projects from listing pages that robots.txt allows.

Sources (no login, no API key, no search endpoint, a handful of page requests per run, identifying User-Agent, delay):
  * freelancermap.de: project search (end customers only; recruiter postings are kept separately as staffing signals)
  * codeur.com: the public project list (French SMEs; budget, offer count and open/closed status shown)
  * peopleperhour.com: public job lists for technology and AI (UK-heavy buyers)
  * community.airtable.com: the community Jobs Board (businesses hiring Airtable/automation help)
Reading is limited to what the boards publish openly. Proposals happen in-platform, by a human. Output is candidates in the
agent_ingest format; nothing is stored here.

  python -m signal_engine.discovery.platform.boards_reader latest --days 7 [--out out/agent/boards-YYYYMMDD.json]
  python -m signal_engine.discovery.platform.boards_reader recheck [--limit 40]   # re-verify open board leads already saved
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
            final = urllib.parse.urlsplit(r.geturl())
            if final.path in ("", "/") and urllib.parse.urlsplit(url).path not in ("", "/"):
                raise FetchError("HTTP 410")      # a listing that now redirects to the site's home page has been removed
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
# Levels, strongest first. Only "verified_open" means the source itself states the opportunity is open now.
STATUSES = ("verified_open", "verified_posted", "reachable_unconfirmed", "closed", "removed", "unreachable")
_FR_MONTHS = {m: i + 1 for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
                                              "octobre", "novembre", "décembre"])}
_CLOSED = re.compile(r"(Projet (fermé|clôturé|terminé|attribué)|Ce projet est (fermé|clôturé)|Projekt (ist )?(nicht mehr verfügbar|beendet|"
                     r"abgelaufen|vergeben)|Bewerbungen (sind )?pausiert|This (job|project) (is|has been) (closed|awarded|cancelled)|"
                     r"Project (Closed|Awarded|Cancelled)|no longer (available|accepting))", re.I)


def _plain(page: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def _jobposting(page: str) -> dict:
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(raw.strip())
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return {}


def _words(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9à-ÿ]{3,}", (t or "").lower())}


def title_matches(expected: Optional[str], found: Optional[str]) -> bool:
    a, b = _words(expected or ""), _words(found or "")
    if not a or not b:
        return False
    return len(a & b) / max(1, min(len(a), len(b))) >= 0.6


def _iso(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(d))
    return m.group(1) if m else None


def _parse_codeur(page: str, text: str) -> dict:
    r: dict = {}
    m = re.search(r"\b(Ouvert|Fermé|Clôturé|Terminé|Attribué|En cours|En travail|Annulé)\s*·", text)
    if m:
        r["open"] = m.group(1) == "Ouvert"
        r["state_text"] = m.group(1)
    m = re.search(r"Publication\s*:\s*(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", text, re.I)
    if m and m.group(2).lower() in _FR_MONTHS:
        r["posted_at"] = f"{int(m.group(3)):04d}-{_FR_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"Budget indicatif\s*:\s*(.+?)\s+Publication", text)
    r["budget"] = m.group(1).strip()[:60] if m else None
    m = re.search(r"(\d+)\s+offres", text)
    r["bids"] = int(m.group(1)) if m else None
    m = re.search(r"Publier un projet similaire\s+(?:p:last-child\]:mb-0\">\s*)?(.+?)\s+(?:\.detail:last-child\]:mb-8\">\s*)?Budget indicatif", text)
    r["requirements"] = m.group(1)[:700] if m else None
    m = re.search(r"Profils recherchés\s*:\s*(.+?)(?:\s{2,}|Compétences|$)", text)
    r["wanted"] = m.group(1)[:200] if m else None
    return r


def _parse_pph(page: str, text: str) -> dict:
    jp, r = _jobposting(page), {}
    r["posted_at"], r["valid_through"] = _iso(jp.get("datePosted")), _iso(jp.get("validThrough"))
    r["title"] = html.unescape(jp.get("title") or "") or None
    m = re.search(r"#\d{5,}\s+(Archived|Closed|Awarded|Cancelled|Expired|OPPORTUNITY Open for Proposals)", text)
    if m:
        r["open"], r["state_text"] = m.group(1).endswith("Open for Proposals"), m.group(1).replace("OPPORTUNITY ", "")
    elif re.search(r"Open for Proposals", text):
        r["open"], r["state_text"] = True, "Open for Proposals"
    m = re.search(r"(Fixed Price|Hourly Rate|Per Hour)\s*([£$€])\s*([\d,.]+[kK]?)", text)
    r["budget"] = (f"{m.group(2)}{m.group(3)}" + ("/hour" if m.group(1) != "Fixed Price" else " (fixed price)")) if m else None
    m = re.search(r"Proposals:\s*(\d+)", text)
    r["bids"] = int(m.group(1)) if m else None
    m = re.search(r"Description\s+(?:Experience Level:\s*\w+\s+)?(.+?)\s+(?:Clarification Board|Login to your account|New Proposal)", text)
    r["requirements"] = (m.group(1) if m else _text(jp.get("description") or ""))[:700] or None
    return r


def _parse_freelancermap(page: str, text: str) -> dict:
    jp, r = _jobposting(page), {}
    r["posted_at"], r["valid_through"] = _iso(jp.get("datePosted")), _iso(jp.get("validThrough"))
    r["title"] = jp.get("title")
    if re.search(r"\bBewerben\b", text) and not _CLOSED.search(text):
        r["open"], r["state_text"] = True, "Bewerben (applications open)"
    r["end_customer"] = "Endkundenprojekt" in text
    m = re.search(r"Beschreibung\s+(.+?)\s+(?:Ähnliche Projekte|Projekt-Ansprechpartner|Kontakt|Freelancer finden)", text)
    r["requirements"] = (m.group(1) if m else _text(jp.get("description") or ""))[:700] or None
    return r


def _parse_airtable(page: str, text: str) -> dict:
    m = re.search(r'"publishedAt"\s*:\s*"([^"]+)"', html.unescape(page))
    return {"posted_at": _iso(m.group(1)) if m else None}


def check_listing(url: str, expected_title: Optional[str] = None, get: Callable[[str], str] = _get,
                  now: Optional[datetime] = None) -> dict:
    """Re-read one listing and report what the SOURCE itself confirms: reachable, title, posting date, open status, budget, bids,
    requirements. 'verified_open' only when the page is reachable, the title matches and the board states the project is open
    (and any stated expiry date has not passed). A reachable page without an explicit open status is never called verified."""
    now = now or datetime.now(timezone.utc)
    out = {"url": url, "checked_at": now.isoformat(timespec="seconds"), "reachable": False, "title": None, "title_match": False,
           "posted_at": None, "date_confirmed": False, "open_confirmed": False, "valid_through": None, "budget": None, "bids": None,
           "requirements": None, "status": "unreachable", "checks": []}
    try:
        page = get(url)
    except FetchError as exc:
        if str(exc) in ("HTTP 404", "HTTP 410"):
            out.update(status="removed", checks=["listing no longer exists (HTTP 404/410)"])
        else:
            out["checks"].append(f"not reachable ({exc})")
        return out
    except Exception as exc:   # network errors: never fatal, never 'verified'
        out["checks"].append(f"not reachable ({type(exc).__name__})")
        return out
    out["reachable"] = True
    text = _plain(page)
    t = re.search(r'<meta property="og:title" content="([^"]+)"', page) or re.search(r"<title[^>]*>([^<]+)</title>", page)
    title = html.unescape(t.group(1)).strip() if t else None
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    parsed = {"www.codeur.com": _parse_codeur, "www.peopleperhour.com": _parse_pph, "www.freelancermap.de": _parse_freelancermap,
              "community.airtable.com": _parse_airtable}.get(host, lambda p, x: {})(page, text)
    title = parsed.pop("title", None) or title
    if title:
        title = re.sub(r"\s*(-|\|)\s*PeoplePerHour.*$|\s+auf www\.freelancermap\.de$", "", title).strip()
    out["title"] = html.unescape(title) if title else title
    out["title_match"] = title_matches(expected_title, title) if expected_title else bool(title)
    out["posted_at"] = parsed.get("posted_at")
    out["date_confirmed"] = bool(out["posted_at"])
    out["valid_through"] = parsed.get("valid_through")
    for k in ("budget", "bids", "requirements"):
        out[k] = parsed.get(k)
    for k in ("state_text", "wanted", "end_customer"):
        if parsed.get(k) is not None:
            out[k] = parsed[k]
    expired = bool(out["valid_through"] and out["valid_through"] < now.date().isoformat())
    closed = parsed.get("open") is False or bool(_CLOSED.search(text)) or expired
    out["open_confirmed"] = bool(parsed.get("open")) and not closed
    checks = ["page reachable"]
    checks.append("title matches the lead" if out["title_match"] else "title differs from the lead")
    checks.append(f"posted {out['posted_at']} (stated by the board)" if out["date_confirmed"] else "posting date not stated on the page")
    if closed:
        checks.append("board shows the project as closed" + (" (expired)" if expired else ""))
        out["status"] = "closed"
    elif out["open_confirmed"] and out["title_match"]:
        checks.append(f"board states it is open ({parsed.get('state_text')})")
        out["status"] = "verified_open"
    elif out["title_match"] and out["date_confirmed"]:
        checks.append("availability not stated by the source")
        out["status"] = "verified_posted"
    else:
        out["status"] = "reachable_unconfirmed"
    out["checks"] = checks
    return out


def fetch_listing(url: str, get: Callable[[str], str] = _get) -> Optional[dict]:
    """Backward-compatible wrapper: None when removed; otherwise {"title", "closed"}."""
    c = check_listing(url, get=get)
    if c["status"] == "removed":
        return None
    if c["status"] == "unreachable":
        raise FetchError("unreachable")
    return {"title": c["title"], "closed": c["status"] == "closed"}


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


def recheck(limit: int = 40, get: Callable[[str], str] = _get, rpc_fn=None, delay: float = DELAY_S) -> dict:
    """Re-verify saved board leads that are still open: what the board states today (open / closed / removed). Counts only."""
    if rpc_fn is None:
        from .rest import rpc as rpc_fn
    due = rpc_fn("board_checks_due", {"p_token": os.environ.get("SIGNAL_INGEST_TOKEN", ""), "p_limit": limit}) or []
    checks = []
    for d in due:
        c = check_listing(d["url"], d.get("title"), get=get)
        checks.append({k: v for k, v in c.items() if k != "requirements"})
        time.sleep(delay)
    res = rpc_fn("record_board_checks", {"p_token": os.environ.get("SIGNAL_INGEST_TOKEN", ""), "p_checks": checks}) if checks else {}
    by = {}
    for c in checks:
        by[c["status"]] = by.get(c["status"], 0) + 1
    return {"checked": len(checks), "by_status": by, "database": res}


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "recheck":
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 40
        print(json.dumps(recheck(limit)))
        return 0
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
