"""The deployed engine endpoints (web/api/engine/*.py) — exercised exactly as Vercel loads them: each file imported from
a copy of the deployment layout (api/ + pyengine/), served over real HTTP, under several request-path forms, against a
fake Supabase. Mocked Supabase responses here are NOT live integration evidence (see docs/platform/acceptance-tests.md)."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "poc" / "fixtures" / "alerts"
CALLS: list[dict] = []
USER_JWT = "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiJ1In0" + ".sig_" + "u" * 20
PUBLISHABLE = "sb_publishable_" + "p" * 24


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

    def _key_ok(self) -> bool:
        a = self.headers.get("Authorization")
        # the platform rejects an opaque sb_ key in Authorization
        return self.headers.get("apikey") == os.environ["SUPABASE_PUBLISHABLE_KEY"] and not (a and a.startswith("Bearer sb_"))

    def do_GET(self):
        if self.path == "/auth/v1/user":
            ok = self._key_ok() and self.headers.get("Authorization") == f"Bearer {USER_JWT}"
            return self._json(200 if ok else 401, {"id": "user-1"} if ok else {"message": "bad jwt"})
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if not self._key_ok() or self.headers.get("Content-Profile") != "solvant":
            return self._json(401, {"message": "bad key or schema"})
        if self.path.endswith("/save_intake"):
            if self.headers.get("Authorization") != f"Bearer {USER_JWT}":
                return self._json(401, {"message": "no user"})
            return self._json(200, {"added": len(body["p_items"]), "updated": 0, "duplicates": 0, "rejected": 0, "results": ["added"]})
        if self.path.endswith("/ingest_records"):
            if body["p_token"] != "t" * 40:
                return self._json(401, {"message": "invalid token"})
            return self._json(200, {"added": len(body["p_items"])})
        self._json(404, {})


def _strip(raw: bytes) -> bytes:
    t = re.sub(r"^X-Fixture:.*\n", "", raw.decode(), flags=re.M).replace("SYNTHETIC FIXTURE", "").replace("SYNTHETIC test alert", "")
    return t.replace("example.invalid", "example.com").encode()


def _load_endpoint(bundle: Path, name: str):
    spec = importlib.util.spec_from_file_location(f"vercel_fn_{name.replace('-', '_')}", bundle / "api" / "engine" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert issubclass(mod.handler, BaseHTTPRequestHandler) and mod.handler.OP == name
    return mod.handler


class DeployedEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = HTTPServer(("127.0.0.1", 0), FakeSupabase)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        os.environ["SUPABASE_URL"] = f"http://127.0.0.1:{cls.fake.server_port}"
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = PUBLISHABLE
        os.environ.pop("SUPABASE_ANON_KEY", None)
        # copy the deployment layout (what vercel.json bundles: api/engine/*.py + includeFiles pyengine/**)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.tmp.name)
        shutil.copytree(ROOT / "web" / "api", cls.bundle / "api")
        shutil.copytree(ROOT / "web" / "pyengine", cls.bundle / "pyengine", ignore=shutil.ignore_patterns("__pycache__"))
        cls.servers, cls.base = [], {}
        for name in ("health", "intake", "inbound-email"):
            srv = HTTPServer(("127.0.0.1", 0), _load_endpoint(cls.bundle, name))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
            cls.base[name] = f"http://127.0.0.1:{srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers + [cls.fake]:
            s.shutdown()
        cls.tmp.cleanup()

    def _req(self, name, path, data=None, headers=None, method=None):
        req = urllib.request.Request(self.base[name] + path, data=data, method=method or ("POST" if data is not None else "GET"), headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()), r.headers.get("X-Solvant-Endpoint")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), e.headers.get("X-Solvant-Endpoint")

    def test_vercel_config_routes_files_not_rewrites(self):
        cfg = json.loads((ROOT / "web" / "vercel.json").read_text())
        self.assertNotIn("rewrites", cfg)
        self.assertIn("pyengine/**", cfg["functions"]["api/engine/*.py"]["includeFiles"])
        self.assertEqual(sorted(p.name for p in (ROOT / "web" / "api" / "engine").glob("*.py")), ["health.py", "inbound-email.py", "intake.py"])
        self.assertFalse(list((ROOT / "web" / "api").glob("*.py")), "no catch-all function file at api/ root")

    def test_operation_is_independent_of_the_request_path(self):
        for path in ("/api/engine/health", "/api/engine/health.py", "/", "/anything?x=1"):
            code, body, ep = self._req("health", path)
            self.assertEqual((code, body["endpoint"], ep), (200, "health", "health"), path)
        for path in ("/api/engine/intake", "/api/engine/intake.py", "/"):
            code, body, ep = self._req("intake", path, data=b"{}", headers={"Content-Type": "application/json"})
            self.assertEqual((code, ep), (401, "intake"), path)
        code, _, ep = self._req("inbound-email", "/api/engine/inbound-email", data=b"x", headers={})
        self.assertEqual((code, ep), (401, "inbound-email"))
        self.assertEqual(self._req("intake", "/api/engine/intake")[0], 405)      # GET on a POST endpoint

    def test_intake_requires_valid_session(self):
        body = json.dumps({"kind": "paste", "payload": {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/a", "text": "Need CRM help"}}).encode()
        self.assertEqual(self._req("intake", "/", body, {"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self._req("intake", "/", body, {"Authorization": "Bearer " + "x" * 40})[0], 401)

    def test_intake_saves_with_user_jwt_and_publishable_key(self):
        CALLS.clear()
        body = json.dumps({"kind": "paste", "payload": {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/acme-9",
                                                        "text": "Our firm needs a consultant to automate HubSpot onboarding"}}).encode()
        code, res, _ = self._req("intake", "/api/engine/intake", body, {"Authorization": f"Bearer {USER_JWT}", "Content-Type": "application/json"})
        self.assertEqual((code, res["added"]), (200, 1))
        h = CALLS[-1]["headers"]
        self.assertEqual((h.get("apikey"), h.get("authorization"), h.get("content-profile")), (PUBLISHABLE, f"Bearer {USER_JWT}", "solvant"))
        self.assertNotIn("results", res)

    def test_uploaded_fixture_is_refused(self):
        raw = (FX / "upwork_alert.eml").read_bytes()
        body = json.dumps({"kind": "email_file", "payload": {"eml_b64": base64.b64encode(raw).decode()}}).encode()
        code, res, _ = self._req("intake", "/", body, {"Authorization": f"Bearer {USER_JWT}"})
        self.assertEqual(code, 422)
        self.assertIn("SYNTHETIC", res["error"])

    def test_inbound_email_machine_path_sends_no_bearer_key(self):
        raw = _strip((FX / "malt_alert.eml").read_bytes())
        self.assertEqual(self._req("inbound-email", "/", raw, {"Content-Type": "message/rfc822"})[0], 401)
        self.assertEqual(self._req("inbound-email", "/", raw, {"X-Signal-Token": "w" * 40})[0], 401)
        code, res, _ = self._req("inbound-email", "/", raw, {"X-Signal-Token": "t" * 40})
        self.assertEqual((code, res["added"]), (200, 1))
        h = CALLS[-1]["headers"]
        self.assertEqual(h.get("apikey"), PUBLISHABLE)
        self.assertNotIn("authorization", h)                     # opaque publishable key is never sent as a bearer token
        self.assertEqual(CALLS[-1]["body"]["p_run"]["scope"], "inbound_email")

    def test_oversized_bodies_refused(self):
        try:
            code = self._req("intake", "/", b"x" * 3_000_001, {"Authorization": f"Bearer {USER_JWT}"})[0]
            self.assertEqual(code, 413)
        except (urllib.error.URLError, ConnectionError):
            pass


class KeyHandling(unittest.TestCase):
    def test_modern_publishable_key(self):
        from signal_engine.discovery.platform.rest import headers, key_kind
        self.assertEqual(key_kind(PUBLISHABLE), "publishable")
        h = headers(PUBLISHABLE, write=True)
        self.assertEqual(h["apikey"], PUBLISHABLE)
        self.assertNotIn("Authorization", h)
        self.assertEqual((h["Accept-Profile"], h["Content-Profile"]), ("solvant", "solvant"))
        self.assertEqual(headers(PUBLISHABLE, USER_JWT)["Authorization"], f"Bearer {USER_JWT}")

    def test_legacy_anon_jwt_key(self):
        from signal_engine.discovery.platform.rest import headers, key_kind
        legacy = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiJ9.abc_DEF-123"
        self.assertEqual(key_kind(legacy), "legacy_jwt")
        self.assertEqual(headers(legacy)["Authorization"], f"Bearer {legacy}")
        self.assertEqual(headers(legacy, USER_JWT)["Authorization"], f"Bearer {USER_JWT}")

    def test_secret_key_and_bad_tokens_refused(self):
        from signal_engine.discovery.platform import rest
        old = {k: os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")}
        try:
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"] = "https://x.supabase.co", "sb_secret_" + "s" * 20
            with self.assertRaises(rest.RestError):
                rest._base()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        with self.assertRaises(rest.RestError):
            rest.headers(PUBLISHABLE, "sb_publishable_not_a_jwt")
