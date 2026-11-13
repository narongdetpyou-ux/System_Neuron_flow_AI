"""Download one open-weight model file and check its size and SHA-256 (the local model lane, ADR-026, ADR-034).
Standard library only; used by the *Local open model eval* workflow.

Two ways to name the file. Run from the repository root:

    # from the pin file: the model's own entry says where the file comes from and which bytes are acceptable
    python .github/scripts/fetch_model.py --profile .github/local_models.json --model <name> --dest ~/models \
        --summary "$GITHUB_STEP_SUMMARY" --github-output "$GITHUB_OUTPUT"
    # the same entry, checked and described without any download (for the cache step's key)
    python .github/scripts/fetch_model.py --profile .github/local_models.json --model <name> --describe \
        --github-output "$GITHUB_OUTPUT"
    # straight from the Hugging Face Hub, as before
    python .github/scripts/fetch_model.py --repo <owner/name> --revision <commit> --file <name or glob> \
        --sha256 <64 hex digits, or empty> --dest ~/models

Sources:
* ``huggingface``: a repository on the Hub at one commit. The Hub is asked which commit the revision is and for
  that commit's file list with each file's size and SHA-256 as the publisher stored them (Git LFS); a pin that
  disagrees with the publisher stops the run before any download. A private repository works with a token from the
  entry's ``token_env``.
* ``link``: an https link kept in an environment variable (a repository secret in Actions), for a file that is not
  published, such as the owner's fine-tune (ADR-034). A Google Drive share link becomes Drive's direct download,
  including the page Drive shows instead of a file it cannot scan for viruses. An optional token from a second
  variable is sent as ``Authorization: Bearer`` to the link's own host only.

Whatever the source:
1. a file already in ``--dest`` (restored from the cache) is kept only when its size and SHA-256 match;
2. otherwise it is downloaded to a temporary name, hashed as it goes, and kept only when the size and the hash
   match; a server that announces another size, or sends more bytes than the pin, is stopped at once;
3. every redirect must stay on https (plain http only on this machine, for the tests), and a token is never sent
   on after a redirect (``add_unredirected_header``);
4. the path, file name, SHA-256, size, model id and whether the file may be cached are written to
   ``$GITHUB_OUTPUT``, and a short table to the summary.

The link and the token are never printed: messages name the source kind, the host and HTTP status codes only. In
GitHub Actions the values derived from a secret (a Drive file id, the direct download address) are also masked.
A link source must say ``"cache": false``: this repository is public and its Actions cache can be restored by other
workflow runs, so a file that is not published is downloaded afresh each run and never cached or uploaded.
``--base-url`` and ``--drive-url`` let the tests use local fakes; anything other than https is refused unless it is
this machine.
"""

import argparse
import fnmatch
import hashlib
from html.parser import HTMLParser
import http.client
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
DRIVE_DOWNLOAD = "https://drive.usercontent.google.com/download"
DRIVE_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
KNOWN_HOSTS = {"huggingface.co": "Hugging Face", **{host: "Google Drive" for host in DRIVE_HOSTS}}
PROFILE_SCHEMA = "neuron-flow-local-models-v1"
USER_AGENT = "neuron-flow-model-fetch/2"  # a generic client name; no contact details
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FILE = re.compile(r"^[A-Za-z0-9*?\[\]][A-Za-z0-9._*?\[\]-]{0,199}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")  # the model id is NAME:<first 12 hex digits of the SHA-256>
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{20,200}$")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CHUNK = 1 << 20
ATTEMPTS = 3
MAX_PAGE_BYTES = 2_000_000
_ENTRY_KEYS = {"title", "file", "size", "sha256", "license", "scope", "cache", "source"}
_OPTIONAL_ENTRY_KEYS = {"base_model", "adapter_sha256", "pinned"}


class FetchError(Exception):
    """A problem the run page should show as it is. It never carries a link or a token."""


# -- addresses and HTTP ------------------------------------------------------------------------------------

def allowed(url):
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and (parts.hostname or "") in LOOPBACK)


