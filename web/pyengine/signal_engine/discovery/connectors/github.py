"""GitHub discovery connector (documented REST search API; GraphQL Discussions when a token exists).

Policy: GitHub API use is permitted; the Acceptable Use Policies forbid using API data for spam or
selling personal information. Therefore: no email harvesting, no automated comments, author handles
hashed, and a reply is suggested only where the issue explicitly invites outside paid help.

Rate limits: search = 10 req/min unauthenticated, 30 req/min with a token. Minimum interval and a
hard request budget are enforced; a 403/429 stops the connector and is logged (never silent).
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from ...collectors.http import FetchBlocked, PoliteClient, classify_error
from .. import registry
from ..models import RawRecord
from ..privacy import author_ref, clean_text
from ..querylib import PlannedQuery, QueryLog
from . import RunLog

API = "https://api.github.com"
SOURCE = "github_issues"


def _headers(token: Optional[str]) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def item_to_record(it: dict, q: Optional[PlannedQuery], fetched_at: str) -> Optional[RawRecord]:
    url = it.get("html_url") or ""
    if not url.startswith("https://github.com/"):
        return None
    repo = (it.get("repository_url") or "").replace(f"{API}/repos/", "")
    owner = repo.split("/")[0] if repo else None
    user = it.get("user") or {}
    return RawRecord(
        source_key=SOURCE, source_id=str(it.get("node_id") or it.get("id") or url), url=url,
        title=(it.get("title") or "").strip(), body=clean_text(it.get("body") or "", limit=800),
        verification="api_verified", created_at=it.get("created_at"), updated_at=it.get("updated_at"),
        state=it.get("state"), fetched_at=fetched_at, query_id=q.query_id if q else None, language=q.lang if q else None,
        author_ref=author_ref(user.get("login")), author_kind=user.get("type"),
        labels=[l.get("name", "") for l in it.get("labels") or []][:10],
        meta={"repo": repo, "repo_owner": owner, "comments": it.get("comments"),
              "author_association": it.get("author_association"), "is_pull_request": "pull_request" in it,
              "query_category": q.category if q else None},
    )


def search_issues(queries: list[PlannedQuery], client: Optional[PoliteClient] = None, token: Optional[str] = None,
                  max_requests: int = 20, per_page: int = 30, querylog: Optional[QueryLog] = None,
                  dry_run: bool = False) -> tuple[list[RawRecord], RunLog]:
    log = RunLog(SOURCE)
    ok, why = registry.may_collect(SOURCE)
    if not ok:
        log.skipped = len(queries)
        log.event(kind="permission", detail=why)
        return [], log
    token = token if token is not None else os.environ.get("GITHUB_TOKEN")
    client = client or PoliteClient(min_interval_s=2.2 if token else 6.5, check_robots=False)
    out: dict[str, RawRecord] = {}
    now = datetime.now(timezone.utc).isoformat()
    for q in queries:
        if log.requests >= max_requests:
            log.skipped += 1
            log.event(kind="budget", query_id=q.query_id, detail="request budget reached")
            continue
        if querylog and querylog.seen_recently(q):
            log.skipped += 1
            log.event(kind="repeat_prevented", query_id=q.query_id)
            continue
        if dry_run:
            log.skipped += 1
            log.event(kind="dry_run", query_id=q.query_id, query=q.query)
            continue
        url = f"{API}/search/issues?q={quote(q.query)}&per_page={per_page}&sort=created&order=desc"
        log.requests += 1
        try:
            data = client.get_json(url, check_robots=False, headers=_headers(token))
        except FetchBlocked as exc:
            log.failed += 1
            log.event(kind="error", query_id=q.query_id, error_kind=exc.kind, status=exc.status, detail=str(exc)[:200])
            if querylog:
                querylog.record(q, 0, f"error:{exc.kind}")
            if exc.kind in ("upstream_forbidden", "rate_limited"):
                log.event(kind="stopped", detail="GitHub rate limit / forbidden — stopping connector for this run")
                break
            continue
        log.ok += 1
        items = data.get("items") or []
        n = 0
        for it in items:
            r = item_to_record(it, q, now)
            if r and r.url not in out and not (r.meta.get("is_pull_request")):
                out[r.url] = r
                n += 1
        log.event(kind="ok", query_id=q.query_id, total_count=data.get("total_count"), returned=len(items), new=n,
                  incomplete=data.get("incomplete_results"))
        if querylog:
            querylog.record(q, len(items), "ok")
    log.records = len(out)
    return list(out.values()), log


GRAPHQL_DISCUSSIONS = """query($q:String!){search(query:$q,type:DISCUSSION,first:30){discussionCount nodes{... on Discussion{
 id url title bodyText createdAt updatedAt closed category{name} repository{nameWithOwner} author{login}}}}}"""


def search_discussions(queries: list[PlannedQuery], token: Optional[str], max_requests: int = 5,
                       opener=None, dry_run: bool = False) -> tuple[list[RawRecord], RunLog]:
    """GitHub Discussions need GraphQL + a token (blocked in Claude Cloud; works in Actions with GITHUB_TOKEN)."""
    log = RunLog("github_discussions")
    ok, why = registry.may_collect("github_discussions")
    if not ok or not token:
        log.skipped = len(queries)
        log.event(kind="permission" if not ok else "credentials", detail=why if not ok else "no token: GraphQL requires authentication")
        return [], log
    out: dict[str, RawRecord] = {}
    now = datetime.now(timezone.utc).isoformat()
    op = opener or (lambda req, t: urllib.request.urlopen(req, timeout=t))
    for q in queries[:max_requests]:
        if dry_run:
            log.skipped += 1
            continue
        query = q.query.replace(" is:issue", "")
        body = json.dumps({"query": GRAPHQL_DISCUSSIONS, "variables": {"q": query}}).encode()
        req = urllib.request.Request(f"{API}/graphql", data=body, method="POST",
                                     headers={**_headers(token), "Content-Type": "application/json", "User-Agent": "SolvantSignalEngine/0.1"})
        log.requests += 1
        try:
            with op(req, 30) as resp:
                data = json.loads(resp.read())
        except Exception as exc:  # logged, never silent
            kind, status = classify_error(exc)
            log.failed += 1
            log.event(kind="error", query_id=q.query_id, error_kind=kind, status=status)
            continue
        if data.get("errors"):
            log.failed += 1
            log.event(kind="graphql_error", query_id=q.query_id, detail=str(data["errors"])[:200])
            continue
        log.ok += 1
        for n in ((data.get("data") or {}).get("search") or {}).get("nodes") or []:
            if not n or not n.get("url"):
                continue
            out[n["url"]] = RawRecord(
                source_key="github_discussions", source_id=n["id"], url=n["url"], title=n.get("title", ""),
                body=clean_text(n.get("bodyText") or ""), verification="api_verified", created_at=n.get("createdAt"),
                updated_at=n.get("updatedAt"), state="closed" if n.get("closed") else "open", fetched_at=now,
                query_id=q.query_id, language=q.lang, author_ref=author_ref((n.get("author") or {}).get("login")),
                meta={"repo": (n.get("repository") or {}).get("nameWithOwner"),
                      "repo_owner": ((n.get("repository") or {}).get("nameWithOwner") or "/").split("/")[0],
                      "category": (n.get("category") or {}).get("name")})
    log.records = len(out)
    return list(out.values()), log
