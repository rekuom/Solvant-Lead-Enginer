"""Vercel Python function: the Solvant qualification engine behind the web app.

POST /api/engine/intake         browser intake (user session JWT required; saved through RLS as that user)
POST /api/engine/inbound-email  inbound-email webhook (ingest token with scope inbound_email; checked in the database)
GET  /api/engine/health

No service-role key is used anywhere: authority comes from the user's JWT or a hashed, revocable ingest token.
External content is treated as untrusted data; files are size-limited and never stored raw.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_engine"))

from signal_engine.discovery.platform import ENGINE_VERSION  # noqa: E402
from signal_engine.discovery.platform.intake import IntakeRejected, is_synthetic, process  # noqa: E402
from signal_engine.discovery.platform.rest import RestError, get_user, rpc  # noqa: E402

MAX_BODY = 3_000_000


def handle_intake(headers: dict, body: bytes) -> tuple[int, dict]:
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or len(auth) < 40:
        return 401, {"error": "Sign in required"}
    jwt = auth.split(" ", 1)[1].strip()
    try:
        get_user(jwt)
    except RestError:
        return 401, {"error": "Your session has expired. Sign in again."}
    try:
        req = json.loads(body or b"{}")
        kind, payload = str(req.get("kind", "")), req.get("payload") or {}
        if not isinstance(payload, dict):
            return 400, {"error": "Invalid request"}
        result = process(kind, payload)
    except IntakeRejected as exc:
        return 422, {"error": str(exc)}
    except (ValueError, TypeError):
        return 400, {"error": "Could not read the submitted data"}
    if not result["items"]:
        return 200, {"added": 0, "updated": 0, "duplicates": 0, "rejected": 0, "errors": result["intake"].get("errors", [])}
    try:
        saved = rpc("save_intake", {"p_intake": result["intake"], "p_items": result["items"]}, user_jwt=jwt)
    except RestError as exc:
        return (403 if exc.status in (401, 403) else 502), {"error": "Not allowed to add leads" if exc.status in (401, 403) else "Database error"}
    saved = saved if isinstance(saved, dict) else {}
    saved["errors"] = result["intake"].get("errors", [])
    saved.pop("results", None)
    return 200, saved


def handle_inbound(headers: dict, body: bytes) -> tuple[int, dict]:
    token = headers.get("x-signal-token", "")
    if len(token) < 32:
        return 401, {"error": "token required"}
    raw = body
    if headers.get("content-type", "").startswith("application/json"):
        try:
            raw = base64.b64decode(json.loads(body).get("raw_b64", ""))
        except (ValueError, TypeError):
            return 400, {"error": "invalid json"}
    if not raw or len(raw) > 2_000_000:
        return 413, {"error": "message missing or too large"}
    if is_synthetic(raw):
        return 422, {"error": "synthetic fixture refused"}
    try:
        result = process("email_file", {"eml_b64": base64.b64encode(raw).decode()})
    except IntakeRejected as exc:
        return 422, {"error": str(exc)}
    run = {"scope": "inbound_email", "source_key": result["intake"].get("source_key"), "unrecognised": result["intake"].get("unrecognised")}
    try:
        res = rpc("ingest_records", {"p_token": token, "p_run": run, "p_items": result["items"]})
    except RestError as exc:
        return (401 if exc.status in (400, 401, 403) else 502), {"error": "rejected"}
    return 200, res if isinstance(res, dict) else {}


class handler(BaseHTTPRequestHandler):  # noqa: N801 (Vercel convention)
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self) -> str:
        p = self.path.split("?", 1)[0].rstrip("/")
        return p.rsplit("/", 1)[-1]

    def do_GET(self) -> None:  # noqa: N802
        if self._route() in ("health", "engine", "engine.py"):
            return self._send(200, {"ok": True, "engine": ENGINE_VERSION})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"error": "request body missing or too large"})
        body = self.rfile.read(length)
        headers = {k.lower(): v for k, v in self.headers.items()}
        route = self._route()
        try:
            if route == "intake":
                status, payload = handle_intake(headers, body)
            elif route == "inbound-email":
                status, payload = handle_inbound(headers, body)
            else:
                status, payload = 404, {"error": "not found"}
        except Exception:  # never echo internals or submitted content
            status, payload = 500, {"error": "internal error"}
        return self._send(status, payload)