def check_base(url):
    if allowed(url):
        return url.rstrip("/")
    raise FetchError("the Hub address must use https")


def host_label(url):
    """What a message may say about where a link points: a known service's name, or nothing more specific."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return KNOWN_HOSTS.get(host, "this machine" if host in LOOPBACK else "another https host")


class SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only on https (or on this machine, for the tests). Headers added with
    ``add_unredirected_header`` (the token) are never copied to the redirect target by urllib."""

    max_redirections = 10

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not allowed(target):
            raise FetchError(f"a redirect (HTTP {code}) left https; nothing was downloaded")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(SafeRedirects)


def _open(url, timeout, token=None):
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT, "accept": "*/*"})
    if token:
        request.add_unredirected_header("Authorization", f"Bearer {token}")  # this host only, never after a redirect
    return OPENER.open(request, timeout=timeout)


def _retrying(action, what):
    """Run ``action`` up to ATTEMPTS times on network errors and 5xx/429 replies; 4xx stops at once."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return action()
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise FetchError(f"{what}: HTTP {exc.code} (the link or its token was refused)") from None
            if exc.code < 500 and exc.code != 429:
                raise FetchError(f"{what}: HTTP {exc.code}") from None
            problem = f"HTTP {exc.code}"
        except FetchError:
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:  # a cut transfer, too
            problem = type(exc).__name__
        if attempt == ATTEMPTS:
            raise FetchError(f"{what}: {problem} after {ATTEMPTS} attempts") from None
        time.sleep(2 * attempt)


def get_json(base, path, what, token=None):
    def call():
        with _open(f"{base}{path}", 30, token) as response:
            return json.loads(response.read(5_000_000).decode("utf-8"))
    try:
        return _retrying(call, what)
    except ValueError:
        raise FetchError(f"{what}: the reply is not JSON") from None


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream(response, part, size):
    """Write the reply to ``part``, hashing as it goes; stop early when it cannot be the pinned file."""
    declared = (response.headers.get("content-length") or "").strip()
    if size is not None and declared.isdigit() and int(declared) != size:
        raise FetchError(f"the source offers {int(declared):,} bytes, not the pinned {size:,}; nothing was kept")
    digest, written = hashlib.sha256(), 0
    with open(part, "wb") as out:
        for block in iter(lambda: response.read(CHUNK), b""):
            written += len(block)
            if size is not None and written > size:
                raise FetchError(f"the source sent more than the pinned {size:,} bytes; nothing was kept")
            out.write(block)
            digest.update(block)
    if declared.isdigit() and written < int(declared):  # the connection ended early: a network error, tried again
        raise http.client.IncompleteRead(b"", int(declared) - written)
    return digest.hexdigest(), written


def _keep(part, target, got, written, size, expected):
    if (size is not None and written != size) or got != expected:
        part.unlink(missing_ok=True)
        wanted = "any number of" if size is None else f"{size:,}"
        raise FetchError(f"the downloaded file does not match: {written:,} bytes, SHA-256 {got[:12]}…, "
                         f"expected {wanted} bytes, {expected[:12]}…; nothing was kept")
    os.replace(part, target)


def _reusable(target, size, expected):
    """A file already there (restored from the cache) is kept only when its size and SHA-256 match."""
    if not target.exists():
        return False
    if (size is None or target.stat().st_size == size) and sha256_of(target) == expected:
        return True
    target.unlink()
    return False


# -- Hugging Face ------------------------------------------------------------------------------------------

def resolve(base, repo, revision, token=None):
    """The fixed commit of ``revision``, and the root files of that commit as {name: (size, sha256 or None)}."""
    quoted = urllib.parse.quote(repo, safe="/")
    info = get_json(base, f"/api/models/{quoted}/revision/{urllib.parse.quote(revision, safe='')}",
                    "reading the revision", token)
    commit = info.get("sha") if isinstance(info, dict) else None
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise FetchError("the Hub did not name a commit for this revision")
    tree = get_json(base, f"/api/models/{quoted}/tree/{commit}", "reading the file list", token)
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


def download(base, repo, commit, name, target, size, expected, token=None):
    url = f"{base}/{urllib.parse.quote(repo, safe='/')}/resolve/{commit}/{urllib.parse.quote(name)}"
    part = target.with_name(target.name + ".part")

    def call():
        try:
            with _open(url, 60, token) as response:
                return _stream(response, part, size)
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    got, written = _retrying(call, "downloading the model file")
    _keep(part, target, got, written, size, expected)


def fetch(base, repo, revision, wanted, pinned, dest, *, token=None, size=None):
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
    commit, files = resolve(base, repo, revision, token)
    name = pick(files, wanted)
    published_size, published = files[name]
    if published is None and not pinned:
        raise FetchError(f"{name} has no SHA-256 on the Hub; pin one with --sha256")
    if pinned and published and pinned != published:
        raise FetchError(f"the pinned SHA-256 {pinned[:12]}… differs from the publisher's {published[:12]}… "
                         f"for {name} at {commit[:12]}; nothing was downloaded")
    if size is not None and published_size is not None and size != published_size:
        raise FetchError(f"the pinned size {size:,} differs from the publisher's {published_size:,} bytes for {name}; "
                         "nothing was downloaded")
    expected = pinned or published
    size = size if size is not None else published_size
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    reused = _reusable(target, size, expected)
    if not reused:
        download(base, repo, commit, name, target, size, expected, token)
    return {"path": str(target), "file": name, "revision": commit, "sha256": expected,
            "size": target.stat().st_size, "pinned": bool(pinned), "reused": reused}


# -- a private link (ADR-034) ------------------------------------------------------------------------------

def drive_file_id(url):
    """The file id in a Google Drive link, or None when the link is not Google Drive's."""
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").lower() not in DRIVE_HOSTS:
        return None
    found = re.search(r"/file/d/([^/?#]+)", parts.path)
    candidate = found.group(1) if found else (urllib.parse.parse_qs(parts.query).get("id") or [""])[0]
    if not DRIVE_ID.fullmatch(candidate):
        raise FetchError("the Google Drive link has no file id (use the file's own share link)")
    return candidate


