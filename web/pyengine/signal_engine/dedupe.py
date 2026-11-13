"""Deduplication: exact (canonical URL / source id / content hash) then near-duplicate."""

from __future__ import annotations

from .models import Signal
from .textutil import canonical_url, fingerprint, jaccard, shingles

NEAR_DUP_THRESHOLD = 0.8


def dedupe(signals: list[Signal]) -> tuple[list[Signal], list[dict]]:
    """Return (kept, dropped_log). Earliest posted_at wins; ties keep first seen.

    Rules, in order:
      1. Same canonical URL                      -> duplicate
      2. Same (source, source_id)                -> duplicate
      3. Same normalised title+text fingerprint  -> duplicate (cross-posts)
      4. Shingle Jaccard >= 0.8 on title+text    -> near-duplicate (reposts)
    """
    ordered = sorted(
        enumerate(signals),
        key=lambda p: (p[1].posted_at or "9999", p[0]),
    )
    kept: list[Signal] = []
    dropped: list[dict] = []
    seen_urls: dict[str, Signal] = {}
    seen_ids: dict[tuple[str, str], Signal] = {}
    seen_fp: dict[str, Signal] = {}
    kept_shingles: list[tuple[Signal, set[str]]] = []

    for _, s in ordered:
        cu = canonical_url(s.url)
        body = f"{s.title} {s.text}"
        fp = fingerprint(body)
        sh = shingles(body)
        reason, match = None, None
        if cu in seen_urls:
            reason, match = "same_url", seen_urls[cu]
        elif (s.source, s.source_id) in seen_ids:
            reason, match = "same_source_id", seen_ids[(s.source, s.source_id)]
        elif fp in seen_fp:
            reason, match = "same_content", seen_fp[fp]
        else:
            for other, osh in kept_shingles:
                if jaccard(sh, osh) >= NEAR_DUP_THRESHOLD:
                    reason, match = "near_duplicate", other
                    break
        if reason:
            dropped.append({"url": s.url, "reason": reason, "duplicate_of": match.url})
            continue
        kept.append(s)
        seen_urls[cu] = s
        seen_ids[(s.source, s.source_id)] = s
        seen_fp[fp] = s
        kept_shingles.append((s, sh))
    return kept, dropped
