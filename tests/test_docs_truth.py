"""Docs truth checks (roadmap 1.5): cheap guards against the docs drifting away from the code.

1. Every relative link in README.md, CLAUDE.md and docs/**/*.md points at a file that exists, and every
   ``#anchor`` points at a heading that exists in the target Markdown file (GitHub's anchor rules).
2. Every place that states the current number of tests states the real number.

Both read files only; nothing is imported from ``app`` or ``neuron_flow``.
"""

from pathlib import Path
import re
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]

# [text](target) and [text](target "title"); images too. Reference-style links are not used in this repo.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
EXPLICIT_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"", re.IGNORECASE)

# Where the docs state the current test count. Each pattern has one group: the number.
TEST_COUNT_CLAIMS = {
    "README.md": re.compile(r"python -m unittest discover -s tests -v\s+#\s*(\d+) tests"),
    "CLAUDE.md": re.compile(r"# all tests \((\d+) on "),
    "docs/architecture.md": re.compile(r"^tests/\s+(\d+) tests:", re.MULTILINE),
    "docs/intake_queue.md": re.compile(r"\((\d+) tests on \d{4}-\d{2}-\d{2}"),
    "docs/ROADMAP.md": re.compile(r"ผ่านชุดทดสอบอัตโนมัติ (\d+) ข้อ"),
}


def prose_lines(text):
    """The lines outside fenced code blocks, with their 1-based numbers."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def github_slug(heading):
    """The anchor GitHub gives a heading: lower case, keep letters, marks, digits, '_', '-' and spaces,
    then spaces become '-'. Inline code keeps its text; links keep their text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "").lower()
    kept = "".join(ch for ch in text if ch in " -" or unicodedata.category(ch)[0] in "LMN" or ch == "_")
    return kept.replace(" ", "-")


def anchors(path):
    found, seen = set(), {}
    text = path.read_text(encoding="utf-8")
    for _number, line in prose_lines(text):
        match = HEADING.match(line)
        if match:
            slug = github_slug(match.group(2))
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            found.add(slug if count == 0 else f"{slug}-{count}")
        found.update(EXPLICIT_ANCHOR.findall(line))
    return found


def links(path):
    for number, line in prose_lines(path.read_text(encoding="utf-8")):
        for target in LINK.findall(INLINE_CODE.sub("", line)):
            yield number, target


class DocsTruthTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        problems, checked = [], 0
        cache = {}
        for doc in DOCS:
            for number, target in links(doc):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):  # https:, mailto:, computer: …
                    continue
                checked += 1
                where = f"{doc.relative_to(ROOT)}:{number}: {target}"
                file_part, _, fragment = target.partition("#")
                resolved = (doc.parent / file_part).resolve() if file_part else doc
                if not resolved.is_relative_to(ROOT):
                    problems.append(f"{where} (points outside the repository)")
                    continue
                if not resolved.exists():
                    problems.append(f"{where} (no such file)")
                    continue
                if fragment and resolved.suffix == ".md":
                    if resolved not in cache:
                        cache[resolved] = anchors(resolved)
                    if fragment.lower() not in cache[resolved]:
                        problems.append(f"{where} (no heading with this anchor)")
        self.assertGreater(checked, 20, "the link scanner found suspiciously few links")
        self.assertEqual(problems, [], "Broken links in the docs:\n" + "\n".join(problems))

    def test_stated_test_counts_match_the_real_count(self):
        real = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT)).countTestCases()
        problems = []
        for name, pattern in TEST_COUNT_CLAIMS.items():
            text = (ROOT / name).read_text(encoding="utf-8")
            stated = pattern.findall(text)
            if not stated:
                problems.append(f"{name}: the test-count sentence was not found (update TEST_COUNT_CLAIMS)")
            problems += [f"{name}: says {value}, but there are {real} tests" for value in stated if int(value) != real]
        self.assertEqual(problems, [], "\n".join(problems))


class SlugTests(unittest.TestCase):
    def test_slugs_follow_githubs_rules(self):
        self.assertEqual(github_slug("Owner decisions"), "owner-decisions")
        self.assertEqual(github_slug("0.1 Put round 2 online on Render (owner + Claude)"),
                         "01-put-round-2-online-on-render-owner--claude")
        self.assertEqual(github_slug("`study_guide.v1`: the first-response study guide"),
                         "study_guidev1-the-first-response-study-guide")
        self.assertEqual(github_slug("สิ่งที่ต้องทำเพื่อเปิดใช้บน Render (ครั้งแรก ทำครั้งเดียว)"),
                         "สิ่งที่ต้องทำเพื่อเปิดใช้บน-render-ครั้งแรก-ทำครั้งเดียว")


if __name__ == "__main__":
    unittest.main()
