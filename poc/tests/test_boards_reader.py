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
        # the card price is a viewer-currency conversion: kept only as a hint, never as the buyer's budget
        self.assertEqual((out[0]["title"], out[0]["budget"], out[0]["facts"]["bid_count"]), ("Workflow Automation: Zapier & Xero", None, 14))
        self.assertEqual(out[0]["facts"]["card_price_viewer_currency"], "£450")

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
            ai.verify_source(rec, fetch_board=lambda u, t: {"status": "removed"})
        rec = ai.verify_source(ai.to_record(self.cand()), fetch_board=lambda u, t: {"status": "closed", "checks": ["closed"]})
        self.assertEqual((rec.state, rec.meta["source_closed"], rec.meta["board_check"]["status"]), ("closed", True, "closed"))

    def test_verified_open_uses_source_date_budget_and_bids(self):
        chk = {"status": "verified_open", "title_match": True, "posted_at": "2026-11-18", "date_confirmed": True, "open_confirmed": True,
               "budget": "1 000 € à 10 000 €", "bids": 140, "requirements": "Brief complet: automatiser les devis et la facturation."}
        items, _ = ai.process([self.cand()], now=NOW, verify=False)
        base = items[0]["rank_score"]
        import unittest.mock as m
        with m.patch.object(ai, "verify_source", side_effect=lambda rec: ai.apply_board_check(rec, chk)):
            it = ai.process([self.cand()], now=NOW, verify=True)[0][0]
        self.assertEqual((it["published_at"], it["meta"]["board_check"]["status"], it["meta"]["crowded"]), ("2026-11-18", "verified_open", 140))
        self.assertIn("automatiser les devis", it["body_excerpt"])
        self.assertLess(it["rank_score"], base + 4)            # 140 offers outweighs the verified-open bonus

    def test_next_action_per_kind(self):
        it = ai.process([self.cand()], now=NOW)[0][0]
        self.assertEqual(it["meta"]["action"]["type"], "submit_proposal")
        self.assertIn("Codeur", it["meta"]["next_action"])
        forum = {"url": "https://community.make.com/t/need-help-automating-invoices/1", "title": "Need help automating invoices (paid)",
                 "evidence_quote": "Small UK firm, paid work: automate invoices from Stripe to Xero.", "published_at": "2026-11-18",
                 "page_read": True, "kind": "customer", "business": {"type": "independent_sme", "country": "UK"},
                 "qualification": {"intent": "explicit_hire_request", "relevance": "relevant", "score": 80}}
        self.assertEqual(ai.process([forum], now=NOW)[0][0]["meta"]["action"]["type"], "reply_publicly")
        invited = dict(forum, url="https://community.make.com/t/x/2", evidence_quote=forum["evidence_quote"] + " DM me with your rate.")
        self.assertEqual(ai.process([invited], now=NOW)[0][0]["meta"]["action"]["type"], "contact_permitted")
        snippet = dict(forum, url="https://www.linkedin.com/posts/x-1", page_read=False)
        self.assertEqual(ai.process([snippet], now=NOW)[0][0]["meta"]["action"]["type"], "research")


class SyntheticGuard(unittest.TestCase):
    def test_real_brief_mentioning_synthetic_data_is_kept_fixture_marker_rejected(self):
        c = Gate().cand()
        c["evidence_quote"] = "Penetration test on a test environment with synthetic data only."
        items, rej = ai.process([c], now=NOW)
        self.assertEqual((len(items), dict(rej)), (1, {}))
        c2 = dict(c, title="SYNTHETIC FIXTURE need help")
        self.assertEqual(ai.process([c2], now=NOW)[1], {"synthetic/test data": 1})


