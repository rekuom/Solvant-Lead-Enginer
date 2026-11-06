"""Regression tests for service relevance (procurement intent ≠ service relevance).

Synthetic cases below are PARAPHRASES of the false-positive categories found in live run 42174857442.
They are regression guards, not proof of quality: real-world quality is measured on the manually
labelled held-out records (benchmark/run_real_eval.py --split heldout), whose text is deliberately
NOT used here.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from signal_engine import validate
from signal_engine.classify import classify
from signal_engine.models import Signal
from signal_engine.qualify import EXCLUDED, PRIORITY_A, PRIORITY_B, REVIEW, WATCHLIST, qualify
from signal_engine.relevance import assess

NOW = datetime(2026, 11, 6, 7, tzinfo=timezone.utc)
DEV = Path(__file__).resolve().parents[1] / "benchmark" / "real_2026-11-06" / "dev.jsonl"


def tender(title, text="", source="find_a_tender", value=None, deadline="2026-12-10T12:00:00Z", **meta):
    m = {"kind": "tender", **meta}
    return Signal(source=source, source_id=title, url=f"https://example.invalid/{abs(hash(title + text))}", title=title,
                  text=text, verification_status="verified_api", posted_at="2026-11-01T00:00:00Z", deadline_at=deadline,
                  value_amount=value, value_currency="GBP" if value else None,
                  country_hint="UK" if source != "ted" else None, raw_meta=m)


def q(s):
    return qualify(s, classify(s, now=NOW), now=NOW)


class FalsePositiveCategories(unittest.TestCase):
    """Every category reported as a false positive must be excluded, whatever generic words it contains."""

    def assertExcluded(self, s, why=""):
        r = q(s)
        self.assertEqual(r.queue, EXCLUDED, f"{s.title}: {r.queue} {r.service_relevance} {r.reasons} {why}")
        self.assertNotIn(r.service_relevance, ("relevant",), s.title)
        return r

    def test_gutter_cleaning_and_roof_inspection(self):
        self.assertExcluded(tender("Gutter clearance and roof survey contract",
                                   "Annual gutter cleaning and roof inspections across council housing, with an inspection report for every property.",
                                   value=300000))

    def test_bridge_construction(self):
        self.assertExcluded(tender("Footbridge repair and waterproofing",
                                   "An integrated project to refurbish the bridge deck, improve waterproofing and meet building regulations."))

    def test_laundry_equipment(self):
        self.assertExcluded(tender("Hospital laundry equipment renewal",
                                   "Replacement of the automated wash line and associated laundry equipment, including installation and integration with existing plant."))

    def test_healthcare_delivery(self):
        for t, d in [("Integrated urgent care service", "Provision of integrated urgent care for patients, with outreach and reporting to the commissioner."),
                     ("Community nursing and therapy service", "Clinical treatment, therapy and case management for patients at home."),
                     ("Digitally enabled mental health service", "Therapeutic interventions for patients delivered via digital tools and platforms.")]:
            self.assertExcluded(tender(t, d))

    def test_medical_consumables_with_crm_acronym(self):
        r = self.assertExcluded(tender("Spain – Disposable non-chemical medical consumables – Suministro de material fungible CRM",
                                       "Electrofisiología cardiaca: dispositivos de CRM (cardiac rhythm management).", source="ted"))
        self.assertTrue(any("CRM" in t for t in r.relevance_against), r.relevance_against)

    def test_crm_acronym_traps(self):
        self.assertExcluded(tender("Norway – Laboratory reagents – Certified reference materials (CRM) for toxicology", "", source="ted"))
        self.assertExcluded(tender("Germany – Radar sets – Lieferung Radar 1X CRM", "Lieferung und Inbetriebnahme einer Radaranlage", source="ted"))

    def test_physical_equipment_and_generic_words(self):
        self.assertExcluded(tender("Automatic doors and access control maintenance", "Planned maintenance of automatic doors, turnstiles and shutters."))
        self.assertExcluded(tender("Traffic signal equipment framework", "Supply, maintenance and reporting for traffic signals."))
        self.assertExcluded(tender("Integrated reporting service system", "An integrated service with reporting and an automatic system for residents."))

    def test_hardware_for_ai_is_hardware(self):
        self.assertExcluded(tender("Italy – Super computer – Fornitura di un server GPU", "Server GPU per il laboratorio di intelligenza artificiale.", source="ted"))
        self.assertExcluded(tender("Supply of an AI-guided fluorescence microscope", "Supply, delivery and installation of a microscope with AI-guided acquisition."))

    def test_api_pharmaceutical_trap(self):
        self.assertNotEqual(assess(tender("Supply of API for generic medicines", "Active pharmaceutical ingredient (API) supply.")).verdict, "relevant")

    def test_care_framework_with_large_value_does_not_rank_high(self):
        recs, _, _ = validate.build_report([
            tender("Integrated care services framework", "Live-in care and complex care for all ages.", value=60_000_000),
            tender("Germany – IT services: consulting, software development, Internet and support – CRM-Weiterentwicklung",
                   "Weiterentwicklung und Support des CRM-Systems auf Basis von Microsoft Dynamics 365.", source="ted"),
        ], now=NOW)
        genuine = [r for r in recs if r["verification_status"] == "verified_api"]
        self.assertEqual(genuine[0]["service_relevance"], "relevant")
        self.assertEqual(genuine[-1]["queue"], EXCLUDED)


class RelevantProcurement(unittest.TestCase):
    def test_relevant_services_tender_is_b_never_a(self):
        r = q(tender("Netherlands – Software programming and consultancy services – CRM-applicatie",
                     "Levering, implementatie, inrichting en beheer van een CRM-applicatie.", source="ted", buyer_country_code="NLD"))
        self.assertEqual((r.service_relevance, r.queue, r.opportunity_kind), ("relevant", PRIORITY_B, "tender_bid"))
        self.assertTrue(any("formal tender" in m for m in r.missing_details))

    def test_multilingual_ai_and_automation(self):
        for t, d in [("France – Software programming and consultancy services – Mise en place d'un chatbot", "Conception et intégration d'un chatbot client."),
                     ("Switzerland – Software-related services – Dienstleistung für Power Automate", "Entwicklung von Automatisierungen mit Power Automate."),
                     ("Germany – Public relations consultancy services – KI-Chatbot", "Bereitstellung und Einführung einer KI-gestützten Chatbot-Lösung.")]:
            r = q(tender(t, d, source="ted"))
            self.assertEqual(r.service_relevance, "relevant", t)
            self.assertIn(r.queue, (PRIORITY_A, PRIORITY_B))

    def test_licence_renewal_is_product_only(self):
        r = q(tender("Romania – Software supply services – Reînnoire subscripții software Salesforce CRM", "Reînnoire subscripții.", source="ted"))
        self.assertEqual((r.service_relevance, r.queue), ("product_only", WATCHLIST))

    def test_unclear_it_tender_goes_to_review(self):
        r = q(tender("Netherlands – IT services: consulting, software development, Internet and support – Raamovereenkomst",
                     "Zie aanbestedingsdocumenten voor de volledige omschrijving van de opdracht en de percelen.", source="ted"))
        self.assertEqual((r.service_relevance, r.queue), ("uncertain", REVIEW))
        self.assertTrue(r.relevance_uncertainty)

    def test_award_and_pre_procurement_stages(self):
        award = q(tender("Germany – Software programming and consultancy services – CRM-Rahmenvertrag",
                         "Gegenstand der Vergabe war die Weiterentwicklung des CRM-Systems auf Basis von Dynamics 365.", source="ted", deadline=None))
        self.assertEqual((award.procurement_stage, award.queue), ("award_or_modification", EXCLUDED))
        pin = q(tender("Market engagement: AI chatbot for resident enquiries", "Prior information notice. Development of an AI chatbot.", deadline=None))
        self.assertEqual(pin.procurement_stage, "pre_procurement")
        self.assertTrue(any("pre-procurement" in m for m in pin.missing_details))

    def test_value_never_raises_score(self):
        small = classify(tender("Workflow automation services", "Implementation of workflow automation.", value=5_000), now=NOW)
        huge = classify(tender("Workflow automation services", "Implementation of workflow automation.", value=50_000_000), now=NOW)
        self.assertEqual(small.score, huge.score)


class CapAndRanking(unittest.TestCase):
    def test_relevance_screened_before_cap_and_all_records_kept(self):
        junk = [tender(f"Grounds maintenance lot {i}", "Grass cutting and cleaning.", value=10_000_000) for i in range(6)]
        good = tender("Netherlands – Software programming and consultancy services – Chatbot",
                      "Implementatie van een AI-chatbot voor klantvragen.", source="ted", buyer_country_code="NLD")
        recs, funnel, _ = validate.build_report(junk + [good], now=NOW, max_records=2)
        self.assertIn(good.url, {r["url"] for r in recs})
        self.assertEqual(funnel["genuine_dropped_by_max_records_cap"], 5)
        self.assertEqual(funnel["dropped_by_cap_by_relevance"], {"not_relevant": 5})
        self.assertEqual(len(validate._ALL_GENUINE), 7)


class CollectorFixes(unittest.TestCase):
    def test_429_backoff_then_success(self):
        import io, urllib.error
        from email.message import Message
        from signal_engine.collectors.http import PoliteClient
        calls, slept = [], []

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): self.close()

        def opener(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                m = Message(); m["Retry-After"] = "3"
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", m, io.BytesIO(b""))
            return R(b'{"ok": 1}')
        c = PoliteClient(opener=opener, check_robots=False, sleep=slept.append, min_interval_s=0)
        self.assertEqual(c.get_json("https://api.example/x"), {"ok": 1})
        self.assertIn(3.0, slept)

    def test_contracts_finder_single_paginated_pull_and_cpv(self):
        from signal_engine.collectors import ocds
        rel = {"ocid": "ocds-b5fd17-11111111-1111-4111-8111-111111111111", "date": "2026-11-01T00:00:00Z",
               "tender": {"title": "CRM implementation", "items": [{"classification": {"scheme": "CPV", "id": "72263000"}}]}}
        pages = {1: {"releases": [rel], "links": {"next": "https://www.contractsfinder.service.gov.uk/next2"}},
                 2: {"releases": [], "links": {}}}

        class C:
            urls = []
            def get_json(self, url, check_robots=None):
                self.urls.append(url)
                return pages[len(self.urls)]
        c = C()
        out = ocds.fetch_contracts_finder(c, "2026-10-07", "2026-11-06", keywords=["ignored"])
        self.assertEqual(len(c.urls), 2)
        self.assertNotIn("keyword", c.urls[0])
        self.assertEqual(out[0].raw_meta["cpv"], ["72263000"])

    def test_cpv_code_drives_relevance_when_text_is_thin(self):
        s = tender("Raamovereenkomst ICT", "Zie aanbestedingsdocumenten voor de volledige omschrijving van de opdracht.", cpv=["72000000"])
        self.assertEqual(assess(s).verdict, "uncertain")
        s2 = tender("Raamovereenkomst", "Zie aanbestedingsdocumenten voor de volledige omschrijving van de opdracht.", cpv=["45000000"])
        self.assertEqual(assess(s2).verdict, "not_relevant")


class RealDevRecords(unittest.TestCase):
    """The DEV split of real records (not the held-out split) as a regression check."""

    def test_dev_split_no_irrelevant_record_in_priority_a_or_b(self):
        from benchmark.run_real_eval import evaluate, load
        res = evaluate(load("dev"))
        self.assertEqual(res["fp"], [], res["fp"])
        self.assertEqual(res["missed"], [], res["missed"])


if __name__ == "__main__":
    unittest.main()
