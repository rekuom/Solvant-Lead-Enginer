#!/usr/bin/env python3
"""Live smoke test for a DEPLOYED Solvant platform (staging or production). Stdlib only; never prints secrets.

  python3 scripts/smoke_test.py --base-url https://<app>.vercel.app

Always-on checks (no credentials, no data written):
  routing of the three Python endpoints, auth denial, security headers, sign-in redirect, export denial.
Optional live-data checks (only when ALL of these are set; uses a REAL lead you are entitled to store — never synthetic):
  SMOKE_USER_JWT (access token of a member), SMOKE_LEAD_SOURCE, SMOKE_LEAD_URL, SMOKE_LEAD_TEXT,
  SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY (to read the record back through RLS as that user)
  SMOKE_NONMEMBER_JWT (optional): access token of a signed-in NON-member, to prove denial.
Exit code 0 only if every executed check passed. Skipped checks are listed and do NOT count as passed integrations.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RESULTS: list[tuple[str, str, str]] = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def http(method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with OPENER.open(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(("PASS" if ok else "FAIL", name, detail))


def skip(name: str, why: str) -> None:
    RESULTS.append(("SKIP", name, why))


def j(body: bytes) -> dict:
    try:
        return json.loads(body)
    except ValueError:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    base = ap.parse_args().base_url.rstrip("/")
    if not base.startswith("https://"):
        print("base URL must be https")
        return 2

    s, h, b = http("GET", f"{base}/api/engine/health")
    check("engine health routed to health function", s == 200 and j(b).get("endpoint") == "health", f"HTTP {s}")
    s, h, b = http("POST", f"{base}/api/engine/intake", b"{}", {"Content-Type": "application/json"})
    check("intake routed and requires sign-in", s == 401 and h.get("X-Solvant-Endpoint") == "intake", f"HTTP {s}")
    s, h, b = http("POST", f"{base}/api/engine/inbound-email", b"x", {"Content-Type": "message/rfc822"})
    check("inbound-email routed and requires a token", s == 401 and h.get("X-Solvant-Endpoint") == "inbound-email", f"HTTP {s}")
    s, h, b = http("GET", f"{base}/api/engine/intake")
    check("intake rejects GET", s == 405, f"HTTP {s}")
    s, h, b = http("GET", f"{base}/")
    check("signed-out visitor redirected to /login", s in (302, 303, 307, 308) and "/login" in h.get("Location", ""), f"HTTP {s}")
    s, h, b = http("GET", f"{base}/login")
    check("login page served", s == 200, f"HTTP {s}")
    check("security headers present", h.get("X-Frame-Options") == "DENY" and "noindex" in h.get("X-Robots-Tag", "") and h.get("X-Content-Type-Options") == "nosniff")
    s, h, b = http("GET", f"{base}/api/export")
    check("CSV export denied without a session", s in (302, 303, 307, 308, 401), f"HTTP {s}")

    jwt = os.environ.get("SMOKE_USER_JWT", "")
    lead = {k: os.environ.get(f"SMOKE_LEAD_{k.upper()}", "") for k in ("source", "url", "text")}
    sb_url, sb_key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not (jwt and all(lead.values()) and sb_url and sb_key):
        skip("live intake + persistence", "set SMOKE_USER_JWT, SMOKE_LEAD_SOURCE/URL/TEXT, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY")
    elif "SYNTHETIC" in lead["text"].upper() or ".invalid" in lead["url"]:
        check("live intake refuses synthetic data", False, "synthetic lead supplied: refused")
    else:
        body = json.dumps({"kind": "manual", "payload": {"source_key": lead["source"], "url": lead["url"], "text": lead["text"]}}).encode()
        auth = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
        s, h, b = http("POST", f"{base}/api/engine/intake", body, auth)
        r1 = j(b)
        check("live intake classified and saved", s == 200 and (r1.get("added", 0) + r1.get("updated", 0)) == 1, f"HTTP {s} {json.dumps({k: r1.get(k) for k in ('added', 'updated', 'rejected')})}")
        q = urllib.parse.urlencode({"select": "id,pipeline,verification,stage", "url": f"eq.{lead['url']}"})
        rest = {"apikey": sb_key, "Authorization": f"Bearer {jwt}", "Accept-Profile": "solvant"}
        s, h, b = http("GET", f"{sb_url}/rest/v1/opportunities?{q}", headers=rest)
        rows = j(b) if s == 200 else []
        check("record persisted and readable through RLS (new request)", s == 200 and isinstance(rows, list) and len(rows) == 1,
              f"HTTP {s}; pipeline={rows[0].get('pipeline') if rows else None}")
        s, h, b = http("POST", f"{base}/api/engine/intake", body, auth)
        check("re-submitting the same lead is detected (updated, not duplicated)", s == 200 and j(b).get("updated") == 1 and j(b).get("added") == 0, f"HTTP {s}")
        other = os.environ.get("SMOKE_NONMEMBER_JWT", "")
        if other:
            s, h, b = http("GET", f"{sb_url}/rest/v1/opportunities?select=id&limit=1", headers={**rest, "Authorization": f"Bearer {other}"})
            check("non-member sees no lead records", s in (200, 401, 403) and (s != 200 or j(b) == []), f"HTTP {s}")
            s, h, b = http("POST", f"{base}/api/engine/intake", body, {**auth, "Authorization": f"Bearer {other}"})
            check("non-member cannot add leads", s in (401, 403), f"HTTP {s}")
        else:
            skip("non-member denial", "set SMOKE_NONMEMBER_JWT")

    for st, name, detail in RESULTS:
        print(f"{st:5} {name}{(' — ' + detail) if detail else ''}")
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{sum(r[0] == 'PASS' for r in RESULTS)} passed, {len(failed)} failed, {sum(r[0] == 'SKIP' for r in RESULTS)} skipped (skipped = NOT verified)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