class ListingCheck(unittest.TestCase):
    CD = ('<meta property="og:title" content="Automatiser la facturation">'
          '<div>Automatiser la facturation Ouvert · 500 € à 1 000 € · 12 offres · 300 vues</div><a>Faire une offre</a> '
          '<a>Publier un projet similaire</a><div>PME de 8 salariés : relier devis, factures et banque.</div>'
          '<div>Budget indicatif : 500 € à 1 000 € Publication : 21 novembre 2026 à 16h10 Profils recherchés : Développeur make freelance</div>')
    PPH = ('<title>Zapier workflows for clinic - PeoplePerHour.com</title><script type="application/ld+json">'
           '{"@type":"JobPosting","title":"Zapier workflows for clinic","datePosted":"2026-11-22 02:48:40","validThrough":"2026-12-22 02:48:40"}</script>'
           '<div>Fixed Price £ 300 (approx. $ 394 ) Posted: 1 day ago Proposals: 26 OPPORTUNITY Open for Proposals</div>'
           '<div>Description Experience Level: Expert We need Zapier between Calendly and Xero. Clarification Board</div>')

    def test_codeur_verified_open(self):
        c = b.check_listing("https://www.codeur.com/projects/1-x", "Automatiser la facturation", get=lambda u: self.CD, now=NOW)
        self.assertEqual((c["status"], c["posted_at"], c["budget"], c["bids"]), ("verified_open", "2026-11-21", "500 € à 1 000 €", 12))
        self.assertIn("relier devis", c["requirements"])

    def test_pph_verified_open_with_original_budget(self):
        c = b.check_listing("https://www.peopleperhour.com/freelance-jobs/a/b/x-1", "Zapier workflows for clinic", get=lambda u: self.PPH, now=NOW)
        self.assertEqual((c["status"], c["budget"], c["bids"], c["valid_through"]), ("verified_open", "£300 (fixed price)", 26, "2026-12-22"))

    def test_reachable_is_not_verified(self):
        c = b.check_listing("https://www.codeur.com/projects/1-x", "Something else entirely", get=lambda u: self.CD, now=NOW)
        self.assertNotEqual(c["status"], "verified_open")
        c = b.check_listing("https://www.codeur.com/projects/1-x", "Automatiser la facturation",
                            get=lambda u: self.CD.replace("Ouvert ·", "· "), now=NOW)
        self.assertEqual(c["status"], "verified_posted")    # title + date confirmed, availability not stated

    def test_in_progress_archived_and_hourly(self):
        self.assertEqual(b.check_listing("https://www.codeur.com/projects/1-x", "Automatiser la facturation",
                                         get=lambda u: self.CD.replace("Ouvert", "En travail"), now=NOW)["status"], "closed")
        arch = self.PPH.replace("OPPORTUNITY Open for Proposals", "Remote #4531536 Archived").replace("Fixed Price £ 300", "Per Hour £ 20 /hr")
        c = b.check_listing("https://www.peopleperhour.com/x-1", "Zapier workflows for clinic", get=lambda u: arch, now=NOW)
        self.assertEqual((c["status"], c["budget"]), ("closed", "£20/hour"))

    def test_closed_expired_removed_unreachable(self):
        self.assertEqual(b.check_listing("https://www.codeur.com/projects/1-x", "Automatiser la facturation",
                                         get=lambda u: self.CD.replace("Ouvert", "Fermé"), now=NOW)["status"], "closed")
        late = datetime(2027, 1, 5, tzinfo=timezone.utc)
        self.assertEqual(b.check_listing("https://www.peopleperhour.com/x-1", "Zapier workflows for clinic", get=lambda u: self.PPH, now=late)["status"], "closed")

        def gone(u):
            raise b.FetchError("HTTP 404")

        def down(u):
            raise b.FetchError("HTTP 503")
        self.assertEqual(b.check_listing("https://www.codeur.com/projects/1-x", "x", get=gone)["status"], "removed")
        self.assertEqual(b.check_listing("https://www.codeur.com/projects/1-x", "x", get=down)["status"], "unreachable")


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

    def test_forum_feed_labels_are_reader_feeds_without_search_budget(self):
        self.assertEqual(fb.strategy_of("forum feed: n8n jobs"), "forum")
        self.assertEqual(fb.strategy_of("forum feed n8n jobs"), "forum")
        plan = fb.allocate(fb.rollup([{"key": "forum feed: n8n", "total": 9, "qualified": 9}]), 20)
        self.assertNotIn("forum", plan)

    def test_zero_yield_searches_lower_a_strategy(self):
        s = {r["key"]: r for r in fb.rollup([{"key": "de: a", "total": 1, "qualified": 1}, {"key": "fr: b", "total": 1, "qualified": 1}],
                                            [{"key": "de", "searches": 20}, {"key": "fr", "searches": 2}])}
        self.assertLess(s["de"]["rate"], s["fr"]["rate"])
        self.assertEqual(s["de"]["searches"], 20)


