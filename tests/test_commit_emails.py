"""The commit e-mail check (.github/scripts/check_commit_emails.py; the independent review of 2026-11-10, point 1).

New commits must not carry a personal e-mail address, because this public repository shows every commit's author
and committer address for good. The check runs on a small git repository made here: which addresses pass, that a
pull request fails and a push only warns, how a new branch is handled, and that no address is ever printed.
"""

import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "check_commit_emails.py"
_spec = importlib.util.spec_from_file_location("check_commit_emails", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

PERSONAL = "someone.private@example.org"  # a made-up personal address
CLAUDE = "noreply@anthropic.com"
GITHUB_PRIVATE = "12345+owner@users.noreply.github.com"


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class CommitEmailTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.repo = self._temp.name
        self.git("init", "-q", "-b", "main")
        self.base = self.commit("first", CLAUDE, CLAUDE)
        self.cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        self._temp.cleanup()

    def git(self, *args, env=None):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
                              env={**os.environ, **(env or {})}).stdout.strip()

    def commit(self, message, author, committer):
        env = {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": author, "GIT_COMMITTER_NAME": "C",
               "GIT_COMMITTER_EMAIL": committer}
        self.git("commit", "-q", "--allow-empty", "-m", message, env=env)
        return self.git("rev-parse", "HEAD")

    def run_check(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = check.main(list(args))
        return code, out.getvalue()

    def test_which_addresses_count_as_private(self):
        for address in (CLAUDE, GITHUB_PRIVATE, "noreply@github.com", "41898282+github-actions[bot]@users.noreply.github.com",
                        "NoReply@Anthropic.com"):
            with self.subTest(address=address):
                self.assertTrue(check.allowed(address))
        for address in (PERSONAL, "owner@gmail.com", "noreply@anthropic.com.evil.example", "users.noreply.github.com",
                        "x@users.noreply.github.com.example", ""):
            with self.subTest(address=address):
                self.assertFalse(check.allowed(address))

    def test_a_pull_request_fails_and_a_push_only_warns(self):
        self.commit("by claude", CLAUDE, CLAUDE)
        head = self.commit("merged on github.com with a personal address", PERSONAL, "noreply@github.com")
        code, out = self.run_check("--base", self.base, "--head", head, "--fail")
        self.assertEqual(code, 1)
        self.assertIn("::error::", out)
        code, out = self.run_check("--base", self.base, "--head", head)
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)
        self.assertIn("2 new commit(s) checked, 1 with a personal e-mail address", out)

    def test_clean_commits_pass(self):
        self.commit("by claude", CLAUDE, CLAUDE)
        head = self.commit("merged with the private address", GITHUB_PRIVATE, "noreply@github.com")
        code, out = self.run_check("--base", self.base, "--head", head, "--fail")
        self.assertEqual((code, "::" in out), (0, False))

    def test_the_committer_counts_too(self):
        head = self.commit("committed by hand", CLAUDE, PERSONAL)
        found = check.findings(check.commits([f"{self.base}..{head}"]))
        self.assertEqual([(field, address) for _sha, field, address in found], [("committer", "<hidden>@example.org")])

    def test_no_address_is_ever_printed_or_written(self):
        head = self.commit("leak", PERSONAL, PERSONAL)
        summary = Path(self.repo) / "summary.md"
        code, out = self.run_check("--base", self.base, "--head", head, "--fail", "--history", "--summary", str(summary))
        written = summary.read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        for text in (out, written):
            self.assertNotIn("someone.private", text)
            self.assertIn("<hidden>@example.org", text)
        self.assertIn("Keep my email addresses private", written)
        self.assertIn("1 commit มีอีเมลส่วนตัว", written)

    def test_a_new_branch_checks_only_what_main_does_not_have(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("checkout", "-q", "-b", "feature")
        head = self.commit("feature work", PERSONAL, PERSONAL)
        self.assertEqual(check.revisions_for("0" * 40, head), [head, "--not", "origin/main"])
        code, _out = self.run_check("--base", "0" * 40, "--head", head, "--fail")
        self.assertEqual(code, 1)
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(check.revisions_for("", head), [f"{head}^!"])

    def test_the_history_count_is_a_number_of_commits(self):
        self.commit("one", PERSONAL, "noreply@github.com")
        self.commit("two", PERSONAL, PERSONAL)
        self.assertEqual(check.history_count(), 2)


if __name__ == "__main__":
    unittest.main()
