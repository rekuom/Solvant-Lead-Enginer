"""Read-only helper for the scheduled discovery task: fresh 'hiring' topics from public Discourse forums.

Uses only public endpoints that the forums' robots.txt allows (category listing + single topic JSON), one listing request
per forum per run plus at most --max-threads topic reads, with a polite delay and an identifying User-Agent. No login, no
search endpoints, no crawling of pagination. Output is for the agent to qualify; nothing is stored here.

  python -m signal_engine.discovery.platform.forum_reader latest --days 3            # fresh hiring topics (titles + urls)
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
FORUMS = [  # (host, category slug, category id) — public hiring categories
    ("community.make.com", "hire-help", 74),
    ("community.n8n.io", "jobs", 13),
]
DELAY_S = 1.5
SELLER = re.compile(r"\[?\s*for\s*hire\s*\]?|\bi will\b|\boffer(ing)? (my|our) services\b|\bavailable for (work|projects)\b", re.I)
NOT_BUYER = re.compile(r"\bfull[- ]time\b|\bsalary\b|\binternship\b|\bvolunteer\b|\bcommission[- ]based\b|\bunpaid\b|"
                       r"\breferral partners?\b|\bbusiness development\b|\bBD\b", re.I)


def _get(url: str) -> dict:
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))


def filter_topics(topics: Iterable[dict], host: str, days: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(days=days)
    out = []
    for t in topics:
        created = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
        title = str(t.get("title") or "")
        if created < cut or SELLER.search(title) or NOT_BUYER.search(title):
            continue
        out.append({"url": f"https://{host}/t/{t.get('slug') or 'topic'}/{t['id']}", "title": title,
                    "created": created.date().isoformat(), "posts": t.get("posts_count")})
    return out


def latest(days: int = 3) -> list[dict]:
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


def thread(urls: list[str], max_threads: int = 25) -> list[dict]:
    out = []
    for u in urls[:max_threads]:
        m = re.match(r"https://([^/]+)/t/(?:[^/]+/)?(\d+)", u)
        if not m or m.group(1) not in {h for h, _, _ in FORUMS} | {"community.zapier.com"}:
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
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 3
        print(json.dumps(latest(days), ensure_ascii=False, indent=1))
        return 0
    if argv[:1] == ["thread"]:
        print(json.dumps(thread(argv[1:]), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
