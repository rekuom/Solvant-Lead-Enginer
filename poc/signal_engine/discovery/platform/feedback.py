"""Print discovery feedback (last N days, counts only) so the scheduled task can re-weight queries and sources.

  python -m signal_engine.discovery.platform.feedback [--days 30]
"""
from __future__ import annotations

import sys
from typing import Optional

from .rest import RestError, rpc


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    try:
        fb = rpc("discovery_feedback", {"p_token": "", "p_days": days}) or {}
    except RestError as exc:
        print(f"feedback unavailable: HTTP {exc.status}")
        return 3
    cols = ("total", "qualified", "priority_a", "employment", "not_qualified", "verified", "progressed_by_human", "corrected_by_human", "won")
    for dim in ("by_source", "by_query"):
        print(f"\n{dim} (last {days} days)\n" + "key".ljust(48) + " ".join(c[:9].rjust(9) for c in cols))
        for r in fb.get(dim, []):
            print(str(r.get("key"))[:47].ljust(48) + " ".join(str(r.get(c, 0)).rjust(9) for c in cols))
    print("\nUse: keep/expand queries and sources with qualified > 0 (especially progressed_by_human or won); drop queries with"
          " total >= 5 and qualified == 0; treat corrected_by_human as a quality warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
