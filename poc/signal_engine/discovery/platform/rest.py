"""Minimal Supabase client for the Data API (PostgREST RPC) and Auth (stdlib only).

Key handling follows Supabase's API-key model (checked against the Supabase docs, Nov 2026):
- Modern publishable keys (`sb_publishable_...`) are NOT JWTs. They are sent ONLY in the `apikey` header. Sending them as
  `Authorization: Bearer` makes the platform try to parse a JWT and reject the request.
- Legacy anon keys ARE JWTs (`eyJ...`); for those, mirroring the key into `Authorization` is accepted (supabase-js does it).
- User-authenticated requests send the user's real session JWT in `Authorization: Bearer <access token>`.
- Machine ingestion sends only the API key (role `anon`); its authority is the scoped, hashed ingest token passed as an RPC
  argument and checked inside the database. No secret/service-role key is used anywhere.
- All application objects live in the `solvant` schema: requests select it with Accept-Profile / Content-Profile.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional

SCHEMA = "solvant"
_JWT = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class RestError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


def key_kind(key: str) -> str:
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("sb_secret_"):
        return "secret"
    if _JWT.match(key):
        return "legacy_jwt"
    return "unknown"


def _base() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or "")
    local = url.startswith(("http://127.0.0.1:", "http://localhost:"))   # local test doubles only
    if not (url.startswith("https://") or local) or not key:
        raise RestError(500, "SUPABASE_URL and a publishable (or legacy anon) key are not configured")
    if key_kind(key) == "secret":
        raise RestError(500, "a SECRET key was configured where a publishable key is required; refusing to use it")
    return url, key


def headers(key: str, user_jwt: Optional[str] = None, *, write: bool = False) -> dict:
    h = {"apikey": key, "Accept-Profile": SCHEMA}
    if write:
        h["Content-Profile"] = SCHEMA
        h["Content-Type"] = "application/json"
    if user_jwt:
        if not _JWT.match(user_jwt):
            raise RestError(401, "invalid session token")
        h["Authorization"] = f"Bearer {user_jwt}"
    elif key_kind(key) == "legacy_jwt":
        h["Authorization"] = f"Bearer {key}"          # legacy anon JWT: accepted in Authorization
    # modern publishable key without a user: NO Authorization header (the gateway derives the anon role from apikey)
    return h


def rpc(fn: str, args: dict, user_jwt: Optional[str] = None, timeout: int = 60) -> object:
    url, key = _base()
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{fn}", data=json.dumps(args).encode(), method="POST",
                                 headers=headers(key, user_jwt, write=True))
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
    """Validate a user session with Supabase Auth (authoritative). Sends apikey + the user's JWT."""
    url, key = _base()
    h = headers(key, user_jwt)
    h.pop("Accept-Profile", None)
    req = urllib.request.Request(f"{url}/auth/v1/user", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RestError(401 if exc.code in (401, 403) else exc.code, "invalid session") from None
