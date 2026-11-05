"""Unit + integration tests. Run from poc/:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from signal_engine import pipeline
from signal_engine.classify import classify
from signal_engine.collectors import discourse, ocds, search_candidates
from signal_engine.collectors.http import FetchBlocked, PoliteClient
from signal_engine.dedupe import dedupe
from signal_engine.models import Signal
from signal_engine.textutil import canonical_url, clean_title, make_excerpt, redact_pii

POC = Path(__file__).resolve().parents[1]
FIX = POC / "fixtures"
NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def sig(title: str, text: str = "", status: str = "verified_api", posted: str | None = "2026-11-01T00:00:00Z",
        url: str | None = None, **kw) -> Signal:
    return Signal(source="test", source_id=url or title, url=url or f"https://example.invalid/{abs(hash(title))}",
                  title=title, text=text, verification_status=status, posted_at=posted, **kw)


class TextUtilTests(unittest.TestCase):
    def test_pii_redacted(self):
        out = redact_pii("mail jo@acme.invalid or call +44 7700 900123 — budget £1,500")
        self.assertNotIn("jo@acme.invalid", out)
        self.assertNotIn("7700", out)
        self.assertIn("£1,500", out)  # money must survive redaction

    def test_excerpt_strips_html_and_caps_length(self):
        ex = make_excerpt("<p>" + "word " * 500 + "</p>")
        self.assertNotIn("<p>", ex)
        self.assertLessEqual(len(ex), 602)

    def test_canonical_url_variants_match(self):
        a = canonical_url("https://community.n8n.io/t/foo/123?tl=en")
        b = canonical_url("https://community.n8n.io/t/foo/123/")
        self.assertEqual(a, b)
        c = canonical_url("https://www.contractsfinder.service.gov.uk/notice/ABC?origin=SearchResults&p=1")
        d = canonical_url("https://www.contractsfinder.service.gov.uk/Notice/abc")
        self.assertEqual(c, d)

    def test_clean_title_removes_site_suffix(self):
        self.assertEqual(clean_title("Looking for X - Jobs - n8n Community"), "Looking for X")
        self.assertEqual(clean_title("Thing - Hire Help - Make Community"), "Thing")


class DedupeTests(unittest.TestCase):
    def test_same_url_and_near_duplicate(self):
        s1 = sig("Need someone to automate invoicing", "We use Xero and spend hours on it every week",
                 url="https://community.n8n.io/t/a/1", posted="2026-11-01T00:00:00Z")
        s2 = sig("Need someone to automate invoicing", "dup", url="https://community.n8n.io/t/a/1?tl=en",
                 posted="2026-11-02T00:00:00Z")
        s3 = sig("Need someone to automate invoicing!", "We use Xero and spend hours on it every week",
                 url="https://community.make.com/t/b/2", posted="2026-11-03T00:00:00Z")
        kept, dropped = dedupe([s3, s2, s1])
        self.assertEqual([k.url for k in kept], [s1.url])  # earliest wins
        self.assertEqual(sorted(d["reason"] for d in dropped), ["same_content", "same_url"])

    def test_distinct_posts_kept(self):
        kept, _ = dedupe([sig("Automate our CRM reporting"), sig("Chatbot for our dental clinic in Dubai")])
        self.assertEqual(len(kept), 2)


class OcdsParserTests(unittest.TestCase):
    def setUp(self):
        data = json.loads((FIX / "synthetic_contracts_finder_package.json").read_text())
        # Parse as if verified so gating logic is exercised; the fixture itself is synthetic.
        self.sigs = ocds.parse_release_package(data["package"], "contracts_finder", verification_status="verified_api")

    def test_release_without_url_is_skipped(self):
        self.assertEqual(len(self.sigs), 3)

    def test_fields_and_redaction(self):
        s = self.sigs[0]
        self.assertEqual(s.url, "https://www.contractsfinder.service.gov.uk/Notice/00000000-0000-4000-8000-000000000001")
        self.assertEqual(s.organisation, "SYNTHETIC Parish Council")
        self.assertEqual(s.value_amount, 2500)
        self.assertNotIn("clerk@example.invalid", s.text)
        self.assertNotIn("567890", s.text)

    def test_open_small_tender_is_tier_a(self):
        c = classify(self.sigs[0], now=NOW)
        self.assertEqual((c.intent_tier, c.actionable, c.freshness), ("A", "A", "fresh"))
        self.assertIn("Invoice", c.suggested_service)

    def test_physical_automation_rejected(self):
        c = classify(self.sigs[1], now=NOW)
        self.assertEqual(c.reject_reason, "unrelated_physical_or_industrial_automation")

    def test_closed_large_tender_not_actionable(self):
        c = classify(self.sigs[2], now=NOW)
        self.assertEqual(c.freshness, "closed")
        self.assertEqual(c.actionable, "REJECT")
        self.assertIn("value_far_above_ticket_size", c.fit_flags)

    def test_fts_url_mapping(self):
        r = {"id": "ocds-h6vhtk-012345-090524-2026", "tender": {}}
        self.assertEqual(ocds.fts_notice_url(r), "https://www.find-tender.service.gov.uk/Notice/090524-2026")


class DiscourseParserTests(unittest.TestCase):
    def test_parse_and_classify(self):
        data = json.loads((FIX / "synthetic_discourse_topic.json").read_text())
        s = discourse.parse_topic(data["_host"], data["topic"], verification_status="verified_api")
        self.assertEqual(s.url, "https://community.n8n.io/t/synthetic-need-someone-to-connect-crm/999001")
        self.assertEqual(s.author_handle, "synthetic_user")
        self.assertNotIn("someone@example.invalid", s.text)
        c = classify(s, now=NOW)
        self.assertEqual(c.intent_tier, "A")
        self.assertEqual(c.country, "UK")
        matched = {e.feature for e in c.evidence}
        self.assertTrue({"looking_for_provider", "money_amount"} <= matched)


class ClassifierRuleTests(unittest.TestCase):
    def tier(self, title, text=""):
        return classify(sig(title, text), now=NOW).intent_tier

    def test_brief_examples(self):
        self.assertEqual(self.tier("Looking for someone to automate our invoicing."), "B")
        self.assertEqual(self.tier("Can anyone recommend an AI automation consultant?"), "B")
        self.assertEqual(self.tier("We need help connecting our CRM to our existing systems."), "B")
        self.assertEqual(self.tier("Looking for someone to automate our manual reporting."), "B")

    def test_hard_negatives(self):
        self.assertEqual(self.tier("[For Hire] Zapier migration, fixed price $350"), "REJECT")
        self.assertEqual(self.tier("Hiring: Senior Make.com Automation Engineers (Ongoing Contractor Work, $75–$95/hr)"), "REJECT")
        self.assertEqual(self.tier("We're hiring a full-time Automation Engineer, salary £55k"), "REJECT")
        self.assertEqual(self.tier("Robotics Process Automation Tool"), "D")  # not physical robots
        self.assertEqual(self.tier("Can anyone recommend a good accountant?"), "REJECT")

    def test_problem_without_request_is_c(self):
        self.assertEqual(self.tier("Our team spends hours every week copying data from emails into spreadsheets."), "C")

    def test_generic_automation_word_cannot_reach_a(self):
        self.assertEqual(self.tier("Expert needed for automation project, budget £2,000"), "B")

    def test_freelance_hiring_is_not_recruitment(self):
        self.assertEqual(self.tier("Hiring: Freelance Zapier expert for a one-off project, £800 fixed"), "A")

    def test_every_tier_has_evidence_from_text(self):
        s = sig("Looking for a freelancer to automate invoicing in Xero. Budget £1,500.")
        c = classify(s, now=NOW)
        for e in c.evidence:
            self.assertIn(e.matched.lower(), (s.title + "\n" + s.text).lower())


class GatingTests(unittest.TestCase):
    T = "Looking for a freelancer to automate invoicing in Xero. Budget £1,500."

    def test_search_only_is_held_and_not_genuine(self):
        s = sig(self.T, status="search_index_only", posted=None)
        self.assertFalse(s.is_genuine)
        self.assertEqual(classify(s, now=NOW).actionable, "HOLD_VERIFY")

    def test_synthetic_is_test_only(self):
        s = sig(self.T, status="synthetic")
        self.assertFalse(s.is_genuine)
        self.assertEqual(classify(s, now=NOW).actionable, "TEST_ONLY")

    def test_stale_downgraded_outdated_rejected_unknown_capped(self):
        self.assertEqual(classify(sig(self.T, posted="2026-09-20T00:00:00Z"), now=NOW).actionable, "B")
        self.assertEqual(classify(sig(self.T, posted="2026-01-01T00:00:00Z"), now=NOW).actionable, "REJECT")
        self.assertEqual(classify(sig(self.T, posted=None), now=NOW).actionable, "C")

    def test_bad_url_rejected(self):
        with self.assertRaises(ValueError):
            sig("x", url="http://insecure.example")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class HttpClientTests(unittest.TestCase):
    def test_robots_disallow_blocks(self):
        def opener(req, timeout):
            if req.full_url.endswith("/robots.txt"):
                return _Resp(b"User-agent: *\nDisallow: /")
            raise AssertionError("must not fetch disallowed URL")
        c = PoliteClient(opener=opener, sleep=lambda s: None)
        with self.assertRaises(FetchBlocked):
            c.get_json("https://forum.example/t/1.json")

    def test_rate_limit_and_json(self):
        slept = []
        c = PoliteClient(min_interval_s=5, opener=lambda r, t: _Resp(b'{"ok": 1}'), check_robots=False, sleep=slept.append)
        self.assertEqual(c.get_json("https://api.example/a"), {"ok": 1})
        c.get_json("https://api.example/b")
        self.assertTrue(slept and slept[0] > 4)

    def test_network_denial_surfaces_as_blocked(self):
        def opener(req, timeout):
            raise OSError("Tunnel connection failed: 403 Forbidden")
        c = PoliteClient(opener=opener, check_robots=False, sleep=lambda s: None)
        with self.assertRaises(FetchBlocked):
            c.get_json("https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search")


class PipelineTests(unittest.TestCase):
    def test_end_to_end_counts_are_honest(self):
        sigs = pipeline.load_fixtures(FIX) + search_candidates.load(POC / "data" / "search_candidates_2026-11-05.json")
        with tempfile.TemporaryDirectory() as d:
            summary = pipeline.run(sigs, Path(d), now=NOW)
            rows = [json.loads(l) for l in (Path(d) / "signals.jsonl").read_text().splitlines()]
        self.assertEqual(summary["genuine_verified_signals"], 0)
        self.assertEqual(summary["by_verification"].get("verified_api", 0), 0)
        self.assertNotIn("A", summary["by_actionable"])  # nothing actionable without verification
        for r in rows:
            self.assertTrue(r["signal"]["url"].startswith("https://"))
            if r["classification"]["intent_tier"] != "REJECT":
                self.assertTrue(r["classification"]["evidence"], r["signal"]["title"])


if __name__ == "__main__":
    unittest.main()
