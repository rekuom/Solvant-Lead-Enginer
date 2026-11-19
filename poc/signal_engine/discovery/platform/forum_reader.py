"""Read-only helper for the scheduled discovery task: fresh 'hiring' topics from public Discourse forums.

Uses only public endpoints that the forums' robots.txt allows (category listing + single topic JSON), one listing request
per forum per run plus at most --max-threads topic reads, with a polite delay and an identifying User-Agent. No login, no
search endpoints, no crawling of pagination. Output is for the agent to qualify; nothing is stored here.

  python -m signal_engine.discovery.platform.forum_reader latest --days 7            # fresh hiring topics (titles + urls)
  python -m signal_engine.discovery.platform.forum_reader thread URL [URL...]        # topic text for qualification
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

UA = {"User-Agent": "SolvantDiscovery/1.0 (low-volume lead research; respects robots.txt)"}
FORUMS = [  # (host, category slug, category id) — public hiring categories (robots.txt permits listing + topic JSON)
    ("community.make.com", "hire-help", 74),
    ("community.n8n.io", "jobs", 13),
    ("forum.bubble.io", "jobs-freelance", 13),
    ("community.weweb.io", "jobs", 22),
    ("community.activepieces.com", "marketplace", 8),
    ("community.latenode.com", "find-the-perfect-partner-to-support-your-business-needs", 9),
]
FORUM_HOSTS = {h for h, _, _ in FORUMS}
DELAY_S = 1.5
SELLER = re.compile(r"\[?\s*for\s*hire\s*\]?|\bi will\b|\boffer(ing)? (my|our) services\b|\bavailable for (work|projects)\b|"
                    r"\bopen to (work|projects)\b|\bhire me\b|\[offer", re.I)
# not demand at all: unpaid / commission-only / internships / volunteers / sales-partner recruiting
NOT_DEMAND = re.compile(r"\binternship\b|\bvolunteer\b|\bcommission[- ](based|only)\b|\bunpaid\b|\bsweat equity\b|"
                        r"\breferral partners?\b|\bbusiness development\b|\bBD\b|\bco-?founder\b", re.I)
# employment: kept, but labelled so it lands in the separate recruitment pipeline (F), never mixed with customers
EMPLOYMENT = re.compile(r"\bfull[- ]time\b|\bsalary\b|\bper (month|year|annum)\b|/month\b|\bk/yr\b|\bbenefits\b|\bpermanent\b|"
                        r"\bjoin our team\b|\bhybrid\b|\bon-?site\b", re.I)


def _get(url: str) -> dict:
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))


def filter_topics(topics: Iterable[dict], host: str, days: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(days=days)
    out = []
    for t in topics:
        created = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
        title = str(t.get("title") or "")
        if created < cut or SELLER.search(title) or NOT_DEMAND.search(title):
            continue
        out.append({"url": f"https://{host}/t/{t.get('slug') or 'topic'}/{t['id']}", "title": title,
                    "created": created.date().isoformat(), "posts": t.get("posts_count"),
                    "kind": "employment" if EMPLOYMENT.search(title) else "project_or_partner"})
    return out


def latest(days: int = 7) -> list[dict]:
    found = []
    for host, slug, cid in FORUMS:
        try:
            data = _get(f"https://{host}/c/{slug}/{cid}.json")
            found += filter_topics(data["topic_list"]["topics"], host, days)
        except Exception as exc:   # one forum failing must not stop the others
            found.append({"error": f"{host}: {type(exc).__name__}"})
        time.sleep(DELAY_S)
    return found


def topic_text(d: dict) -> dict:
    p = (d.get("post_stream") or {}).get("posts", [{}])[0]
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p.get("cooked", "")))).strip()
    return {"title": d.get("title"), "created": str(d.get("created_at", ""))[:10], "closed": d.get("closed"), "text": text[:1500]}


def fetch_topic(url: str) -> Optional[dict]:
    """Official Discourse topic JSON for an approved forum URL (used for automatic source verification)."""
    m = re.match(r"https://([^/]+)/t/(?:[^/]+/)?(\d+)", url)
    if not m or m.group(1) not in FORUM_HOSTS:
        return None
    return topic_text(_get(f"https://{m.group(1)}/t/{m.group(2)}.json"))


def thread(urls: list[str], max_threads: int = 25) -> list[dict]:
    out = []
    for u in urls[:max_threads]:
        m = re.match(r"https://([^/]+)/t/(?:[^/]+/)?(\d+)", u)
        if not m or m.group(1) not in FORUM_HOSTS:
            out.append({"url": u, "error": "not an approved forum thread"})
            continue
        try:
            out.append({"url": u.split("?")[0], **topic_text(_get(f"https://{m.group(1)}/t/{m.group(2)}.json"))})
        except Exception as exc:
            out.append({"url": u, "error": type(exc).__name__})
        time.sleep(DELAY_S)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["latest"]:
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 7
        print(json.dumps(latest(days), ensure_ascii=False, indent=1))
        return 0
    if argv[:1] == ["thread"]:
        print(json.dumps(thread(argv[1:]), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