def download_address(url, drive_url=DRIVE_DOWNLOAD):
    """``(address, kind, file id)``: a Google Drive share link becomes Drive's direct download; any other link is
    used as it is. Only https is accepted (and plain http on this machine, for the tests)."""
    url = (url or "").strip()
    parts = urllib.parse.urlsplit(url)
    if not allowed(url) or not parts.hostname:
        raise FetchError("the link must be an https address")
    if parts.username or parts.password:
        raise FetchError("the link must not carry a user name or password")
    file_id = drive_file_id(url)
    if file_id is None:
        return url, "link", None
    query = urllib.parse.urlencode({"id": file_id, "export": "download", "confirm": "t"})
    return f"{drive_url}?{query}", "google_drive", file_id


class _Forms(HTMLParser):
    """The forms in a page: [(id, action, {hidden name: value})]."""

    def __init__(self):
        super().__init__()
        self.forms, self._current = [], None

    def handle_starttag(self, tag, attrs):
        values = {name: value or "" for name, value in attrs}
        if tag == "form":
            self._current = (values.get("id", ""), values.get("action", ""), {})
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None and values.get("type", "").lower() == "hidden" \
                and values.get("name"):
            self._current[2][values["name"]] = values.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._current = None


def _page_problem(text, kind):
    lowered = text.lower()
    if "quota" in lowered or "too many users" in lowered:
        return ("Google Drive has limited downloads of this shared file for now (download quota); "
                "try again later, or put the file on Hugging Face instead (docs/local_model_finetune.md)")
    if "servicelogin" in lowered or "accounts.google.com" in lowered or "sign in" in lowered:
        return "Google Drive asked for a sign-in: share the file with \"Anyone with the link\" (Viewer)"
    if kind == "google_drive":
        return ("Google Drive answered with a web page instead of the file; check that the link is the model "
                "file's own and that it is shared with \"Anyone with the link\"")
    return "the link answered with a web page instead of the file"


