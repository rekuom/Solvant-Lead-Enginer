"""Minimal Supabase PostgREST RPC client (stdlib). The anon/publishable key is public by design; authority comes from the
caller's user JWT (browser intake) or a hashed ingest token checked inside the database (machine ingestion)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional


class RestError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


def _base() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or ""
    if not url.startswith("https://") or not key:
        raise RestError(500, "SUPABASE_URL / SUPABASE_ANON_KEY not configured")
    return url, key


def rpc(fn: str, args: dict, user_jwt: Optional[str] = None, timeout: int = 60) -> object:
    url, key = _base()
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{fn}", data=json.dumps(args).encode(), method="POST",
                                 headers={"apikey": key, "Authorization": f"Bearer {user_jwt or key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("message", "")
        except Exception:
            msg = ""
        raise RestError(exc.code, msg[:200] or exc.reason) from None


def get_user(user_jwt: str, timeout: int = 15) -> dict:
    """Validate a user session with Supabase Auth (the authoritative check)."""
    url, key = _base()
    req = urllib.request.Request(f"{url}/auth/v1/user", headers={"apikey": key, "Authorization": f"Bearer {user_jwt}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RestError(401 if exc.code in (401, 403) else exc.code, "invalid session") from None
