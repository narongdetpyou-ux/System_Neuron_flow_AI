"""Download one open-weight model file from the Hugging Face Hub and check its SHA-256 (the local model lane,
ADR-026). Standard library only; used by the *Local open model eval* workflow.

Run from the repository root, for example:

    python .github/scripts/fetch_model.py --repo typhoon-ai/typhoon2.5-qwen3-4b-gguf --revision <commit> \
        --file <file name or glob> --sha256 <64 hex digits, or empty> --dest ~/models \
        --summary "$GITHUB_STEP_SUMMARY" --github-output "$GITHUB_OUTPUT"

What it does:
1. asks the Hub which commit the revision is (so a moving name such as ``main`` becomes one fixed commit), and
   for that commit's file list with each file's size and SHA-256 as the publisher stored them (Git LFS);
2. picks exactly one file: the exact name given, or the single file that matches a glob (case-insensitive);
3. expects the pinned SHA-256; without a pin it expects the publisher's and says on the run page that the file
   is not pinned yet; a pin that disagrees with the publisher stops the run before any download;
4. keeps a file already in ``--dest`` (restored from the cache) only when its SHA-256 matches; otherwise
   downloads it from that commit to a temporary name, hashing as it goes, and keeps it only when the size and
   the hash match;
5. writes the path, file name, commit and SHA-256 to ``$GITHUB_OUTPUT`` and a short table to the summary.

Nothing here sends a key: the files are public. ``--base-url`` lets the tests use a local fake Hub; anything
other than https is refused unless it is this machine.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HUB = "https://huggingface.co"
USER_AGENT = "neuron-flow-model-fetch/1"  # a generic client name; no contact details
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FILE = re.compile(r"^[A-Za-z0-9*?\[\]][A-Za-z0-9._*?\[\]-]{0,199}$")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CHUNK = 1 << 20
ATTEMPTS = 3


class FetchError(Exception):
    """A problem the run page should show as it is (no secrets are involved)."""


def check_base(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and (parts.hostname or "") in LOOPBACK):
        return url.rstrip("/")
    raise FetchError("the Hub address must use https")


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT, "accept": "*/*"})
    return urllib.request.urlopen(request, timeout=timeout)


def _retrying(action, what):
    """Run ``action`` up to ATTEMPTS times on network errors and 5xx/429 replies; 4xx stops at once."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return action()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise FetchError(f"{what}: HTTP {exc.code}") from None
            problem = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            problem = type(exc).__name__
        if attempt == ATTEMPTS:
            raise FetchError(f"{what}: {problem} after {ATTEMPTS} attempts") from None
        time.sleep(2 * attempt)


def get_json(base, path, what):
    def call():
        with _open(f"{base}{path}", 30) as response:
            return json.loads(response.read(5_000_000).decode("utf-8"))
    try:
        return _retrying(call, what)
    except ValueError:
        raise FetchError(f"{what}: the reply is not JSON") from None


def resolve(base, repo, revision):
    """The fixed commit of ``revision``, and the root files of that commit as {name: (size, sha256 or None)}."""
    quoted = urllib.parse.quote(repo, safe="/")
    info = get_json(base, f"/api/models/{quoted}/revision/{urllib.parse.quote(revision, safe='')}",
                    "reading the revision")
    commit = info.get("sha") if isinstance(info, dict) else None
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise FetchError("the Hub did not name a commit for this revision")
    tree = get_json(base, f"/api/models/{quoted}/tree/{commit}", "reading the file list")
    if not isinstance(tree, list):
        raise FetchError("the file list is not a list")
    files = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "file" or not isinstance(entry.get("path"), str):
            continue
        lfs = entry.get("lfs") if isinstance(entry.get("lfs"), dict) else {}
        digest = lfs.get("oid") if isinstance(lfs.get("oid"), str) and SHA256.fullmatch(lfs.get("oid")) else None
        size = lfs.get("size", entry.get("size"))
        files[entry["path"]] = (size if type(size) is int and size >= 0 else None, digest)
    return commit, files


