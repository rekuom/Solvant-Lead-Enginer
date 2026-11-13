"""Regression tests for run #43412718994 (migration workflow):
  defect 1: preflight.py took the --expect-ref VALUE as the connection string (connected to a local socket);
  defect 2: `preflight | tee` under `bash -e` (no pipefail) reported success when preflight failed, so apply ran.
The GitHub Actions step scripts are extracted from the workflow file and executed exactly as GitHub runs `shell: bash`
(bash --noprofile --norc -eo pipefail), against a stub `psql` — no network, no real database."""
from __future__ import annotations

import importlib.util
import io
import os
import re
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "apply-database-migrations.yml"
REF = "dfnaevcsergsphiiodtm"
SECRET = "S3cr3t-p@ss!word"
GOOD = f"postgresql://postgres.{REF}:{SECRET.replace('@', '%40').replace('!', '%21')}@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("preflight_cli", ROOT / "supabase" / "scripts" / "preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _policy():
    spec = importlib.util.spec_from_file_location("policy_check_mw", ROOT / "poc" / "scripts" / "policy_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def step_script(name_prefix: str) -> str:
    """The exact `run:` script of a step in the migration workflow (dedented)."""
    for name, body in _policy().run_blocks(WF.read_text()):
        if name.startswith(name_prefix):
            lines = [l for l in body.splitlines()]
            ind = min(len(l) - len(l.lstrip()) for l in lines if l.strip())
            return "\n".join(l[ind:] for l in lines) + "\n"
    raise AssertionError(f"step {name_prefix!r} not found")


class ArgumentParsing(unittest.TestCase):
    def setUp(self):
        self.pf = _load_preflight()

    def test_expect_ref_value_is_never_the_connection_string(self):
        args = self.pf.parse_args(["--expect-ref", REF])
        self.assertIsNone(args.dsn)
        self.assertEqual(args.expect_ref, REF)
        self.assertEqual(self.pf.resolve_dsn(args, {"SUPABASE_DB_URL": GOOD}), GOOD)
        args2 = self.pf.parse_args(["--expect-ref", REF, "--check-uri-only"])
        self.assertTrue(args2.check_uri_only and args2.dsn is None)

    def test_missing_connection_string_fails_without_connecting(self):
        orig = self.pf.subprocess.run
        self.pf.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not connect"))
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(self.pf.main(["--expect-ref", REF], env={}), 2)
                self.assertEqual(self.pf.main([], env={}), 2)
        finally:
            self.pf.subprocess.run = orig

    def test_psql_receives_the_env_dsn_not_the_ref(self):
        seen = {}

        class R:
            returncode, stderr = 0, ""
            stdout = "0\x1fOK\x1fVERDICT\x1fSafe\n1\x1fOK\x1fsupabase_platform\x1fok\n"

        def fake_run(cmd, **kw):
            seen["dsn"] = cmd[1]
            return R()
        orig = self.pf.subprocess.run
        self.pf.subprocess.run = fake_run
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(self.pf.main(["--expect-ref", REF], env={"SUPABASE_DB_URL": GOOD}), 0)
        finally:
            self.pf.subprocess.run = orig
        self.assertEqual(seen["dsn"], GOOD)
        self.assertNotEqual(seen["dsn"], REF)

    def test_wrong_project_ref_refused(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.pf.main(["--expect-ref", "someotherproject"], env={"SUPABASE_DB_URL": GOOD}), 1)


class SessionPoolerUri(unittest.TestCase):
    def setUp(self):
        self.pf = _load_preflight()

    def test_valid_session_pooler_uri(self):
        self.assertEqual(self.pf.validate_pooler_uri(GOOD, REF), [])
        self.assertEqual(self.pf.validate_pooler_uri(GOOD.replace(":5432/postgres", "/postgres"), REF), [])

    def test_invalid_forms(self):
        cases = {
            GOOD.replace(f"postgres.{REF}:", "postgres:"): "requires 'postgres.",                       # the run's actual mistake
            GOOD.replace(f"postgres.{REF}:", "postgres.abcdefghijklmnopqrst:"): "different Supabase project",
            GOOD.replace(":5432/", ":6543/"): "Transaction pooler",
            GOOD.replace("aws-0-eu-west-2.pooler.supabase.com", f"db.{REF}.supabase.co"): "Session Pooler host",
            f"postgresql://postgres.{REF}@aws-0-eu-west-2.pooler.supabase.com:5432/postgres": "password is missing",
            "host=localhost user=postgres": "must be a URI",
            "": "empty",
            GOOD.replace("/postgres", "/other"): "database name",
        }
        for uri, expected in cases.items():
            problems = " | ".join(self.pf.validate_pooler_uri(uri, REF))
            self.assertIn(expected, problems, uri.replace(SECRET, "***"))

    def test_credentials_never_printed(self):
        bad = GOOD.replace(f"postgres.{REF}:", "postgres:")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self.pf.main(["--expect-ref", REF, "--check-uri-only"], env={"SUPABASE_DB_URL": bad}), 2)
            self.assertEqual(self.pf.main(["--expect-ref", REF, "--check-uri-only"], env={"SUPABASE_DB_URL": GOOD}), 0)
        out = buf.getvalue()
        for leak in (SECRET, "S3cr3t", "%40", "pooler.supabase.com:5432", "aws-0-eu-west-2"):
            self.assertNotIn(leak, out)


