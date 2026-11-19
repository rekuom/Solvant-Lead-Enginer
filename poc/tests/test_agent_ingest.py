"""Scheduled Claude discovery: the deterministic gate between the agent's qualification and the database."""
from __future__ import annotations

import json
import unittest

from signal_engine.discovery.platform import agent_ingest as ai

NOW_ISO = "2026-11-15T10:00:00+00:00"


def cand(**over):
    c = {"url": "https://community.make.com/t/looking-for-a-make-com-developer/95986", "title": "Looking for a Make.com developer",
         "evidence_quote": "We run a small online shop and need a Make.com developer to automate orders from Shopify into Xero. Paid work.",
         "published_at": NOW_ISO, "page_read": True, "query": "make.com developer wanted",
         "business": {"type": "independent_sme", "country": "UK", "name": "Example Shop"},
         "qualification": {"intent": "explicit_hire_request", "relevance": "relevant", "score": 88,
                           "reason": "owner hiring a Make.com developer for Shopify-Xero automation", "service": "Make.com automation"}}
    c.update(over)
    return c


class AgentGate(unittest.TestCase):
    def run_one(self, **over):
        items, rej = ai.process([cand(**over)])
        return (items[0] if items else None), rej

    def test_forum_hiring_post_read_on_page_is_priority_a(self):
        it, _ = self.run_one()
        self.assertEqual((it["source_key"], it["verification"], it["pipeline"], it["priority"]),
                         ("make_community", "agent_reviewed", "A_DIRECT_SME", "A"))
        self.assertEqual(it["engine"], "llm")
        self.assertIn("claude:", " ".join(it["dims"]["buying_intent"]["evidence"]))
        self.assertEqual(it["meta"]["business"]["type"], "independent_sme")
        self.assertGreaterEqual(it["rank_score"], 60)

    def test_social_platform_is_snippet_only_and_capped_at_b(self):
        it, _ = self.run_one(url="https://www.linkedin.com/posts/founder-123_ai", page_read=True,
                             title="Can anyone recommend an AI developer?",
                             evidence_quote="Founder of a 6-person clinic: can anyone recommend an AI developer to build a booking chatbot?",
                             qualification={"intent": "recommendation_request", "relevance": "relevant", "score": 90, "reason": "founder asks"})
        self.assertEqual((it["source_key"], it["verification"], it["pipeline"], it["priority"]),
                         ("linkedin", "search_snippet_only", "A_DIRECT_SME", "B"))      # page_read ignored for no-fetch platforms

    def test_exclusions(self):
        bad = [
            dict(url="https://www.find-tender.service.gov.uk/Notice/000123-2026"),
            dict(url="https://chatgpt.com/share/6731abc"),
            dict(url="https://claude.ai/share/abc"),
            dict(url="https://www.fiverr.com/someone/build-ai-chatbot"),
            dict(url="https://www.upwork.com/hire/n8n-freelancers/"),
            dict(url="http://community.make.com/t/x/1"),
            dict(url="https://example.com/blog/how-to-hire"),
            dict(title="For Hire: n8n and Make.com automation expert"),
            dict(business={"type": "public_sector"}),
            dict(title="SYNTHETIC FIXTURE need help"),
        ]
        for b in bad:
            items, rej = ai.process([cand(**b)])
            self.assertEqual(items, [], b)
            self.assertTrue(rej, b)

    def test_seller_and_job_seeker_judgement_routes_excluded(self):
        it, _ = self.run_one(qualification={"intent": "seller_offer", "relevance": "relevant", "score": 10, "reason": "agency advertising"})
        self.assertEqual(it["pipeline"], "EXCLUDED")
        it, _ = self.run_one(qualification={"intent": "job_seeker", "relevance": "relevant", "score": 5, "reason": "dev looking for work"})
        self.assertEqual(it["pipeline"], "EXCLUDED")

    def test_problem_statement_without_hire_is_not_a_buyer(self):
        it, _ = self.run_one(url="https://www.reddit.com/r/smallbusiness/comments/abc/drowning_in_admin/",
                             title="Spending 15 hours a week on manual invoicing",
                             evidence_quote="I run a 4-person accounting practice and spend hours copying invoices between systems.",
                             qualification={"intent": "problem_only", "relevance": "relevant", "score": 55, "reason": "pain, no hire yet"})
        self.assertNotIn(it["pipeline"], ("A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER"))

    def test_larger_organisations_never_priority_a(self):
        it, _ = self.run_one(business={"type": "enterprise", "country": "UK"})
        self.assertNotEqual(it["priority"], "A")

    def test_stale_posts_excluded(self):
        it, _ = self.run_one(published_at="2025-01-01T00:00:00+00:00")
        self.assertEqual(it["pipeline"], "EXCLUDED")

    def test_batch_dedupe_and_payload_shape(self):
        items, rej = ai.process([cand(), cand()])
        self.assertEqual((len(items), rej["duplicate in batch"]), (1, 1))
        import re
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261119000005_agent_discovery.sql").read_text()
        used = set(re.findall(r"p_item ->> '([a-z_]+)'", sql)) | set(re.findall(r"p_item -> '([a-z_]+)'", sql))
        self.assertLessEqual(used - set(items[0]) - {"engine"}, set())
        json.dumps(items)                                   # serialisable

    def test_dry_run_cli_prints_counts_only(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([cand()], fh)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(ai.main([fh.name, "--dry-run"]), 0)
        out = buf.getvalue()
        self.assertIn('"accepted": 1', out)
        self.assertNotIn("Shopify", out)                    # no lead content in logs


class PriorityFromScore(unittest.TestCase):
    def test_tiny_jobs_and_vague_requests_are_not_priority_a(self):
        items, _ = ai.process([cand(budget="$25", qualification={"intent": "explicit_hire_request", "relevance": "relevant", "score": 20,
                                                                  "reason": "very small quick fix"})])
        self.assertNotEqual(items[0]["priority"], "A")
        items, _ = ai.process([cand(qualification={"intent": "explicit_hire_request", "relevance": "relevant", "score": 95, "reason": "clear paid scope"})])
        self.assertEqual(items[0]["priority"], "A")
