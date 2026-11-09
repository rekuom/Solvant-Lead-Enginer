"""Phase 4 discovery tests. Synthetic texts are regression guards (paraphrased from categories seen in the
live GitHub run of 2026-11-06); they are NOT evidence of real-world lead quality."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from signal_engine.discovery import intake, querylib, registry, router
from signal_engine.discovery.assess import assess
from signal_engine.discovery.connectors import github as gh
from signal_engine.discovery.connectors import hn
from signal_engine.discovery.connectors.search import BraveProvider, FixtureProvider, ProviderDisabled, read_feed, run_search
from signal_engine.discovery.models import RawRecord
from signal_engine.discovery.privacy import author_ref, clean_text, public_view
from signal_engine.discovery.run import build_opportunities

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def rec(title, body="", source="github_issues", verification="api_verified", created="2026-11-01T00:00:00Z", state="open", **kw):
    return RawRecord(source, f"id-{abs(hash(title + body))}", f"https://github.com/o/r/issues/{abs(hash(title)) % 9999}", title, body,
                     verification, created_at=created, state=state, **kw)


def route(r):
    o = router.build(r, assess(r, now=NOW))
    return o.pipeline, o


class Registry(unittest.TestCase):
    def test_registry_valid_and_statuses(self):
        reg = registry.load()
        self.assertGreaterEqual(len(reg), 40)
        self.assertEqual({s["status"] for s in reg.values()} - set(registry.STATUSES), set())

    def test_collection_gating(self):
        self.assertTrue(registry.may_collect("github_issues")[0])
        self.assertFalse(registry.may_collect("hn_algolia")[0])                       # restricted: off by default
        self.assertTrue(registry.may_collect("hn_algolia", ["hn_algolia"])[0])        # explicit opt-in
        for k in ("linkedin", "facebook_groups", "upwork", "reddit", "web_search_google_cse", "bark"):
            self.assertFalse(registry.may_collect(k)[0], k)
        self.assertFalse(registry.may_intake("web_search_bing")[0])                   # prohibited

    def test_restricted_connector_makes_no_request_without_opt_in(self):
        calls = []

        class C:
            def get_json(self, *a, **k):
                calls.append(a)
                return {}
        out, log = hn.seeking_freelancer(client=C())
        self.assertEqual((out, calls, log.status), ([], [], "skipped"))


class NewFalsePositiveCategories(unittest.TestCase):
    """Every category from the Phase 4 brief §11 plus those seen in the live GitHub run."""

    def assertExcluded(self, r, contains=""):
        p, o = route(r)
        self.assertEqual(p, "EXCLUDED", f"{r.title}: {p} {o.pipeline_reason} {o.assessment.noise_flags}")
        if contains:
            self.assertIn(contains, o.pipeline_reason + " ".join(o.assessment.noise_flags))

    def test_permanent_employment_is_not_consultancy(self):
        p, o = route(rec("Hiring: Senior Automation Engineer (full-time)", "Salary £70k plus benefits. Join our team in London."))
        self.assertEqual(p, "F_RECRUITMENT_SIGNAL")
        self.assertEqual(o.assessment.engagement_type.value, "permanent_employment")

    def test_freelancer_seeking_work(self):
        self.assertExcluded(rec("Available for freelance: n8n and Make automations", "Open to work. My portfolio: ..."), "job seeker")

    def test_agency_promoting_itself(self):
        self.assertExcluded(rec("[For Hire] AI automation agency — fixed price builds", "We offer n8n, Zapier and Make automations. Book a call with us."))

    def test_support_bug_is_not_a_paid_project(self):
        p, o = route(rec("Zapier step fails with 401 error", "Bug: the webhook integration crashes with a stack trace when the token expires."))
        self.assertNotIn(p, ("A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER"))

    def test_public_tender_never_direct_sme(self):
        p, _ = route(rec("CRM implementation partner", "Implementation of a Dynamics 365 CRM system for the council.", source="contracts_finder",
                         created="2026-11-01T00:00:00Z"))
        self.assertEqual(p, "E_PROCUREMENT")

    def test_licence_purchase_not_implementation(self):
        p, o = route(rec("Renewal of Salesforce CRM subscription licences", "Licence renewal for 24 months.", source="ted"))
        self.assertNotIn(p, ("A_DIRECT_SME", "E_PROCUREMENT"))

    def test_hobby_project_not_decision_maker(self):
        p, o = route(rec("Looking for someone to help with my side project bot", "Just a hobby project for fun, can't pay much."))
        self.assertIn("hobby_or_personal_project", o.assessment.noise_flags)
        self.assertEqual(o.assessment.business_type.value, "individual_or_hobby")

    def test_old_or_resolved_request(self):
        self.assertExcluded(rec("Looking for a freelancer to build a Zapier integration", "Contact me.", created="2026-05-01T00:00:00Z"), "older")
        self.assertExcluded(rec("Looking for a freelancer to build a Zapier integration", "Contact me.", state="closed"), "closed")

    def test_open_status_is_not_proof_of_availability(self):
        _, o = route(rec("Looking for a freelancer to build a Zapier integration for our UK shop", "Contact me."))
        self.assertTrue(any("not proof" in e for e in o.assessment.freshness.evidence))

    def test_search_snippet_is_never_verified(self):
        p, o = route(rec("Looking for an n8n developer", "snippet", source="web_search_brave", verification="search_snippet_only", created=None))
        self.assertEqual(p, "H_RESEARCH_UNVERIFIED")
        self.assertEqual(o.assessment.evidence_confidence.value, "unverified")

    def test_seller_listing_and_seo_content(self):
        self.assertExcluded(rec("Top 10 Software Development Companies in Delhi", "Best services..."), "seo")
        self.assertExcluded(rec("8 Signs Your Business Needs a Software Development Company", "Businesses grow..."), "seo")

    def test_lead_marketplace_advertising(self):
        self.assertExcluded(rec("Get more qualified leads for your agency", "Our lead generation platform: we connect businesses with agencies."), "lead_marketplace")

    def test_lead_bot_and_digest_posts(self):
        for t in ("Leads — 2026-11-04 (5)", "Hiring lead: Acme, Remote AI Automation Engineer", "New Jobs Found (31) — 2026-10-23",
                  "AI CLI Tools Digest 2026-11-06", "Job-Room scan result 42177719063"):
            self.assertExcluded(rec(t, "Freelance leads — integration. Is anyone willing to help, hiring a developer. Willing to pay."), "lead_aggregator")

    def test_crypto_bounty_farm(self):
        self.assertExcluded(rec("[BOUNTY] Content round", "Earn 50 RTC tokens, paid in USDC to your wallet"), "crypto")

    def test_internal_task_with_paid_words(self):
        self.assertExcluded(rec("Earn & Work: payout activation gates", "Production gate. One active freelance contract; paid work disabled."), "internal")

    def test_spam_campaign_across_repos(self):
        rs = [RawRecord("github_issues", f"s{i}", f"https://github.com/u{i}/r/issues/1", "Looking for a Developer / IT Partner to Build Something Together",
                        "Contact me", "api_verified", created_at="2026-11-01T00:00:00Z", state="open", meta={"repo_owner": f"u{i}"}) for i in range(4)]
        opps, audit = build_opportunities(rs, now=NOW)
        self.assertTrue(all(o.pipeline == "EXCLUDED" and "spam_campaign" in o.assessment.noise_flags for o in opps))

    def test_tender_false_positive_categories_still_excluded(self):
        for t, d in [("Gutter cleaning and roof inspection", "Inspection report for every property."), ("Bridge refurbishment", "Waterproofing works."),
                     ("Hospital laundry equipment replacement", "Automated wash line."), ("Integrated urgent care services", "Clinical care for patients."),
                     ("Medical consumables CRM", "Cardiac rhythm management devices, consumables.")]:
            p, o = route(rec(t, d, source="find_a_tender"))
            self.assertEqual(p, "EXCLUDED", t)


class Pipelines(unittest.TestCase):
    def test_direct_sme_buyer(self):
        p, o = route(rec("Looking for a freelancer to build an n8n workflow connecting HubSpot to Xero",
                         "We are a 12-person accounting firm in Leeds. I'm the owner. Budget £1,500. Contact me if interested."))
        a = o.assessment
        self.assertEqual(p, "A_DIRECT_SME")
        self.assertEqual((a.business_type.value, a.decision_maker_access.value, a.location.value),
                         ("independent_sme_self_reported", "self_reported_decision_maker", "UK"))
        self.assertTrue(any("12-person" in e for e in a.business_type.evidence))
        self.assertGreater(o.rank_score, 70)

    def test_agency_partner(self):
        p, _ = route(rec("We need a white-label n8n developer for our clients", "Our agency in Berlin has overflow work, ongoing. Get in touch."))
        self.assertEqual(p, "C_AGENCY_PARTNER")

    def test_operational_pain_from_forum(self):
        p, _ = route(rec("Spending hours copying invoices into spreadsheets", "Our team in Dublin does manual data entry every week.",
                         source="uk_business_forums", verification="user_submitted"))
        self.assertEqual(p, "D_OPERATIONAL_PAIN")

    def test_global_review_for_strong_out_of_market_request(self):
        p, _ = route(rec("Looking for a freelancer to automate our CRM", "Our office in Toronto needs HubSpot automation. Contact me."))
        self.assertEqual(p, "GLOBAL_REVIEW")

    def test_marketplace_project_and_rules(self):
        p, o = route(rec("Build Zapier automation for Shopify orders", "Need someone to automate order emails. Budget $400.",
                         source="peopleperhour", verification="user_submitted"))
        self.assertEqual(p, "B_FREELANCE_PROJECT")
        self.assertEqual(o.assessment.contact_permission.value, "in_platform_only")

    def test_licensed_lead(self):
        p, _ = route(rec("Need an AI chatbot for our dental clinic", "Looking for an agency, Manchester.", source="bark", verification="licensed_import"))
        self.assertEqual(p, "G_LICENSED_LEADS")

    def test_rank_profiles_differ_by_pipeline(self):
        r = rec("Looking for a freelancer to build an n8n workflow for our UK shop", "Contact me. Budget £500.")
        a = assess(r, now=NOW)
        sa, _ = router.rank(r, a, "A_DIRECT_SME")
        sc, _ = router.rank(r, a, "C_AGENCY_PARTNER")
        self.assertNotEqual(sa, sc)


class IntakeTests(unittest.TestCase):
    def test_manual_csv_dedupe_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "intake.jsonl"
            rows = [{"source_key": "linkedin", "url": "https://www.linkedin.com/posts/x", "post_date": "2026-11-03",
                     "text": "Can anyone recommend an automation agency? Our Paris clinic wants to automate bookings.", "stated_role": "founder"},
                    {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/x?utm_source=share", "text": "dup"},
                    {"source_key": "linkedin", "url": "http://insecure", "text": "x"},
                    {"source_key": "web_search_bing", "url": "https://x.example", "text": "x"}]
            res = intake.add(rows, "csv", path=store)
            self.assertEqual(res["added"], 1)
            self.assertEqual(len(res["duplicates"]), 1)
            self.assertEqual(len(res["errors"]), 2)
            r = intake.load_store(store)[0]
            self.assertEqual(r.verification, "user_submitted")
            p, o = route(r)
            self.assertEqual(p, "A_DIRECT_SME")
            self.assertIn("reviewer must open the original URL and confirm content and date", o.assessment.missing_facts)

    def test_licensed_and_marketplace_rules(self):
        r = intake.make_record({"source_key": "bark", "url": "https://www.bark.com/x", "text": "Need a CRM consultant"}, "csv")
        self.assertEqual(r.verification, "licensed_import")
        r2 = intake.make_record({"source_key": "upwork", "url": "https://www.upwork.com/jobs/~01", "text": "Need n8n expert"}, "email")
        self.assertIs(r2.meta["marketplace_rules"]["off_platform_contact"], False)

    def test_email_alert_import(self):
        eml = ("From: alerts@example.invalid\nTo: me@example.invalid\nSubject: New jobs matching n8n\nDate: Wed, 04 Nov 2026 10:00:00 +0000\n"
               "Content-Type: text/plain\n\nn8n workflow for Shopify orders\nhttps://www.upwork.com/jobs/~0123abc\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.eml"
            p.write_text(eml)
            rows = intake.read_email(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source_key"], rows[0]["url"]), ("upwork", "https://www.upwork.com/jobs/~0123abc"))
        self.assertTrue(rows[0]["post_date"].startswith("2026-11-04"))


class ConnectorTests(unittest.TestCase):
    def test_github_item_mapping_hashes_author(self):
        it = {"html_url": "https://github.com/acme/app/issues/5", "title": "Looking for a contractor", "body": "Email me at a@b.invalid @someone",
              "repository_url": "https://api.github.com/repos/acme/app", "user": {"login": "someone", "type": "User"}, "state": "open",
              "created_at": "2026-11-01T00:00:00Z", "labels": [{"name": "help wanted"}], "node_id": "N1"}
        r = gh.item_to_record(it, None, "now")
        self.assertNotIn("someone", json.dumps(r.to_dict()))
        self.assertNotIn("a@b.invalid", r.body)
        self.assertEqual((r.meta["repo_owner"], r.author_kind, r.labels), ("acme", "User", ["help wanted"]))

    def test_github_budget_repeat_and_dry_run(self):
        qs = querylib.plan("github", "2026-10-01", max_queries=5)

        class C:
            n = 0
            def get_json(self, url, check_robots=None, headers=None):
                C.n += 1
                return {"total_count": 0, "items": []}
        with tempfile.TemporaryDirectory() as d:
            ql = querylib.QueryLog(Path(d) / "q.json")
            _, log = gh.search_issues(qs, client=C(), max_requests=3, querylog=ql)
            self.assertEqual((C.n, log.requests, log.skipped), (3, 3, 2))
            _, log2 = gh.search_issues(qs, client=C(), max_requests=3, querylog=ql)
            self.assertEqual(C.n, 5)  # first 3 repeat-prevented, remaining 2 fetched
            _, log3 = gh.search_issues(qs, client=C(), dry_run=True)
            self.assertEqual((C.n, log3.status), (5, "skipped"))

    def test_github_rate_limit_stops_and_is_logged(self):
        from signal_engine.collectors.http import FetchBlocked

        class C:
            def get_json(self, *a, **k):
                raise FetchBlocked("rate", "upstream_forbidden", 403)
        _, log = gh.search_issues(querylib.plan("github", "2026-10-01", max_queries=4), client=C())
        self.assertEqual((log.status, log.requests), ("failed", 1))
        self.assertTrue(any(e["kind"] == "stopped" for e in log.events))

    def test_search_adapter_disabled_and_fixture_never_lead(self):
        with self.assertRaises(ProviderDisabled):
            BraveProvider(api_key="")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "fx.json"
            f.write_text(json.dumps({"looking for someone to automate": [{"url": "https://example.invalid/post", "title": "Need automation help",
                                                                            "snippet": "looking for someone to automate invoices", "age": "2 days"}]}))
            recs, log = run_search(FixtureProvider(f), querylib.plan("fixture", "x", categories=["explicit_project_request"], langs=["en"], max_queries=1),
                                   fixture=True)
        self.assertEqual(recs[0].verification, "fixture")
        self.assertEqual(route(recs[0])[0], "EXCLUDED")

    def test_feed_parsing(self):
        rss = ("<rss><channel><item><title>Need a CRM consultant</title><link>https://example.invalid/1</link>"
               "<description>Looking for help</description><pubDate>Wed, 04 Nov 2026 10:00:00 +0000</pubDate></item></channel></rss>")
        out = read_feed(rss, "rss_atom", "t")
        self.assertEqual((len(out), out[0].created_at[:10]), (1, "2026-11-04"))

    def test_query_library_multilingual_and_categories(self):
        lib = querylib.load_library()
        self.assertGreaterEqual(len({p["lang"] for p in lib["phrases"]}), 14)
        for c in ("explicit_project_request", "recommendation_request", "external_provider_search", "agency_partnership",
                  "problem_statement", "implementation_blocker", "freelancer_hiring"):
            self.assertIn(c, lib["categories"])
        self.assertTrue(all(q.lang == "en" for q in querylib.plan("github", "x", max_queries=50)))
        brave = querylib.plan("brave", "x", max_queries=200)
        self.assertGreater(sum(q.est_cost_usd for q in brave), 0)
        self.assertNotIn("github_broad", {q.category for q in brave})


class PrivacyAndAudit(unittest.TestCase):
    def test_author_ref_and_public_view(self):
        self.assertNotIn("alice", author_ref("alice"))
        self.assertIn("@[user]", clean_text("ping @alice-dev please"))
        r = rec("Looking for a freelancer", "x", author_ref="a_123", stated_role="founder")
        o = router.build(r, assess(r, now=NOW)).to_dict()
        pv = public_view(o)
        self.assertNotIn("author_ref", pv["record"])
        self.assertNotIn("stated_role", pv["record"])

    def test_stage_audit_counts_and_dedupe(self):
        a = rec("Looking for a freelancer to build an n8n flow for our UK shop", "Contact me.")
        b = RawRecord(**{**a.to_dict(), "url": a.url + "?tl=en"})
        opps, audit = build_opportunities([a, b, rec("Top 10 SEO companies", "")], now=NOW)
        self.assertEqual((audit["stage_1_raw"], audit["stage_2_after_dedupe"], audit["duplicates_removed"]), (3, 2, 1))
        self.assertEqual(sum(audit["stage_6_pipelines"].values()), 2)


if __name__ == "__main__":
    unittest.main()


class BraveIntegration(unittest.TestCase):
    """Brave: no request unless explicitly enabled AND a key is configured; hard cap 100; snippets never verified;
    output withheld unless storage rights are confirmed. Uses stubs only — no live request."""

    def setUp(self):
        import os
        from signal_engine.discovery import run as runmod
        self.run, self.tmp = runmod, tempfile.TemporaryDirectory()
        self.old_out, runmod.OUT = runmod.OUT, Path(self.tmp.name)
        self.old_key = os.environ.pop("BRAVE_SEARCH_API_KEY", None)

    def tearDown(self):
        import os
        self.run.OUT = self.old_out
        self.tmp.cleanup()
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        if self.old_key is not None:
            os.environ["BRAVE_SEARCH_API_KEY"] = self.old_key

    def _fake_provider(self, calls):
        class Fake:
            name, registry_key = "brave", "web_search_brave"
            def __init__(self, freshness="pm"):
                pass
            def search(self, q):
                calls.append(q)
                return [] if len(calls) > 1 else [
                    __import__("signal_engine.discovery.connectors.search", fromlist=["SearchHit"]).SearchHit(
                        "https://www.upwork.com/jobs/~01x", "Need n8n expert", "looking for someone to automate", "2 days", q.lang)]
        return Fake

    def test_not_enabled_means_plan_only(self):
        import os
        os.environ["BRAVE_SEARCH_API_KEY"] = "dummy-not-real"
        calls = []
        orig, self.run.BraveProvider = self.run.BraveProvider, self._fake_provider(calls)
        try:
            run = self.run.discover(["search:brave"], 30, 20, False, [])
        finally:
            self.run.BraveProvider = orig
        log = run["logs"][0]
        self.assertEqual((calls, log["requests"], log["planned_requests"]), ([], 0, 100))
        self.assertAlmostEqual(log["est_cost_usd_if_run"], 0.5)

    def test_enabled_without_key_is_skipped(self):
        run = self.run.discover(["search:brave"], 30, 20, False, [], enable_brave=True)
        self.assertEqual(run["logs"][0]["status"], "skipped")
        self.assertIn("key", run["logs"][0]["detail"])

    def test_enabled_with_key_respects_hard_cap_and_retains_no_brave_output(self):
        calls = []
        orig, self.run.BraveProvider = self.run.BraveProvider, self._fake_provider(calls)
        try:
            run = self.run.discover(["search:brave"], 30, 20, False, [], enable_brave=True, brave_max_requests=500)
        finally:
            self.run.BraveProvider = orig
        self.assertEqual(len(calls), 100)                                   # hard cap, not 500
        self.assertEqual(self.run._read_raw(self.run.OUT / "raw_discovered.jsonl"), [])   # snippet never stored
        agg = run["brave_aggregate"]
        self.assertEqual((agg["brave_results_total"], agg["unverified_snippets"], agg["independently_verified_original_source"]), (1, 1, 0))
        self.assertEqual(agg["unverified_by_landing_source"], {"upwork": 1})
        self.assertIn("discarded", agg["snippet_handling"])
        audit = self.run.report()
        self.assertEqual(audit["stage_6_pipelines"]["H_RESEARCH_UNVERIFIED"], 0)
        self.assertIn("never published", audit["brave_record_level_output"])
        self.assertEqual(audit["brave_aggregate"]["unverified_snippets"], 1)
        self.assertIn("search:brave", audit["source_metrics"])
        for f in self.run.OUT.rglob("*"):
            if f.is_file():
                txt = f.read_text()
                for leaked in ("upwork.com/jobs", "Need n8n expert", "looking for someone to automate"):
                    self.assertNotIn(leaked, txt, f"{leaked!r} leaked into {f.name}")

    def test_brave_request_uses_documented_parameters(self):
        from signal_engine.discovery.connectors.search import BraveProvider
        seen = {}

        class C:
            def get_json(self, url, check_robots=None, headers=None):
                seen["url"], seen["headers"] = url, headers
                return {"web": {"results": [{"url": "https://example.invalid/a", "title": "t", "description": "d", "age": "1 day"}]}}
        q = querylib.plan_web(max_requests=100)
        uae = next(x for x in q if x.market == "UAE")
        hits = BraveProvider(api_key="dummy", client=C()).search(uae)
        self.assertEqual(seen["headers"], {"X-Subscription-Token": "dummy"})
        for part in ("country=ALL", "search_lang=en", "count=20", "freshness=pm", "spellcheck=0"):
            self.assertIn(part, seen["url"])
        self.assertIn("Dubai", uae.query)
        self.assertEqual(hits[0].url, "https://example.invalid/a")

    def test_web_plan_prioritises_direct_requests_and_covers_markets(self):
        p = querylib.plan_web(max_requests=100)
        from collections import Counter
        cats, mk = Counter(x.category for x in p), Counter(x.market for x in p)
        direct = sum(cats[c] for c in ("explicit_project_request", "external_provider_search", "recommendation_request", "agency_partnership"))
        self.assertGreaterEqual(direct, 75)
        self.assertLessEqual(cats["problem_statement"] + cats["implementation_blocker"], 12)
        for m in ("UK", "UAE", "Germany", "France", "Switzerland", "Norway", "Poland"):
            self.assertIn(m, mk)
        self.assertTrue(all(x.country in querylib.BRAVE_COUNTRIES for x in p))

    def test_github_landing_page_verified_through_api_only(self):
        from signal_engine.discovery.connectors.search import verify_landing
        snip = RawRecord("web_search_brave", "u", "https://github.com/acme/app/issues/7", "Need contractor", "snippet",
                         "search_snippet_only", meta={"landing_source": "github_issues", "provider": "brave", "query_category": "explicit_project_request"})
        other = RawRecord("web_search_brave", "v", "https://www.reddit.com/r/x/1", "t", "s", "search_snippet_only", meta={"landing_source": "reddit"})

        class C:
            def get_json(self, url, check_robots=None, headers=None):
                self.url = url
                return {"html_url": "https://github.com/acme/app/issues/7", "title": "Looking for a contractor", "body": "Contact me",
                        "repository_url": "https://api.github.com/repos/acme/app", "user": {"login": "x", "type": "User"}, "state": "open",
                        "created_at": "2026-11-01T00:00:00Z", "node_id": "N7"}
        c = C()
        out, log = verify_landing([snip, other], client=c)
        self.assertEqual(c.url, "https://api.github.com/repos/acme/app/issues/7")
        self.assertEqual((out[0].verification, out[0].meta["discovered_via"]), ("api_verified", "brave"))
        self.assertEqual(out[1].verification, "search_snippet_only")
        self.assertIn("restricted", out[1].meta["landing_verification"])


class BraveNonRetention(unittest.TestCase):
    """Regression: Brave output (Data for Search/AI plans: no retention) must never reach any file, public or private,
    including duplicate-detection logs; only records re-fetched from an original source's permitted API survive."""
    BRAVE_URLS = ["https://www.upwork.com/jobs/~01dup", "https://www.reddit.com/r/smallbusiness/comments/abc/need_crm_help",
                  "https://example-agency.invalid/blog/hiring-automation-partner"]
    GH = "https://github.com/acme/app/issues/7"

    def setUp(self):
        import os
        from signal_engine.discovery import run as runmod
        from signal_engine.discovery.connectors import search as smod
        self.run, self.smod, self.tmp = runmod, smod, tempfile.TemporaryDirectory()
        self.old_out, runmod.OUT = runmod.OUT, Path(self.tmp.name)
        self.saved = {k: os.environ.pop(k, None) for k in ("BRAVE_SEARCH_API_KEY", smod.ATTESTATION_ENV)}
        test = self

        class Fake:
            name, registry_key = "brave", "web_search_brave"
            def __init__(self, freshness="pm"):
                pass
            def search(self, q):   # every query returns the SAME results -> heavy duplication across queries
                return [smod.SearchHit(u, f"Brave title {i} SECRETTITLE", f"brave snippet {i} SECRETSNIPPET contact bob@example.com",
                                       "1 day", q.lang) for i, u in enumerate(test.BRAVE_URLS + [test.GH, test.GH])]

        class GHClient:
            def get_json(self, url, check_robots=None, headers=None):
                return {"html_url": test.GH, "title": "Looking for a contractor to build an n8n CRM integration",
                        "body": "We are a small agency and need a freelancer for paid work.", "user": {"login": "someone", "type": "User"},
                        "repository_url": "https://api.github.com/repos/acme/app", "state": "open",
                        "created_at": "2026-11-01T00:00:00Z", "node_id": "N7"}
        self.orig_prov, runmod.BraveProvider = runmod.BraveProvider, Fake
        self.orig_vl = runmod.verify_landing
        runmod.verify_landing = lambda recs, **kw: smod.verify_landing(recs, client=GHClient(), **kw)

    def tearDown(self):
        import os
        self.run.OUT, self.run.BraveProvider, self.run.verify_landing = self.old_out, self.orig_prov, self.orig_vl
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def _all_files(self):
        return {f.name: f.read_text() for f in self.run.OUT.rglob("*") if f.is_file()}

    def _run(self, retention=False, n=5):
        run = self.run.discover(["search:brave"], 30, 20, False, [], enable_brave=True, brave_max_requests=n,
                                brave_retention_permitted=retention)
        audit = self.run.report()
        return run, audit

    def test_duplicate_brave_results_leave_no_trace_in_any_file(self):
        run, audit = self._run()
        files = self._all_files()
        self.assertIn("stage_audit.json", files)
        self.assertNotIn("private_brave_review_attested.jsonl", files)
        for name, txt in files.items():
            for u in self.BRAVE_URLS:
                self.assertNotIn(u, txt, f"Brave URL leaked into {name}")
            for marker in ("SECRETTITLE", "SECRETSNIPPET", "bob@example.com", "example-agency.invalid", "reddit.com/r/"):
                self.assertNotIn(marker, txt, f"{marker} leaked into {name}")
        agg = run["brave_aggregate"]
        self.assertEqual(agg["independently_verified_original_source"], 1)     # the GitHub issue, re-fetched via GitHub API
        self.assertEqual(agg["unverified_snippets"], 3)
        self.assertNotIn("duplicates", audit)                                  # no per-record duplicate log at all
        self.assertIsInstance(audit["duplicates_by_reason"], dict)

    def test_verified_original_source_record_is_kept_separately_from_brave(self):
        self._run()
        raw = self.run._read_raw(self.run.OUT / "raw_discovered.jsonl")
        self.assertEqual([(r.source_key, r.verification) for r in raw], [("github_issues", "api_verified")])
        self.assertEqual(raw[0].meta["discovered_via"], "brave")
        self.assertIn("api:github", raw[0].meta["verification_route"])
        self.assertNotIn("SECRET", json.dumps(raw[0].to_dict()))               # nothing copied from the Brave result

    def test_retention_flag_alone_cannot_enable_retention(self):
        run, _ = self._run(retention=True)
        self.assertIn("not configured", run["brave_aggregate"]["retention_decision"])
        self.assertNotIn("private_brave_review_attested.jsonl", self._all_files())

    def test_malformed_attestation_is_rejected(self):
        import os
        os.environ[self.smod.ATTESTATION_ENV] = "yes"
        run, _ = self._run(retention=True)
        self.assertIn("malformed", run["brave_aggregate"]["retention_decision"])
        self.assertNotIn("private_brave_review_attested.jsonl", self._all_files())

    def test_attested_rights_keep_snippets_private_and_never_public(self):
        import os
        os.environ[self.smod.ATTESTATION_ENV] = "plan=Search Pro Storage;confirmed_by=ops lead;date=2026-11-06"
        run, audit = self._run(retention=True)
        files = self._all_files()
        self.assertIn("private_brave_review_attested.jsonl", files)
        for name in ("report_public.md", "report_public.csv", "report_public.jsonl", "stage_audit.json", "run_log.json",
                     "raw_discovered.jsonl", "opportunities_private.jsonl", "query_log.json"):
            for u in self.BRAVE_URLS:
                self.assertNotIn(u, files.get(name, ""), f"{u} leaked into {name}")
        self.assertIn("PRIVATE", run["brave_aggregate"]["retention_decision"])

    def test_attestation_requires_flag_and_variable(self):
        good = {self.smod.ATTESTATION_ENV: "plan=Storage;confirmed_by=ops;date=2026-11-06"}
        self.assertFalse(self.smod.brave_storage_rights_attested(False, good)[0])
        self.assertFalse(self.smod.brave_storage_rights_attested(True, {})[0])
        self.assertTrue(self.smod.brave_storage_rights_attested(True, good)[0])

    def test_workflow_upload_list_contains_no_private_files(self):
        wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "multi-source-discovery.yml").read_text()
        up = wf[wf.index("upload-artifact"):]
        for private in ("raw_discovered", "opportunities_private", "private_brave", "intake.jsonl", "review_packet", "query_log"):
            self.assertNotIn(private, up)


