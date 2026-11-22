"""A walk through the web page in a real browser on a phone-sized screen (roadmap 1.8).

Most page tests read the page's source (``tests/test_web_page.py``), so a button that cannot be clicked would pass
while its text is still there (the quality report of 2026-11-19, page 6). This walk clicks like a person, with
Playwright's "Pixel 7" (412 × 839 CSS pixels, touch, Chromium), against a running service whose queue is empty and
whose AI is the mock:

1. sign in with the access key on the gate;
2. type a synthetic case, send it, and confirm it on the confirm card;
3. when it waits for a person, open the drawer (☰), find it in "รอรีวิว" and open it from there;
4. approve it on the decision card, with a reason;
5. see the handoff ("ส่งต่อแล้ว"), open the job it started, and wait until that job has recorded the approval;
6. open the settings tab and find the decision counted in "กฎกับ AI เทียบกับคำตัดสินของคน", timed (roadmap 2.10: the
   page sent how long its decision card was open);
7. check the same over the API: the case approved, one handoff, the linked job completed with a Core receipt, and
   the scorecard's count with one timed decision.

On every screen it checks that nothing scrolls sideways and that the page has raised no script error and got no 5xx
reply. A click only succeeds on an element that is visible, enabled, still and not covered, so a button that
cannot be pressed fails the walk. Each screen is saved in ``--out`` as the phone shows it, scrolled to the part the
step is about (on failure too), and each step adds a Thai line to ``--summary``.

Run it against a fresh service (the counts assume an empty queue):

    pip install "playwright==1.63.0"
    python -m playwright install --with-deps --only-shell chromium
    python -m tests.browser_walk --url http://127.0.0.1:8003 --key <access key> --out walk --summary summary.md

Playwright is a test dependency for CI only (roadmap 1.8, rule 8): the image and the app never import it, and the
unit tests do not need it. The walk only types synthetic text, and it never prints or saves the access key: the gate
masks it, and the first picture is taken after sign-in.
"""

import argparse
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from examples.service_smoke_test import Client, check, wait_for_ready, wait_until_healthy, write_summary

DEVICE = "Pixel 7"
# A synthetic case on which the rules and the mock AI agree (upload_review), so it waits for a person unraised.
CASE = "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99% ทดสอบด้วยเบราว์เซอร์"
REASON = "ทดสอบด้วยเบราว์เซอร์: อนุมัติตามที่กฎเสนอ"
STEP_MS = 30_000     # one click or one screen
CASE_MS = 90_000     # a case from "send" to "waits for a person", on a container that has just started
SCORECARD = "กฎกับ AI เทียบกับคำตัดสินของคน"


class Walk:
    """One browser page, with the checks that every screen must pass."""

    def __init__(self, page, out, summary):
        self.page, self.out, self.summary = page, out, summary
        self.problems = []
        self.shots = 0
        page.set_default_timeout(STEP_MS)
        page.on("pageerror", lambda exc: self.problems.append(f"script error: {str(exc)[:200]}"))
        page.on("console", self._console)
        page.on("response", self._response)

    def _console(self, message):
        # A refused request (a 401 before sign-in) is logged as "Failed to load resource"; that is not a page bug.
        if message.type == "error" and not message.text.startswith("Failed to load resource"):
            self.problems.append(f"console error: {message.text[:200]}")

    def _response(self, response):
        if response.status >= 500:
            self.problems.append(f"HTTP {response.status} from {urlsplit(response.url).path[:80]}")

    def picture(self, name):
        """The phone's screen as a person sees it. The page is a fixed frame whose parts scroll inside it, so a
        "full page" picture would show the same screen: the step scrolls to what it is about instead."""
        self.shots += 1
        path = self.out / f"{self.shots:02d}-{name}.png"
        self.page.screenshot(path=str(path))
        return path.name

    def screen(self, name, thai, focus=None):
        """The checks every screen must pass, then its picture and its Thai line."""
        if focus is not None:
            focus.scroll_into_view_if_needed()
        wider = self.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(wider <= 1, f"{name}: nothing scrolls sideways (the page is {wider}px wider than the screen)")
        check(not self.problems, f"{name}: no script error and no 5xx reply" +
              (f" ({'; '.join(self.problems)})" if self.problems else ""))
        picture = self.picture(name)
        write_summary(self.summary, f"- {thai} ✓ (`{picture}`)")


