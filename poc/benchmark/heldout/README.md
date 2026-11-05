# Held-out evaluation set (independent accuracy)

**Status: 0 items.** No real post has been fully reviewed yet: every source host was
blocked by the session network policy in Phase 1 and at the start of Phase 2A. Until
this file has items, **no independent accuracy claim exists**. The development
benchmark (`../gold_labels.json`) was used for tuning and is not proof of accuracy.

## Protocol (must be followed for an item to count)

1. **Only real, fully read posts.** `verification_status` must be `verified_api` (fetched
   by the pipeline) or `human_verified` (a named reviewer opened the original page).
   Titles from search results are not allowed.
2. **Label before you look.** Write the gold tier and qualification *before* running the
   classifier on the item. Record `labelled_by` and `labelled_at`.
3. **Freeze.** After labelling, run `python3 -m benchmark.run_benchmark --set heldout --freeze`.
   This records a SHA-256 of the file in `heldout.lock`. Editing labels afterwards breaks the lock.
4. **Never tune on it.** If a held-out error leads to a rule change, move that item into
   the dev set and replace it with a fresh item.
5. **Two annotators** for at least 50% of items. Record disagreements in `notes`.
6. **Target:** at least 200 items, at least 30% from UK/UAE sources.

## Line format (`heldout.jsonl`, one JSON object per line)

```json
{"url": "https://…", "source": "discourse:community.n8n.io", "verification_status": "verified_api",
 "title": "…", "text": "<excerpt as fetched, PII removed>", "posted_at": "2026-11-03T09:12:00Z",
 "gold_tier": "A|B|C|D|REJECT", "gold_qualified": true, "labelled_by": "name", "labelled_at": "2026-11-…",
 "notes": ""}
```
