"""Load candidates discovered via a web-search index (URL + verbatim title only).

These were found during Phase 1 because every source host was blocked for direct
fetching. They are stored as `search_index_only`: the page body, posting date,
status and budget have NOT been verified by this pipeline. They are never
counted as genuine signals and are always routed to HOLD_VERIFY.
Claims that appeared only in the search engine's own summary are kept in
raw_meta["search_summary_claims"] for the human reviewer and are NOT used by the
classifier.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Signal
from ..textutil import clean_title


def load(path: str | Path) -> list[Signal]:
    data = json.loads(Path(path).read_text())
    out: list[Signal] = []
    for c in data["candidates"]:
        out.append(
            Signal(
                source=c["source"],
                source_id=c["url"],
                url=c["url"],
                title=clean_title(c["title_verbatim"]),
                text="",  # body not retrieved — classifier sees the title only
                verification_status="search_index_only",
                posted_at=None,
                collected_at=data["discovered_at"],
                raw_meta={
                    "kind": c.get("kind", "forum_post"),
                    "search_query": c.get("query"),
                    "search_summary_claims": c.get("search_summary_claims"),
                },
            )
        )
    return out
