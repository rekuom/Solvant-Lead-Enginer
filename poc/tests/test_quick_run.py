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


class EngineDeviceGate(unittest.TestCase):
    """The Python engine endpoints apply the same private-access rule as the website proxy."""
    SECRET = "sb_secret_test_value_for_unit_tests_only"
    DEV = "11111111-2222-4333-8444-555555555555"
    SIG = "a03450dbacf447fe394756b624c555cda6d0ef70a2dcbc8a140d19b4f0dab87d"   # same value the TypeScript test pins

    def gate(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web" / "pyengine"))
        import solvant_api
        return solvant_api.device_ok

    def test_cookie_and_host_required(self):
        ok = self.gate()
        env = {"SUPABASE_SECRET_KEY": self.SECRET, "SOLVANT_PUBLIC_HOST": "solvant-lead-enginer-web-i2ae.vercel.app"}
        h = {"host": "solvant-lead-enginer-web-i2ae.vercel.app", "cookie": f"a=1; solvant_device={self.DEV}.{self.SIG}"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertTrue(ok(h))
            self.assertFalse(ok({**h, "cookie": f"solvant_device={self.DEV}." + "0" * 64}))
            self.assertFalse(ok({**h, "cookie": f"solvant_device=11111111-2222-4333-8444-555555555556.{self.SIG}"}))
            self.assertFalse(ok({**h, "cookie": ""}))
            self.assertFalse(ok({**h, "host": "solvant-lead-enginer-git-x.vercel.app"}))     # alternative deployment URL
        with mock.patch.dict("os.environ", {**env, "SUPABASE_SECRET_KEY": ""}, clear=False):
            self.assertFalse(ok(h))                                                           # not configured: closed
