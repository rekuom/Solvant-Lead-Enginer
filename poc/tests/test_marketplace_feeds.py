"""Freelancer.com official-API feed, TheirStack employment feed, and the ingest gate's handling of them (no network)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from signal_engine.discovery import registry
from signal_engine.discovery.platform import agent_ingest as ai
from signal_engine.discovery.platform import freelancer_feed as ff
from signal_engine.discovery.platform import theirstack_feed as ts

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
TS = int(datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc).timestamp())


def fl_project(**over):
    p = {"id": 40123456, "seo_url": "api-development/automate-shopify-orders-into-xero", "status": "active",
         "title": "Automate Shopify orders into Xero", "time_submitted": TS, "type": "fixed",
         "description": "Small UK homeware shop. Need every Shopify order pushed into Xero as an invoice, with stock sync. Urgent, this week.",
         "budget": {"minimum": 1500, "maximum": 3000}, "currency": {"code": "GBP"},
         "jobs": [{"name": "Shopify"}, {"name": "Xero"}], "bid_stats": {"bid_count": 12}, "upgrades": {"urgent": True, "featured": False},
         "_owner_country": "United Kingdom"}
    p.update(over)
    return p


def ts_job(**over):
    j = {"id": 987, "job_title": "Part-time Automation Specialist (Zapier/Make)", "url": "https://acme-lettings.co.uk/careers/automation",
         "date_posted": "2026-11-16", "company": "Acme Lettings", "country": "United Kingdom", "salary_string": "£25/hour",
         "description": "Independent letting agency (12 staff) seeks a contract automation specialist to connect our CRM, Xero and email.",
         "company_object": {"name": "Acme Lettings", "employee_count": 12, "domain": "acme-lettings.co.uk", "industry": "Real Estate"},
         "employment_statuses": ["part_time", "contract"]}
    j.update(over)
    return j


class FreelancerFeed(unittest.TestCase):
    def test_project_maps_to_marketplace_candidate(self):
        c = ff.to_candidate(fl_project(), "xero integration")
        self.assertEqual(c["url"], "https://www.freelancer.com/projects/api-development/automate-shopify-orders-into-xero")
        self.assertEqual((c["kind"], c["source_api"], c["source_id"], c["published_at"]), ("marketplace", "freelancer", "40123456", "2026-11-17"))
        self.assertIn("GBP 1500", c["budget"])
        self.assertEqual(c["business"]["country"], "United Kingdom")
        self.assertEqual(c["facts"]["upgrades"], ["urgent"])

    def test_closed_or_incomplete_projects_are_skipped(self):
        self.assertIsNone(ff.to_candidate(fl_project(status="closed"), "q"))
        self.assertIsNone(ff.to_candidate(fl_project(seo_url=None), "q"))

    def test_target_market_filter_keeps_unknown_drops_known_elsewhere(self):
        self.assertTrue(ff.in_target_market(ff.to_candidate(fl_project(), "q")))
        self.assertTrue(ff.in_target_market(ff.to_candidate(fl_project(_owner_country=None), "q")))
        self.assertFalse(ff.in_target_market(ff.to_candidate(fl_project(_owner_country="United States"), "q")))

    def test_missing_token_reports_not_configured(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 401, "unauthorised", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ff.NotConfigured):
                ff.search("n8n", TS)
            self.assertEqual(ff.main(["--days", "7"]), 0)

    def test_collect_dedupes_across_queries(self):
        with mock.patch.object(ff, "search", return_value=[fl_project()]):
            cands, stats = ff.collect(7, queries=["a", "b"], delay_s=0)
        self.assertEqual(len(cands), 1)


class TheirStackFeed(unittest.TestCase):
    def test_query_is_small_company_recent_and_capped(self):
        q = ts.build_query(7, 6)
        self.assertEqual((q["limit"], q["posted_at_max_age_days"], q["company_employee_count_max"]), (6, 7, 50))
        self.assertIn("GB", q["job_country_code_or"])
        self.assertIn("AE", q["job_country_code_or"])

    def test_hard_credit_cap_cannot_be_exceeded(self):
        captured = {}

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"data": []}'

        def fake(req, timeout=0):
            import json
            captured.update(json.loads(req.data))
            return R()
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            ts.fetch(7, 500)
        self.assertEqual(captured["limit"], ts.HARD_MAX_CREDITS)

    def test_contract_role_at_small_company_is_outsourcing_fit(self):
        c = ts.to_candidate(ts_job())
        self.assertEqual((c["kind"], c["source_api"]), ("employment", "theirstack"))
        self.assertTrue(c["facts"]["outsourcing_fit"])
        self.assertEqual(c["business"]["type"], "independent_sme")
        c2 = ts.to_candidate(ts_job(job_title="Automation Engineer", description="Full-time permanent role.", employment_statuses=["full_time"]))
        self.assertFalse(c2["facts"]["outsourcing_fit"])

    def test_unauthorised_or_out_of_credits_is_not_configured(self):
        import urllib.error
        for code in (401, 402):
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", code, "x", {}, None)):
                with self.assertRaises(ts.NotConfigured):
                    ts.fetch()


class GateHandlesApiSources(unittest.TestCase):
    def test_freelancer_project_goes_to_marketplace_pipeline_verified(self):
        items, rej = ai.process([ff.to_candidate(fl_project(), "xero integration")], now=NOW)
        it = items[0]
        self.assertEqual((it["source_key"], it["pipeline"], it["verification"]), ("freelancer_com", "B_FREELANCE_PROJECT", "api_verified"))
        self.assertEqual(it["meta"]["source_api"], "freelancer")
        self.assertIn("urgency", it["meta"])
        self.assertGreaterEqual(it["meta"]["value_gbp_est"], 1000)

    def test_theirstack_job_is_employment_never_customer(self):
        items, _ = ai.process([ts.to_candidate(ts_job())], now=NOW)
        it = items[0]
        self.assertEqual((it["source_key"], it["pipeline"], it["verification"]), ("theirstack", "F_RECRUITMENT_SIGNAL", "licensed_import"))
        self.assertTrue(it["meta"]["facts"]["outsourcing_fit"])

    def test_employment_kind_overrides_a_buyer_intent(self):
        c = ts.to_candidate(ts_job())
        c["qualification"]["intent"] = "explicit_hire_request"
        items, _ = ai.process([c], now=NOW)
        self.assertEqual(items[0]["pipeline"], "F_RECRUITMENT_SIGNAL")

    def test_job_board_urls_still_rejected_from_web_search(self):
        c = ts.to_candidate(ts_job(url="https://uk.indeed.com/viewjob?jk=1"))
        c.pop("source_api")
        _, rej = ai.process([c], now=NOW)
        self.assertTrue(rej)

    def test_spoofed_freelancer_api_candidate_on_other_host_is_not_api(self):
        c = ff.to_candidate(fl_project(), "q")
        c["url"] = "https://community.make.com/t/x/1"
        items, _ = ai.process([c], now=NOW)
        self.assertNotEqual(items[0]["verification"], "api_verified")

    def test_tender_urls_rejected_even_from_api(self):
        c = ts.to_candidate(ts_job(url="https://www.find-tender.service.gov.uk/Notice/1"))
        _, rej = ai.process([c], now=NOW)
        self.assertTrue(rej)

    def test_freelancer_recheck_rejects_removed_and_flags_closed(self):
        rec = ai.to_record(ff.to_candidate(fl_project(), "q"))
        with self.assertRaises(ai.Rejected):
            ai.verify_source(rec, fetch_freelancer=lambda pid: None)
        rec = ai.to_record(ff.to_candidate(fl_project(), "q"))
        out = ai.verify_source(rec, fetch_freelancer=lambda pid: {"id": pid, "status": "closed"})
        self.assertEqual((out.state, out.meta["source_closed"]), ("closed", True))


class Ranking(unittest.TestCase):
    def test_budget_parsing(self):
        self.assertEqual(ai.budget_gbp("GBP 1500–3000 (fixed)"), 3000)
        self.assertAlmostEqual(ai.budget_gbp("€5k"), 4250)
        self.assertEqual(ai.budget_gbp("£25/hour"), 500)
        self.assertIsNone(ai.budget_gbp("negotiable"))
        self.assertEqual(ai.budget_gbp("10 000 € et plus"), 8500)          # French thousands separator
        self.assertEqual(ai.budget_gbp("500 € à 1 000 €"), 850)
        self.assertEqual(ai.budget_gbp("1.000 € bis 5.000 €"), 4250)

    def test_urgency_and_value_raise_rank_low_budget_lowers(self):
        base = ff.to_candidate(fl_project(description="Small UK shop needs Shopify orders into Xero.", budget={}), "q")
        urgent = ff.to_candidate(fl_project(), "q")
        cheap = ff.to_candidate(fl_project(description="Small UK shop needs Shopify orders into Xero.",
                                           budget={"minimum": 10, "maximum": 30}, seo_url="x/cheap"), "q")
        r = {k: ai.process([c], now=NOW)[0][0]["rank_score"] for k, c in (("base", base), ("urgent", urgent), ("cheap", cheap))}
        self.assertGreater(r["urgent"], r["base"])
        self.assertLess(r["cheap"], r["base"])

    def test_multilingual_urgency(self):
        for t in ("Wir brauchen das dringend", "c'est à faire au plus vite", "lo necesitamos lo antes posible", "graag met spoed"):
            self.assertTrue(ai.URGENT.search(t), t)


class EuropeanAlertEmails(unittest.TestCase):
    def test_freelancermap_and_codeur_alert_links_are_extracted(self):
        from signal_engine.discovery import intake
        raw = (b"From: Projektalarm <noreply@freelancermap.de>\r\nSubject: Neue Projekte\r\nDate: Tue, 17 Nov 2026 08:00:00 +0000\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
               b"Automatisierung von Rechnungen mit n8n (Remote, 20 Tage)\r\nhttps://www.freelancermap.de/projekt/automatisierung-rechnungen-n8n\r\n\r\n"
               b"Integration CRM et facturation\r\nhttps://www.codeur.com/projects/412345-integration-crm-facturation\r\n")
        rows = intake.read_email_bytes(raw)
        urls = sorted(r["url"] for r in rows)
        self.assertEqual(urls, ["https://www.codeur.com/projects/412345-integration-crm-facturation",
                                "https://www.freelancermap.de/projekt/automatisierung-rechnungen-n8n"])
        self.assertTrue(all(r["source_key"] == "eu_freelance_boards" for r in rows))


class Registry(unittest.TestCase):
    def test_new_sources_registered_and_mapped(self):
        for key in ("theirstack", "eu_freelance_boards", "accounting_communities", "property_communities", "ecommerce_seller_communities",
                    "hospitality_retail_communities", "recruitment_communities", "professional_services_communities", "eu_business_communities"):
            self.assertNotEqual(registry.policy(key)["status"], "prohibited")
        self.assertEqual(ai.platform_of("https://www.freelancermap.de/projekt/automatisierung"), "eu_freelance_boards")
        self.assertEqual(ai.platform_of("https://www.property118.com/x"), "property_communities")
        self.assertEqual(ai.platform_of("https://www.freelancer.de/projects/x"), "freelancer_com")

    def test_community_search_results_are_snippets_capped_at_b(self):
        c = {"url": "https://www.accountingweb.co.uk/any-answers/recommend-someone-to-automate-our-bank-feeds",
             "title": "Can anyone recommend someone to automate our client onboarding?", "page_read": True, "published_at": "2026-11-18",
             "evidence_quote": "Small practice, 6 staff, in Leeds. Looking to pay someone to automate onboarding between Xero Practice Manager and our forms.",
             "business": {"type": "independent_sme", "country": "UK"}, "kind": "customer",
             "qualification": {"intent": "recommendation_request", "relevance": "relevant", "score": 90}}
        it = ai.process([c], now=NOW)[0][0]
        self.assertEqual((it["verification"], it["pipeline"]), ("search_snippet_only", "A_DIRECT_SME"))
        self.assertNotEqual(it["priority"], "A")


if __name__ == "__main__":
    unittest.main()