class GitHubActionsSteps(unittest.TestCase):
    """Runs the workflow's own step scripts with GitHub's `shell: bash` invocation and a stub psql."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "bin").mkdir()
        self.summary = self.dir / "summary.md"
        self.summary.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def _stub_psql(self, mode: str):
        psql = self.dir / "bin" / "psql"
        psql.write_text("#!/usr/bin/env bash\n"
                        f'printf "%s" "$1" > "{self.dir}/psql_dsn"\n'
                        + {"connect_fail": 'echo "psql: error: connection failed" >&2; exit 2\n',
                           "reject": "printf '0\\x1fREJECT\\x1fVERDICT\\x1fDo NOT apply\\n4\\x1fREJECT\\x1funexpected_objects_in_solvant\\x1ffound\\n'\n",
                           "ok": "printf '0\\x1fOK\\x1fVERDICT\\x1fSafe to apply\\n'\n"}[mode])
        psql.chmod(psql.stat().st_mode | stat.S_IEXEC)

    def _run_step(self, prefix: str, dsn: str, shell: tuple = ("bash", "--noprofile", "--norc", "-eo", "pipefail")):
        script = self.dir / "step.sh"
        script.write_text(step_script(prefix))
        env = {**os.environ, "SUPABASE_DB_URL": dsn, "RUNNER_TEMP": str(self.dir), "GITHUB_STEP_SUMMARY": str(self.summary),
               "PATH": f"{self.dir / 'bin'}:{os.environ['PATH']}"}
        return subprocess.run([*shell, str(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)

    def test_job_uses_bash_with_pipefail_and_apply_requires_preflight(self):
        t = WF.read_text()
        self.assertRegex(t, r"defaults:\n\s+run:\n\s+shell: bash")
        self.assertIn("--expect-ref dfnaevcsergsphiiodtm", step_script("Read-only preflight"))
        self.assertNotRegex(step_script("Read-only preflight"), r"preflight\.py[^\n]*\|\s*tee")
        self.assertIn("if: success() && steps.preflight.outcome == 'success'", t.split("- name: Apply all migrations")[1].split("run:")[0])
        self.assertEqual(_policy().check_pipefail(t, WF.name), [])

    def test_preflight_connection_failure_fails_the_step(self):
        self._stub_psql("connect_fail")
        r = self._run_step("Read-only preflight", GOOD)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("migrations NOT applied", r.stdout)
        self.assertEqual((self.dir / "psql_dsn").read_text(), GOOD)          # defect 1: env DSN used, not the ref
        self.assertNotIn(SECRET, r.stdout + r.stderr + self.summary.read_text())

    def test_preflight_reject_verdict_fails_the_step(self):
        self._stub_psql("reject")
        r = self._run_step("Read-only preflight", GOOD)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("REJECT", self.summary.read_text())

    def test_preflight_ok_passes(self):
        self._stub_psql("ok")
        r = self._run_step("Read-only preflight", GOOD)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("VERDICT", self.summary.read_text())

    def test_bad_username_stops_before_any_connection(self):
        self._stub_psql("ok")
        bad = GOOD.replace(f"postgres.{REF}:", "postgres:")
        r = self._run_step("Validate the connection string format", bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Session Pooler requires", r.stdout)
        self.assertFalse((self.dir / "psql_dsn").exists())                  # no connection attempted
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        r = self._run_step("Read-only preflight", bad)
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.dir / "psql_dsn").exists())

    def test_old_command_hid_the_failure_and_policy_now_rejects_it(self):
        """Documents defect 2: the pre-fix step under GitHub's default `bash -e` exited 0 although preflight failed."""
        self._stub_psql("connect_fail")
        old = ('[ -n "$SUPABASE_DB_URL" ] || { echo "::error::Secret SUPABASE_DB_URL is not set"; exit 1; }\n'
               'python3 supabase/scripts/preflight.py --expect-ref dfnaevcsergsphiiodtm | tee -a "$GITHUB_STEP_SUMMARY"\n')
        script = self.dir / "old.sh"
        script.write_text(old)
        env = {**os.environ, "SUPABASE_DB_URL": GOOD, "GITHUB_STEP_SUMMARY": str(self.summary), "PATH": f"{self.dir / 'bin'}:{os.environ['PATH']}"}
        r = subprocess.run(["bash", "-e", str(script)], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)            # the failure was masked by tee
        wf_old = "jobs:\n  apply:\n    steps:\n      - name: Read-only preflight\n        run: |\n" + "".join("          " + l + "\n" for l in old.splitlines())
        self.assertTrue(_policy().check_pipefail(wf_old, "old.yml"))