class VerificationRoutes(unittest.TestCase):
    def test_find_a_tender_notice_is_refetched_from_the_official_api(self):
        from signal_engine.discovery.connectors.search import verify_landing
        snip = RawRecord("web_search_brave", "x", "https://www.find-tender.service.gov.uk/Notice/012345-2026", "t", "s",
                         "search_snippet_only", meta={"landing_source": "find_a_tender", "provider": "brave"})

        class C:
            def get_json(self, url, check_robots=None, headers=None):
                self.url = url
                return {"releases": [{"ocid": "ocds-h6vhtk-0abc", "id": "012345-2026", "date": "2026-11-01T00:00:00Z",
                                      "buyer": {"name": "Example Council"},
                                      "tender": {"title": "CRM workflow automation", "description": "Integration services",
                                                 "tenderPeriod": {"endDate": "2026-12-01T00:00:00Z"}}}]}
        c = C()
        out, _ = verify_landing([snip], client=c)
        self.assertEqual(c.url, "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages/012345-2026")
        self.assertEqual((out[0].source_key, out[0].verification), ("find_a_tender", "api_verified"))
        self.assertEqual(out[0].url, "https://www.find-tender.service.gov.uk/Notice/012345-2026")

    def test_hn_is_not_verified_unless_explicitly_allowed(self):
        from signal_engine.discovery.connectors.search import verify_landing
        snip = RawRecord("web_search_brave", "h", "https://news.ycombinator.com/item?id=1", "t", "s", "search_snippet_only",
                         meta={"landing_source": "hn_algolia"})

        class C:
            def get_json(self, *a, **k):
                raise AssertionError("no HN request without allow_restricted")
        out, log = verify_landing([snip], client=C())
        self.assertEqual((out[0].verification, log.requests), ("search_snippet_only", 0))

    def test_manual_reviewer_verification(self):
        row = {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/x", "text": "We need a CRM automation partner",
               "post_date": "2026-11-05"}
        rec = intake.make_record(row, "add", verified_by="RM")
        self.assertEqual((rec.verification, rec.meta["verified_by"]), ("reviewer_verified", "RM"))
        with self.assertRaises(intake.IntakeError):
            intake.make_record(row, "add", fixture=True, verified_by="RM")
        with self.assertRaises(intake.IntakeError):
            intake.make_record(row, "add", verified_by="someone@example.com")


