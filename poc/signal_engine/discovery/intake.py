"""Marketplace / manual / licensed-lead intake.

Routes supported (all legitimate, user-initiated):
  1. manual entry (CLI)                      -> verification "user_submitted"
  2. CSV / JSON import (alerts, exports the user is entitled to)  -> "user_submitted"
  3. user-authorised alert e-mails (.eml)    -> "user_submitted" (one record per project link)
  4. licensed lead-feed rows (lead marketplaces)                  -> "licensed_import"
A reviewer later promotes a record to "reviewer_verified" after opening the original URL.

Storage is PRIVATE: poc/out/private/ (git-ignored). Nothing here is committed or uploaded unredacted.
Platform rules (can propose / off-platform contact / export / agency accounts) come from the registry;
off-platform contact is never assumed.
"""

from __future__ import annotations

import csv
import email
import json
import re
from datetime import datetime, timezone
from email import policy as email_policy
from pathlib import Path
from typing import Iterable, Optional

from ..textutil import canonical_url, fingerprint
from . import registry
from .models import RawRecord
from .privacy import clean_text

PRIVATE = Path("out/private")
STORE = PRIVATE / "intake.jsonl"
FIELDS = ("source_key", "url", "post_date", "title", "text", "organisation", "stated_role", "country", "budget", "notes")

# Known project-link patterns in alert e-mails, by registry key.
_U = r"[^\s\"'<>)]+"
EMAIL_LINKS = {
    "upwork": re.compile(rf"https://www\.upwork\.com/(?:jobs/|freelance-jobs/apply/|ab/proposals/job/|nx/search/jobs/details/|nx/proposals/job/){_U}"),
    "freelancer_com": re.compile(rf"https://www\.freelancer\.[a-z.]{{2,6}}/projects/{_U}"),
    "peopleperhour": re.compile(rf"https://www\.peopleperhour\.com/freelance-jobs/{_U}"),
    "malt": re.compile(rf"https://www\.malt\.[a-z.]{{2,6}}/{_U}(?:project|mission|opportunit|offer){_U}|https://www\.malt\.[a-z.]{{2,6}}/(?:project|mission|opportunit|offer){_U}"),
    "fiverr_briefs": re.compile(rf"https://www\.fiverr\.com/{_U}brief{_U}|https://www\.fiverr\.com/briefs{_U}"),
    "bark": re.compile(rf"https://www\.bark\.com/{_U}"),
}
# Sender / link domains per platform: used when an alert's link format is not recognised.
PLATFORM_DOMAINS = {"upwork": "upwork.com", "freelancer_com": "freelancer.", "peopleperhour": "peopleperhour.com", "malt": "malt.",
                    "fiverr_briefs": "fiverr.com", "bark": "bark.com"}


class IntakeError(ValueError):
    pass


def _verification(source_key: str) -> str:
    return "licensed_import" if registry.policy(source_key)["family"] == "lead_marketplace" else "user_submitted"


