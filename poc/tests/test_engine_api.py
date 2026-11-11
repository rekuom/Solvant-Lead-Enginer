"""web/api/engine.py (Vercel Python function) against a fake Supabase: auth required, payload forwarded with the user's
JWT (RLS applies), synthetic fixtures refused, inbound webhook needs a token, errors never echo submitted content."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "poc" / "fixtures" / "alerts"
CALLS: list[dict] = []


class FakeSupabase(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/auth/v1/user":
            ok = self.headers.get("Authorization") == "Bearer " + "u" * 40
            return self._json(200 if ok else 401, {"id": "user-1"} if ok else {"message": "bad jwt"})
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if self.path.endswith("/save_intake"):
            return self._json(200, {"added": len(body["p_items"]), "updated": 0, "duplicates": 0, "rejected": 0, "results": ["added"]})
        if self.path.endswith("/ingest_records"):
            if body["p_token"] != "t" * 40:
                return self._json(401, {"message": "invalid token"})
            return self._json(200, {"added": len(body["p_items"])})
        self._json(404, {})


def _strip(raw: bytes) -> bytes:
    t = re.sub(r"^X-Fixture:.*\n", "", raw.decode(), flags=re.M).replace("SYNTHETIC FIXTURE", "").replace("SYNTHETIC test alert", "")
    return t.replace("example.invalid", "example.com").encode()


class EngineApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = HTTPServer(("127.0.0.1", 0), FakeSupabase)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        os.environ["SUPABASE_URL"] = f"http://127.0.0.1:{cls.fake.server_port}"
        os.environ["SUPABASE_ANON_KEY"] = "anon-public-key"
        spec = importlib.util.spec_from_file_location("engine_fn", ROOT / "web" / "api" / "engine.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import signal_engine.discovery.platform.rest as rest_mod
        cls._orig_base = rest_mod._base
        rest_mod._base = lambda: (os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])   # allow http for the local fake
        mod.rpc.__globals__["_base"] = rest_mod._base
        mod.get_user.__globals__["_base"] = rest_mod._base
        cls.app = HTTPServer(("127.0.0.1", 0), mod.handler)
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.app.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.fake.shutdown()

    def _post(self, path, data: bytes, headers: dict):
        req = urllib.request.Request(self.base + path, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health(self):
        with urllib.request.urlopen(self.base + "/api/engine/health") as r:
            self.assertEqual(json.loads(r.read())["ok"], True)

    def test_intake_requires_valid_session(self):
        body = json.dumps({"kind": "paste", "payload": {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/a", "text": "Need CRM help"}}).encode()
        self.assertEqual(self._post("/api/engine/intake", body, {"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self._post("/api/engine/intake", body, {"Authorization": "Bearer " + "x" * 40})[0], 401)

    def test_intake_saves_with_user_jwt(self):
        CALLS.clear()
        body = json.dumps({"kind": "paste", "payload": {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/acme-9",
                                                        "text": "Our firm needs a consultant to automate HubSpot onboarding"}}).encode()
        code, res = self._post("/api/engine/intake", body, {"Authorization": "Bearer " + "u" * 40, "Content-Type": "application/json"})
        self.assertEqual((code, res["added"]), (200, 1))
        call = CALLS[-1]
        self.assertEqual(call["auth"], "Bearer " + "u" * 40)            # RLS evaluated as the signed-in user, not a service key
        self.assertEqual(call["body"]["p_items"][0]["source_key"], "linkedin")
        self.assertNotIn("results", res)

    def test_uploaded_fixture_is_refused(self):
        raw = (FX / "upwork_alert.eml").read_bytes()
        body = json.dumps({"kind": "email_file", "payload": {"eml_b64": base64.b64encode(raw).decode()}}).encode()
        code, res = self._post("/api/engine/intake", body, {"Authorization": "Bearer " + "u" * 40})
        self.assertEqual(code, 422)
        self.assertIn("SYNTHETIC", res["error"])

    def test_inbound_email_requires_token_and_parses_alert(self):
        raw = _strip((FX / "malt_alert.eml").read_bytes())
        self.assertEqual(self._post("/api/engine/inbound-email", raw, {"Content-Type": "message/rfc822"})[0], 401)
        self.assertEqual(self._post("/api/engine/inbound-email", raw, {"X-Signal-Token": "w" * 40})[0], 401)
        code, res = self._post("/api/engine/inbound-email", raw, {"X-Signal-Token": "t" * 40})
        self.assertEqual((code, res["added"]), (200, 1))
        self.assertEqual(CALLS[-1]["body"]["p_run"]["scope"], "inbound_email")

    def test_oversized_and_unknown_routes(self):
        self.assertEqual(self._post("/api/engine/nope", b"{}", {})[0], 404)
        try:   # refused before the body is read: the client sees 413 or a reset connection
            code = self._post("/api/engine/intake", b"x" * 3_000_001, {"Authorization": "Bearer " + "u" * 40})[0]
            self.assertEqual(code, 413)
        except (urllib.error.URLError, ConnectionError):
            pass