def _next_from_page(text, address, drive_url):
    """The address that Drive's "can't scan this file for viruses" page submits to, or None."""
    forms = _Forms()
    forms.feed(text)
    for form_id, action, hidden in forms.forms:
        if form_id != "download-form" or "id" not in hidden:
            continue
        target = urllib.parse.urljoin(address, action or drive_url)
        host = (urllib.parse.urlsplit(target).hostname or "").lower()
        if not allowed(target) or (host not in DRIVE_HOSTS
                                   and host != (urllib.parse.urlsplit(drive_url).hostname or "").lower()):
            return None
        return target.split("?", 1)[0] + "?" + urllib.parse.urlencode(hidden)
    return None


def fetch_link(url, token, file, size, expected, dest, *, drive_url=DRIVE_DOWNLOAD, mask=None):
    """Download a pinned file from a private link. Returns a dict like :func:`fetch`'s, without a revision."""
    if not FILE.fullmatch(file) or any(c in file for c in "*?[]") or ".." in file:
        raise FetchError("the pinned file name must be a plain name, without folders or wildcards")
    address, kind, file_id = download_address(url, drive_url)
    if mask:
        for value in (url.strip(), address, file_id):
            if value:
                mask(value)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / file
    if _reusable(target, size, expected):
        return {"path": str(target), "file": file, "sha256": expected, "size": size, "reused": True,
                "kind": kind, "host": host_label(url)}
    part = target.with_name(target.name + ".part")
    send_token = token

    def call(current):
        try:
            with _open(current, 120, send_token) as response:
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type.startswith("text/html"):
                    return "page", response.read(MAX_PAGE_BYTES).decode("utf-8", "replace"), response.geturl()
                return "file", _stream(response, part, size), None
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    outcome, value, landed = _retrying(lambda: call(address), "downloading the model file")
    if outcome == "page":
        if (urllib.parse.urlsplit(landed or "").hostname or "").lower() == "accounts.google.com":
            raise FetchError(_page_problem("accounts.google.com", kind))
        following = _next_from_page(value, address, drive_url) if kind == "google_drive" else None
        if following is None:
            raise FetchError(_page_problem(value, kind))
        if mask:
            mask(following)
        send_token = None  # the form's address is Drive's own; a token for the first host is not sent there
        outcome, value, _landed = _retrying(lambda: call(following), "downloading the model file")
        if outcome == "page":
            raise FetchError(_page_problem(value, kind))
    got, written = value
    _keep(part, target, got, written, size, expected)
    return {"path": str(target), "file": file, "sha256": expected, "size": written, "reused": False,
            "kind": kind, "host": host_label(url)}


# -- the pin file ------------------------------------------------------------------------------------------

