"""Text normalisation, PII redaction and URL canonicalisation."""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EXCERPT_MAX_CHARS = 600

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone-ish: 9+ digits possibly separated by spaces, dashes, dots, brackets, leading +
_PHONE_RE = re.compile(r"(?<![\w£$€])\+?\(?\d[\d\s().-]{7,}\d(?![\w])")

# Query params that never identify content (tracking / translation / UI state).
_DROP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "tl", "origin", "p", "fbclid", "gclid", "share",
}

# Site-name suffixes that search engines / forums append to titles.
_TITLE_SUFFIX_RE = re.compile(
    r"\s+-\s+(Jobs|Hire Help|Community Archive|Help me Build my Workflow)\s+-\s+"
    r"(n8n|Make) Community\s*$"
    r"|\s+-\s+(n8n|Make) Community\s*$"
    r"|\s+-\s+Contracts Finder( - GOV\.UK)?\s*$"
    r"|\s+-\s+Find a Tender\s*$",
    re.IGNORECASE,
)


def strip_html(s: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", s or ""))


def normalise_ws(s: str) -> str:
    return _WS_RE.sub(" ", s or "").strip()


def redact_pii(s: str) -> str:
    """Remove emails and phone numbers. We never need them: outreach goes via the source."""
    s = _EMAIL_RE.sub("[email removed]", s)
    s = _PHONE_RE.sub("[phone removed]", s)
    return s


def make_excerpt(raw: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    text = redact_pii(normalise_ws(strip_html(raw)))
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


def clean_title(title: str) -> str:
    return normalise_ws(_TITLE_SUFFIX_RE.sub("", normalise_ws(title)))


def canonical_url(url: str) -> str:
    """Canonicalise a URL so the same page from different links dedupes."""
    parts = urlsplit(url.strip())
    scheme = "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www.") and not host.endswith(".gov.uk"):
        host = host[4:]
    path = parts.path or "/"
    # Contracts Finder serves /Notice/ and /notice/ — treat case-insensitively there.
    if host.endswith("contractsfinder.service.gov.uk") or host.endswith("find-tender.service.gov.uk"):
        path = path.lower()
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _DROP_PARAMS))
    return urlunsplit((scheme, host, path, query, ""))


def fingerprint(text: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", normalise_ws(text.lower()))
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def shingles(text: str, k: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9£$€]+", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
