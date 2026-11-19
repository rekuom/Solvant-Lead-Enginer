"""Public project boards reader (synthetic page fixtures; no network) and its handling in the ingest gate + feedback."""
from __future__ import annotations

import html
import json
import unittest
from datetime import datetime, timezone

from signal_engine.discovery.platform import agent_ingest as ai
from signal_engine.discovery.platform import boards_reader as b
from signal_engine.discovery.platform import feedback as fb

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def fm_page(projects):
    return ('<script type="application/json" class="js-react-on-rails-component" data-component-name="ProjectSearch" data-dom-id="x">'
            + json.dumps({"initialResults": projects}) + "</script>")


def fm_proj(**o):
    p = {"id": 1, "slug": "n8n-automatisierung-fuer-handwerksbetrieb-1", "title": "n8n Automatisierung für Handwerksbetrieb",
         "description": "<p>Wir sind ein Handwerksbetrieb mit 12 Mitarbeitern und suchen Unterstützung bei der Automatisierung von Angeboten.</p>",
         "created": "2026-11-17T09:00:00+01:00", "expires": int(NOW.timestamp()) + 86400, "applicationsPaused": False,
         "endcustomer": True, "company": "Beispiel GmbH", "country": {"nameEn": "Germany"}, "budget": None, "poster": {"accountType": "CUSTOMER"}}
    p.update(o)
    return p


def cd_card(path, title, when, status, budget, offers, desc):
    return (f'<a class="x" rel="nofollow" aria-label="{title}" href="{path}"> <div class="flex"> <h3 class="t"> {title} </h3> '
            f'<span class="text-sm"> {when} </span> </div> <div class="m"> <span class="s"> <span class="d"></span> {status} </span> '
            f'<span class="i" title="Budget"> <img class="w" alt="" src="/c.svg" /> {budget} </span> <span title="Offres"> {offers} Offres </span> </div> '
            f'<div class="text-blue-dark/70 text-sm line-clamp-3"> {desc} </div>')


def pph_card(url, title, price, desc, when, proposals):
    return (f'<div class="card__price⤍L"><span class="title-nano"><div><span>{price}</span></div></span></div>'
            f'<h6 class="item__title"><a class="item__url⤍L" href="{url}">{title}</a></h6><p class="item__desc⤍L">{desc}</p>'
            f'<div class="nano card__footer-left⤍L"><span>{when}</span><span class="u-mgl--1">{proposals}<!-- --> <!-- -->proposals</span></div>')


class Relevance(unittest.TestCase):
    def test_service_terms_required_and_roles_excluded(self):
        self.assertTrue(b.relevant("Workflow Automation: Zapier & Google Apps Script", ""))
        self.assertTrue(b.relevant("Agent IA pour la gestion des demandes", ""))
        self.assertTrue(b.relevant("Intégration Web API Avantio", ""))
        self.assertFalse(b.relevant("Teacher Digital Accounting (m/w/d)", "KI und Automatisierung im Unterricht"))
        self.assertFalse(b.relevant("Sales Closer remote", "AI tools"))
        self.assertFalse(b.relevant("Création site vitrine", "intégration"))
        self.assertFalse(b.relevant("Logo design", "ai"))

    def test_relative_dates_in_three_languages(self):
        self.assertEqual(b.rel_date("Il y a 2 jours", NOW), "2026-11-17")
        self.assertEqual(b.rel_date("a day ago", NOW), "2026-11-18")
        self.assertEqual(b.rel_date("vor 3 Tagen", NOW), "2026-11-16")
        self.assertEqual(b.rel_date("Il y a 16 heures", NOW), "2026-11-18")
        self.assertEqual(b.rel_date("Il y a 2 mois", NOW), "2026-09-20")
        self.assertIsNone(b.rel_date("", NOW))


