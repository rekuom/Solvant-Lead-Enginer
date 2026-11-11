"""Platform bridge: intake parsing/classification payloads, synthetic-data guard, discovery push payload."""
from __future__ import annotations

import base64
import json
import re
import tempfile
import unittest
from pathlib import Path

from signal_engine.discovery.platform import intake as pin
from signal_engine.discovery.platform import push
from signal_engine.discovery.platform.items import to_item

FX = Path(__file__).resolve().parents[1] / "fixtures" / "alerts"
SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261111000002_functions.sql").read_text()


def _strip_marker(raw: bytes) -> bytes:
    """Fixtures carry SYNTHETIC markers; strip them ONLY to exercise the parser in tests."""
    t = raw.decode()
    t = re.sub(r"^X-Fixture:.*\n", "", t, flags=re.M).replace("SYNTHETIC FIXTURE", "").replace("SYNTHETIC test alert", "")
    return t.replace("example.invalid", "example.com").encode()


class WebIntake(unittest.TestCase):
    def test_pasted_linkedin_request_is_classified(self):
        r = pin.process("paste", {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/acme-123", "post_date": "2026-11-10",
                                   "text": "We are a 20-person logistics firm in Manchester looking for a consultant to automate our "
                                           "HubSpot CRM and invoice processing with AI."})
        it = r["items"][0]
        self.assertEqual((it["pipeline"], it["verification"], it["source_key"]), ("A_DIRECT_SME", "user_submitted", "linkedin"))
        self.assertIn("HubSpot", it["technologies"])
        self.assertIn("buying_intent", it["dims"])                      # interpretation kept separate from source facts
        self.assertTrue(it["canonical_url"].startswith("https://"))

    def test_reviewer_verification_route(self):
        r = pin.process("manual", {"source_key": "reddit", "url": "https://www.reddit.com/r/smallbusiness/comments/x1/need_crm",
                                    "text": "Looking to hire someone to integrate our Shopify store with Xero", "verified_by": "RM"})
        self.assertEqual(r["items"][0]["verification"], "reviewer_verified")

    def test_repository_fixtures_are_refused(self):
        for f in sorted(FX.glob("*.eml")):
            with self.assertRaises(pin.IntakeRejected, msg=f.name):
                pin.process("email_file", {"eml_b64": base64.b64encode(f.read_bytes()).decode()})

    def test_marketplace_alert_parser_reused(self):
        raw = _strip_marker((FX / "upwork_alert.eml").read_bytes())
        r = pin.process("email_file", {"eml_b64": base64.b64encode(raw).decode(), "filename": "alert.eml"})
        it = r["items"][0]
        self.assertEqual((it["source_key"], it["pipeline"]), ("upwork", "B_FREELANCE_PROJECT"))
        self.assertIn("In-platform", it["contact_route"])
        digest = pin.process("email_file", {"eml_b64": base64.b64encode(_strip_marker((FX / "freelancer_alert.eml").read_bytes())).decode()})
        self.assertEqual(len(digest["items"]), 3)                      # digest split per project

    def test_csv_import_validates_rows(self):
        csv_text = "source_key,url,text,post_date,acquisition_cost\n" \
                   "bark,https://www.bark.com/leads/1,Need a CRM consultant for HubSpot setup,2026-11-09,£12\n" \
                   "bark,http://insecure.example.com/x,bad row,2026-11-09,\n"
        r = pin.process("csv", {"csv_text": csv_text})
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["pipeline"], "G_LICENSED_LEADS")
        self.assertEqual(r["items"][0]["acquisition_cost"], 12.0)
        self.assertEqual(len(r["intake"]["errors"]), 1)

    def test_synthetic_rows_rejected(self):
        r = pin.process("manual", {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/x", "text": "SYNTHETIC FIXTURE need help"})
        self.assertEqual(r["items"], [])

    def test_oversized_and_unknown_inputs(self):
        with self.assertRaises(pin.IntakeRejected):
            pin.process("email_file", {"eml_text": "x" * (pin.MAX_EMAIL_BYTES + 1)})
        with self.assertRaises(pin.IntakeRejected):
            pin.process("shell", {})

    def test_item_keys_match_database_ingest(self):
        it = pin.process("paste", {"source_key": "linkedin", "url": "https://www.linkedin.com/posts/k", "text": "Need an automation agency"})["items"][0]
        used = set(re.findall(r"p_item ->> '([a-z_]+)'", SQL)) | set(re.findall(r"p_item -> '([a-z_]+)'", SQL))
        self.assertLessEqual(used - set(it), set(), f"database reads keys the engine never sends: {used - set(it)}")


class DiscoveryPush(unittest.TestCase):
    def test_payload_has_no_brave_or_fixture_records_and_no_handles(self):
        from signal_engine.discovery.models import RawRecord
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            recs = [RawRecord("github_issues", "1", "https://github.com/a/b/issues/1", "Looking for a contractor for n8n",
                              "We need to hire someone to build an n8n CRM workflow", "api_verified", created_at="2026-11-08T00:00:00Z",
                              author_ref="a_123456789012", meta={"kind": "issue"}),
                    RawRecord("github_issues", "2", "https://github.com/a/b/issues/2", "t", "b", "fixture")]
            (out / "raw_discovered.jsonl").write_text("\n".join(json.dumps(r.to_dict()) for r in recs))
            (out / "run_log.json").write_text(json.dumps({"run_at": "2026-11-11T00:00:00Z", "logs": [
                {"source": "github_issues", "status": "ok", "requests": 2, "records": 1},
                {"source": "search:brave", "status": "skipped", "requests": 0}], "brave_aggregate": {"brave_results_total": 5}}))
            run, items = push.build_payload(out)
        self.assertEqual([i["source_key"] for i in items], ["github_issues"])
        self.assertEqual({l["source_key"] for l in run["logs"]}, {"github_issues", "web_search_brave"})
        blob = json.dumps([run, items])
        self.assertNotIn("http", json.dumps(run["logs"]))
        self.assertEqual(items[0]["meta"]["author_ref"], "a_123456789012")

    def test_push_without_token_sends_nothing(self):
        import os
        old = os.environ.pop("SIGNAL_INGEST_TOKEN", None)
        try:
            self.assertEqual(push.main(), 0)
        finally:
            if old is not None:
                os.environ["SIGNAL_INGEST_TOKEN"] = old


class ProcurementInDiscovery(unittest.TestCase):
    def test_one_failing_api_does_not_stop_the_others(self):
        from signal_engine.collectors.http import FetchBlocked
        from signal_engine.discovery.connectors import procurement
        from signal_engine.models import Signal

        def ok():
            return [Signal("find_a_tender", "ocds-1", "https://www.find-tender.service.gov.uk/Notice/000123-2026", "CRM workflow automation",
                           "Integration of CRM and workflow automation services", "verified_api", posted_at="2026-11-01T00:00:00Z",
                           organisation="Example Council", country_hint="UK", value_amount=50000, value_currency="GBP",
                           raw_meta={"tender_status": "active", "cpv": ["72000000"]})]

        def down():
            raise FetchBlocked("http_503", "unavailable")
        recs, logs = procurement.collect(plan={"contracts_finder": down, "find_a_tender": ok, "ted": ok})
        self.assertEqual({l.source: l.status for l in logs}, {"contracts_finder": "failed", "find_a_tender": "ok", "ted": "ok"})
        self.assertEqual(recs[0].verification, "api_verified")
        self.assertEqual(recs[0].meta["budget"], "GBP 50,000")


class SchedulePolicy(unittest.TestCase):
    def test_schedule_rules(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pc", Path(__file__).resolve().parents[1] / "scripts" / "policy_check.py")
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        wf = (pc.WF / "multi-source-discovery.yml").read_text()
        self.assertEqual(pc.check_workflows(), [])
        ungated = wf.replace("vars.DISCOVERY_SCHEDULE_ENABLED == 'true'", "true")
        brave_on_schedule = wf.replace("github.event_name == 'workflow_dispatch' && inputs.enable_brave", "inputs.enable_brave")
        orig = (pc.WF / "multi-source-discovery.yml")
        for bad, expect in ((ungated, "gated"), (brave_on_schedule, "Brave must be impossible")):
            try:
                orig.write_text(bad)
                self.assertTrue(any(expect in e for e in pc.check_workflows()), expect)
            finally:
                orig.write_text(wf)