def make_record(row: dict, origin: str, fixture: bool = False) -> RawRecord:
    key = (row.get("source_key") or "").strip()
    ok, why = registry.may_intake(key)
    if not ok:
        raise IntakeError(why)
    url = (row.get("url") or "").strip()
    if not url.startswith("https://"):
        raise IntakeError(f"original https URL required (got {url!r})")
    text = (row.get("text") or "").strip()
    if not text and not row.get("title"):
        raise IntakeError("post text or title required")
    date = (row.get("post_date") or "").strip() or None
    if date:
        try:
            datetime.fromisoformat(date.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IntakeError(f"post_date must be ISO-8601 (got {date!r})") from exc
    meta = {"kind": "intake", "origin": origin, "notes": (row.get("notes") or "")[:300],
            "marketplace_rules": registry.marketplace_rules(key)}
    if row.get("budget"):
        meta["budget"] = str(row["budget"])[:60]
    return RawRecord(source_key=key, source_id=canonical_url(url), url=url, title=(row.get("title") or text[:100]).strip(),
                     body=clean_text(text, limit=1200), verification="fixture" if fixture else _verification(key), created_at=date,
                     state="unknown", fetched_at=datetime.now(timezone.utc).isoformat(), query_id=f"intake:{origin}",
                     organisation=(row.get("organisation") or "").strip() or None,
                     stated_role=(row.get("stated_role") or "").strip() or None,
                     country_hint=(row.get("country") or "").strip() or None, meta=meta)


def read_csv(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def read_json(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text())
    return data if isinstance(data, list) else data.get("records", [])


def read_email(path: Path, source_key: Optional[str] = None) -> list[dict]:
    """Parse a user-forwarded alert e-mail into rows (one per recognised project link)."""
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=email_policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.I)
        hrefs = " ".join(re.findall(r'href="([^"]+)"', text, flags=re.I))
        text = re.sub(r"<[^>]+>", " ", text) + "\n" + hrefs
    visible = re.sub(r"https?://\S+", " ", text.split("\n" + hrefs)[0] if body is not None and body.get_content_type() == "text/html" else text)
    # Alert e-mails wrap links in tracking redirects (…?url=https%3A%2F%2Fwww.upwork.com%2Fjobs%2F…): unwrap them.
    from urllib.parse import unquote
    text = text + "\n" + unquote(unquote(text))
    sender = str(msg.get("From", "")).lower()
    date = msg.get("Date")
    iso = None
    if date:
        try:
            iso = email.utils.parsedate_to_datetime(date).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            iso = None
    rows = []
    for key, rx in EMAIL_LINKS.items():
        if source_key and key != source_key:
            continue
        found = [u for u in dict.fromkeys(m.rstrip(").,") for m in rx.findall(text)) if "%" not in u]
        if not found and PLATFORM_DOMAINS[key] in sender:
            # unrecognised link format: keep the e-mail as one record with the first platform link, flagged for review
            generic = re.findall(rf"https://[a-z.]*{re.escape(PLATFORM_DOMAINS[key])}[^\s\"'<>)]*", text)
            if generic:
                rows.append({"source_key": key, "url": generic[0], "post_date": None, "title": str(msg.get("Subject", ""))[:120],
                             "text": re.sub(r"\s+", " ", text)[:600], "notes": "alert link format not recognised; verify the project URL manually"})
            continue
        for n, m in enumerate(found):
            # excerpt: visible text around the link when the link is visible; otherwise the n-th visible block
            i = text.find(m)
            if 0 <= i < len(visible):
                # segment = text after the previous project link up to the end of this link (no bleed between projects)
                prev_end = max((text.find(x) + len(x) for x in found[:n] if 0 <= text.find(x) < i), default=0)
                ctx = text[max(prev_end, i - 600): i + len(m)]
            else:
                blocks = [b.strip() for b in re.split(r"\n\s*\n|-{3,}", visible) if len(b.strip()) > 30]
                ctx = blocks[n] if n < len(blocks) else visible[:600]
            ctx = re.sub(r"<[^>]+>|https?://\S+", " ", ctx)
            rows.append({"source_key": key, "url": m.rstrip(").,"), "post_date": iso, "title": str(msg.get("Subject", ""))[:120],
                         "text": ctx, "notes": "imported from a user-authorised alert e-mail; alert date used as post date"})
    return rows


def load_store(path: Path = STORE) -> list[RawRecord]:
    if not path.exists():
        return []
    return [RawRecord(**json.loads(l)) for l in path.read_text().splitlines() if l.strip()]


def add(rows: Iterable[dict], origin: str, path: Path = STORE, fixture: bool = False) -> dict:
    """Validate, deduplicate (URL and content) and append to the private store. Returns a summary."""
    existing = load_store(path)
    seen_url = {canonical_url(r.url) for r in existing}
    seen_fp = {fingerprint(r.title + " " + r.body) for r in existing}
    added, dups, errors = [], [], []
    for i, row in enumerate(rows):
        try:
            rec = make_record(row, origin, fixture=fixture)
        except IntakeError as exc:
            errors.append({"row": i, "error": str(exc)})
            continue
        cu, fp = canonical_url(rec.url), fingerprint(rec.title + " " + rec.body)
        if cu in seen_url or fp in seen_fp:
            dups.append({"row": i, "url": rec.url})
            continue
        seen_url.add(cu)
        seen_fp.add(fp)
        added.append(rec)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for r in added:
                fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    return {"added": len(added), "duplicates": dups, "errors": errors, "store": str(path)}