class Parsers(unittest.TestCase):
    def test_freelancermap_end_customer_fresh_open_relevant_only(self):
        page = fm_page([fm_proj(), fm_proj(id=2, slug="old-2", created="2026-10-01T09:00:00+01:00"),
                        fm_proj(id=3, slug="paused-3", applicationsPaused=True),
                        fm_proj(id=4, slug="expired-4", expires=int(NOW.timestamp()) - 10),
                        fm_proj(id=5, slug="teacher-5", title="Dozent KI-Management (m/w/d)"),
                        fm_proj(id=6, slug="agency-6", endcustomer=False, title="n8n Engineer via Agentur")])
        out = b.parse_freelancermap(page, NOW, 7, "n8n")
        self.assertEqual([c["url"].rsplit("/", 1)[1] for c in out], ["n8n-automatisierung-fuer-handwerksbetrieb-1", "agency-6"])
        self.assertEqual((out[0]["kind"], out[0]["business"]["country"], out[0]["business"]["name"]), ("marketplace", "Germany", "Beispiel GmbH"))
        self.assertEqual((out[1]["kind"], out[1]["business"]["name"]), ("employment", None))   # recruiter posting = staffing signal

    def test_codeur_open_fresh_relevant(self):
        page = (cd_card("/projects/1-agent-ia-devis", "Agent IA pour les devis", "Il y a 2 jours", "Ouvert", "1 000 € à 10 000 €", 12,
                        "Petite entreprise de rénovation : automatiser les devis.")
                + cd_card("/projects/2-site-vitrine", "Création site vitrine", "Il y a 1 jour", "Ouvert", "Moins de 500 €", 50, "Site.")
                + cd_card("/projects/3-integration-crm", "Intégration CRM", "Il y a 1 jour", "Fermé", "500 € à 1 000 €", 9, "Fermé.")
                + cd_card("/projects/4-automatisation", "Automatisation factures", "Il y a 2 mois", "Ouvert", "Moins de 500 €", 3, "Vieux."))
        out = b.parse_codeur(page, NOW, 7)
        self.assertEqual([c["url"] for c in out], ["https://www.codeur.com/projects/1-agent-ia-devis"])
        self.assertEqual((out[0]["budget"], out[0]["facts"]["bid_count"], out[0]["published_at"]), ("1 000 € à 10 000 €", 12, "2026-11-17"))

    def test_peopleperhour_cards(self):
        u = "https://www.peopleperhour.com/freelance-jobs/technology-programming/other/workflow-automation-zapier-1234567"
        page = (pph_card(u, "Workflow Automation: Zapier &amp; Xero", "£450", "Small UK firm needs Zapier between Xero and Pipedrive.", "2 days ago", 14)
                + pph_card(u.replace("1234567", "7654321"), "3D artist wanted", "$100", "Render.", "a day ago", 3))
        out = b.parse_pph(page, NOW, 7)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["title"], out[0]["budget"], out[0]["facts"]["bid_count"]), ("Workflow Automation: Zapier & Xero", "£450", 14))

    def test_gainsight_jobs_board_embedded_topics(self):
        topics = [{"categoryUrl": "https://community.airtable.com/jobs-board-16",
                   "topicUrl": {"destination": "https://community.airtable.com/jobs-board-16/hiring-airtable-builder-1"},
                   "title": "Hiring an Airtable builder for our clinic", "content": "<p>Paid project, 3 weeks.</p>",
                   "publishedAt": "2026-11-17T10:00:00+00:00", "replyCount": 0},
                  {"categoryUrl": "x", "topicUrl": {"destination": "https://community.airtable.com/jobs-board-16/open-to-work-2"},
                   "title": "Open to work as an Airtable developer", "content": "", "publishedAt": "2026-11-18T10:00:00+00:00"}]
        page = '<div data-props="' + html.escape(json.dumps({"topics": topics}, separators=(",", ":"))) + '"></div>'
        out = b.parse_gainsight(page, NOW, 7)
        self.assertEqual([c["title"] for c in out], ["Hiring an Airtable builder for our clinic"])
        self.assertEqual(out[0]["kind"], "customer")


class Gate(unittest.TestCase):
    def cand(self):
        return b.parse_codeur(cd_card("/projects/1-agent-ia-devis", "Agent IA pour les devis", "Il y a 2 jours", "Ouvert",
                                      "1 000 € à 10 000 €", 12, "Petite entreprise de rénovation : automatiser les devis."), NOW, 7)[0]

    def test_board_listing_is_page_read_marketplace(self):
        it = ai.process([self.cand()], now=NOW)[0][0]
        self.assertEqual((it["source_key"], it["pipeline"], it["verification"]), ("eu_freelance_boards", "B_FREELANCE_PROJECT", "agent_reviewed"))
        self.assertTrue(it["meta"]["board_listing"])

    def test_reread_rejects_removed_and_flags_closed(self):
        rec = ai.to_record(self.cand())
        with self.assertRaises(ai.Rejected):
            ai.verify_source(rec, fetch_board=lambda u: None)
        rec = ai.verify_source(ai.to_record(self.cand()), fetch_board=lambda u: {"title": "x", "closed": True})
        self.assertEqual((rec.state, rec.meta["source_closed"]), ("closed", True))

    def test_closed_listing_is_excluded(self):
        c = self.cand()
        rec = ai.verify_source(ai.to_record(c), fetch_board=lambda u: {"title": "x", "closed": True})
        self.assertEqual(rec.state, "closed")


class Feedback(unittest.TestCase):
    def test_strategy_rollup_and_allocation(self):
        rows = [{"key": "codeur: project list", "total": 10, "qualified": 6}, {"key": "biz-accounting: recommend", "total": 4, "qualified": 3},
                {"key": "de: suche Freelancer", "total": 6, "qualified": 0}, {"key": "social: looking for", "total": 8, "qualified": 0}]
        s = {r["key"]: r for r in fb.rollup(rows)}
        self.assertEqual(s["biz-accounting"]["rate"], round(4 / 6, 3))
        plan = fb.allocate(list(s.values()), 20)
        self.assertEqual(sum(plan.values()), 20)
        self.assertNotIn("codeur", plan)                       # reader feeds take no search budget
        self.assertGreater(plan["biz-accounting"], plan["social"])
        self.assertGreaterEqual(plan["social"], 1)             # still explored


class SearchLog(unittest.TestCase):
    def test_entries_normalised_and_capped(self):
        e = ai.search_entries([{"strategy": "Biz-Accounting", "query": "can anyone recommend  automation", "kept": 3, "lang": "en"},
                               {"strategy": "", "query": "dropped"}, {"strategy": "de", "query": "x", "kept": 999}])
        self.assertEqual([(x["strategy"], x["kept"]) for x in e], [("biz-accounting", 3), ("de", 100)])

    def test_zero_yield_searches_lower_a_strategy(self):
        s = {r["key"]: r for r in fb.rollup([{"key": "de: a", "total": 1, "qualified": 1}, {"key": "fr: b", "total": 1, "qualified": 1}],
                                            [{"key": "de", "searches": 20}, {"key": "fr", "searches": 2}])}
        self.assertLess(s["de"]["rate"], s["fr"]["rate"])
        self.assertEqual(s["de"]["searches"], 20)


if __name__ == "__main__":
    unittest.main()