if __name__ == "__main__":
    unittest.main()


class Commercial(unittest.TestCase):
    def test_draft_file_validation(self):
        import tempfile
        from signal_engine.discovery.platform import commercial as cm
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([{"url": "https://www.codeur.com/projects/1-x", "title": "T", "body": "Bonjour", "amount": 1800, "currency": "eur"},
                       {"url": "http://insecure", "body": "x"}, {"url": "https://x", "body": "  "}], fh)
        d = cm.load_drafts(fh.name)
        self.assertEqual([(x["url"], x["amount"], x["currency"]) for x in d], [("https://www.codeur.com/projects/1-x", "1800", "EUR")])

    def test_report_is_concise_and_actionable(self):
        from signal_engine.discovery.platform import commercial as cm
        txt = cm.format_report([{"priority": "A", "title": "Zapier for clinic", "budget_text": "£300", "bids": "26", "posted": "2026-11-22",
                                 "check_status": "verified_open", "draft_ready": True, "next_step": "Submit a proposal on PeoplePerHour",
                                 "url": "https://www.peopleperhour.com/x"}], {"open_now": 5, "proposal_possible": 3})
        self.assertIn("Next: Submit a proposal on PeoplePerHour", txt)
        self.assertIn("open (confirmed by board)", txt)
        self.assertIn("open now 5", txt)

    def test_report_shows_original_budget_status_flags_and_change_sections(self):
        from signal_engine.discovery.platform import commercial as cm
        txt = cm.format_report(
            [{"priority": "C", "title": "Gumroad to Airtable", "budget_text": "$1,000 (open to hearing what this should cost)", "commercial_score": 71,
              "status_label": "requirement_stated", "next_step": "Reply in the thread", "url": "https://community.make.com/t/x/120066", "flags": []},
             {"priority": "A", "title": "Scrape letting agents", "budget_text": "£363 (fixed price)", "bids": "84", "commercial_score": 61,
              "status_label": "confirmed_open", "flags": ["heavily contested (84 offers)"], "next_step": "Submit a proposal", "url": "https://www.peopleperhour.com/x"}],
            {"open_now": 2}, {"new_buyers": [{"title": "New one", "budget_text": None, "url": "https://x"}], "partners": [], "employment": []})
        self.assertIn("1. 71 [C] Gumroad to Airtable", txt)
        self.assertIn("$1,000 (open to hearing what this should cost) · no visible offers · requirement stated in a forum post", txt)
        self.assertIn("£363 (fixed price) · 84 offers", txt)
        self.assertIn("Review: heavily contested (84 offers)", txt)
        self.assertIn("New buyers (1)\n   - New one · budget not stated · https://x", txt)
        self.assertIn("Updated leads (0): none", txt)
        self.assertIn("Agency partnerships (0): none", txt)
        self.assertIn("Employment signals (0): none", txt)
        self.assertNotIn("$474", txt)

    def test_recheck_sends_counts_not_requirements(self):
        sent = {}

        def fake(name, args):
            if name == "board_checks_due":
                return [{"url": "https://www.codeur.com/projects/1-x", "title": "Automatiser la facturation"}]
            sent.update(args)
            return {"recorded": 1}
        out = b.recheck(5, get=lambda u: ListingCheck.CD, rpc_fn=fake, delay=0)
        self.assertEqual(out["by_status"], {"verified_open": 1})
        self.assertNotIn("requirements", sent["p_checks"][0])
