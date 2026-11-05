"""Tests for the Phase 2A validation layer. Run from poc/: python -m unittest discover -s tests -v"""

from __future__ import annotations

import io
import json
import socket
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from signal_engine import probe, validate
from signal_engine.classify import classify
from signal_engine.collectors import discourse
from signal_engine.collectors.http import (AUTH_REQUIRED, DNS_BLOCKED, PROXY_BLOCK, RATE_LIMITED,
                                           UPSTREAM_FORBIDDEN, FetchBlocked, PoliteClient, classify_error)
from signal_engine.models import Signal
from signal_engine.qualify import parse_budget, qualify

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
FIX = Path(__file__).resolve().parents[1] / "fixtures"


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.example/", code, "msg", Message(), io.BytesIO(b""))


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, url: str = "https://x.example/", ctype: str = "application/json", status: int = 200):
        super().__init__(body)
        self.headers = {"Content-Type": ctype}
        self.status = status
        self._url = url

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class ErrorClassificationTests(unittest.TestCase):
    def test_proxy_block_vs_upstream(self):
        kind, status = classify_error(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden")))
        self.assertEqual((kind, status), (PROXY_BLOCK, 403))
        self.assertEqual(classify_error(http_error(403))[0], UPSTREAM_FORBIDDEN)  # origin answered
        self.assertEqual(classify_error(http_error(401))[0], AUTH_REQUIRED)
        self.assertEqual(classify_error(http_error(429))[0], RATE_LIMITED)
        self.assertEqual(classify_error(urllib.error.URLError(socket.gaierror(-2, "Name or service not known")))[0], DNS_BLOCKED)

    def test_unreachable_robots_is_not_reported_as_disallow(self):
        def opener(req, timeout):
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        c = PoliteClient(opener=opener, sleep=lambda s: None)
        with self.assertRaises(FetchBlocked) as cm:
            c.get_json("https://community.n8n.io/t/1.json")
        self.assertEqual(cm.exception.kind, PROXY_BLOCK)

    def test_missing_robots_allows(self):
        def opener(req, timeout):
            if req.full_url.endswith("robots.txt"):
                raise http_error(404)
            return _Resp(b'{"ok": true}')
        self.assertEqual(PoliteClient(opener=opener, sleep=lambda s: None).get_json("https://f.example/a.json"), {"ok": True})


class ProbeTests(unittest.TestCase):
    EP = {"name": "x", "url": "https://h.example/a.json", "expect": "json", "confirmed": True}

    def test_ok_json(self):
        r = probe.probe_url("h.example", self.EP, "2026-10-06", "2026-11-05",
                            open_fn=lambda u, ua, t: (_Resp(b'{"a":1}'), ["301 -> https://h.example/a.json"]))
        self.assertTrue(r.ok)
        self.assertEqual((r.kind, r.blocked_by, len(r.redirects)), ("ok", "none", 1))

    def test_login_redirect_is_auth(self):
        r = probe.probe_url("h.example", self.EP, "s", "t",
                            open_fn=lambda u, ua, t: (_Resp(b"<html>", url="https://h.example/login", ctype="text/html"), ["302 -> /login"]))
        self.assertEqual((r.kind, r.blocked_by), ("auth_required", "source"))

    def test_proxy_block_attributed_to_us(self):
        def boom(u, ua, t):
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        r = probe.probe_url("h.example", self.EP, "s", "t", open_fn=boom)
        self.assertEqual((r.kind, r.blocked_by, r.status), ("proxy_block", "our_network_policy", 403))

    def test_upstream_403_attributed_to_source(self):
        def boom(u, ua, t):
            raise http_error(403)
        r = probe.probe_url("h.example", self.EP, "s", "t", open_fn=boom)
        self.assertEqual((r.kind, r.blocked_by), ("upstream_forbidden", "source"))


def sig(title, text="", status="verified_api", posted="2026-11-01T00:00:00Z", source="discourse:community.n8n.io", **kw):
    return Signal(source=source, source_id=title, url=f"https://community.n8n.io/t/x/{abs(hash(title))}", title=title,
                  text=text, verification_status=status, posted_at=posted,
                  raw_meta=kw.pop("raw_meta", {"kind": "forum_post", "closed": False}), **kw)


def q(s):
    return qualify(s, classify(s, now=NOW), now=NOW)


class QualificationTests(unittest.TestCase):
    GOOD = "Looking for a freelancer to automate invoicing between HubSpot and Xero for our Leeds office. Budget £1,500."

    def test_budget_parsing(self):
        self.assertEqual(parse_budget("Budget £1,500")[2], "fit")
        self.assertEqual(parse_budget("$800-$1,500 fixed")[2], "fit")
        self.assertEqual(parse_budget("AED 8,000")[2], "fit")
        self.assertEqual(parse_budget("£215,000")[2], "out")
        self.assertEqual(parse_budget("$75–$95/hr ongoing")[2], "hourly_only")
        self.assertEqual(parse_budget("no money mentioned")[0], "unknown")

    def test_verified_fresh_uk_tier_a_qualifies(self):
        r = q(sig(self.GOOD))
        self.assertEqual(r.qualification, "QUALIFIED", r.reasons)
        self.assertEqual((r.country, r.budget_fit, r.availability), ("UK", "fit", "no_visible_closure"))
        self.assertTrue(r.intent_verified)

    def test_no_visible_closure_is_not_verified_open(self):
        self.assertNotEqual(q(sig(self.GOOD)).availability, "verified_open")

    def test_currency_is_not_location_evidence(self):
        r = q(sig("Looking for a freelancer to automate invoicing in Xero. Budget £1,500."))
        self.assertEqual(r.country, "unknown")

    def test_unknown_location_needs_review(self):
        r = q(sig("Looking for a freelancer to automate invoicing in Xero. Budget £1,500."))
        self.assertEqual(r.qualification, "NEEDS_REVIEW")
        self.assertIn("UK/UAE location not evidenced", r.reasons)

    def test_search_title_never_qualifies(self):
        r = q(sig(self.GOOD, status="search_index_only", posted=None))
        self.assertNotEqual(r.qualification, "QUALIFIED")
        self.assertFalse(r.intent_verified)

    def test_stale_closed_nonukuae_recruitment_excluded(self):
        self.assertEqual(q(sig(self.GOOD, posted="2026-08-01T00:00:00Z")).qualification, "EXCLUDED")
        self.assertEqual(q(sig(self.GOOD, raw_meta={"kind": "forum_post", "closed": True})).qualification, "EXCLUDED")
        self.assertEqual(q(sig(self.GOOD.replace("Leeds office", "office in Ohio, USA"))).qualification, "EXCLUDED")
        self.assertEqual(q(sig("JOB OFFER - n8n developer full time, salary, London")).qualification, "EXCLUDED")
        self.assertEqual(q(sig("[For Hire] n8n automations for UK businesses, fixed price £500")).qualification, "EXCLUDED")

    def test_large_tender_excluded_as_out_of_budget(self):
        s = Signal(source="contracts_finder", source_id="t", url="https://www.contractsfinder.service.gov.uk/Notice/x",
                   title="Intelligent automation delivery partner", text="RPA and workflow automation services",
                   verification_status="verified_api", posted_at="2026-11-01T00:00:00Z", deadline_at="2026-12-01T00:00:00Z",
                   value_amount=215000, value_currency="GBP", raw_meta={"kind": "tender"})
        r = q(s)
        self.assertEqual((r.country, r.availability, r.budget_fit, r.qualification), ("UK", "verified_open", "out", "EXCLUDED"))

    def test_unknown_fields_are_literal_unknown(self):
        r = q(sig("Need someone to set up automation", text=""))
        self.assertEqual(r.budget_stated, "unknown")
        self.assertTrue(r.buyer_request.startswith("unknown"))


class _StubClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_json(self, url, check_robots=None):
        self.calls.append(url)
        r = self.responses.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise FetchBlocked("nope", "not_found", 404)
        return r


class VerifyAndDiscoverTests(unittest.TestCase):
    def test_verify_discourse_candidate(self):
        topic = json.loads((FIX / "synthetic_discourse_topic.json").read_text())["topic"]
        cand = Signal(source="discourse:community.n8n.io", source_id="u",
                      url="https://community.n8n.io/t/some-slug/999001?tl=en", title="t", text="",
                      verification_status="search_index_only")
        client = _StubClient({"https://community.n8n.io/t/999001.json": topic})
        got, log = validate.verify_one(client, cand)
        self.assertEqual(log["result"], "verified")
        self.assertEqual(got.verification_status, "verified_api")
        self.assertEqual(got.posted_at, "2026-11-02T08:00:00Z")

    def test_verify_records_block_kind(self):
        cand = Signal(source="discourse:community.make.com", source_id="u", url="https://community.make.com/t/x/97223",
                      title="t", text="", verification_status="search_index_only")
        client = _StubClient({"https://community.make.com/t/97223.json": FetchBlocked("blocked", PROXY_BLOCK, 403)})
        got, log = validate.verify_one(client, cand)
        self.assertIsNone(got)
        self.assertEqual((log["result"], log["kind"]), ("failed", PROXY_BLOCK))

    def test_discourse_since_filter_skips_old_topics_before_detail_fetch(self):
        listing = {"topic_list": {"topics": [
            {"id": 1, "created_at": "2026-11-01T00:00:00Z"},
            {"id": 2, "created_at": "2026-06-01T00:00:00Z"},
            {"id": 3, "pinned": True, "created_at": "2026-11-01T00:00:00Z"}]}}
        topic = {"id": 1, "slug": "s", "title": "Looking for an n8n expert", "post_stream": {"posts": [
            {"created_at": "2026-11-01T00:00:00Z", "cooked": "<p>Need help</p>", "username": "u"}]}}
        client = _StubClient({"https://community.n8n.io/c/jobs/13.json": listing, "https://community.n8n.io/t/1.json": topic})
        out = discourse.fetch_forum(client, "community.n8n.io", since=datetime(2026, 10, 6, tzinfo=timezone.utc))
        self.assertEqual(len(out), 1)
        self.assertNotIn("https://community.n8n.io/t/2.json", client.calls)


class ReportTests(unittest.TestCase):
    def test_funnel_counts_only_genuine(self):
        good = sig(QualificationTests.GOOD)
        title_only = sig(QualificationTests.GOOD + " (copy)", status="search_index_only", posted=None)
        synthetic = sig("Looking for someone to automate reporting in Dubai, budget AED 6,000", status="synthetic")
        recs, funnel, md = validate.build_report([good, title_only, synthetic], now=NOW)
        self.assertEqual(funnel["genuine_records"], 1)
        self.assertEqual(funnel["1_verified_uk_uae_last_30d"], 1)
        self.assertEqual(funnel["qualified"], 1)
        self.assertIn("low (title only)", md)

    def test_human_capture_counts_as_genuine(self):
        s = sig(QualificationTests.GOOD, status="human_verified", source="human:linkedin")
        self.assertTrue(s.is_genuine)
        self.assertEqual(q(s).contact_permitted, None)  # unknown platform policy -> unknown, not assumed


if __name__ == "__main__":
    unittest.main()
