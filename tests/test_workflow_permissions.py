"""Public-repository hardening for the GitHub Actions workflows (ROADMAP 7.4).

Once the repository is public, anyone can open a pull request. So every workflow sets a top-level
``permissions:`` block that only reads (its token cannot push, comment or change settings unless a job asks
for more), and no workflow uses ``pull_request_target``, which runs with the repository's secrets on code
that a fork can influence. The standard library has no YAML parser, so these checks read the files as text.
"""
import pathlib
import re
import unittest

WORKFLOW_DIR = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))

READ_ONLY_SCOPE = re.compile(r"^\s+[a-z][a-z-]*:\s*(read|none)\s*(#.*)?$")


def top_level_permissions(text):
    """Return the lines of the top-level ``permissions:`` block, or None when there is none."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("permissions:"):
            value = line[len("permissions:"):].split("#", 1)[0].strip()
            if value:
                return [value]
            block = []
            for follower in lines[index + 1:]:
                if follower.strip() and not follower.startswith((" ", "\t")):
                    break
                if follower.strip() and not follower.strip().startswith("#"):
                    block.append(follower)
            return block
    return None


class WorkflowPermissionTests(unittest.TestCase):
    def test_every_workflow_has_a_read_only_token(self):
        self.assertTrue(WORKFLOWS, f"no workflows found in {WORKFLOW_DIR}")
        problems = []
        for path in WORKFLOWS:
            block = top_level_permissions(path.read_text(encoding="utf-8"))
            if block is None:
                problems.append(f"{path.name}: no top-level 'permissions:' block (add 'contents: read')")
            elif block in (["read-all"], ["{}"]):
                continue
            elif not block or not all(READ_ONLY_SCOPE.match(line) for line in block):
                problems.append(f"{path.name}: the top-level permissions grant more than read: {block}")
        self.assertEqual(problems, [])

    def test_no_workflow_uses_pull_request_target(self):
        self.assertTrue(WORKFLOWS, f"no workflows found in {WORKFLOW_DIR}")
        uses_it = re.compile(r"^[^#\n]*\bpull_request_target\b", re.MULTILINE)
        offenders = [path.name for path in WORKFLOWS if uses_it.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
