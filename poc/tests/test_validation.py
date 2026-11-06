"""Tests for the validation layer (markets, unrestricted budgets, permissions, queues, reports).
Run from poc/: python -m unittest discover -s tests -v"""

from __future__ import annotations

import csv
import io
import json
import socket
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from signal_engine import markets, probe, sources, validate
from signal_engine.classify import classify
from signal_engine.collectors import discourse, ted
from signal_engine.collectors.http import (AUTH_REQUIRED, DNS_BLOCKED, PROXY_BLOCK, RATE_LIMITED,
                                           UPSTREAM_FORBIDDEN, FetchBlocked, PoliteClient, classify_error)
from signal_engine.models import Signal
from signal_engine.qualify import (EXCLUDED, PRIORITY_A, PRIORITY_B, PRIORITY_C, UNVERIFIED, WATCHLIST,
                                   parse_budget, qualify)

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


# ----------------------------------------------------------------------------- network error handling
class ErrorClassificationTests(unittest.TestCase):
    def test_proxy_block_vs_upstream(self):
        kind, status = classify_error(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden")))
        self.assertEqual((kind, status), (PROXY_BLOCK, 403))
        self.assertEqual(classify_error(http_error(403))[0], UPSTREAM_FORBIDDEN)
        self.assertEqual(classify_error(http_error(401))[0], AUTH_REQUIRED)
        self.assertEqual(classify_error(http_error(429))[0], RATE_LIMITED)
        self.assertEqual(classify_error(urllib.error.URLError(socket.gaierror(-2, "Name or service not known")))[0], DNS_BLOCKED)

    def test_unreachable_robots_is_not_reported_as_disallow(self):
        def opener(req, timeout):
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        with self.assertRaises(FetchBlocked) as cm:
            PoliteClient(opener=opener, sleep=lambda s: None).get_json("https://forum.example/t/1.json")
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
        r = probe.probe_url("h.example", self.EP, "s", "t",
                            open_fn=lambda u, ua, t: (_Resp(b'{"a":1}'), ["301 -> https://h.example/a.json"]))
        self.assertEqual((r.ok, r.kind, r.blocked_by, len(r.redirects)), (True, "ok", "none", 1))

    def test_login_redirect_is_auth(self):
        r = probe.probe_url("h.example", self.EP, "s", "t",
                            open_fn=lambda u, ua, t: (_Resp(b"<html>", url="https://h.example/login", ctype="text/html"), ["302"]))
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


# ----------------------------------------------------------------------------- helpers
def sig(title, text="", status="verified_api", posted="2026-11-01T00:00:00Z", source="contracts_finder", **kw):
    meta = kw.pop("raw_meta", {"kind": "forum_post", "closed": False})
    return Signal(source=source, source_id=title, url=f"https://example.invalid/{abs(hash(title + text))}", title=title,
                  text=text, verification_status=status, posted_at=posted, raw_meta=meta, **kw)


def q(s):
    return qualify(s, classify(s, now=NOW), now=NOW)


def tender(title, text="", value=None, currency="EUR", code=None, deadline="2026-12-15T12:00:00Z", source="ted", posted="2026-10-28T00:00:00Z"):
    meta = {"kind": "tender", "tender_status": "active"}
    if code:
        meta["buyer_country_code"] = code
    return Signal(source=source, source_id=title, url=f"https://ted.europa.eu/en/notice/-/detail/{abs(hash(title)) % 999999:06d}-2026",
                  title=title, text=text, verification_status="verified_api", posted_at=posted, deadline_at=deadline,
                  value_amount=value, value_currency=currency, raw_meta=meta)


# ----------------------------------------------------------------------------- markets
class MarketTests(unittest.TestCase):
    def test_target_markets(self):
        for text, market in [("Our London office", "UK"), ("Dubai-based retailer", "UAE"), ("Lyon manufacturer", "Europe"),
                             ("Zürich insurer", "Europe"), ("based in Norway", "Europe"), ("Belgrade startup", "Europe"),
                             ("Sarajevo agency", "Europe"), ("We are in Iceland", "Europe")]:
            self.assertEqual(markets.detect(text).market, market, text)

    def test_currency_is_never_location(self):
        for t in ("Budget £1,500", "EUR 50,000", "AED 8,000", "CHF 20k"):
            self.assertEqual(markets.detect(t).market, "unknown", t)

    def test_ambiguous_words_are_not_places(self):
        for t in ("Reading list automation", "Nice to have: Zapier", "Turkey dinner booking bot", "Georgia state office"):
            self.assertEqual(markets.detect(t).market, "unknown", t)

    def test_structured_codes(self):
        self.assertEqual(markets.from_code("FRA").country, "France")
        self.assertEqual(markets.from_code("CHE").market, "Europe")
        self.assertEqual(markets.from_code("ARE").market, "UAE")
        self.assertEqual(markets.from_code("USA").market, "other")

    def test_sanctions_and_transcontinental_flags(self):
        self.assertIn("sanctions_review", markets.from_code("RUS").flags)
        self.assertIn("transcontinental", markets.from_code("TUR").flags)


# ----------------------------------------------------------------------------- acceptance criteria
class AcceptanceTests(unittest.TestCase):
    def test_eur_50k_french_automation_not_rejected(self):
        s = tender("Mise en place d'une solution de workflow automation et intégration CRM",
                   "The city of Lyon seeks a provider for workflow automation and CRM integration services.",
                   value=50000, currency="EUR", code="FRA")
        r = q(s)
        self.assertEqual((r.country, r.market), ("France", "Europe"))
        self.assertIn(r.queue, (PRIORITY_A, PRIORITY_B))
        self.assertNotEqual(r.queue, EXCLUDED)
        self.assertEqual(r.budget_kind, "notice_value")
        self.assertTrue(r.budget_stated.startswith("EUR 50,000"))
        self.assertFalse(any("budget" in x.lower() for x in r.reasons))

    def test_very_large_project_flagged_not_rejected(self):
        r = q(tender("Intelligent automation delivery partner", "RPA and workflow automation services.", value=2_500_000,
                     currency="EUR", code="DEU"))
        self.assertIn(r.queue, (PRIORITY_A, PRIORITY_B))
        self.assertTrue(r.partnership_opportunity)
        self.assertIn("large_project_may_need_delivery_partner", r.risk_flags)
        self.assertEqual(r.complexity, "high")

    def test_swiss_opportunity_eligible(self):
        r = q(sig("Looking for a consultant to automate invoice processing for our Zürich office",
                  "We need an external partner to build AI document extraction into SAP. Budget CHF 30,000.",
                  source="human:linkedin", status="human_verified"))
        self.assertEqual((r.country, r.market), ("Switzerland", "Europe"))
        self.assertIn(r.queue, (PRIORITY_A, PRIORITY_B))

    def test_uae_opportunity_eligible(self):
        r = q(sig("Dubai clinic looking for an agency to build a WhatsApp booking chatbot", "Need it live this month.",
                  source="human:linkedin", status="human_verified"))
        self.assertEqual(r.market, "UAE")
        self.assertIn(r.queue, (PRIORITY_A, PRIORITY_B))

    def test_no_budget_remains_eligible(self):
        r = q(sig("Looking for a freelancer to automate invoicing between HubSpot and Xero for our Leeds office",
                  source="discourse:community.n8n.io"))
        self.assertEqual(r.budget_kind, "not_stated")
        self.assertEqual(r.queue, PRIORITY_A, r.missing_details)

    def test_small_budget_not_rejected(self):
        r = q(sig("Looking for a freelancer to set up a Zapier workflow for our Manchester shop, budget £150",
                  source="discourse:community.n8n.io"))
        self.assertEqual(r.queue, PRIORITY_A, r.reasons + r.missing_details)

    def test_unknown_location_goes_to_review(self):
        r = q(sig("Looking for a freelancer to automate invoicing in Xero. Budget £1,500.", source="discourse:community.n8n.io"))
        self.assertEqual(r.market, "unknown")
        self.assertEqual(r.queue, PRIORITY_B)
        self.assertIn("location unknown: review", r.missing_details)

    def test_vendor_still_rejected(self):
        for t in ("[For Hire] n8n and AI automations for UK and EU businesses, fixed price €500",
                  "I will build your Make.com automations — book a call with us"):
            r = q(sig(t, source="discourse:community.n8n.io"))
            self.assertEqual(r.queue, EXCLUDED, t)
            self.assertIn("vendor advertising its own services", r.reasons)

    def test_recruitment_and_physical_still_rejected(self):
        self.assertEqual(q(sig("JOB OFFER - n8n developer full time, salary, London")).queue, EXCLUDED)
        self.assertEqual(q(tender("Autonomous robot cell for warehouse picking", code="NLD")).queue, EXCLUDED)

    def test_out_of_market_closed_outdated_excluded(self):
        good = "Looking for a freelancer to automate invoicing between HubSpot and Xero"
        self.assertEqual(q(sig(good + " for our office in Ohio, USA")).queue, EXCLUDED)
        self.assertEqual(q(sig(good + " in Leeds", raw_meta={"kind": "forum_post", "closed": True})).queue, EXCLUDED)
        self.assertEqual(q(sig(good + " in Leeds", posted="2026-05-01T00:00:00Z")).queue, EXCLUDED)
        self.assertEqual(q(tender("Workflow automation services", code="FRA", deadline="2026-10-01T00:00:00Z")).queue, EXCLUDED)

    def test_stale_but_valid_goes_to_b(self):
        r = q(sig("Looking for a freelancer to automate invoicing in Leeds", posted="2026-09-20T00:00:00Z",
                  source="discourse:community.n8n.io"))
        self.assertEqual(r.queue, PRIORITY_B)

    def test_problem_without_request_is_priority_c(self):
        r = q(sig("Our Dublin team spends hours every week copying invoices from email into spreadsheets"))
        self.assertEqual(r.queue, PRIORITY_C)

    def test_search_title_never_verified(self):
        r = q(sig("Looking for a freelancer to automate invoicing in Leeds", status="search_index_only", posted=None))
        self.assertEqual(r.queue, UNVERIFIED)
        self.assertFalse(r.intent_verified)


class BudgetTests(unittest.TestCase):
    def test_budget_is_metadata_only(self):
        self.assertEqual(parse_budget("Budget £1,500")[2], "fixed_or_range")
        self.assertEqual(parse_budget("$800-$1,500 fixed")[0], "$800; $1,500")
        self.assertAlmostEqual(parse_budget("EUR 50,000")[1], 42500.0)
        self.assertEqual(parse_budget("CHF 1.500.000")[1], 1_500_000 * 0.88)
        self.assertEqual(parse_budget("€2m programme")[1], 2_000_000 * 0.85)
        self.assertEqual(parse_budget("$75–$95/hr ongoing")[2], "rate")
        self.assertEqual(parse_budget("no money mentioned")[:3], ("not stated", None, "not_stated"))

    def test_unknown_fields_are_explicit(self):
        r = q(sig("Need someone to set up automation", text=""))
        self.assertEqual(r.budget_stated, "not stated")
        self.assertTrue(r.business_requirement.startswith("unknown"))


# ----------------------------------------------------------------------------- permissions
class _StubClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.min_interval_s = 0
        self.user_agent = "test"
        self._sleep = lambda s: None

    def get_json(self, url, check_robots=None):
        self.calls.append(url)
        r = self.responses.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise FetchBlocked("nope", "not_found", 404)
        return r


class PermissionTests(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(set(sources.permitted_collectors()), {"contracts_finder", "find_a_tender", "ted"})
        self.assertEqual(set(sources.blocked_collectors()), {"discourse:community.n8n.io", "discourse:community.make.com"})
        for k in sources.blocked_collectors():
            self.assertTrue(sources.policy(k).blocker)

    def test_discover_never_calls_blocked_collectors(self):
        called = []
        plan = {
            "contracts_finder": lambda: called.append("cf") or [],
            "discourse:community.n8n.io": lambda: called.append("n8n") or [],
            "discourse:community.make.com": lambda: called.append("make") or [],
        }
        with tempfile.TemporaryDirectory() as d:
            old = validate.OUT
            validate.OUT = Path(d)
            try:
                _, logs = validate.cmd_discover(30, client=_StubClient({}), plan=plan)
            finally:
                validate.OUT = old
        self.assertEqual(called, ["cf"])
        skipped = {l["source"] for l in logs if l.get("kind") == "permission_not_obtained"}
        self.assertEqual(skipped, {"discourse:community.n8n.io", "discourse:community.make.com"})

    def test_collector_itself_refuses_without_permission(self):
        client = _StubClient({"https://community.n8n.io/c/jobs/13.json": {"topic_list": {"topics": []}}})
        with self.assertRaises(FetchBlocked) as cm:
            discourse.fetch_forum(client, "community.n8n.io")
        self.assertEqual(cm.exception.kind, "permission_not_obtained")
        self.assertEqual(client.calls, [])  # no request made

    def test_verify_skips_blocked_sources_without_request(self):
        cand = Signal(source="discourse:community.make.com", source_id="u", url="https://community.make.com/t/x/97223",
                      title="t", text="", verification_status="search_index_only")
        client = _StubClient({})
        got, log = validate.verify_one(client, cand)
        self.assertIsNone(got)
        self.assertEqual((log["result"], log["kind"]), ("skipped", "permission_not_obtained"))
        self.assertEqual(client.calls, [])

    def test_verify_permitted_source_records_failure_kind(self):
        cand = Signal(source="find_a_tender", source_id="u", url="https://www.find-tender.service.gov.uk/Notice/090524-2026",
                      title="t", text="", verification_status="search_index_only")
        client = _StubClient({"https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages/090524-2026":
                              FetchBlocked("blocked", PROXY_BLOCK, 403)})
        got, log = validate.verify_one(client, cand)
        self.assertIsNone(got)
        self.assertEqual((log["result"], log["kind"]), ("failed", PROXY_BLOCK))

    def test_discourse_parser_and_since_filter_still_work_when_permitted(self):
        topic = json.loads((FIX / "synthetic_discourse_topic.json").read_text())["topic"]
        s = discourse.parse_topic("community.n8n.io", topic)
        self.assertEqual(s.posted_at, "2026-11-02T08:00:00Z")
        listing = {"topic_list": {"topics": [{"id": 1, "created_at": "2026-11-01T00:00:00Z"},
                                             {"id": 2, "created_at": "2026-06-01T00:00:00Z"}]}}
        t1 = {"id": 1, "slug": "s", "title": "Looking for an n8n expert",
              "post_stream": {"posts": [{"created_at": "2026-11-01T00:00:00Z", "cooked": "<p>x</p>", "username": "u"}]}}
        client = _StubClient({"https://community.n8n.io/c/jobs/13.json": listing, "https://community.n8n.io/t/1.json": t1})
        orig = sources.SOURCES["discourse:community.n8n.io"]
        sources.SOURCES["discourse:community.n8n.io"] = sources.SourcePolicy(**{**orig.__dict__, "collection_permitted": True})
        try:
            out = discourse.fetch_forum(client, "community.n8n.io", since=datetime(2026, 10, 6, tzinfo=timezone.utc))
        finally:
            sources.SOURCES["discourse:community.n8n.io"] = orig
        self.assertEqual(len(out), 1)
        self.assertNotIn("https://community.n8n.io/t/2.json", client.calls)


# ----------------------------------------------------------------------------- TED parser
class TedTests(unittest.TestCase):
    def test_parse_multilingual_notice(self):
        n = {"publication-number": "654321-2026", "notice-title": {"fra": "Automatisation", "eng": "Workflow automation services"},
             "publication-date": "2026-10-20+02:00", "buyer-name": {"fra": ["Ville de Lyon"]}, "buyer-country": ["FRA"],
             "deadline-receipt-tender-date-lot": ["2026-12-01+01:00"], "description-lot": {"eng": ["Automate invoice workflows."]}}
        s = ted.parse_notice(n)
        self.assertEqual(s.url, "https://ted.europa.eu/en/notice/-/detail/654321-2026")
        self.assertEqual((s.title, s.organisation), ("Workflow automation services", "Ville de Lyon"))
        self.assertTrue(s.posted_at.startswith("2026-10-20"))
        r = q(s)
        self.assertEqual((r.country, r.market), ("France", "Europe"))

    def test_query_has_date_and_keywords(self):
        qy = ted.build_query("20261006")
        self.assertTrue(qy.startswith("publication-date>=20261006 AND ("))
        self.assertIn('FT~"workflow automation"', qy)

    def test_notice_without_number_skipped(self):
        self.assertIsNone(ted.parse_notice({"notice-title": "x"}))


# ----------------------------------------------------------------------------- reports
class ReportTests(unittest.TestCase):
    def test_queues_csv_markdown_and_counts(self):
        recs_in = [
            sig("Looking for a freelancer to automate invoicing between HubSpot and Xero for our Leeds office",
                source="discourse:community.n8n.io"),
            tender("Workflow automation and CRM integration services", value=50000, code="FRA"),
            sig("[For Hire] n8n automations, fixed price", source="discourse:community.n8n.io"),
            sig("Looking for a freelancer to automate invoicing in Leeds (copy)", status="search_index_only", posted=None),
            sig("Our Dublin team spends hours copying invoices into spreadsheets", text="manual data entry"),
            sig("Looking for someone to automate reporting in Dubai", status="synthetic"),
        ]
        recs, funnel, md = validate.build_report(recs_in, now=NOW)
        self.assertEqual(funnel["genuine_records"], 4)
        # The direct post is Priority A; the relevant tender is Priority B because a published notice needs its
        # procedure checked before it counts as a contactable buyer.
        self.assertEqual(funnel["by_queue"][PRIORITY_A], 1)
        self.assertEqual(funnel["by_queue"][PRIORITY_B], 1)
        self.assertEqual(funnel["by_queue"][PRIORITY_C], 1)
        self.assertEqual(funnel["by_queue"][UNVERIFIED], 1)
        for title in ("Priority A — Immediate opportunities", "Priority B — Promising opportunities",
                      "Priority C — Potential prospects", "Excluded", "Source permissions"):
            self.assertIn(title, md)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.csv"
            validate.write_csv(path, recs)
            rows = list(csv.DictReader(path.open()))
        self.assertEqual(len(rows), len(recs))
        self.assertEqual(set(rows[0]), set(validate.CSV_COLUMNS))

    def test_no_personal_contact_details_in_outputs(self):
        s = Signal(source="human:linkedin", source_id="x", url="https://example.invalid/p",
                   title="Looking for an automation agency in Paris", text="Call me on +33 6 12 34 56 78 or jean@example.invalid",
                   verification_status="human_verified", posted_at="2026-11-01T00:00:00Z", author_handle="jean.dupont")
        from signal_engine.textutil import make_excerpt
        s.text = make_excerpt(s.text)
        recs, _, md = validate.build_report([s], now=NOW)
        blob = md + json.dumps(recs)
        for secret in ("jean@example.invalid", "12 34 56 78", "jean.dupont"):
            self.assertNotIn(secret, blob)

    def test_max_records_cap_keeps_most_actionable(self):
        many = [sig(f"Unrelated catering contract number {i}", posted="2026-11-01T00:00:00Z") for i in range(5)]
        good = sig("Looking for a freelancer to automate invoicing for our Leeds office", source="discourse:community.n8n.io")
        recs, funnel, _ = validate.build_report(many + [good], now=NOW, max_records=2)
        self.assertEqual(funnel["genuine_records"], 2)
        self.assertEqual(funnel["genuine_dropped_by_max_records_cap"], 4)
        self.assertIn(good.url, {r["url"] for r in recs})

    def test_human_capture_counts_as_genuine(self):
        s = sig("Looking for an automation agency in Paris", status="human_verified", source="human:linkedin")
        self.assertTrue(s.is_genuine)
        self.assertIsNone(q(s).contact_permitted)  # unknown platform rules: not assumed


if __name__ == "__main__":
    unittest.main()