def drawer_settled(page):
    """The drawer slides in for 0.22 s (app.css); wait until it stands still, open."""
    page.wait_for_function("getComputedStyle(document.getElementById('sidebar')).transform === 'none'")


def walk(page, url, key, out, summary):
    w = Walk(page, out, summary)
    thread = page.locator("#thread")

    # 1. The gate.
    page.goto(url)
    page.locator("#gate-key").fill(key)
    page.locator("#gate-form button[type=submit]").click()
    expect(page.locator("#app")).to_be_visible()
    expect(page.locator("#sys-runner")).to_contain_text("พร้อม")
    w.screen("signed-in", "ใส่รหัสเข้าใช้แล้วเข้าหน้าแชทได้ ตัวรันงานบอก \"พร้อม\"")

    # 2. Send a case and confirm it.
    page.locator("#case-summary").fill(CASE)
    page.locator("#case-submit").click()
    confirm = thread.locator('button[data-action="confirm"]')
    expect(confirm).to_have_text("ยืนยันและส่ง")
    w.screen("confirm-card", "พิมพ์เคสแล้วกด \"ส่ง\" ระบบยังไม่ส่ง แต่ขึ้นการ์ด \"รอยืนยัน\" พร้อมขั้นตอน",
             focus=confirm)
    confirm.click()

    # 3. It waits for a person: find it in the drawer's "รอรีวิว" and open it from there.
    expect(thread.locator("section.decide")).to_be_visible(timeout=CASE_MS)
    page.locator("#open-sidebar").click()
    expect(page.locator("#open-sidebar")).to_have_attribute("aria-expanded", "true")
    item = page.locator("#inbox-list button.inbox-item", has_text=CASE)
    expect(item).to_be_visible()
    drawer_settled(page)
    w.screen("inbox", "เคสถึง \"รอคนตรวจ\" และอยู่ในกล่อง \"รอรีวิว\" ในเมนู ☰", focus=item)
    item.click()
    expect(page.locator("#open-sidebar")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#sidebar")).to_be_hidden()  # closed: hidden once it has slid out
    decide = thread.locator("section.decide")
    expect(decide).to_be_visible()
    w.screen("decision-card", "เปิดเคสจากกล่อง \"รอรีวิว\" แล้วเห็นการ์ด \"ตัดสินเคสนี้\"", focus=decide)

    # 4. Approve it, with a reason.
    decide.locator('button[data-action="review-choose"][data-decision="APPROVE"]').click()
    expect(decide.locator('button[data-action="review-choose"][data-decision="APPROVE"]')).to_have_attribute(
        "aria-pressed", "true")
    decide.locator("#review-reason").fill(REASON)
    submit = decide.locator('button[data-action="review-submit"]')
    expect(submit).to_have_text("บันทึก: อนุมัติ")
    submit.click()
    expect(thread).to_contain_text("คนตัดสินแล้ว: อนุมัติ")
    expect(decide).to_have_count(0)

    # 5. The handoff, and the job it started.
    handoff = thread.locator("section.handoff")
    expect(handoff.locator("h3")).to_contain_text("ส่งต่อแล้ว")
    w.screen("decided", "กด \"อนุมัติ\" ใส่เหตุผล กดบันทึก แล้วเห็น \"คนตัดสินแล้ว\" และ \"ส่งต่อแล้ว\"",
             focus=handoff.locator("h3"))
    handoff.locator('button[data-action="open-job"]').click()
    expect(thread).to_contain_text("งานนี้ถูกส่งต่อมาผ่านตัวกลาง")
    expect(thread).to_contain_text("บันทึกผลเสร็จแล้ว พร้อมใบรับจาก Core", timeout=CASE_MS)
    w.screen("linked-job", "เปิดงานที่ส่งต่อไป และงานนั้นบันทึกผลการอนุมัติเสร็จพร้อมใบรับจาก Core",
             focus=thread.get_by_text("บันทึกผลเสร็จแล้ว พร้อมใบรับจาก Core"))

    # 6. The decision is counted in the settings tab.
    page.locator("#tab-settings").click()
    panel = page.locator("#view-settings section.panel", has=page.locator("h2", has_text=SCORECARD))
    expect(panel).to_contain_text("อนุมัติ 1 เคส")
    expect(panel).to_contain_text("จับเวลาได้ 1 จาก 1 เคส")  # the page sent the card's time (roadmap 2.10)
    w.screen("scorecard", f"แท็บ \"ตั้งค่า\" นับคำตัดสินนี้ในส่วน \"{SCORECARD}\" (อนุมัติ 1 เคส) และจับเวลาตัดสินได้ 1 เคส",
             focus=panel.get_by_text("อนุมัติ 1 เคส"))


def same_over_the_api(client):
    """What the clicks did, read back from the server."""
    status, listed = client.call("GET", "/v1/jobs?limit=20")
    cases = [job for job in listed.get("jobs", []) if job.get("summary_preview") == CASE]
    check(status == 200 and len(cases) == 1 and cases[0]["status"] == "APPROVED",
          "over the API: the case sent from the page is approved")
    status, job = client.call("GET", f"/v1/jobs/{cases[0]['job_id']}")
    handoffs = (job.get("handoff") or {}).get("to") or []
    check(status == 200 and [item.get("state") for item in handoffs] == ["STARTED"],
          "over the API: the approval handed on once")
    status, applied = client.call("GET", f"/v1/jobs/{handoffs[0]['target_job_id']}")
    receipt = ((applied.get("result") or {}).get("receipt") or {}).get("sha256", "")
    check(status == 200 and applied.get("status") == "COMPLETED" and len(receipt) == 64,
          "over the API: the linked job completed with a Core receipt")
    status, card = client.call("GET", "/v1/reviews/scorecard")
    totals = card.get("totals") or {}
    check(status == 200 and (totals.get("decided"), totals.get("approved")) == (1, 1),
          "over the API: the scorecard counts the one decision")
    time = ((card.get("groups") or [{}])[0]).get("review_time") or {}
    check(time.get("timed") == 1 and isinstance(time.get("median_s"), (int, float)) and time["median_s"] > 0,
          "over the API: the decision was timed (the seconds its card was open, roadmap 2.10)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True, help="the service's NEURON_FLOW_ACCESS_KEY (never printed)")
    parser.add_argument("--out", default="browser-walk", help="folder for the pictures of each screen")
    parser.add_argument("--summary", help="append the Thai lines here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--timeout", type=float, default=90, help="seconds to wait for the service to be ready")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.url, args.key)
    wait_until_healthy(client, args.timeout)
    wait_for_ready(client, args.timeout)
    write_summary(args.summary, f"### เดินหน้าเว็บด้วยเบราว์เซอร์บนจอขนาดมือถือ ({DEVICE}, ขั้น 1.8)\n")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(**playwright.devices[DEVICE], locale="th-TH", timezone_id="Asia/Bangkok")
        page = context.new_page()
        try:
            walk(page, args.url, args.key, out, args.summary)
        except (PlaywrightError, AssertionError, SystemExit) as exc:
            path = out / "99-failed.png"
            try:
                page.screenshot(path=str(path))
            except PlaywrightError:
                pass
            reason = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
            write_summary(args.summary, f"- ไม่ผ่าน: {reason} (รูปหน้าจอตอนพัง `{path.name}`)")
            print(f"FAILED: {reason}")
            return 1
        finally:
            context.close()
            browser.close()
    same_over_the_api(client)
    write_summary(args.summary, "- ตรวจซ้ำผ่าน API ตรงกับที่กดบนหน้าเว็บ: เคสอนุมัติแล้ว ส่งต่อ 1 ครั้ง"
                                " งานที่ส่งต่อเสร็จพร้อมใบรับ และตารางนับ 1 คำตัดสิน ✓")
    write_summary(args.summary, "- ทุกหน้าจอ: ไม่มีส่วนที่ล้นออกด้านข้าง ไม่มีข้อผิดพลาดของสคริปต์ และไม่มีคำตอบ 5xx"
                                " · รูปหน้าจอทุกขั้นอยู่ใน artifact `browser-walk` ของ run นี้\n")
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
