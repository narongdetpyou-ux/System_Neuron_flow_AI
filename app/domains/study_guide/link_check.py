"""Link check for the study library (roadmap 3.1). *Actions → Study library link check* runs it every week,
by hand, and on every push or pull request that changes the study guide.

It opens every resource URL in the library and reports what came back. It never edits the library: a
broken link fails the run loudly, and a person decides what to change (a new address, or removing the
entry).

Outcomes:

* ``ok``: a 2xx answer at the listed address (a redirect that only adds or drops a final ``/`` counts).
* ``moved``: a 2xx answer, but only after a redirect to another address. The link still works; update the
  entry to the new address after checking that it is still the same resource. A warning, not a failure.
* ``blocked``: 401, 403 or 429. The site refused an automated visit, which does not prove the link is
  broken; check it by hand. A warning, not a failure.
* ``broken``: 404, 410 or any other 4xx; 5xx after one retry; a network, DNS or TLS error or a timeout
  after one retry; a redirect loop; or a redirect from https to http. These fail the run.

The report shows each page's own title, so a person can see that the link still leads to the resource the
entry describes. Page titles are text from other sites, so they are cleaned before they go into the
Markdown report, and they never go into annotations.

Exit status: 0 when no link is broken; 1 when any link is broken; 2 when the library itself is invalid.
Usage: ``python -m app.domains.study_guide.link_check [--summary FILE] [--timeout SECONDS]``
"""

import argparse
from dataclasses import dataclass
import html
import http.client
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from .library import LibraryError, load_library

# A plain browser-like name. Some sites refuse clients that do not look like a browser.
USER_AGENT = "Mozilla/5.0 (compatible; neuron-flow-link-check/1.0)"
HEADERS = {"User-Agent": USER_AGENT,
           "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
           "Accept-Language": "en;q=0.9,th;q=0.8"}