def load_profile(path, name):
    """One checked entry of the pin file (``.github/local_models.json``)."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise FetchError(f"cannot read the pin file {path}") from None
    if not isinstance(document, dict) or document.get("schema") != PROFILE_SCHEMA \
            or not isinstance(document.get("models"), dict):
        raise FetchError(f"the pin file must use schema {PROFILE_SCHEMA}")
    if name not in document["models"]:
        raise FetchError(f"no model {name!r} in the pin file (there: {', '.join(sorted(document['models']))})")
    entry = document["models"][name]
    problems = []
    if not NAME.fullmatch(name):
        problems.append("the name must be 1-64 lowercase letters, digits, '.', '_' or '-'")
    if not isinstance(entry, dict) or not _ENTRY_KEYS <= set(entry) <= _ENTRY_KEYS | _OPTIONAL_ENTRY_KEYS:
        raise FetchError(f"model {name}: the entry needs exactly {', '.join(sorted(_ENTRY_KEYS))} "
                         f"(optional: {', '.join(sorted(_OPTIONAL_ENTRY_KEYS))})")
    if not isinstance(entry["file"], str) or not FILE.fullmatch(entry["file"]) or not entry["file"].endswith(".gguf") \
            or any(c in entry["file"] for c in "*?[]"):
        problems.append("file must be a plain .gguf file name")
    if type(entry["size"]) is not int or entry["size"] <= 0:
        problems.append("size must be a whole number of bytes")
    if not isinstance(entry["sha256"], str) or not SHA256.fullmatch(entry["sha256"]):
        problems.append("sha256 must be 64 lowercase hex digits")
    if type(entry["cache"]) is not bool:
        problems.append("cache must be true or false")
    source = entry["source"] if isinstance(entry["source"], dict) else {}
    kind = source.get("kind")
    for key in ("token_env", "url_env"):
        if key in source and (not isinstance(source[key], str) or not ENV_NAME.fullmatch(source[key])):
            problems.append(f"source.{key} must be an environment variable name")
    if kind == "huggingface":
        if set(source) - {"kind", "repo", "revision", "token_env"}:
            problems.append("a huggingface source has repo, revision and optionally token_env")
        if not isinstance(source.get("repo"), str) or not REPO.fullmatch(source["repo"]):
            problems.append("source.repo must look like owner/name")
        if not isinstance(source.get("revision"), str) or not COMMIT.fullmatch(source["revision"]):
            problems.append("source.revision must be a 40-digit commit, not a branch")
    elif kind == "link":
        if set(source) - {"kind", "url_env", "token_env"} or "url_env" not in source:
            problems.append("a link source has url_env and optionally token_env")
        if entry["cache"] is not False:
            problems.append("a link source must set \"cache\": false (this public repository's cache is not private)")
    else:
        problems.append("source.kind must be huggingface or link")
    if problems:
        raise FetchError(f"model {name}: " + "; ".join(problems))
    return {**entry, "name": name, "model_id": f"{name}:{entry['sha256'][:12]}"}


def describe(entry):
    """What the workflow needs before any download: the cache key's parts and the model id."""
    return {"name": entry["name"], "model_id": entry["model_id"], "file": entry["file"], "size": entry["size"],
            "sha256": entry["sha256"], "cache": "true" if entry["cache"] else "false",
            "source": entry["source"]["kind"], "url_env": entry["source"].get("url_env", "")}


def fetch_profile(entry, dest, environ, *, base_url=HUB, drive_url=DRIVE_DOWNLOAD, mask=None):
    source = entry["source"]
    token = environ.get(source["token_env"], "").strip() if source.get("token_env") else ""
    if token and mask:
        mask(token)
    if source["kind"] == "huggingface":
        result = fetch(base_url, source["repo"], source["revision"], entry["file"], entry["sha256"], dest,
                       token=token or None, size=entry["size"])
        return {**result, "kind": "huggingface", "host": "Hugging Face", "where": source["repo"]}
    url = environ.get(source["url_env"], "").strip()
    if not url:
        raise FetchError(f"the link for {entry['name']} is missing: add the repository secret {source['url_env']} "
                         "(Settings -> Secrets and variables -> Actions), then run again")
    result = fetch_link(url, token or None, entry["file"], entry["size"], entry["sha256"], dest,
                        drive_url=drive_url, mask=mask)
    return {**result, "revision": "", "pinned": True, "where": f"secret {source['url_env']}"}


# -- the run page ------------------------------------------------------------------------------------------

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