def pick(files, wanted):
    if wanted in files:
        return wanted
    matches = sorted(name for name in files if "/" not in name and fnmatch.fnmatch(name.lower(), wanted.lower()))
    if len(matches) == 1:
        return matches[0]
    listed = ", ".join(sorted(name for name in files if name.lower().endswith(".gguf"))) or "none"
    raise FetchError(f"{len(matches)} files match {wanted!r} (model files here: {listed})")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download(base, repo, commit, name, target, size, expected):
    url = f"{base}/{urllib.parse.quote(repo, safe='/')}/resolve/{commit}/{urllib.parse.quote(name)}"
    part = target.with_name(target.name + ".part")

    def call():
        digest, written = hashlib.sha256(), 0
        try:
            with _open(url, 60) as response, open(part, "wb") as out:
                for block in iter(lambda: response.read(CHUNK), b""):
                    out.write(block)
                    digest.update(block)
                    written += len(block)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        return digest.hexdigest(), written

    got, written = _retrying(call, "downloading the model file")
    if (size is not None and written != size) or got != expected:
        part.unlink(missing_ok=True)
        raise FetchError(f"the downloaded file does not match: {written} bytes, SHA-256 {got[:12]}…, "
                         f"expected {size} bytes, {expected[:12]}…; nothing was kept")
    os.replace(part, target)


def fetch(base, repo, revision, wanted, pinned, dest):
    """Returns a dict with path, file, revision (commit), sha256, size, pinned and reused."""
    if not REPO.fullmatch(repo) or ".." in repo:
        raise FetchError("--repo must look like owner/name")
    if not REVISION.fullmatch(revision):
        raise FetchError("--revision must be a branch, tag or commit name")
    if not FILE.fullmatch(wanted) or ".." in wanted:
        raise FetchError("--file must be a file name or a glob, without folders")
    pinned = (pinned or "").strip().lower()
    if pinned and not SHA256.fullmatch(pinned):
        raise FetchError("--sha256 must be 64 hex digits, or empty")
    commit, files = resolve(base, repo, revision)
    name = pick(files, wanted)
    size, published = files[name]
    if published is None and not pinned:
        raise FetchError(f"{name} has no SHA-256 on the Hub; pin one with --sha256")
    if pinned and published and pinned != published:
        raise FetchError(f"the pinned SHA-256 {pinned[:12]}… differs from the publisher's {published[:12]}… "
                         f"for {name} at {commit[:12]}; nothing was downloaded")
    expected = pinned or published
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    reused = False
    if target.exists():
        if sha256_of(target) == expected:
            reused = True
        else:
            target.unlink()
    if not reused:
        download(base, repo, commit, name, target, size, expected)
    return {"path": str(target), "file": name, "revision": commit, "sha256": expected,
            "size": target.stat().st_size, "pinned": bool(pinned), "reused": reused}


def summary_lines(repo, result):
    lines = ["### ไฟล์โมเดล (model file)", "",
             "| | |", "|---|---|",
             f"| ที่มา (Hugging Face) | `{repo}` |",
             f"| commit | `{result['revision']}` |",
             f"| ไฟล์ | `{result['file']}` ({result['size']:,} bytes) |",
             f"| SHA-256 | `{result['sha256']}` |",
             f"| ตรึงไว้ในไฟล์ workflow (pinned) | {'ใช่' if result['pinned'] else 'ยังไม่ตรึง: ใช้ค่าของผู้เผยแพร่'} |",
             f"| ได้มาจาก | {'แคชของรอบก่อน (ตรวจ SHA-256 แล้ว)' if result['reused'] else 'ดาวน์โหลดใหม่ (ตรวจ SHA-256 แล้ว)'} |", ""]
    if not result["pinned"]:
        lines += ["> ยังไม่ได้ตรึงไฟล์: รอบนี้เชื่อค่า SHA-256 ที่ผู้เผยแพร่บันทึกไว้ ให้นำ commit และ SHA-256 ข้างบนไปใส่ใน workflow "
                  "(*Not pinned yet: this run trusted the publisher's SHA-256. Put the commit and SHA-256 above into the "
                  "workflow.*)", ""]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--file", required=True, help="exact file name, or a glob such as '*q4_k_m.gguf'")
    parser.add_argument("--sha256", default="", help="the pinned SHA-256; empty = trust the publisher's (warned)")
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--summary", help="append a Markdown table here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--github-output", help="append key=value lines here (e.g. $GITHUB_OUTPUT)")
    parser.add_argument("--base-url", default=HUB, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        result = fetch(check_base(args.base_url), args.repo, args.revision, args.file, args.sha256,
                       args.dest.expanduser())
    except FetchError as exc:
        print(f"::error::model file: {exc}")
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as stream:
                stream.write(f"### ไฟล์โมเดล (model file)\n\nดาวน์โหลดหรือตรวจไฟล์ไม่ผ่าน: {exc}\n\n")
        return 1
    text = "\n".join(summary_lines(args.repo, result)) + "\n"
    print(text)
    if not result["pinned"]:
        print("::warning::The model file is not pinned yet; this run trusted the publisher's SHA-256.")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            for key in ("path", "file", "revision", "sha256", "size"):
                stream.write(f"{key}={result[key]}\n")
            stream.write(f"pinned={'true' if result['pinned'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