READ_LIMIT = 256 * 1024
BLOCKED = (401, 403, 429)
OUTCOMES = ("ok", "moved", "blocked", "broken")
_TITLE = re.compile(rb"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_PDF_TITLE = re.compile(rb"/Title\s*\(((?:[^()\\]|\\.){1,300})\)")
_LABEL_TH = {"ok": "✅ เปิดได้", "moved": "↪️ ย้ายที่อยู่", "blocked": "⚠️ เว็บไม่ให้ตรวจอัตโนมัติ",
             "broken": "❌ เสีย"}


class InsecureRedirect(Exception):
    """A redirect from https to http."""


@dataclass(frozen=True)
class LinkResult:
    resource_id: str
    url: str
    outcome: str        # one of OUTCOMES
    status: object      # the HTTP status, or None when no answer came back
    final_url: str
    title: str          # the page's own title, cleaned; empty when none was found
    detail: str         # a short reason, in English; empty for ok
    attempts: int


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(req.full_url).scheme == "https" and urlsplit(newurl).scheme != "https":
            raise InsecureRedirect(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(proxies=None):
    """An opener that follows redirects (but never from https to http). ``proxies=None`` uses the
    environment's proxy settings; ``{}`` uses none."""
    handlers = [_RedirectHandler()]
    if proxies is not None:
        handlers.append(urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener(*handlers)


def check_url(resource_id, url, *, timeout=20.0, retry_delay=5.0, opener=None, sleep=time.sleep):
    """Open one URL; a server error or a network problem is retried once."""
    opener = opener or build_opener()
    result, retry = _attempt(resource_id, url, timeout, opener, 1)
    if retry:
        sleep(retry_delay)
        result, _ = _attempt(resource_id, url, timeout, opener, 2)
    return result


def _attempt(resource_id, url, timeout, opener, attempt):
    def outcome(kind, status=None, final=url, title="", detail=""):
        return LinkResult(resource_id, url, kind, status, final, title, detail, attempt)

    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, final = response.status, response.geturl()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(READ_LIMIT)
    except InsecureRedirect as exc:
        return outcome("broken", detail=f"redirected from https to http ({_clean(str(exc), 120)})"), False
    except urllib.error.HTTPError as exc:
        status, final = exc.code, exc.geturl() or url
        exc.close()
        if status in BLOCKED:
            return outcome("blocked", status, final, detail=f"HTTP {status}: the site refused an automated "
                                                            "check; check it by hand"), False
        if status >= 500:
            return outcome("broken", status, final, detail=f"HTTP {status} (server error)"), True
        if 300 <= status < 400:
            return outcome("broken", status, final, detail=f"HTTP {status}: a redirect loop or a redirect "
                                                           "without an address"), False
        return outcome("broken", status, final, detail=f"HTTP {status}"), False
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        return outcome("broken", detail=_describe(getattr(exc, "reason", exc), timeout)), True
    title = _title(body, content_type, charset)
    if _same_address(url, final):
        return outcome("ok", status, final, title), False
    return outcome("moved", status, final, title, detail=f"now answers at {_clean(final, 200)}"), False


def _describe(reason, timeout):
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return f"no answer within {timeout:g} s"
    if isinstance(reason, socket.gaierror):
        return "host name not found"
    if isinstance(reason, ssl.SSLError):
        return f"TLS error ({_clean(getattr(reason, 'reason', None) or type(reason).__name__, 80)})"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, ConnectionResetError):
        return "connection reset"
    return f"{type(reason).__name__}: {_clean(str(reason), 120)}"


def _same_address(listed, final):
    def normal(address):
        parts = urlsplit(address)
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
    return normal(listed) == normal(final)


def _title(body, content_type, charset):
    if content_type == "application/pdf" or body.startswith(b"%PDF-"):
        match = _PDF_TITLE.search(body)
        return _clean(re.sub(r"\\(.)", r"\1", match.group(1).decode("latin-1")), 160) if match else ""
    match = _TITLE.search(body)
    if not match:
        return ""
    try:
        text = match.group(1).decode(charset, errors="replace")
    except LookupError:
        text = match.group(1).decode("utf-8", errors="replace")
    return _clean(html.unescape(text), 160)


def _clean(text, limit):
    """One line of text that is safe inside a Markdown code span in a table cell: no line breaks or other
    control characters, no backtick (it would end the code span) and no '|' (it would split the cell).
    Inside a code span, Markdown and HTML are shown as plain text."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    text = " ".join(text.replace("`", "'").replace("|", "/").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _code(text):
    return f"`{text}`" if text else "—"


def _annotation(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def summary_markdown(library, results):
    counts = {kind: sum(r.outcome == kind for r in results) for kind in OUTCOMES}
    verdict = "ไม่ผ่าน" if counts["broken"] else "ผ่าน"
    lines = [
        f"## ตรวจลิงก์คลังแหล่งเรียน (study library link check): {verdict}",
        "",
        f"คลัง `{library.version}` (sha256 `{library.sha256[:12]}…`): {len(results)} ลิงก์ — "
        f"เปิดได้ {counts['ok']} · ย้ายที่อยู่ {counts['moved']} · เว็บไม่ให้ตรวจอัตโนมัติ {counts['blocked']} · "
        f"เสีย {counts['broken']}",
        "",
        "| ผล | แหล่ง (id) | รหัส HTTP | ชื่อหน้าที่เว็บตอบมา | หมายเหตุ |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {_LABEL_TH[r.outcome]} | `{r.resource_id}` | {r.status or '—'} | {_code(_clean(r.title, 160))} | "
                     f"{_code(_clean(r.detail, 240))} |")
    lines += [
        "",
        "การตรวจนี้ไม่แก้คลังเอง ถ้ามีลิงก์เสีย ให้คนตัดสินว่าจะเปลี่ยนที่อยู่หรือเอาแหล่งนั้นออก "
        "(ไฟล์ `app/domains/study_guide/catalog/resources_v1.json`) · "
        "ย้ายที่อยู่ = ยังเปิดได้แต่ควรอัปเดตที่อยู่ · เว็บไม่ให้ตรวจอัตโนมัติ = ต้องเปิดดูเองด้วยมือ",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check that every link in the study library still opens.")
    parser.add_argument("--summary", help="append a Markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds to wait for each page")
    parser.add_argument("--library-version", default="v1")
    args = parser.parse_args(argv)
    try:
        library = load_library(args.library_version)
    except LibraryError as exc:
        for problem in exc.problems:
            print(f"::error title=Study library is invalid::{_annotation(problem)}")
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as stream:
                stream.write("## ตรวจลิงก์คลังแหล่งเรียน (study library link check): ไม่ผ่าน\n\n"
                             f"คลังแหล่งเรียนไม่ผ่านการตรวจโครงสร้าง ({len(exc.problems)} ปัญหา) ดูรายละเอียดใน log\n")
        return 2

    opener = build_opener()
    results = []
    for resource in library.resources:
        result = check_url(resource.id, resource.url, timeout=args.timeout, opener=opener)
        results.append(result)
        print(f"{result.outcome:8} {result.status or '-':>4} {result.resource_id}: {result.url}"
              f"{' — ' + result.detail if result.detail else ''}{' — title: ' + result.title if result.title else ''}")
        message = _annotation(f"{result.resource_id}: {result.url} — {result.detail}")
        if result.outcome == "broken":
            print(f"::error title=Broken study link::{message}")
        elif result.outcome in ("moved", "blocked"):
            print(f"::warning title=Study link {result.outcome}::{message}")
    report = summary_markdown(library, results)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(report)
    broken = sum(r.outcome == "broken" for r in results)
    print(f"{len(results)} links: " + ", ".join(f"{sum(r.outcome == k for r in results)} {k}" for k in OUTCOMES))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
