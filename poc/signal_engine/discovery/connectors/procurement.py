"""Procurement connectors (UK Contracts Finder, UK Find a Tender, EU TED) inside the discovery pipeline.

Reuses the tested Phase 2/3 collectors (signal_engine.collectors.ocds / ted) and converts their Signals into RawRecords so
tenders flow through the same assessment, routing (Pipeline E), deduplication and platform ingestion as everything else.
Each source runs independently: one failing API never stops the others; failures are logged and stay visible.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from ...collectors import ocds, ted
from ...collectors.http import FetchBlocked, PoliteClient
from ...models import Signal
from .. import registry
from ..models import RawRecord
from . import RunLog

KEYS = ("contracts_finder", "find_a_tender", "ted")


def signal_to_record(s: Signal) -> RawRecord:
    meta = {"kind": "tender", "deadline_at": s.deadline_at, "tender_status": (s.raw_meta or {}).get("tender_status"),
            "cpv": (s.raw_meta or {}).get("cpv")}
    if s.value_amount is not None:
        meta["budget"] = f"{s.value_currency or ''} {s.value_amount:,.0f}".strip()
    return RawRecord(source_key=s.source, source_id=str(s.source_id), url=s.url, title=s.title, body=s.text, verification="api_verified",
                     created_at=s.posted_at, state=(s.raw_meta or {}).get("tender_status") or "unknown", fetched_at=s.collected_at,
                     organisation=s.organisation, country_hint=s.country_hint, meta={k: v for k, v in meta.items() if v is not None})


def _plan(client: PoliteClient, since: datetime, max_pages: int) -> dict[str, Callable[[], list[Signal]]]:
    d, today = since.date().isoformat(), datetime.now(timezone.utc).date().isoformat()
    return {
        "contracts_finder": lambda: ocds.fetch_contracts_finder(client, d, today, max_pages=max_pages),
        "find_a_tender": lambda: ocds.fetch_find_a_tender(client, f"{d}T00:00:00", max_pages=max_pages),
        "ted": lambda: ted.fetch_ted(client, since, limit=50, max_pages=max_pages),
    }


def collect(keys: tuple[str, ...] = KEYS, since_days: int = 30, max_pages: int = 3, client: Optional[PoliteClient] = None,
            dry_run: bool = False, plan: Optional[dict[str, Callable[[], list[Signal]]]] = None) -> tuple[list[RawRecord], list[RunLog]]:
    client = client or PoliteClient(min_interval_s=2.0, check_robots=False)
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    plan = plan or _plan(client, since, max_pages)
    out: list[RawRecord] = []
    logs: list[RunLog] = []
    for key in keys:
        log = RunLog(key)
        logs.append(log)
        ok, why = registry.may_collect(key)
        if not ok:
            log.skipped += 1
            log.event(kind="permission", detail=why[:200])
            continue
        if dry_run:
            log.skipped += 1
            log.event(kind="dry_run")
            continue
        try:
            sigs = plan[key]()
            log.requests += max(1, min(max_pages, (len(sigs) // 50) + 1))
            log.ok += 1
        except FetchBlocked as exc:
            log.requests += 1
            log.failed += 1
            log.event(kind="error", error_kind=exc.kind)
            continue
        except Exception as exc:  # isolate any unexpected collector failure
            log.requests += 1
            log.failed += 1
            log.event(kind="error", error_kind=type(exc).__name__)
            continue
        recs = []
        for s in sigs:
            try:
                recs.append(signal_to_record(s))
            except ValueError:
                continue
        log.records = len(recs)
        out += recs
    return out, logs
