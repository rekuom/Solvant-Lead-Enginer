"""Hacker News connector (official Algolia HN Search API).

Registry status: RESTRICTED. The API is public and intended for third-party apps, but commercial
reuse terms could not be confirmed, so the connector runs only when the operator explicitly opts in
(--allow-restricted hn_algolia) after reviewing the terms.

Highest-value target: the monthly "Freelancer? Seeking freelancer?" thread, where buyers post
top-level comments starting "SEEKING FREELANCER". Only those are treated as buyer posts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import quote

from ...collectors.http import FetchBlocked, PoliteClient
from .. import registry
from ..models import RawRecord
from ..privacy import author_ref, clean_text
from ..querylib import PlannedQuery
from . import RunLog

ALGOLIA = "https://hn.algolia.com/api/v1"
SOURCE = "hn_algolia"
SEEKING = re.compile(r"^\s*(?:<p>)?\s*seeking\s+freelancer", re.I)


def hit_to_record(h: dict, query_id: str, now: str) -> Optional[RawRecord]:
    oid = h.get("objectID") or h.get("id")
    if not oid:
        return None
    text = h.get("comment_text") or h.get("story_text") or h.get("text") or ""
    created = h.get("created_at")
    return RawRecord(source_key=SOURCE, source_id=str(oid), url=f"https://news.ycombinator.com/item?id={oid}",
                     title=(h.get("title") or h.get("story_title") or text[:90] or "").strip(), body=clean_text(text),
                     verification="api_verified", created_at=created, state="unknown", fetched_at=now, query_id=query_id,
                     author_ref=author_ref(h.get("author")), meta={"kind": "forum_post", "hn_type": (h.get("_tags") or [""])[0]})


def seeking_freelancer(client: Optional[PoliteClient] = None, allow_restricted: Iterable[str] = (), max_comments: int = 200,
                       log: Optional[RunLog] = None) -> tuple[list[RawRecord], RunLog]:
    log = log or RunLog(SOURCE)
    ok, why = registry.may_collect(SOURCE, allow_restricted)
    if not ok:
        log.skipped += 1
        log.event(kind="permission", detail=why)
        return [], log
    client = client or PoliteClient(min_interval_s=1.0, check_robots=False)
    now = datetime.now(timezone.utc).isoformat()
    try:
        log.requests += 1
        res = client.get_json(f"{ALGOLIA}/search_by_date?query={quote('Freelancer? Seeking freelancer?')}&tags=story,author_whoishiring&hitsPerPage=1",
                              check_robots=False)
        hits = res.get("hits") or []
        if not hits:
            log.ok += 1
            log.event(kind="ok", detail="no thread found")
            return [], log
        thread = hits[0]
        log.requests += 1
        item = client.get_json(f"{ALGOLIA}/items/{thread['objectID']}", check_robots=False)
        log.ok += 2
    except FetchBlocked as exc:
        log.failed += 1
        log.event(kind="error", error_kind=exc.kind, detail=str(exc)[:200])
        return [], log
    out = []
    for c in (item.get("children") or [])[:max_comments]:
        if c.get("text") and SEEKING.search(c["text"]):
            r = hit_to_record({"objectID": c.get("id"), "comment_text": c.get("text"), "created_at": c.get("created_at"),
                               "author": c.get("author"), "story_title": thread.get("title")}, "hn:seeking_freelancer", now)
            if r:
                r.title = clean_text(c["text"], limit=110)
                out.append(r)
    log.records += len(out)
    log.event(kind="ok", thread=thread.get("title"), top_level=len(item.get("children") or []), seeking=len(out))
    return out, log


def search(queries: list[PlannedQuery], client: Optional[PoliteClient] = None, allow_restricted: Iterable[str] = (),
           since_ts: int = 0, max_requests: int = 10, dry_run: bool = False) -> tuple[list[RawRecord], RunLog]:
    log = RunLog(SOURCE)
    ok, why = registry.may_collect(SOURCE, allow_restricted)
    if not ok:
        log.skipped = len(queries)
        log.event(kind="permission", detail=why)
        return [], log
    client = client or PoliteClient(min_interval_s=1.0, check_robots=False)
    now = datetime.now(timezone.utc).isoformat()
    out: dict[str, RawRecord] = {}
    for q in queries:
        if log.requests >= max_requests or dry_run:
            log.skipped += 1
            continue
        log.requests += 1
        try:
            res = client.get_json(f"{ALGOLIA}/search_by_date?query={quote(q.text)}&tags=(story,comment)"
                                  f"&numericFilters=created_at_i>{since_ts}&hitsPerPage=30", check_robots=False)
        except FetchBlocked as exc:
            log.failed += 1
            log.event(kind="error", query_id=q.query_id, error_kind=exc.kind)
            continue
        log.ok += 1
        for h in res.get("hits") or []:
            r = hit_to_record(h, q.query_id, now)
            if r:
                out.setdefault(r.url, r)
        log.event(kind="ok", query_id=q.query_id, returned=len(res.get("hits") or []))
    log.records = len(out)
    return list(out.values()), log
