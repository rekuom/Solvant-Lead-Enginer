"""Discourse forum collector (n8n Community "Jobs", Make Community "Hire a Pro").

Discourse exposes public JSON for any public page (append `.json`). That is a
technical capability, NOT a licence: commercial collection requires checking
each forum's Terms of Service / robots.txt and ideally written permission from
the community owner (see docs/data-sources.md). The client honours robots.txt.

Category listing: GET https://<host>/c/<slug>/<id>.json   -> topic_list.topics[]
Topic detail:     GET https://<host>/t/<topic_id>.json    -> post_stream.posts[0]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..models import Signal
from ..textutil import make_excerpt, normalise_ws
from .http import PoliteClient

FORUMS = {
    "community.n8n.io": {"category": "c/jobs/13"},
    "community.make.com": {"category": "c/hire-a-pro/50"},
}


def topic_url(host: str, topic: dict[str, Any]) -> str:
    slug = topic.get("slug") or "topic"
    return f"https://{host}/t/{slug}/{topic['id']}"


def parse_topic(host: str, topic_json: dict[str, Any], verification_status: str = "verified_api",
                collected_at: Optional[str] = None) -> Optional[Signal]:
    posts = (topic_json.get("post_stream") or {}).get("posts") or []
    if not posts:
        return None
    first = posts[0]
    return Signal(
        source=f"discourse:{host}",
        source_id=str(topic_json["id"]),
        url=topic_url(host, topic_json),
        title=normalise_ws(topic_json.get("title") or ""),
        text=make_excerpt(first.get("cooked") or first.get("raw") or ""),
        verification_status=verification_status,
        posted_at=first.get("created_at") or topic_json.get("created_at"),
        collected_at=collected_at or datetime.now(timezone.utc).isoformat(),
        author_handle=first.get("username"),  # public forum handle only
        raw_meta={"kind": "forum_post", "closed": topic_json.get("closed"),
                  "archived": topic_json.get("archived"), "category_id": topic_json.get("category_id")},
    )


def fetch_forum(client: PoliteClient, host: str, max_topics: int = 30,
                since: Optional[datetime] = None) -> list[Signal]:
    """Fetch recent topics. Topics created before `since` are skipped *before* the
    detail request, to keep load on the forum minimal."""
    cfg = FORUMS[host]
    listing = client.get_json(f"https://{host}/{cfg['category']}.json")
    topics = (listing.get("topic_list") or {}).get("topics") or []
    out: list[Signal] = []
    for t in topics[:max_topics]:
        if t.get("pinned"):
            continue  # category rules / "about" topics
        if since is not None and t.get("created_at"):
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
            if created < since:
                continue
        detail = client.get_json(f"https://{host}/t/{t['id']}.json")
        sig = parse_topic(host, detail)
        if sig:
            out.append(sig)
    return out