class PublicArtifactPrivacy(unittest.TestCase):
    def test_public_view_redacts_contacts_and_private_meta(self):
        from signal_engine.discovery.privacy import public_view
        o = {"record": {"title": "Need help, mail jane.doe@example.com", "body": "Call +44 7700 900123 or email jane.doe@example.com",
                        "author_ref": "a_1", "stated_role": "founder",
                        "meta": {"verified_by": "RM", "notes": "private", "query_category": "explicit_project_request"}}}
        v = json.dumps(public_view(o))
        for bad in ("jane.doe@example.com", "7700 900123", "a_1", "founder", "verified_by", "private"):
            self.assertNotIn(bad, v)
        self.assertIn("explicit_project_request", v)


class MarketplaceAlertFixtures(unittest.TestCase):
    """Synthetic alerts (poc/fixtures/alerts) — exercise parsing and classification; never stored as real leads."""
    FX = Path(__file__).resolve().parents[1] / "fixtures" / "alerts"

    def test_each_platform_parses_with_correct_source(self):
        expect = {"upwork_alert.eml": ("upwork", 1), "freelancer_alert.eml": ("freelancer_com", 3), "peopleperhour_alert.eml": ("peopleperhour", 1),
                  "malt_alert.eml": ("malt", 1), "fiverr_alert.eml": ("fiverr_briefs", 1), "unknown_format_alert.eml": ("upwork", 1)}
        for f, (key, n) in expect.items():
            rows = intake.read_email(self.FX / f)
            self.assertEqual((len(rows), {r["source_key"] for r in rows}), (n, {key}), f)
        up = intake.read_email(self.FX / "upwork_alert.eml")[0]
        self.assertEqual(up["url"], "https://www.upwork.com/jobs/~0199synthetic01")          # tracking redirect unwrapped
        self.assertIn("HubSpot", up["text"])
        fl = intake.read_email(self.FX / "freelancer_alert.eml")
        self.assertNotIn("Logo design", fl[0]["text"])                                      # no bleed between digest items
        self.assertIn("not recognised", intake.read_email(self.FX / "unknown_format_alert.eml")[0]["notes"])

    def test_fixture_import_is_never_a_lead(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "s.jsonl"
            res = intake.add(intake.read_email(self.FX / "peopleperhour_alert.eml"), "email", path=store, fixture=True)
            r = intake.load_store(store)[0]
        self.assertEqual((res["added"], r.verification), (1, "fixture"))
        self.assertEqual(route(r)[0], "EXCLUDED")

    def test_same_alert_as_real_user_submission_routes_by_content(self):
        """What a REAL alert with this content would become (verification stays user_submitted, never verified)."""
        cases = {"peopleperhour_alert.eml": "B_FREELANCE_PROJECT", "malt_alert.eml": "B_FREELANCE_PROJECT",
                 "upwork_alert.eml": "B_FREELANCE_PROJECT", "fiverr_alert.eml": "B_FREELANCE_PROJECT"}
        for f, pipe in cases.items():
            r = intake.make_record(intake.read_email(self.FX / f)[0], "email")
            p, o = route(r)
            self.assertEqual((r.verification, p), ("user_submitted", pipe), f"{f}: {o.pipeline_reason} {o.assessment.buying_intent.value}")
            self.assertEqual(o.assessment.contact_permission.value, "in_platform_only")
        rows = intake.read_email(self.FX / "freelancer_alert.eml")
        routed = [route(intake.make_record(r, "email")) for r in rows]
        self.assertEqual(routed[0][0], "B_FREELANCE_PROJECT")
        self.assertEqual(routed[1][0], "EXCLUDED")                       # logo design: not Solvant work
        # permanent role: never consultancy demand (generic Python job -> excluded as unrelated; an automation role -> F)
        self.assertNotIn(routed[2][0], ("A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER"))
        self.assertEqual(routed[2][1].assessment.engagement_type.value, "permanent_employment")


class Persistence(unittest.TestCase):
    def test_private_outputs_are_git_ignored(self):
        gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
        self.assertIn("poc/out/", gi)


class PolicyCheckScript(unittest.TestCase):
    """scripts/policy_check.py: repository policy passes; seeded public-artifact violations are caught."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("policy_check", Path(__file__).resolve().parents[1] / "scripts" / "policy_check.py")
        cls.pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pc)

    def test_repository_workflows_and_registry_pass(self):
        self.assertEqual(self.pc.check_workflows() + self.pc.check_registry(), [])

    def test_seeded_artifact_violations_are_caught(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rec = {"record": {"source_key": "web_search_brave", "verification": "search_snippet_only"}}
            (d / "report_public.jsonl").write_text(json.dumps(rec) + "\n")
            (d / "report_public.md").write_text("contact jane.doe@example.com or +44 7700 900123\n")
            (d / "stage_audit.json").write_text(json.dumps({"duplicates": [{"url": "https://x.invalid"}]}))
            (d / "run_log.json").write_text(json.dumps({"brave_aggregate": {"top": "https://x.invalid/a"}}))
            errs = " | ".join(self.pc.check_artifacts(d))
            for expected in ("Brave record", "e-mail", "phone", "duplicate log", "URL inside Brave aggregate"):
                self.assertIn(expected, errs)
            self.assertNotIn("jane.doe", errs)            # the checker itself must not echo the address


class PublicationFailClosed(unittest.TestCase):
    """Regression: discovery artifacts / job summary may be published ONLY if report generation and the privacy gate succeeded."""
    WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "multi-source-discovery.yml"

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("policy_check", Path(__file__).resolve().parents[1] / "scripts" / "policy_check.py")
        cls.pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pc)
        cls.text = cls.WF.read_text()

    def test_current_workflow_is_fail_closed(self):
        self.assertEqual(self.pc.check_publication_gate(self.text), [])
        self.assertIn(f"if: {self.pc.PUBLISH_IF}", self.text)

    def test_upload_with_always_is_rejected(self):
        bad = self.text.replace(f"        id: upload\n        if: {self.pc.PUBLISH_IF}", "        id: upload\n        if: always()")
        self.assertNotEqual(bad, self.text)
        self.assertTrue(any("Upload" in e for e in self.pc.check_publication_gate(bad)))

    def test_original_pre_fix_layout_is_rejected(self):
        # the layout flagged in review: gate and upload both `if: always()`, summary written in the report step
        old = """jobs:
  discover:
    steps:
      - name: Assess, route, rank (redacted public report)
        if: always()
        working-directory: poc
        run: |
          python -m signal_engine.discovery.run report --shortlist 20 > /dev/null
          cat out/discovery/report_public.md >> "$GITHUB_STEP_SUMMARY"

      - name: Public-artifact privacy gate (no Brave output, no e-mail addresses)
        if: always()
        working-directory: poc
        run: python scripts/policy_check.py --artifacts out/discovery

      - name: Upload REDACTED outputs only
        if: always()
        uses: actions/upload-artifact@v4
        with:
          if-no-files-found: warn
"""
        self.assertTrue(self.pc.check_publication_gate(old))

    def test_summary_before_gate_is_rejected(self):
        bad = self.text.replace("run: python -m signal_engine.discovery.run report --shortlist 20 > /dev/null",
                                "run: |\n          python -m signal_engine.discovery.run report --shortlist 20 > /dev/null\n"
                                "          cat out/discovery/report_public.md >> \"$GITHUB_STEP_SUMMARY\"")
        self.assertTrue(any("must use" in e or "before the privacy gate" in e for e in self.pc.check_publication_gate(bad)))

    def test_gate_without_require_all_or_id_is_rejected(self):
        self.assertTrue(self.pc.check_publication_gate(self.text.replace(" --require-all", "")))
        self.assertTrue(self.pc.check_publication_gate(self.text.replace("id: privacy", "id: gate")))

    def test_missing_public_files_fail_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "report_public.md").write_text("ok\n")
            self.assertEqual(self.pc.check_artifacts(Path(d)), [])
            self.assertTrue(any("missing" in e for e in self.pc.check_artifacts(Path(d), require_all=True)))