def profile_summary_lines(entry, result):
    if result["kind"] == "huggingface":
        where = f"Hugging Face `{entry['source']['repo']}` at commit `{result['revision'][:12]}`"
    else:
        where = (f"ลิงก์ส่วนตัวจาก secret `{entry['source']['url_env']}` ({result['host']}); ไม่แสดงลิงก์ "
                 "(*a private link from a secret; the link is not shown*)")
    cached = ("ได้ (ไฟล์สาธารณะ)" if entry["cache"]
              else "ไม่เก็บ: ไฟล์ที่ไม่ได้เผยแพร่ ดาวน์โหลดใหม่ทุกรอบ และไม่อัปโหลดเป็น artifact")
    return ["### ไฟล์โมเดล (model file)", "",
            "| | |", "|---|---|",
            f"| โมเดล | {entry['title']} |",
            f"| รุ่นที่ระบบบันทึก (model id) | `{entry['model_id']}` |",
            f"| ที่มา | {where} |",
            f"| ไฟล์ | `{result['file']}` ({result['size']:,} bytes) |",
            f"| SHA-256 | `{result['sha256']}` |",
            "| ตรึงไว้ (pinned) | ใช่: ขนาดและ SHA-256 ใน `.github/local_models.json` |",
            f"| เก็บในแคชของ Actions | {cached} |",
            f"| ได้มาจาก | {'แคชของรอบก่อน' if result['reused'] else 'ดาวน์โหลดใหม่'} (ตรวจขนาดและ SHA-256 แล้ว ตรงกับที่ตรึงไว้) |",
            f"| ขอบเขต | {entry['scope']} |", ""]


def _github_mask(value):
    """GitHub Actions hides a masked value wherever it would appear in the log; the command line itself is not shown."""
    if os.environ.get("GITHUB_ACTIONS") == "true" and value and "\n" not in value:
        print(f"::add-mask::{value}", flush=True)


def _write_outputs(path, values):
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", type=Path, help="the pin file (.github/local_models.json)")
    parser.add_argument("--model", help="the model's name in the pin file")
    parser.add_argument("--describe", action="store_true", help="check the entry and write its outputs; no download")
    parser.add_argument("--repo")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--file", help="exact file name, or a glob such as '*q4_k_m.gguf'")
    parser.add_argument("--sha256", default="", help="the pinned SHA-256; empty = trust the publisher's (warned)")
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--summary", help="append a Markdown table here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--github-output", help="append key=value lines here (e.g. $GITHUB_OUTPUT)")
    parser.add_argument("--base-url", default=HUB, help=argparse.SUPPRESS)
    parser.add_argument("--drive-url", default=DRIVE_DOWNLOAD, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.profile and not args.model:
        parser.error("--profile needs --model")
    if not args.profile and not (args.repo and args.file):
        parser.error("give --profile and --model, or --repo and --file")
    if not args.describe and args.dest is None:
        parser.error("--dest is required unless --describe is given")
    try:
        if args.profile:
            entry = load_profile(args.profile, args.model)
            if args.describe:
                if args.github_output:
                    _write_outputs(args.github_output, describe(entry))
                print(json.dumps(describe(entry), indent=1))
                return 0
            result = fetch_profile(entry, args.dest.expanduser(), environ, base_url=check_base(args.base_url),
                                   drive_url=args.drive_url, mask=_github_mask)
            text = "\n".join(profile_summary_lines(entry, result)) + "\n"
            outputs = {"path": result["path"], "file": result["file"], "sha256": result["sha256"],
                       "size": result["size"], **{k: v for k, v in describe(entry).items()
                                                  if k in ("name", "model_id", "cache", "source")}}
        else:
            result = fetch(check_base(args.base_url), args.repo, args.revision, args.file, args.sha256,
                           args.dest.expanduser())
            text = "\n".join(summary_lines(args.repo, result)) + "\n"
            outputs = {key: result[key] for key in ("path", "file", "revision", "sha256", "size")}
            outputs["pinned"] = "true" if result["pinned"] else "false"
    except FetchError as exc:
        return _failed(args, str(exc))
    except Exception as exc:  # never print a message that could quote a link: the class name only
        return _failed(args, f"unexpected {type(exc).__name__}")
    print(text)
    if not args.profile and not result["pinned"]:
        print("::warning::The model file is not pinned yet; this run trusted the publisher's SHA-256.")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    if args.github_output:
        _write_outputs(args.github_output, outputs)
    return 0


def _failed(args, message):
    print(f"::error::model file: {message}")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(f"### ไฟล์โมเดล (model file)\n\nดาวน์โหลดหรือตรวจไฟล์ไม่ผ่าน: {message}\n\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
