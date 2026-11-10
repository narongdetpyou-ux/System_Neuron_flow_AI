"""Check that new commits carry no personal e-mail address (the independent review of 2026-11-10, point 1).

This repository is public with its full history (owner decision D5, 2026-11-08). Every commit shows its author's
and committer's e-mail address, so a commit made with a personal address publishes that address for good: a later
commit cannot take it back, and a rewrite of the history is an owner decision (D8 in docs/ROADMAP.md). This check
stops the number from growing unnoticed. Run by .github/workflows/secret-scan.yml:

* on a pull request, every commit the pull request adds: a personal address **fails** the check, so it is seen
  before the merge;
* on a push, the pushed commits: a personal address is a **warning** only. The commits are public already, and a
  red check on ``main`` would stop Render from deploying (``autoDeployTrigger: checksPass``). The remedy is a
  setting of the person who made the commit, not code: GitHub → Settings → Emails → "Keep my email addresses
  private", after which merges made on github.com use the private ``…@users.noreply.github.com`` address;
* ``--history`` also counts the commits in the whole history that carry one (reported, never failed).

Allowed: GitHub's private addresses (``…@users.noreply.github.com``, which bots use too), ``noreply@github.com``
(GitHub's web-flow committer) and ``noreply@anthropic.com`` (Claude Code). Anything else counts as personal. The
output never prints an address: only the commit, the field and the domain (``<hidden>@example.com``).

Usage: python .github/scripts/check_commit_emails.py --base SHA --head SHA [--fail] [--history] [--summary FILE]
A base of zeros (a new branch) checks the head's commits that ``origin/main`` does not have.
"""

import argparse
import re
import subprocess
import sys

ALLOWED = (re.compile(r"^[A-Za-z0-9._%+\-\[\]]+@users\.noreply\.github\.com$", re.IGNORECASE),
           re.compile(r"^noreply@github\.com$", re.IGNORECASE),
           re.compile(r"^noreply@anthropic\.com$", re.IGNORECASE))
ZEROS = re.compile(r"^0+$")
FIELDS = ("author", "committer")


def allowed(address):
    return any(pattern.fullmatch(address.strip()) for pattern in ALLOWED)


def hidden(address):
    """``<hidden>@domain``: enough to see which kind of address it is, never the address."""
    domain = address.rsplit("@", 1)[-1] if "@" in address else "?"
    return f"<hidden>@{domain.lower()}"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def commits(revisions, cwd=None):
    """``[(sha, author_email, committer_email)]`` for ``git log`` arguments."""
    out = git("log", "--format=%H%x1f%ae%x1f%ce", *revisions, "--", cwd=cwd)
    return [tuple(line.split("\x1f")) for line in out.splitlines() if line]


def revisions_for(base, head, cwd=None):
    if base and not ZEROS.fullmatch(base):
        return [f"{base}..{head}"]
    try:  # a new branch: the commits that main does not have yet
        git("rev-parse", "--verify", "--quiet", "origin/main", cwd=cwd)
        return [head, "--not", "origin/main"]
    except subprocess.CalledProcessError:
        return [f"{head}^!"]


def findings(rows):
    """``[(sha, field, hidden address)]`` for every author or committer address that is not allowed."""
    found = []
    for sha, *addresses in rows:
        for field, address in zip(FIELDS, addresses):
            if not allowed(address):
                found.append((sha, field, hidden(address)))
    return found


def history_count(cwd=None):
    """How many commits on every branch carry a personal address (a number, never the addresses)."""
    return len({sha for sha, _field, _address in findings(commits(["--all"], cwd=cwd))})


def summary_text(found, checked, *, fail, history):
    lines = ["## อีเมลใน commit (Commit e-mail check)", ""]
    if not found:
        lines.append(f"ผ่าน: {checked} commit ที่เพิ่มเข้ามาไม่มีอีเมลส่วนตัว (No personal e-mail address in the "
                     f"{checked} new commit(s).)")
    else:
        lines += [f"{'ไม่ผ่าน' if fail else 'คำเตือน'}: พบอีเมลส่วนตัวใน {len({f[0] for f in found})} จาก {checked} commit "
                  "ที่เพิ่มเข้ามา repo นี้เป็นสาธารณะ อีเมลนี้จึงเปิดเผยแล้วและลบด้วย commit ใหม่ไม่ได้", "",
                  "| commit | ช่อง | ที่อยู่ (ซ่อนแล้ว) |", "|---|---|---|"]
        lines += [f"| `{sha[:12]}` | {field} | `{address}` |" for sha, field, address in found]
        lines += ["", "**วิธีแก้ (คลิกอย่างเดียว ทำครั้งเดียว):** รูปโปรไฟล์ GitHub → Settings → Emails → ติ๊ก "
                  "\"Keep my email addresses private\" และ \"Block command line pushes that expose my email\" "
                  "หลังจากนั้นการกด Merge บน github.com จะใช้อีเมลแบบ `…@users.noreply.github.com` แทน",
                  "", "(Fix: GitHub → Settings → Emails → keep my email addresses private. Addresses already in the "
                  "history stay; removing them is owner decision D8 in docs/ROADMAP.md.)"]
    if history is not None:
        lines += ["", f"ประวัติทั้งหมดทุก branch: {history} commit มีอีเมลส่วนตัว (ตัวเลขนี้ไม่ควรเพิ่มอีก) "
                  f"({history} commit(s) in the whole history carry a personal address; D8 decides about them.)"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--fail", action="store_true", help="exit 1 when a new commit has a personal address")
    parser.add_argument("--history", action="store_true", help="also count the whole history")
    parser.add_argument("--summary", help="append a Thai/English summary to this file (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    rows = commits(revisions_for(args.base, args.head))
    found = findings(rows)
    history = history_count() if args.history else None
    for sha, field, address in found:
        level = "error" if args.fail else "warning"
        print(f"::{level}::commit {sha[:12]} has a personal e-mail address as {field} ({address}). "
              "Fix: GitHub → Settings → Emails → Keep my email addresses private.")
    print(f"{len(rows)} new commit(s) checked, {len({f[0] for f in found})} with a personal e-mail address"
          + (f"; {history} in the whole history" if history is not None else ""))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as summary:
            summary.write(summary_text(found, len(rows), fail=args.fail, history=history))
    return 1 if found and args.fail else 0


if __name__ == "__main__":
    sys.exit(main())
