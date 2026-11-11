"""Web / inbound intake: parse, validate and classify. Pure functions (no network, no disk), so they are unit-tested
and run identically in the Vercel Python function and locally. Raw files are never stored; only redacted records."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from .. import intake as engine_intake
from .. import registry
from ..assess import assess
from ..router import build
from .items import to_item

MAX_EMAIL_BYTES = 2_000_000
MAX_CSV_BYTES = 2_000_000
MAX_TEXT = 20_000
KINDS = ("manual", "paste", "email_file", "csv", "json")


class IntakeRejected(ValueError):
    pass


def is_synthetic(raw: bytes) -> bool:
    """Repository fixtures carry an X-Fixture header / SYNTHETIC marker: they must never become real records."""
    head = raw[:20000].decode("utf-8", "replace")
    return "\nX-Fixture:" in "\n" + head or "SYNTHETIC FIXTURE" in head or "SYNTHETIC test alert" in head


def _synthetic_row(row: dict) -> bool:
    blob = " ".join(str(v) for v in row.values())
    return "SYNTHETIC FIXTURE" in blob or ".invalid/" in blob or "example.invalid" in blob


def classify_rows(rows: list[dict], origin: str, verified_by: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    items, errors = [], []
    now = datetime.now(timezone.utc)
    for i, row in enumerate(rows):
        if _synthetic_row(row):
            errors.append({"row": i, "error": "synthetic/test data (reserved .invalid domain or fixture marker): not stored"})
            continue
        try:
            rec = engine_intake.make_record(row, origin, verified_by=verified_by)
        except engine_intake.IntakeError as exc:
            errors.append({"row": i, "error": str(exc)[:200]})
            continue
        if row.get("acquisition_cost"):
            try:
                rec.meta["acquisition_cost"] = float(str(row["acquisition_cost"]).replace("£", "").replace("$", "").replace(",", ""))
            except ValueError:
                pass
        opp = build(rec, assess(rec, now=now))
        rules = registry.marketplace_rules(rec.source_key) or {}
        note = "user-authorised alert / user capture; platform rules apply" if rules else None
        items.append(to_item(opp, rights_note=note))
    return items, errors


def process(kind: str, payload: dict) -> dict:
    """payload: manual/paste -> fields; email_file -> {"eml_b64" | "eml_text", "source_key"?}; csv -> {"csv_text", "source_key"?};
    json -> {"records": [...]}. Returns {"intake": {...}, "items": [...]} for public.save_intake."""
    import base64
    if kind not in KINDS:
        raise IntakeRejected("unknown intake kind")
    verified_by = (payload.get("verified_by") or "").strip() or None
    source_key = (payload.get("source_key") or "").strip() or None
    unrecognised = False
    if kind in ("manual", "paste"):
        row = {k: str(payload.get(k) or "")[:MAX_TEXT] for k in engine_intake.FIELDS}
        if kind == "paste" and not row.get("title"):
            row["title"] = (row.get("text") or "")[:100]
        rows = [row]
    elif kind == "email_file":
        raw = base64.b64decode(payload.get("eml_b64") or "") if payload.get("eml_b64") else (payload.get("eml_text") or "").encode()
        if not raw or len(raw) > MAX_EMAIL_BYTES:
            raise IntakeRejected("e-mail file missing or larger than 2 MB")
        if is_synthetic(raw):
            raise IntakeRejected("this is a SYNTHETIC test fixture: it is never stored as an opportunity")
        rows = engine_intake.read_email_bytes(raw, source_key)
        unrecognised = any("not recognised" in (r.get("notes") or "") for r in rows) or not rows
        if not rows:
            return {"intake": {"origin": kind, "source_key": source_key, "filename": payload.get("filename"), "unrecognised": True,
                               "errors": [{"error": "no marketplace project links recognised in this e-mail"}]}, "items": []}
    elif kind == "csv":
        text = payload.get("csv_text") or ""
        if not text or len(text.encode()) > MAX_CSV_BYTES:
            raise IntakeRejected("CSV missing or larger than 2 MB")
        rows = engine_intake.read_csv_text(text)
        for r in rows:
            if source_key and not r.get("source_key"):
                r["source_key"] = source_key
            r.setdefault("text", r.get("description") or r.get("body") or "")
            r.setdefault("post_date", r.get("date") or r.get("posted") or "")
    else:
        recs = payload.get("records")
        if isinstance(recs, str):
            recs = json.loads(recs)
        if not isinstance(recs, list) or len(recs) > 1000:
            raise IntakeRejected("records must be a list of at most 1000 objects")
        rows = [{k: str(v)[:MAX_TEXT] for k, v in r.items() if isinstance(r, dict)} for r in recs]
    items, errors = classify_rows(rows, kind, verified_by=verified_by)
    return {"intake": {"origin": kind, "source_key": source_key or (items[0]["source_key"] if items else None),
                       "filename": (payload.get("filename") or "")[:200] or None, "unrecognised": unrecognised, "errors": errors},
            "items": items}
