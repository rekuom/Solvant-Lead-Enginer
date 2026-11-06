"""Discovery connectors. Every connector:
  * checks the registry before any request (registry.may_collect),
  * respects a request budget and a minimum interval,
  * logs every request outcome (no silent failures),
  * returns RawRecords with provenance and PII-redacted excerpts (author handles hashed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunLog:
    source: str
    requests: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    records: int = 0
    est_cost_usd: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    def event(self, **kw: Any) -> None:
        self.events.append(kw)

    @property
    def status(self) -> str:
        if self.requests == 0 and self.skipped:
            return "skipped"
        if self.failed and not self.ok:
            return "failed"
        if self.failed:
            return "partial"
        return "ok"

    def to_dict(self) -> dict:
        return {"source": self.source, "status": self.status, "requests": self.requests, "ok": self.ok, "failed": self.failed,
                "skipped": self.skipped, "records": self.records, "est_cost_usd": round(self.est_cost_usd, 4), "events": self.events[-60:]}
