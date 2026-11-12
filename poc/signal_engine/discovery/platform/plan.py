"""Collector plan: which sources run in THIS GitHub Actions execution.

Inputs: the administrator's source settings (fetched from the private database with the scoped discovery token) and the
engine's own source registry. A source runs only if ALL of these hold:
  1. the engine has an automated connector for it;
  2. the registry permits automated collection (permitted; or restricted WITH a recorded approval) — a dashboard toggle can
     never override unknown/prohibited/manual-only/licensed terms;
  3. an administrator enabled it;
  4. scheduled runs: its cron schedule is due since its last run (manual runs ignore the schedule);
  5. paid sources: never on a schedule; manual runs need a monthly budget above zero, enough remaining budget and the
     credential present; requests are capped by the remaining budget and the hard cap;
  6. rate limit: max_requests from the source settings (1–30).
If the plan cannot be fetched, scheduled runs collect NOTHING (central control is then reported as not active).

  python -m signal_engine.discovery.platform.plan --mode scheduled|manual   -> writes GITHUB_OUTPUT keys; prints reasons only
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import registry
from ..querylib import PROVIDER_COST
from .rest import RestError, rpc

CONNECTOR_SOURCE = {   # registry key -> discover() source name
    "github_issues": "github_issues", "github_discussions": "github_discussions", "contracts_finder": "contracts_finder",
    "find_a_tender": "find_a_tender", "ted": "ted", "rss_atom": "feeds", "hn_algolia": "hn_algolia", "web_search_brave": "search:brave",
}
PAID_CREDENTIAL = {"web_search_brave": "BRAVE_SEARCH_API_KEY"}
BRAVE_HARD_CAP = 100


# ----------------------------------------------------------------------------- cron
def _field_match(spec: str, value: int, lo: int, hi: int) -> bool:
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if a <= value <= b and (value - a) % step == 0:
            return True
    return False


def cron_matches(expr: str, t: datetime) -> bool:
    f = expr.split()
    if len(f) != 5:
        raise ValueError("cron needs 5 fields")
    minute, hour, dom, month, dow = f
    dow_v = (t.weekday() + 1) % 7   # cron: 0 = Sunday
    dom_ok, dow_ok = _field_match(dom, t.day, 1, 31), _field_match(dow, dow_v, 0, 7) or (dow_v == 0 and _field_match(dow, 7, 0, 7))
    day_ok = (dom_ok and dow_ok) if (dom == "*" or dow == "*") else (dom_ok or dow_ok)
    return _field_match(minute, t.minute, 0, 59) and _field_match(hour, t.hour, 0, 23) and _field_match(month, t.month, 1, 12) and day_ok


def cron_due(expr: str, last_run: Optional[datetime], now: datetime) -> bool:
    """True if the schedule fired in (last_run, now]. Never-run sources look back 25 hours."""
    start = max(last_run or now - timedelta(hours=25), now - timedelta(days=8))
    t = now.replace(second=0, microsecond=0)
    while t > start:
        if cron_matches(expr, t):
            return True
        t -= timedelta(minutes=1)
    return False


# ----------------------------------------------------------------------------- decisions
@dataclass
class Decision:
    key: str
    run: bool
    reason: str
    max_requests: int = 0
    allow_restricted: bool = False


@dataclass
class Plan:
    active: bool
    decisions: list[Decision] = field(default_factory=list)
    note: str = ""

    def selected(self) -> list[Decision]:
        return [d for d in self.decisions if d.run]


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def decide(rows: list[dict], mode: str, now: Optional[datetime] = None, env: Optional[dict] = None) -> Plan:
    now = now or datetime.now(timezone.utc)
    env = os.environ if env is None else env
    out = []
    for r in rows:
        key = r["key"]
        if key not in CONNECTOR_SOURCE:
            out.append(Decision(key, False, "no automated connector in the engine (manual intake only)"))
            continue
        approved = bool((r.get("restricted_approval") or {}).get("basis"))
        if key in PAID_CREDENTIAL:
            # licensed/paid API: the legal basis is the operator's contract, evidenced by an approved budget + credential (below)
            st = registry.policy(key)["status"]
            legal_ok, why = st == "licensed", f"registry status {st}"
        else:
            try:
                legal_ok, why = registry.may_collect(key, [key] if approved else [])
            except Exception as exc:   # unknown to the registry
                legal_ok, why = False, f"not in the engine registry ({type(exc).__name__})"
        if not legal_ok:
            out.append(Decision(key, False, f"blocked by source terms: {why[:120]}"))
            continue
        if not r.get("enabled"):
            out.append(Decision(key, False, "disabled by an administrator"))
            continue
        cap = max(1, min(30, int(r.get("max_requests") or 20)))
        if r.get("paid") or key in PAID_CREDENTIAL:
            if mode == "scheduled":
                out.append(Decision(key, False, "paid source: never run on a schedule (manual runs only)"))
                continue
            budget, spent = float(r.get("monthly_budget_usd") or 0), float(r.get("month_spend_usd") or 0)
            unit = PROVIDER_COST.get("brave", 0.005) if key == "web_search_brave" else 0.01
            if budget <= 0:
                out.append(Decision(key, False, "paid source without an approved monthly budget"))
                continue
            cred = PAID_CREDENTIAL.get(key, "")
            if not (env.get(cred) or env.get(cred + "_PRESENT")):
                out.append(Decision(key, False, "credential not configured"))
                continue
            affordable = int((budget - spent) / unit) if unit else 0
            if affordable < 1:
                out.append(Decision(key, False, f"monthly budget used (${spent:.2f} of ${budget:.2f})"))
                continue
            cap = min(BRAVE_HARD_CAP, affordable, int(r.get("max_requests") or BRAVE_HARD_CAP))
        if mode == "scheduled":
            cron = r.get("schedule_cron")
            if not cron:
                out.append(Decision(key, False, "no schedule set"))
                continue
            try:
                due = cron_due(cron, _ts(r.get("last_run_at")), now)
            except ValueError:
                out.append(Decision(key, False, "invalid schedule"))
                continue
            if not due:
                out.append(Decision(key, False, "not due yet"))
                continue
        out.append(Decision(key, True, "eligible", cap, approved and r.get("permission_status") == "restricted"))
    return Plan(True, out)


def fetch_plan(mode: str) -> Plan:
    token = os.environ.get("SIGNAL_INGEST_TOKEN", "")
    if not token:
        return Plan(False, note="central source control NOT active: SIGNAL_INGEST_TOKEN not configured")
    try:
        res = rpc("collector_plan", {"p_token": token})
    except RestError as exc:
        return Plan(False, note=f"central source control NOT active: plan request failed (HTTP {exc.status})")
    return decide((res or {}).get("sources", []), mode)


def to_outputs(plan: Plan) -> dict:
    sel = plan.selected()
    srcs = [CONNECTOR_SOURCE[d.key] for d in sel]
    brave = next((d for d in sel if d.key == "web_search_brave"), None)
    non_paid = [d.max_requests for d in sel if d.key != "web_search_brave"]
    return {
        "active": "true" if plan.active else "false",
        "sources": ",".join(srcs),
        "allow_restricted": ",".join(d.key for d in sel if d.allow_restricted),
        "max_requests": str(min(non_paid) if non_paid else 20),
        "enable_brave": "true" if brave else "false",
        "brave_max_requests": str(brave.max_requests if brave else 0),
        "include_discussions": "false",   # discussions run as their own source when selected
    }


def main() -> int:
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "scheduled"
    plan = fetch_plan(mode)
    outs = to_outputs(plan)
    print(f"collector plan ({mode}): {'ACTIVE' if plan.active else 'NOT ACTIVE'} {plan.note}")
    for d in plan.decisions:
        print(f"  {'RUN ' if d.run else 'skip'} {d.key:22} {d.reason}{f' (max {d.max_requests} requests)' if d.run else ''}")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as fh:
            for k, v in outs.items():
                fh.write(f"{k}={v}\n")
    else:
        print(json.dumps(outs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
