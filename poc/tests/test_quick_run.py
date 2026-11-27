"""Dashboard 'Run discovery': bounded quick refresh under the owner's session (no network; boards and database faked)."""
from __future__ import annotations

import unittest
from unittest import mock

from signal_engine.discovery.platform import boards_reader, quick_run


def cand(url, title="Automatiser les devis d'une PME"):
    return {"url": url, "title": title, "evidence_quote": "Petite entreprise : automatiser devis et factures.", "published_at": "2026-11-26",
            "page_read": True, "query": "codeur: project list", "kind": "marketplace", "budget": "500 € à 1 000 €",
            "business": {"type": "unknown", "country": "France"}, "facts": {"bid_count": 12}, "board_listing": True}


class QuickRun(unittest.TestCase):
    def test_saves_through_member_rpc_and_rechecks(self):
        calls = []

        def rpc(fn, args):
            calls.append(fn)
            if fn == "member_ingest_discovery":
                self.assertEqual(len(args["p_items"]), 2)
                return {"added": 2, "updated": 0, "duplicates": 0}
            if fn == "board_checks_due":
                return []
            return {}
        with mock.patch.object(boards_reader, "freelancermap", return_value=[]), \
             mock.patch.object(boards_reader, "codeur", return_value=[cand("https://www.codeur.com/projects/1-a"), cand("https://www.codeur.com/projects/1-a")]), \
             mock.patch.object(boards_reader, "peopleperhour", return_value=[cand("https://www.codeur.com/projects/2-b")]), \
             mock.patch.object(boards_reader, "airtable_jobs", side_effect=RuntimeError("down")):
            out = quick_run.run(rpc)
        self.assertEqual((out["found"], out["accepted"], out["added"]), (2, 2, 2))
        self.assertTrue(str(out["boards"]["airtable"]).startswith("error"))      # one board failing never stops the run
        self.assertEqual(calls[0], "member_ingest_discovery")
        self.assertIn("board_checks_due", calls)

    def test_nothing_found_makes_no_write(self):
        calls = []
        with mock.patch.object(boards_reader, "freelancermap", return_value=[]), mock.patch.object(boards_reader, "codeur", return_value=[]), \
             mock.patch.object(boards_reader, "peopleperhour", return_value=[]), mock.patch.object(boards_reader, "airtable_jobs", return_value=[]):
            out = quick_run.run(lambda fn, args: calls.append(fn) or [])
        self.assertEqual(out["added"], 0)
        self.assertNotIn("member_ingest_discovery", calls)


if __name__ == "__main__":
    unittest.main()
