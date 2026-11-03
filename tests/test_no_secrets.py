"""No keys or tokens in the repository's files (roadmap 7.4).

*Actions → Secret scan* runs gitleaks over every commit of every branch in CI. This test is the quick local
check of the files as they are now, with the standard library only, so a cloud session catches a pasted key
before it is pushed. It covers the formats this project could meet: Anthropic, OpenAI, GitHub, AWS, Slack,
Google, Stripe, Render and Honeycomb keys, private keys, Sentry DSNs and URLs that carry a password. The
fake keys the tests use on purpose (``sk-ant-test-…``) do not match. Findings name the file, the line and
the kind, never the value.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "neuron_workspace", "batch_workspace"}
PATTERNS = {
    "Anthropic key": re.compile(r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    "Stripe key": re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}"),
    "Render API key": re.compile(r"\brnd_[A-Za-z0-9]{20,}"),
    # Ingest keys are the key id and its secret run together; management keys put a colon between them.
    "Honeycomb key": re.compile(r"\bhc[a-z](?:ik_[A-Za-z0-9]{58}|mk_[A-Za-z0-9]{26}:[A-Za-z0-9]{32})\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    "Sentry DSN": re.compile(r"https?://[0-9a-f]{32}(?::[0-9a-f]{32})?@[A-Za-z0-9.-]*sentry\.io/\d+"),
    "URL with a password": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@'\"]+:[^\s/@'\"]{6,}@[A-Za-z0-9.-]+"),
}


def repository_files():
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def findings(text):
    """``(line number, kind)`` for every match; the matched value is not returned."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        found += [(number, kind) for kind, pattern in PATTERNS.items() if pattern.search(line)]
    return found


class NoSecretsTests(unittest.TestCase):
    def test_every_pattern_catches_its_format_and_spares_the_test_fakes(self):
        # Built from pieces, so this file never contains a string that a scanner would report.
        samples = {
            "Anthropic key": "sk-ant-" + "api03-" + "A1b2" * 24,
            "OpenAI key": "sk-" + "proj-" + "Ab1" * 16,
            "GitHub token": "gh" + "p_" + "aB3" * 12,
            "AWS access key": "AK" + "IA" + "ABCDEFGHIJ234567",
            "Slack token": "xo" + "xb-" + "1234567890-abcdef",
            "Google API key": "AI" + "za" + "Sy" + "A1b2c3" * 5 + "d4e",
            "Stripe key": "sk" + "_live_" + "a1B2c3D4" * 3,
            "Render API key": "rn" + "d_" + "AbCd1234" * 3,
            "Honeycomb key": "hc" + "aik_" + "01hq7v3k" * 7 + "ab",
            "private key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
            "Sentry DSN": "https://" + "0123456789abcdef" * 2 + "@o1.ingest.us." + "sentry.io/42",
            "URL with a password": "postgres://admin:" + "hunter2hunter2" + "@db.internal",
        }
        self.assertEqual(set(samples), set(PATTERNS))
        for kind, sample in samples.items():
            self.assertIn(kind, [found for _, found in findings(f"value = '{sample}'")], kind)
        for fake in ("sk-ant-test-SECRET-123", "sk-ant-test-0123", "test-access-key-0123456789",
                     "https://user:pw@proxy.example", "https://api.example.com/v1/messages"):
            self.assertEqual(findings(f"value = '{fake}'"), [], fake)

    def test_no_file_in_the_repository_holds_a_key(self):
        problems, scanned = [], 0
        for path in repository_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # binary files: the CI scan covers them
            scanned += 1
            problems += [f"{path.relative_to(ROOT)}:{number}: {kind}" for number, kind in findings(text)]
        self.assertGreater(scanned, 50, "the scan found suspiciously few files")
        self.assertEqual(problems, [], "Keys or tokens in files (move them to a secret, then rotate them):\n"
                         + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
