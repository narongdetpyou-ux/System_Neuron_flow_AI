"use strict";
/* Neuron Flow web page ("Nocturne" look): a chat-style intake, the steps of each case (Flow) and its
 * history (Trace), and a read-only settings view.
 *
 * Plain JavaScript, no external requests: it only talks to this service's own /v1 API. Server data is
 * always inserted as text (never as HTML) and no style attribute is ever set (only CSSOM properties),
 * so the strict Content-Security-Policy holds. The access key stays in this browser (session storage,
 * or local storage when "remember" is ticked).
 *
 * What the page can honestly show: Core runs a job as one blocking loop, so while a case is RUNNING
 * the page knows only that it is running; each step's result appears when the case finishes. */
(function () {
  const KEY_STORAGE = "neuronflow.accessKey";
  const TERMINAL = new Set(["REVIEW_REQUIRED", "COMPLETED", "FAILED", "DELIVERY_FAILED", "CANCELLED"]);
  const CASE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
  const JOB_ID = /^job_[0-9a-f]{24}$/;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const STATUS = {
    QUEUED: "รอคิว", RUNNING: "กำลังทำงาน", REVIEW_REQUIRED: "รอคนตรวจ", COMPLETED: "เสร็จแล้ว",
    FAILED: "ไม่สำเร็จ", DELIVERY_FAILED: "บันทึกรายงานไม่สำเร็จ", CANCELLED: "ยกเลิกแล้ว",
  };
  const CATEGORY = { access: "เข้าระบบ / บัญชี", upload: "อัปโหลดไฟล์", billing: "การเงิน / การชำระเงิน", other: "เรื่องอื่น ๆ" };
  const QUEUE = {
    access_review: "คิวตรวจเรื่องเข้าระบบ", upload_review: "คิวตรวจเรื่องอัปโหลด",
    billing_review: "คิวตรวจเรื่องการเงิน", general_review: "คิวตรวจทั่วไป",
  };
  const CONFIDENCE = { high: "สูง", medium: "กลาง", low: "ต่ำ" };
  const MASKED = {
    email: "อีเมล", thai_id: "เลขบัตรประชาชน", card: "เลขแบบบัตรเครดิต", phone: "เบอร์โทร",
    number: "ตัวเลขยาว (เช่น เลขบัญชี)", name: "ชื่อ",
  };
  const REASON = {
    rules_llm_disagree: "กฎกับ AI เห็นไม่ตรงกัน",
    llm_low_confidence: "AI ไม่ค่อยมั่นใจ",
    llm_unavailable: "AI ใช้งานไม่ได้ตอนนั้น จึงใช้ข้อเสนอของกฎอย่างเดียว",
    rules_no_keyword_match: "กฎไม่เจอคำสำคัญ (กฎรู้จักแค่คำภาษาอังกฤษบางคำ)",
  };
  const UNAVAILABLE = {
    provider_unavailable: "ผู้ให้บริการ AI ไม่ตอบ (ลองแล้ว 2 ครั้ง)",
    invalid_model_output: "AI ตอบผิดรูปแบบ (ลองแล้ว 2 ครั้ง)",
    model_declined: "AI ปฏิเสธที่จะตอบ",
  };
  const FAILURE = {
    step_failed: "มีขั้นตอนที่ทำไม่สำเร็จ ดูขั้นที่มีเครื่องหมาย ✕",
    configuration_changed: "ตั้งค่า AI หรือ prompt ถูกเปลี่ยนหลังรับเคส ระบบจึงไม่รันต่อด้วยค่าใหม่โดยไม่บอก ส่งเคสใหม่ได้เลย",
    runner_attempts_exhausted: "ตัวรันงานหยุดกลางคันระหว่างทำเคสนี้หลายครั้ง ระบบจึงพักเคสนี้ไว้ไม่ให้วนซ้ำ",
    runtime_error: "ระบบขัดข้องระหว่างทำงาน (แจ้งเตือนไปที่ระบบติดตามข้อผิดพลาดแล้ว ถ้าตั้งค่าไว้)",
    delivery_failed: "ทำงานครบทุกขั้น แต่บันทึกรายงานไม่สำเร็จ เพราะมีรายงานเดิมที่ไม่ตรงกัน",
    unknown_workflow_type: "ระบบไม่รู้จักประเภทงานนี้แล้ว",
  };
  const FAILURE_SHORT = {
    step_failed: "มีขั้นตอนที่ไม่สำเร็จ", configuration_changed: "ตั้งค่าเปลี่ยนหลังรับเคส",
    runner_attempts_exhausted: "ตัวรันงานหยุดกลางคันหลายครั้ง", runtime_error: "ระบบขัดข้อง",
    delivery_failed: "บันทึกรายงานไม่สำเร็จ", unknown_workflow_type: "ไม่รู้จักประเภทงาน",
  };
  const STEP = {
    classify_rules: "กฎเดิมจัดหมวด", classify_llm: "AI ให้ความเห็นที่สอง", compare: "เทียบสองความเห็น",
    prepare: "เตรียมข้อเสนอให้คนตรวจ", classify: "กฎจัดหมวด",
  };
  const STEP_SHORT = { classify_rules: "กฎเดิม", classify_llm: "AI", compare: "เทียบ", prepare: "เตรียม", classify: "กฎ" };
  const ROLE = {
    classify_rules: "ข้อเสนอหลัก (กฎ)", classify: "ข้อเสนอหลัก (กฎ)", classify_llm: "ความเห็นที่สอง (AI · shadow)",
    compare: "เทียบสองความเห็น", prepare: "เตรียมให้คนตรวจ",
  };
  const WORKFLOW = {
    "case_triage.v2": "จัดหมวดเคส: กฎเดิม + AI ความเห็นที่สอง",
    "case_triage.v1": "จัดหมวดเคส: กฎอย่างเดียว",
  };
  const ERROR_TYPE = {
    ControllerInterrupted: "ตัวรันงานหยุดกลางคัน แล้วทำต่อหลังเปิดใหม่",
    TimeoutError: "ใช้เวลานานเกินกำหนด",
    LLMConfigError: "ตั้งค่า AI ไม่ถูกต้อง (เช่น API key)",
    LLMRequestError: "ผู้ให้บริการ AI ไม่รับคำขอ",
    LLMTransientError: "ผู้ให้บริการ AI ติดขัดชั่วคราว",
    InvalidModelOutput: "AI ตอบผิดรูปแบบ",
    OutputValidationError: "ผลลัพธ์ไม่ผ่านด่านตรวจ",
    DependencyFailed: "ขั้นก่อนหน้าไม่สำเร็จ",
    InputContractError: "ข้อมูลเข้าไม่ตรงสัญญา",
    PermanentAgentError: "ผิดพลาดแบบลองใหม่ก็ไม่หาย",
  };
  const API_ERROR = {
    invalid_input: "ข้อมูลเคสไม่ถูกต้อง",
    invalid_fields: "รูปแบบคำขอไม่ถูกต้อง",
    invalid_json: "รูปแบบคำขอไม่ถูกต้อง",
    unknown_workflow_type: "ไม่รู้จักประเภทงานนี้",
    invalid_idempotency_key: "รหัสส่งงานไม่ถูกต้อง",
    idempotency_conflict: "รหัสส่งงานนี้เคยใช้กับเคสอื่นแล้ว กด \"ยกเลิก\" แล้วส่งใหม่เพื่อสร้างงานใหม่",
    queue_full: "คิวเต็มแล้ว รอสักครู่แล้วลองใหม่",
    rate_limited: "ส่งถี่เกินไป",
    body_too_large: "ข้อความยาวเกินไป",
    internal_error: "ระบบขัดข้องฝั่งเซิร์ฟเวอร์",
  };
  const STEP_STATE = { done: "สำเร็จ", fail: "ไม่สำเร็จ", skip: "ข้าม", none: "ไม่ได้รัน", pending: "ยังไม่เริ่ม", working: "กำลังทำงาน", preview: "ตัวอย่าง" };
  const LEVEL = { ok: "ok", run: "run", err: "err", warn: "warn", info: "info" };

  const $ = (id) => document.getElementById(id);

  function el(tag, props, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (name === "text") node.textContent = value;
      else if (name === "class") node.className = value;
      else if (name === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(name, value === true ? "" : String(value));
    }
    for (const child of [].concat(children === undefined ? [] : children)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (value !== null && value !== undefined) node.setAttribute(name, String(value));
    }
    return node;
  }

  const state = {
    key: null, status: null, jobs: [], nextBefore: null,
    view: "chat",
    selectedId: null, job: null,
    draft: null,     // a case typed but not yet confirmed: { id, autoId, body, sending, error }
    last: null,      // the last case sent from this tab: { jobId, body } (for the "send again" test)
    cancelAsk: null, // job id whose "cancel this case" button was pressed once and now asks to confirm
    cancelling: false,
    trace: { jobId: null, events: [], after: 0, loading: false },
    traceFilter: "all",
    techOpen: false, howOpen: false,
    keys: { thread: null, side: null, flow: null },
    graph: { nodes: new Map(), edges: [] },
    refreshTimer: null, jobTimer: null,
  };
  let draftCounter = 0;

  // ---------- small formatters --------------------------------------------------------------

  const pad = (n, width) => String(n).padStart(width || 2, "0");

  function shortTime(iso) {
    return iso ? new Date(iso).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) : "";
  }
  function clockTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  }
  function fullTime(iso) {
    return iso ? new Date(iso).toLocaleString("th-TH") : "—";
  }
  function seconds(fromIso, toIso) {
    if (!fromIso) return null;
    const end = toIso ? new Date(toIso) : new Date();
    return Math.max(0, (end - new Date(fromIso)) / 1000);
  }
  function stopwatch(total) {
    if (total === null || total === undefined) return "";
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${pad(h)}:${pad(m)}:${s.toFixed(1).padStart(4, "0")}`;
  }
  function limitText(timeout) {
    if (typeof timeout !== "number") return "";
    if (timeout < 60) return `${Number(timeout.toFixed(2))} วิ`;
    return `${Number((timeout / 60).toFixed(1))} นาที`;
  }
  function dayLabel(iso) {
    const day = new Date(iso);
    const today = new Date();
    const start = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const diff = Math.round((start(today) - start(day)) / 86400000);
    if (diff === 0) return "วันนี้";
    if (diff === 1) return "เมื่อวาน";
    return day.toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });
  }
  function aiLabel(ai) {
    if (!ai || !ai.provider) return "AI";
    if (ai.provider === "mock") return "AI จำลอง";
    if (ai.provider === "anthropic") return `Claude (${ai.model})`;
    return `${ai.provider}/${ai.model}`;
  }
  function stepName(id) { return STEP[id] || id; }

  // ---------- access key -------------------------------------------------------------------

  function loadKey() {
    try { return sessionStorage.getItem(KEY_STORAGE) || localStorage.getItem(KEY_STORAGE); } catch (_) { return null; }
  }
  function saveKey(key, remember) {
    try {
      sessionStorage.setItem(KEY_STORAGE, key);
      if (remember) localStorage.setItem(KEY_STORAGE, key); else localStorage.removeItem(KEY_STORAGE);
    } catch (_) { /* storage blocked: the key lives in memory for this tab */ }
  }
  function forgetKey() {
    try { sessionStorage.removeItem(KEY_STORAGE); localStorage.removeItem(KEY_STORAGE); } catch (_) { /* ignore */ }
    state.key = null;
  }

  // ---------- API --------------------------------------------------------------------------

  async function call(method, path, body) {
    const headers = { Accept: "application/json" };
    if (state.key) headers.Authorization = "Bearer " + state.key;
    const init = { method, headers, cache: "no-store", credentials: "omit" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (_) {
      const error = new Error("network");
      error.network = true;
      throw error;
    }
    let data = {};
    try { data = (await response.json()) || {}; } catch (_) { /* not JSON */ }
    return { status: response.status, data };
  }

  function handleAccessProblem(result) {
    if (result.status === 401) {
      forgetKey();
      showGate("รหัสเข้าใช้ไม่ถูกต้อง หรือถูกเปลี่ยนแล้ว ใส่ใหม่อีกครั้ง");
      return true;
    }
    if (result.status === 429 && result.data.error === "too_many_attempts") {
      forgetKey();
      showGate(`ลองรหัสผิดหลายครั้งเกินไป รอประมาณ ${result.data.retry_after_s || 60} วินาทีแล้วลองใหม่`);
      return true;
    }
    if (result.status === 503 && result.data.error === "access_key_not_configured") {
      forgetKey();
      showGate(null, true);
      return true;
    }
    return false;
  }

  // ---------- screens ----------------------------------------------------------------------

  function showGate(message, needsSetup) {
    stopTimers();
    closePanels();
    $("app").hidden = true;
    $("gate").hidden = false;
    $("gate-form").hidden = Boolean(needsSetup);
    $("gate-setup").hidden = !needsSetup;
    const error = $("gate-error");
    error.hidden = !message;
    error.textContent = message || "";
    if (!needsSetup) $("gate-key").focus();
  }

  function showApp() {
    $("gate").hidden = true;
    $("app").hidden = false;
  }

  function banner(message, kind) {
    const node = $("banner");
    node.hidden = !message;
    node.textContent = message || "";
    node.className = "banner" + (kind ? " " + kind : "");
  }

  let toastTimer = null;
  function toast(message) {
    const node = $("toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
  }

  async function enter() {
    let result;
    try {
      result = await call("GET", "/v1/status");
    } catch (_) {
      banner("ติดต่อระบบไม่ได้ กำลังลองใหม่…");
      setTimeout(enter, 4000);
      return;
    }
    if (handleAccessProblem(result)) return;
    if (result.status !== 200) {
      banner("ระบบตอบผิดปกติ กำลังลองใหม่…");
      setTimeout(enter, 4000);
      return;
    }
    banner(null);
    showApp();
    applyStatus(result.data);
    await refreshQueue();
    renderAll();
    startTimers();
    const fromLink = location.hash.slice(1);
    if (JOB_ID.test(fromLink)) await selectJob(fromLink);
  }

  async function probeSetup() {
    try {
      const result = await call("GET", "/healthz");
      if (result.status === 200 && result.data.access_key === "not_configured") showGate(null, true);
    } catch (_) { /* the gate stays as it is */ }
  }

  // ---------- status -----------------------------------------------------------------------

  function setSys(id, text, kind, title) {
    const node = $(id);
    node.textContent = text;
    node.className = "sys-value" + (kind ? " " + kind : "");
    if (title) node.title = title; else node.removeAttribute("title");
  }

  function workflowInfo(name) {
    return ((state.status || {}).workflows || []).find((w) => w.name === name) || null;
  }
  function defaultWorkflow() {
    return (state.status || {}).default_workflow || "case_triage.v2";
  }
  function limits() {
    const limit = (state.status || {}).limits || {};
    return { min: limit.summary_min_chars || 8, max: limit.summary_max_chars || 500 };
  }

  function applyStatus(status) {
    state.status = status;
    const runner = status.runner || {};
    if (runner.state === "blocked_config") {
      setSys("sys-runner", "หยุดรอ: ตั้งค่า AI ไม่ครบ", "warn", runner.detail);
      banner(`ตัวรันงานหยุดรอ เพราะตั้งค่า AI ไม่ครบ: ${runner.detail || ""} เคสที่ส่งจะรออยู่ในคิวจนกว่าจะแก้`, "warn");
    } else if (!runner.alive) {
      setSys("sys-runner", runner.state === "unknown" ? "● กำลังเริ่ม" : "● ไม่ตอบ", "bad",
        "ตัวรันงานไม่ส่งสัญญาณชีพ เคสใหม่ยังรับเข้าคิวได้ และจะถูกทำเมื่อตัวรันงานกลับมา");
      banner(null);
    } else {
      setSys("sys-runner", runner.state === "running" ? "● กำลังทำเคส" : "● พร้อม", runner.state === "running" ? "busy" : "ok");
      banner(null);
    }
    const ai = status.ai || {};
    if (ai.problem) setSys("sys-ai", "ตั้งค่าไม่ครบ", "warn", ai.problem);
    else if (ai.simulated) setSys("sys-ai", "AI จำลอง", "", "ตัวจำลองแบบคำสำคัญ ใช้ทดสอบระบบโดยไม่เสียค่า API (ไม่ใช่ AI จริง)");
    else setSys("sys-ai", aiLabel(ai), "ok");
    const storage = status.storage || {};
    if (storage.persistent) setSys("sys-storage", "ถาวร", "ok");
    else setSys("sys-storage", "ชั่วคราว: เคสหายเมื่อรีสตาร์ท", "warn",
      "ยังไม่มีดิสก์ถาวร (Render แบบฟรีไม่มีดิสก์) ระบบยังทำงานครบทุกขั้น แต่เคสเก่าจะหายเมื่อระบบหลับหรือรีสตาร์ท");
    $("version").textContent = status.version ? "v" + status.version : "";
    const workflow = defaultWorkflow();
    const aiShort = ai.problem ? "AI ตั้งค่าไม่ครบ" : ai.simulated ? "AI จำลอง" : aiLabel(ai);
    $("mode-tag").textContent = workflow === "case_triage.v1" ? "กฎอย่างเดียว" : `${aiShort} · ความเห็นที่สอง (shadow)`;
    const { min, max } = limits();
    $("case-summary").maxLength = max;
    $("summary-hint").textContent = `อย่างน้อย ${min} ตัวอักษร`;
    updateCounter();
    renderCounts(status.queue || {});
    if (state.view === "settings") renderSettings();
  }

  function renderCounts(queue) {
    const items = [
      ["รอคิว", queue.QUEUED, ""], ["กำลังทำ", queue.RUNNING, ""],
      ["รอคนตรวจ", queue.REVIEW_REQUIRED, queue.REVIEW_REQUIRED ? "warn" : ""],
      ["ไม่สำเร็จ", (queue.FAILED || 0) + (queue.DELIVERY_FAILED || 0), (queue.FAILED || queue.DELIVERY_FAILED) ? "err" : ""],
    ];
    if (queue.COMPLETED) items.push(["เสร็จแล้ว", queue.COMPLETED, ""]);
    if (queue.CANCELLED) items.push(["ยกเลิกแล้ว", queue.CANCELLED, ""]);
    $("counts").replaceChildren(...items.map(([label, n, kind]) =>
      el("span", {}, [label + " ", el("span", { class: "n" + (kind ? " " + kind : ""), text: String(n || 0) })])));
  }

  // ---------- case list (left) -------------------------------------------------------------

  async function refreshQueue(more) {
    const params = new URLSearchParams({ limit: "20" });
    if (more && state.nextBefore) params.set("before", String(state.nextBefore));
    const result = await call("GET", "/v1/jobs?" + params.toString());
    if (handleAccessProblem(result) || result.status !== 200) return;
    const page = result.data.jobs || [];
    if (more) {
      state.jobs = state.jobs.concat(page);
      state.nextBefore = result.data.next_before;
    } else {
      const fresh = new Set(page.map((job) => job.job_id));
      const oldest = page.length ? page[page.length - 1].seq : Infinity;
      const kept = state.jobs.filter((job) => !fresh.has(job.job_id) && job.seq < oldest);
      state.jobs = page.concat(kept);
      if (!kept.length) state.nextBefore = result.data.next_before;
    }
    renderSidebar();
  }

  function jobTone(job) {
    if (job.status === "RUNNING") return ["st-running", "กำลังทำงาน", true];
    if (job.status === "QUEUED") return ["st-queued", "รอคิว", false];
    if (job.status === "REVIEW_REQUIRED") {
      return job.review_priority === "elevated" ? ["st-elevated", "รอคนตรวจ · ยกให้ดูก่อน", false] : ["st-review", "รอคนตรวจ", false];
    }
    if (job.status === "COMPLETED") return ["st-done", "เสร็จแล้ว", false];
    if (job.status === "CANCELLED") return ["st-cancelled", "ยกเลิกแล้ว", false];
    return ["st-failed", STATUS[job.status] || job.status, false];
  }

  function renderSidebar() {
    const key = JSON.stringify([state.selectedId, state.nextBefore,
      state.jobs.map((job) => [job.job_id, job.status, job.review_priority])]);
    if (key === state.keys.side) return;
    state.keys.side = key;
    const nodes = [];
    let group = null;
    for (const job of state.jobs) {
      const label = dayLabel(job.created_at);
      if (label !== group) {
        nodes.push(el("div", { class: "group-label", text: label }));
        group = label;
      }
      const [tone, text, blink] = jobTone(job);
      nodes.push(el("button", {
        type: "button", class: "job", dataset: { id: job.job_id },
        "aria-current": job.job_id === state.selectedId ? "true" : null,
      }, [
        el("span", { class: "job-title" }, [el("span", { class: "case", text: job.case_id }), el("span", { class: "time", text: shortTime(job.created_at) })]),
        el("span", { class: "job-preview", text: job.summary_preview }),
        el("span", { class: "job-status " + tone }, [el("span", { class: "dot" + (blink ? " blink" : "") }), text]),
      ]));
    }
    $("job-list").replaceChildren(...nodes);
    $("queue-empty").hidden = state.jobs.length > 0;
    $("queue-more").hidden = !state.nextBefore;
  }

  // ---------- one case ---------------------------------------------------------------------

  function setHash(jobId) {
    try {
      history.replaceState(null, "", jobId ? "#" + jobId : location.pathname + location.search);
    } catch (_) { /* some embedded browsers refuse; the link is only a convenience */ }
  }

  function dropDraft(keepText) {
    const draft = state.draft;
    if (!draft) return;
    state.draft = null;
    if (keepText && !$("case-summary").value.trim()) {
      $("case-summary").value = draft.body.input.summary;
      if (!draft.autoId) $("case-id").value = draft.body.input.case_id;
      updateCounter();
      autoGrow();
    }
  }

  async function selectJob(jobId) {
    dropDraft(true);
    state.selectedId = jobId;
    state.job = null;
    state.techOpen = false;
    setHash(jobId);
    resetTrace(jobId);
    closePanels();
    setView("chat");
    renderAll();
    clearTimeout(state.jobTimer);
    await loadJob();
  }

  function clearSelection() {
    clearTimeout(state.jobTimer);
    state.selectedId = null;
    state.job = null;
    setHash(null);
    resetTrace(null);
  }

  async function loadJob() {
    const jobId = state.selectedId;
    if (!jobId) return;
    let result;
    try {
      result = await call("GET", `/v1/jobs/${encodeURIComponent(jobId)}`);
    } catch (_) {
      state.jobTimer = setTimeout(loadJob, 3000);
      return;
    }
    if (handleAccessProblem(result) || jobId !== state.selectedId) return;
    if (result.status === 404) {
      clearSelection();
      toast("ไม่พบเคสนี้แล้ว (แผนฟรีล้างเคสเก่าเมื่อระบบหลับหรือรีสตาร์ท)");
      renderAll();
      return;
    }
    if (result.status !== 200) {
      state.jobTimer = setTimeout(loadJob, 3000);
      return;
    }
    const before = state.job;
    const job = result.data;
    state.job = job;
    if (before && before.job_id === job.job_id && !TERMINAL.has(before.status) && TERMINAL.has(job.status)) {
      toast(`${job.case_id}: ${STATUS[job.status] || job.status}`);
      refreshStatus();  // the counts on the left change now, not at the next 4-second refresh
    }
    const listed = state.jobs.find((item) => item.job_id === job.job_id);
    if (listed && (listed.status !== job.status || listed.review_priority !== job.review_priority)) {
      listed.status = job.status;
      listed.review_priority = job.review_priority;
    }
    renderAll();
    await loadTrace();
    if (jobId !== state.selectedId) return;
    if (!TERMINAL.has(job.status)) state.jobTimer = setTimeout(loadJob, 1000);
  }

  // ---------- step plan and step states ----------------------------------------------------

  function planFor(job) {
    if (job && Array.isArray(job.plan) && job.plan.length) return job.plan;
    const info = workflowInfo(job ? job.workflow_type : defaultWorkflow());
    if (info && Array.isArray(info.steps) && info.steps.length) return info.steps;
    const steps = job && job.result && job.result.steps;
    if (Array.isArray(steps) && steps.length) {
      return steps.map((step, i) => ({ id: step.id, agent: step.agent, depends_on: i ? [steps[i - 1].id] : [],
        max_attempts: step.max_attempts, timeout_s: null }));
    }
    return null;
  }

  function stepStates(job, plan) {
    const results = new Map((((job || {}).result || {}).steps || []).map((step) => [step.id, step]));
    const states = new Map();
    for (const step of plan) {
      const result = results.get(step.id) || null;
      let value = "preview";
      if (job) {
        if (job.status === "QUEUED") value = "pending";
        else if (job.status === "RUNNING") value = "working";
        else if (!result) value = "none";
        else value = { SUCCEEDED: "done", FAILED: "fail", BLOCKED: "skip" }[result.status] || "none";
      }
      states.set(step.id, { state: value, result });
    }
    return states;
  }

  function stepDetail(stepId, job) {
    const review = ((job || {}).result || {}).review;
    if (!review) return null;
    if (stepId === "classify_rules" || stepId === "classify") {
      return `กฎเสนอ: ${CATEGORY[review.suggested_category] || review.suggested_category}`;
    }
    if (stepId === "classify_llm") {
      const second = review.second_opinion;
      if (!second) return null;
      return second.status === "ok"
        ? `AI: ${CATEGORY[second.category] || second.category} · มั่นใจ${CONFIDENCE[second.confidence] || second.confidence}`
        : "AI ใช้งานไม่ได้ จึงใช้กฎอย่างเดียว";
    }
    if (stepId === "compare") {
      return { agree: "ตรงกัน", disagree: "ไม่ตรงกัน → ยกให้ดูก่อน", llm_unavailable: "เทียบไม่ได้ (AI ใช้งานไม่ได้)" }[review.agreement] || null;
    }
    if (stepId === "prepare") return `→ ${QUEUE[review.suggested_queue] || review.suggested_queue}`;
    return null;
  }

  function stepMark(info, step) {
    const result = info.result;
    switch (info.state) {
      case "done": return `✓ ${result.attempts}/${result.max_attempts}`;
      case "fail": return `✕ ${result.attempts}/${result.max_attempts}`;
      case "skip": return "ข้าม";
      case "none": return "—";
      case "pending": return "รอ";
      case "working": return "…";
      default: return "";  // a preview: the node's own line already says the time limit and tries
    }
  }

  function levels(plan) {
    const byId = new Map(plan.map((step) => [step.id, step]));
    const depth = new Map();
    const visit = (id, trail) => {
      if (depth.has(id)) return depth.get(id);
      if (trail.has(id)) return 0;
      trail.add(id);
      const deps = ((byId.get(id) || {}).depends_on || []).filter((dep) => byId.has(dep));
      const value = deps.length ? 1 + Math.max(...deps.map((dep) => visit(dep, trail))) : 0;
      depth.set(id, value);
      return value;
    };
    plan.forEach((step) => visit(step.id, new Set()));
    const rows = [];
    plan.forEach((step) => { (rows[depth.get(step.id)] = rows[depth.get(step.id)] || []).push(step); });
    return rows.filter(Boolean);
  }

  // ---------- render: everything -----------------------------------------------------------

  function renderAll() {
    renderHeader();
    renderSidebar();
    renderThread();
    renderFlow();
  }

  function statusTag(job) {
    const kind = { QUEUED: "tag-neutral", RUNNING: "tag-accent", REVIEW_REQUIRED: "tag-warn", COMPLETED: "tag-ok",
      FAILED: "tag-err", DELIVERY_FAILED: "tag-err", CANCELLED: "tag-neutral" }[job.status] || "tag-neutral";
    return el("span", { class: "tag " + kind }, [job.status === "RUNNING" ? el("span", { class: "dot blink" }) : null,
      STATUS[job.status] || job.status]);
  }

  function renderHeader() {
    const subtitle = [];
    let title = "เคสใหม่";
    if (state.view === "settings") {
      title = "ตั้งค่า";
      subtitle.push(el("span", { class: "tag tag-neutral", text: "ดูอย่างเดียว" }));
    } else if (state.draft) {
      subtitle.push(el("span", { class: "tag tag-warn", text: "รอยืนยันก่อนส่ง" }));
    } else if (state.job) {
      title = state.job.case_id;
      subtitle.push(statusTag(state.job));
      if (state.job.review_priority === "elevated") subtitle.push(el("span", { class: "tag tag-elev", text: "ยกให้ดูก่อน" }));
      subtitle.push(el("span", { class: "mono", text: state.job.job_id }));
    } else if (state.selectedId) {
      title = "กำลังโหลดเคส…";
    } else {
      subtitle.push("พิมพ์ปัญหาของลูกค้าในช่องด้านล่าง");
    }
    $("title").textContent = title;
    $("subtitle").replaceChildren(...subtitle);
    document.title = (state.job && state.view === "chat" && !state.draft ? state.job.case_id + " · " : "") + "Neuron Flow";
  }

  // ---------- render: thread (middle) ------------------------------------------------------

  function botMsg(children, extra) {
    return el("div", { class: "msg-bot" + (extra ? " " + extra : "") }, [
      el("div", { class: "avatar", "aria-hidden": "true", text: "N" }),
      el("div", { class: "msg-body" }, children),
    ]);
  }

  /* What the thread shows ("identity") and the data it was drawn from ("version"). The thread is only
   * redrawn when one of them changes, so polling never resets an open section or the scroll position. */
  function threadIdentity() {
    if (state.draft) return "d" + state.draft.id;
    if (state.job) return "j" + state.job.job_id;
    if (state.selectedId) return "l" + state.selectedId;
    return "w";
  }

  function threadVersion() {
    if (state.draft) return JSON.stringify([state.draft.sending, state.draft.error]);
    if (state.job) {
      const job = state.job;
      return JSON.stringify([job.status, job.queue_position, job.claims, job.updated_at,
        Boolean(state.last && state.last.jobId === job.job_id), state.cancelAsk === job.job_id, state.cancelling]);
    }
    const status = state.status || {};
    return JSON.stringify([status.storage, status.ai, defaultWorkflow(), Boolean(workflowInfo(defaultWorkflow()))]);
  }

  function renderThread(force) {
    const identity = threadIdentity();
    const key = identity + "|" + threadVersion();
    if (!force && key === state.keys.thread) return;
    const thread = $("thread");
    const atBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 48;
    const moved = !state.keys.thread || !state.keys.thread.startsWith(identity + "|");
    state.keys.thread = key;
    let parts;
    if (state.draft) parts = draftView(state.draft);
    else if (state.job) parts = jobView(state.job);
    else if (state.selectedId) parts = [botMsg([el("p", { class: "progress-line" }, [el("span", { class: "spinner" }), "กำลังโหลดเคส…"])])];
    else parts = welcomeView();
    thread.replaceChildren(...parts.filter(Boolean));
    if (moved) thread.scrollTop = state.draft ? thread.scrollHeight : 0;  // a draft ends with its confirm buttons
    else if (atBottom && thread.scrollTop > 0) thread.scrollTop = thread.scrollHeight;
  }

  function howItWorks() {
    const details = el("details", { class: "how", open: state.howOpen }, [
      el("summary", { text: "ระบบทำงานอย่างไร (อ่านแบบภาษาธรรมดา)" }),
      el("ol", {}, [
        el("li", {}, [el("b", { text: "ตรวจก่อนรับ " }), "ระบบตรวจข้อความเคสก่อน ถ้าสั้นไปหรือข้อมูลไม่ครบ จะบอกทันทีโดยยังไม่เริ่มงานใด ๆ"]),
        el("li", {}, [el("b", { text: "บันทึกลงคิวถาวรก่อนตอบ " }), "ระบบตอบว่า \"รับแล้ว\" หลังบันทึกเสร็จเท่านั้น ถ้ากดส่งซ้ำด้วยรหัสส่งงานเดิม ระบบรู้ว่าเป็นเคสเดิม ไม่สร้างงานซ้ำ"]),
        el("li", {}, [el("b", { text: "ตัวรันงานมีตัวเดียว " }), "หยิบเคสตามลำดับที่ส่งเข้ามา ส่งให้แกนระบบ (Core) ทำทีละขั้น และตรวจผลทุกขั้นก่อนบันทึก"]),
        el("li", {}, [el("b", { text: "กฎเดิมกับ AI ทำคู่กัน " }), "กฎเดิมเป็นข้อเสนอหลัก AI ให้ความเห็นที่สอง ถ้าไม่ตรงกัน เคสจะถูกยกให้คนดูก่อน"]),
        el("li", {}, [el("b", { text: "เครื่องดับกลางทางก็ไม่หาย " }), "เมื่อระบบเปิดใหม่ ตัวรันงานจะทำเคสที่ค้างต่อจากเดิม และนับจำนวนครั้งที่ลองตามงบเดิม"]),
        el("li", {}, [el("b", { text: "คนตัดสินเสมอ " }), "ผลสุดท้ายคือ \"รอคนตรวจ\" AI เสนอได้ ระบบตรวจ แต่คนเป็นผู้ตัดสิน (ปุ่มตัดสินจะมาในรอบถัดไป)"]),
      ]),
    ]);
    details.addEventListener("toggle", () => { state.howOpen = details.open; });
    return details;
  }

  function welcomeView() {
    const status = state.status || {};
    const ai = status.ai || {};
    const info = workflowInfo(defaultWorkflow());
    const steps = (info && info.steps) || [];
    return [botMsg([
      el("p", { class: "msg-text" }, "สวัสดีครับ พิมพ์ปัญหาของลูกค้าเป็นภาษาธรรมดา ภาษาไทยหรืออังกฤษก็ได้ ในช่องด้านล่าง แล้วกดส่ง"),
      el("p", { class: "msg-text" }, ["ระบบจะแสดงขั้นตอนให้ดูก่อน เมื่อคุณ", el("span", { class: "hl", text: "กดยืนยัน" }),
        steps.length ? " เคสจะเข้าคิวและทำตามลำดับนี้" : " เคสจะเข้าคิวแล้วระบบจะเริ่มทำ"]),
      steps.length ? el("ol", { class: "msg-list" }, steps.map((step) => el("li", { text: stepName(step.id) }))) : null,
      el("p", { class: "msg-text" }, ["ผลสุดท้ายคือ ", el("span", { class: "hl", text: "\"รอคนตรวจ\"" }), " — AI เสนอได้ ระบบตรวจ แต่คนเป็นผู้ตัดสิน"]),
      status.storage && !status.storage.persistent
        ? el("p", { class: "notice", text: "ตอนนี้ใช้ที่เก็บชั่วคราว: เคสจะหายเมื่อระบบหลับ รีสตาร์ท หรืออัปเดต (Render แผนฟรี)" }) : null,
      ai.simulated ? el("p", { class: "muted", text: "AI ตอนนี้เป็น \"AI จำลอง\" (จับคำสำคัญ) ผลของมันไม่ใช่ความแม่นยำของ AI จริง" }) : null,
      el("p", { class: "muted", text: "ช่องนี้รับเฉพาะข้อความเคส ยังคุยถาม-ตอบเรื่องอื่นไม่ได้ (ช่องคุยภาษาธรรมดาอยู่ในแผนขั้นที่ 4)" }),
      howItWorks(),
    ])];
  }

  function runCard(options) {
    const { plan, states, workflow, tag, foot } = options;
    const numberOf = new Map((plan || []).map((step, i) => [step.id, pad(i + 1)]));
    let body;
    if (plan) {
      body = el("div", { class: "run-steps" }, plan.flatMap((step) => {
        const info = states ? states.get(step.id) : null;
        const deps = (step.depends_on || []).map((dep) => numberOf.get(dep) || dep);
        return [
          el("span", { class: "num", text: numberOf.get(step.id) }),
          el("span", { class: "name" }, [stepName(step.id), el("span", { class: "id", text: step.id }),
            deps.length ? el("span", { class: "deps", text: ` ← ${deps.join(", ")}` }) : null]),
          el("span", { class: "limit", text: `${limitText(step.timeout_s)} · ≤${step.max_attempts} ครั้ง` }),
          el("span", { class: "mark " + (info ? (info.state === "working" ? "running" : info.state === "none" ? "skip" : info.state) : "pending"),
            text: info ? stepMark(info, step) : "" }),
        ];
      }));
    } else {
      body = el("p", { class: "run-steps muted", text: "ยังแสดงขั้นตอนของงานนี้ไม่ได้" });
    }
    return el("div", { class: "run-card" }, [
      el("div", { class: "run-head" }, [el("span", { class: "run-cmd", text: "/run" }),
        el("span", { class: "run-name mono", text: workflow }), tag]),
      body,
      foot ? el("div", { class: "run-foot" }, foot) : null,
    ]);
  }

  function draftView(draft) {
    const workflow = draft.body.workflow_type;
    const info = workflowInfo(workflow);
    const plan = info && info.steps;
    const foot = [
      el("button", { type: "button", class: "btn btn-primary", dataset: { action: "confirm" }, disabled: draft.sending,
        text: draft.sending ? "กำลังส่ง…" : (draft.error ? "ส่งอีกครั้ง" : "ยืนยันและส่ง") }),
      el("button", { type: "button", class: "btn btn-ghost", dataset: { action: "edit" }, disabled: draft.sending, text: "แก้ข้อความ" }),
      el("button", { type: "button", class: "btn btn-quiet", dataset: { action: "cancel" }, disabled: draft.sending, text: "ยกเลิก" }),
      el("span", { class: "right", text: "ผลสุดท้ายต้องรอคนตรวจเสมอ" }),
      draft.error ? el("p", { class: "form-error", role: "alert", text: draft.error }) : null,
    ];
    return [
      el("div", { class: "msg-user", text: draft.body.input.summary }),
      el("div", { class: "msg-meta" }, [el("span", { class: "file-chip", text: draft.body.input.case_id }),
        draft.autoId ? el("span", { text: "รหัสเคสที่ระบบตั้งให้" }) : null]),
      botMsg([
        el("p", { class: "msg-text" }, [`จะส่งเคสนี้เข้าคิวงาน "${WORKFLOW[workflow] || workflow}"` +
          (plan ? ` ระบบจะทำ ${plan.length} ขั้นตอนตามนี้ แล้วรอคนตรวจ ` : " "),
          el("span", { class: "hl", text: "กดยืนยันก่อนจึงจะเริ่ม" })]),
        runCard({ plan, states: null, workflow, tag: el("span", { class: "tag tag-warn", text: "รอยืนยัน" }), foot }),
      ], "draft-msg"),
    ];
  }

  function introText(job) {
    switch (job.status) {
      case "QUEUED": return `รับเคสเข้าคิวแล้ว (บันทึกถาวรก่อนตอบ) · รอลำดับที่ ${job.queue_position || "-"}`;
      case "RUNNING": return job.claims > 1 ? "ตัวรันงานกำลังทำเคสนี้ต่อหลังระบบเปิดใหม่…" : "ตัวรันงานกำลังทำเคสนี้…";
      case "REVIEW_REQUIRED": return "ทำครบทุกขั้นแล้ว ข้อเสนอด้านล่างรอคนตรวจ — AI ไม่มีสิทธิ์ตัดสินเอง";
      case "COMPLETED": return "ทำครบทุกขั้นแล้ว";
      case "DELIVERY_FAILED": return "ทำครบทุกขั้น แต่บันทึกรายงานไม่สำเร็จ";
      case "CANCELLED": return "เคสนี้ถูกยกเลิกก่อนตัวรันงานหยิบไปทำ จึงไม่มีขั้นไหนถูกรัน และ AI ไม่ได้เห็นเคสนี้";
      default: return "เคสนี้ทำไม่สำเร็จ ดูเหตุผลด้านล่าง";
    }
  }

  function jobFoot(job) {
    if (job.status === "QUEUED") return [el("span", { class: "ok", text: "✓ บันทึกถาวรแล้ว" }), el("span", { class: "right", text: `รอลำดับที่ ${job.queue_position || "-"}` })];
    if (job.status === "RUNNING") return [el("span", { class: "ok", text: "✓ บันทึกถาวรแล้ว" }), el("span", { class: "right", text: "กำลังทำงาน…" })];
    if (job.status === "CANCELLED") return [el("span", { text: `ยกเลิกเมื่อ ${clockTime(job.finished_at)}` }), el("span", { class: "right", text: "ไม่ได้รัน" })];
    const took = job.started_at && job.finished_at ? seconds(job.started_at, job.finished_at) : null;
    const done = job.status === "REVIEW_REQUIRED" || job.status === "COMPLETED";
    return [
      el("span", { class: done ? "ok" : "", text: `${done ? "✓" : "✕"} ${done ? "เสร็จเมื่อ" : "จบเมื่อ"} ${clockTime(job.finished_at)}` }),
      el("span", { class: "right", text: took === null ? "" : `ใช้เวลา ${took.toFixed(1)} วินาที` }),
    ];
  }

  function verdict(job) {
    const review = (job.result || {}).review;
    if (job.status === "FAILED" || job.status === "DELIVERY_FAILED") {
      const failure = job.failure || {};
      const failed = (failure.failed_steps || []).map(stepName);
      return el("div", { class: "verdict failed" }, [
        el("div", { class: "label", text: "ผลของเคสนี้" }),
        el("div", { class: "big", text: STATUS[job.status] }),
        el("p", { text: FAILURE[failure.reason] || failure.reason || "" }),
        failed.length ? el("p", { text: `ขั้นที่ไม่สำเร็จ: ${failed.join(", ")}` }) : null,
      ]);
    }
    if (!review) return null;
    const elevated = review.review_priority === "elevated";
    return el("div", { class: "verdict" }, [
      el("div", { class: "label", text: "ระบบเสนอให้ส่งไปที่" }),
      el("div", { class: "big", text: QUEUE[review.suggested_queue] || review.suggested_queue }),
      el("span", { class: "tag " + (elevated ? "tag-elev" : "tag-ok"), text: elevated ? "ความสำคัญ: ยกให้คนดูก่อน" : "ความสำคัญ: ปกติ" }),
    ]);
  }

  function facts(job) {
    const result = job.result || {};
    const review = result.review;
    if (!review) return null;
    const rows = [];
    rows.push(["ข้อเสนอหลัก (จากกฎเดิม)", `${CATEGORY[review.suggested_category] || review.suggested_category} → ${QUEUE[review.suggested_queue] || review.suggested_queue}`]);
    const second = review.second_opinion;
    const who = aiLabel(result.ai);
    if (!second) rows.push(["ความเห็นที่สอง", "ไม่มี (โหมดกฎอย่างเดียว)"]);
    else if (second.status === "ok") {
      rows.push([`ความเห็นที่สอง (${who})`, el("span", {}, [
        `${CATEGORY[second.category] || second.category} · ความมั่นใจ${CONFIDENCE[second.confidence] || second.confidence}`,
        second.rationale ? el("q", { text: second.rationale }) : null,
      ])]);
    } else rows.push([`ความเห็นที่สอง (${who})`, "ใช้งานไม่ได้: " + (UNAVAILABLE[second.reason] || second.reason)]);
    const masked = (result.ai || {}).masked;
    if (masked && typeof masked === "object") {
      const found = Object.entries(masked).map(([kind, n]) => `${MASKED[kind] || kind} ${n}`);
      rows.push(["ปิดข้อมูลส่วนตัวก่อนส่งให้ AI", found.length
        ? `${found.join(" · ")} — AI เห็นเป็นป้ายแทน เช่น [PHONE]` : "ไม่พบรูปแบบที่ระบบปิดได้"]);
    }
    const agreement = {
      agree: "ตรงกัน ความสำคัญปกติ",
      disagree: "ไม่ตรงกัน ระบบจึงยกให้คนดูก่อน (ข้อเสนอหลักยังเป็นของกฎ)",
      llm_unavailable: "เทียบไม่ได้ เพราะ AI ใช้งานไม่ได้ จึงใช้ข้อเสนอของกฎ",
    }[review.agreement];
    if (agreement) rows.push(["ผลเทียบ", agreement]);
    const reasons = review.review_reasons || [];
    rows.push(["สิ่งที่ระบบบอกคนตรวจ", reasons.length
      ? el("span", { class: "reasons" }, reasons.map((code) => el("span", { class: "tag tag-elev", text: REASON[code] || code })))
      : "ไม่มีข้อสังเกต"]);
    rows.push(["การตัดสิน", review.decision === "PENDING_HUMAN_REVIEW"
      ? "รอคนตรวจ — AI เสนอได้อย่างเดียว (ปุ่มอนุมัติ/ไม่อนุมัติจะมาในรอบถัดไป)" : review.decision]);
    return el("dl", { class: "facts" }, rows.flatMap(([term, value]) => [el("dt", { text: term }), el("dd", {}, value)]));
  }

  function technical(job) {
    const result = job.result || {};
    const kv = [["รหัสงาน (job id)", job.job_id], ["ประเภทงาน", job.workflow_type],
      ["ตัวรันงานหยิบเคสนี้", `${job.claims} ครั้ง`], ["รับเข้าคิว", fullTime(job.created_at)],
      ["เริ่มทำ", fullTime(job.started_at)], ["เสร็จ", fullTime(job.finished_at)]];
    if (job.request_id) kv.splice(1, 0, ["รหัสคำขอที่ส่งเคสนี้ (request id)", job.request_id]);
    const ai = result.ai;
    if (ai) {
      kv.push(["AI ที่ใช้", `${ai.provider}/${ai.model}` + (ai.served_model && ai.served_model !== ai.model ? ` (ตอบโดย ${ai.served_model})` : "")]);
      kv.push(["prompt", `${ai.prompt_id}@${String(ai.prompt_sha256 || "").slice(0, 12)}`]);
      if (ai.redaction) kv.push(["กฎปิดข้อมูลส่วนตัว (redaction)", ai.redaction]);
      if (ai.usage) kv.push(["token (เข้า/ออก)", `${ai.usage.input_tokens}/${ai.usage.output_tokens}` + (ai.usage.estimated ? " (ประมาณ)" : "")]);
      if (typeof ai.latency_ms === "number") kv.push(["เวลาที่ AI ตอบ", `${Math.round(ai.latency_ms)} ms`]);
    }
    if (result.receipt) kv.push(["ใบรับผล (SHA-256)", `${result.receipt.sha256.slice(0, 16)}… · ${result.receipt.bytes} ไบต์`]);
    const details = el("details", { class: "tech", open: state.techOpen }, [
      el("summary", { text: "รายละเอียดเชิงเทคนิค" }),
      el("div", { class: "kv" }, kv.flatMap(([k, v]) => [el("span", { text: k }), el("span", { text: v })])),
    ]);
    details.addEventListener("toggle", () => { state.techOpen = details.open; });
    return details;
  }

  function jobView(job) {
    const plan = planFor(job);
    const states = plan ? stepStates(job, plan) : null;
    const body = [el("p", { class: "msg-text", text: introText(job) }),
      runCard({ plan, states, workflow: job.workflow_type, tag: statusTag(job), foot: jobFoot(job) })];
    if (job.status === "RUNNING") {
      body.push(el("p", { class: "progress-line" }, [el("span", { class: "spinner" }),
        "กฎเดิมกับ AI กำลังวิเคราะห์คู่กัน ผลของแต่ละขั้นจะขึ้นเมื่อเคสเสร็จ หน้านี้อัปเดตเอง"]));
    }
    body.push(verdict(job), facts(job));
    if (job.status === "QUEUED") body.push(cancelActions(job));
    if (state.last && state.last.jobId === job.job_id) {
      body.push(el("div", { class: "msg-actions" }, [
        el("button", { type: "button", class: "btn btn-secondary", dataset: { action: "resend" }, text: "ส่งซ้ำ (ทดสอบว่าไม่เกิดงานซ้ำ)" }),
      ]));
    }
    if (TERMINAL.has(job.status)) body.push(technical(job));
    return [
      el("div", { class: "msg-user", text: (job.input || {}).summary || "" }),
      el("div", { class: "msg-meta" }, [el("span", { class: "file-chip", text: job.case_id }),
        el("span", { text: `ส่งเมื่อ ${shortTime(job.created_at)}` })]),
      botMsg(body.filter(Boolean)),
    ];
  }

  /* Cancelling cannot be undone, so the first press only asks; the second press sends it. Only a case that
   * is still waiting has the button: once the Runner takes it, Core cannot stop it part-way. */
  function cancelActions(job) {
    if (state.cancelAsk !== job.job_id) {
      return el("div", { class: "msg-actions" }, [
        el("button", { type: "button", class: "btn btn-quiet", dataset: { action: "cancel-job" }, text: "ยกเลิกเคสนี้" }),
        el("span", { class: "hint", text: "ยกเลิกได้เฉพาะตอนที่ยังรอคิว" }),
      ]);
    }
    return el("div", { class: "msg-actions" }, [
      el("span", { class: "hint", text: "ยกเลิกแล้วเอากลับคืนไม่ได้ ถ้าต้องการส่งเคสนี้อีก ให้ส่งเป็นเคสใหม่" }),
      el("button", { type: "button", class: "btn btn-danger", dataset: { action: "cancel-job-confirm" }, disabled: state.cancelling,
        text: state.cancelling ? "กำลังยกเลิก…" : "ยืนยันยกเลิก" }),
      el("button", { type: "button", class: "btn btn-ghost", dataset: { action: "cancel-job-keep" }, disabled: state.cancelling, text: "ไม่ยกเลิก" }),
    ]);
  }

  async function cancelJob() {
    const job = state.job;
    if (!job || state.cancelling) return;
    state.cancelling = true;
    renderThread();
    let result;
    try {
      result = await call("POST", `/v1/jobs/${encodeURIComponent(job.job_id)}/cancel`, {});
    } catch (_) {
      result = null;
    }
    state.cancelling = false;
    state.cancelAsk = null;
    if (result && handleAccessProblem(result)) return;
    if (result && result.status === 200) {
      if (state.selectedId === job.job_id) state.job = result.data;  // no second "finished" toast from polling
      toast(`ยกเลิกเคส ${job.case_id} แล้ว`);
      refreshStatus();
      await refreshQueue();
    } else if (result && result.status === 409) {
      toast("ตัวรันงานหยิบเคสนี้ไปทำแล้ว จึงยกเลิกไม่ได้ ระบบจะทำเคสนี้ต่อจนจบ");
    } else {
      toast("ยกเลิกไม่สำเร็จ ลองอีกครั้ง");
    }
    renderAll();
    if (state.selectedId === job.job_id) {
      clearTimeout(state.jobTimer);
      await loadJob();
    }
  }

  // ---------- render: flow and trace (right) -----------------------------------------------

  function terminalTone(job, end) {
    if (!job) return ["", end ? "คนตัดสิน · AI ไม่มีสิทธิ์ตัดสินเอง" : "ส่งเคส → บันทึกลงคิวถาวร"];
    if (!end) {
      return job.status === "QUEUED" ? ["wait", `รับเข้าคิวแล้ว · รอลำดับที่ ${job.queue_position || "-"}`] : ["done", "รับเข้าคิว · บันทึกถาวรแล้ว"];
    }
    switch (job.status) {
      case "REVIEW_REQUIRED": return ["wait", "รอคนตรวจ · AI ไม่มีสิทธิ์ตัดสินเอง"];
      case "COMPLETED": return ["done", "เสร็จแล้ว"];
      case "FAILED": return ["fail", "ไม่มีข้อเสนอ (ไม่สำเร็จ)"];
      case "DELIVERY_FAILED": return ["fail", "บันทึกรายงานไม่สำเร็จ"];
      case "CANCELLED": return ["", "ยกเลิกแล้ว · ไม่มีขั้นไหนถูกรัน"];
      default: return ["", "คนตัดสิน · AI ไม่มีสิทธิ์ตัดสินเอง"];
    }
  }

  function renderFlow() {
    const job = state.draft ? null : state.job;
    const workflow = state.draft ? state.draft.body.workflow_type : null;
    const plan = job ? planFor(job) : (workflow ? (workflowInfo(workflow) || {}).steps || null : (state.selectedId ? null : planFor(null)));
    $("flow-sub").textContent = job ? job.case_id : (state.selectedId ? "" : "ตัวอย่างขั้นตอน");
    updateClock();
    $("trace-live").hidden = !(job && !TERMINAL.has(job.status));
    const key = JSON.stringify([job && [job.job_id, job.status, job.updated_at, job.queue_position], workflow,
      state.selectedId, plan && plan.map((step) => step.id)]);
    if (key === state.keys.flow) return;
    state.keys.flow = key;
    const graph = $("graph");
    const note = $("graph-note");
    graph.classList.toggle("running", Boolean(job && job.status === "RUNNING"));
    if (!plan) {
      state.graph = { nodes: new Map(), edges: [] };
      graph.replaceChildren(el("p", { class: "graph-empty", text: state.selectedId ? "กำลังโหลด…" : "ยังไม่มีข้อมูลขั้นตอน" }));
      note.textContent = "";
      renderStrip(null, null);
      return;
    }
    const states = stepStates(job, plan);
    const nodes = new Map();
    const edges = [];
    const startTone = terminalTone(job, false);
    const endTone = terminalTone(job, true);
    const start = el("div", { class: "terminal " + startTone[0], role: "listitem", text: startTone[1] });
    const end = el("div", { class: "terminal " + endTone[0], role: "listitem", text: endTone[1] });
    nodes.set("__start", start);
    nodes.set("__end", end);
    const used = new Set();
    const rows = levels(plan).map((row) => el("div", { class: "level", role: "none" }, row.map((step) => {
      const info = states.get(step.id);
      const deps = (step.depends_on || []).filter((dep) => plan.some((other) => other.id === dep));
      if (!deps.length) edges.push(["__start", step.id]);
      deps.forEach((dep) => { edges.push([dep, step.id]); used.add(dep); });
      let sub;
      if (info.state === "done") sub = stepDetail(step.id, job) || "สำเร็จ";
      else if (info.state === "fail") sub = ERROR_TYPE[info.result.error_type] || info.result.error_type || "ไม่สำเร็จ";
      else if (info.state === "skip") sub = "ข้าม เพราะขั้นก่อนหน้าไม่สำเร็จ";
      else if (info.state === "none") sub = "ไม่ได้รัน";
      else if (info.state === "working") sub = "กำลังทำงาน…";
      else sub = `หมดเวลา ${limitText(step.timeout_s)} · ลองได้ ${step.max_attempts} ครั้ง`;
      const cls = { working: "pending", none: "skip" }[info.state] || info.state;
      const node = el("div", { class: "node " + cls, role: "listitem", "aria-label": `${stepName(step.id)}: ${STEP_STATE[info.state]}. ${sub}` }, [
        el("div", { class: "node-top", "aria-hidden": "true" }, [el("span", { class: "node-agent", text: step.agent }),
          el("span", { class: "node-mark", text: stepMark(info, step) })]),
        el("div", { class: "node-title", "aria-hidden": "true", text: stepName(step.id) }),
        el("div", { class: "node-sub", "aria-hidden": "true", text: sub }),
      ]);
      nodes.set(step.id, node);
      return node;
    })));
    plan.filter((step) => !used.has(step.id)).forEach((step) => edges.push([step.id, "__end"]));
    state.graph = { nodes, edges, states, job };
    graph.replaceChildren(svgEl("svg", { class: "edges", "aria-hidden": "true", focusable: "false" }), start, ...rows, end);
    scheduleEdges();
    if (!job) note.textContent = workflow ? "ขั้นตอนที่จะรันเมื่อกดยืนยัน" : `ขั้นตอนที่จะรันเมื่อส่งเคส (${defaultWorkflow()})`;
    else if (job.status === "QUEUED") note.textContent = "บันทึกถาวรแล้ว รอตัวรันงานหยิบไปทำตามลำดับ";
    else if (job.status === "CANCELLED") note.textContent = "ยกเลิกก่อนเริ่มทำ ไม่มีขั้นไหนถูกรัน";
    else if (job.status === "RUNNING") note.textContent = "กำลังทำงาน — ระบบยังไม่ส่งความคืบหน้าทีละขั้นระหว่างรัน ผลของทุกขั้นจะขึ้นเมื่อเคสเสร็จ";
    else note.textContent = job.claims > 1 ? `ตัวรันงานหยิบเคสนี้ ${job.claims} ครั้ง (ทำต่อหลังระบบเปิดใหม่)` : "";
    renderStrip(plan, states);
  }

  let edgeFrame = 0;
  function scheduleEdges() {
    cancelAnimationFrame(edgeFrame);
    edgeFrame = requestAnimationFrame(drawEdges);
  }

  function drawEdges() {
    const graph = $("graph");
    const svg = graph.querySelector("svg.edges");
    if (!svg) return;
    const box = graph.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const { nodes, edges, states } = state.graph;
    const lit = (id) => id === "__start" ? Boolean(state.graph.job && state.graph.job.started_at)
      : Boolean(states && states.get(id) && states.get(id).state === "done");
    const paths = [];
    for (const [from, to] of edges) {
      const a = nodes.get(from);
      const b = nodes.get(to);
      if (!a || !b) continue;
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      const x1 = ra.left + ra.width / 2 - box.left;
      const y1 = ra.bottom - box.top;
      const x2 = rb.left + rb.width / 2 - box.left;
      const y2 = rb.top - box.top;
      const mid = (y1 + y2) / 2;
      paths.push(svgEl("path", { d: `M${x1.toFixed(1)},${y1.toFixed(1)} C${x1.toFixed(1)},${mid.toFixed(1)} ${x2.toFixed(1)},${mid.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`,
        class: lit(from) ? "lit" : null }));
    }
    svg.replaceChildren(...paths);
  }

  function updateClock() {
    const job = state.draft ? null : state.job;
    let text = "";
    if (job && job.started_at) text = stopwatch(seconds(job.started_at, job.finished_at));
    else if (job && job.status === "QUEUED") text = "รอคิว";
    else if (job && job.status === "CANCELLED") text = "ยกเลิกแล้ว";
    $("flow-time").textContent = text;
  }

  function renderStrip(plan, states) {
    const strip = $("flow-strip");
    if (!plan) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    const parts = [];
    plan.forEach((step, i) => {
      const info = states.get(step.id);
      const cls = { working: "running", none: "skip" }[info.state] || info.state;
      const mark = { done: "✓ ", fail: "✕ ", working: "… " }[info.state] || "";
      if (i) parts.push(el("span", { class: "strip-arrow", "aria-hidden": "true", text: "→" }));
      parts.push(el("span", { class: "strip-step " + cls, text: mark + (STEP_SHORT[step.id] || step.id) }));
    });
    parts.push(el("span", { class: "strip-open", text: "ดู Flow ›" }));
    strip.replaceChildren(...parts);
    strip.setAttribute("aria-label", "ขั้นตอน: " + plan.map((step) => `${stepName(step.id)} ${STEP_STATE[states.get(step.id).state]}`).join(", ") + " — เปิดดูรายละเอียด");
  }

  function resetTrace(jobId) {
    state.trace = { jobId, events: [], after: 0, loading: false };
    renderTrace();
  }

  async function loadTrace() {
    const trace = state.trace;
    if (!trace.jobId || trace.loading) return;
    trace.loading = true;
    try {
      for (let page = 0; page < 5; page += 1) {
        let result;
        try {
          result = await call("GET", `/v1/jobs/${encodeURIComponent(trace.jobId)}/events?after=${trace.after}&limit=100`);
        } catch (_) { break; }
        if (state.trace !== trace || result.status !== 200) break;
        trace.events = trace.events.concat(result.data.events || []);
        trace.after = result.data.next_after;
        if (!result.data.has_more) break;
      }
    } finally {
      trace.loading = false;
    }
    if (state.trace === trace) renderTrace();
  }

  function describeEvent(event) {
    const p = event.payload || {};
    const kind = event.kind || "";
    const base = { t: clockTime(event.at), raw: `${kind} ${JSON.stringify(p)}` };
    if (kind === "job.queued") return { ...base, lv: "info", msg: "รับเข้าคิว", k: [p.workflow_type, p.request_id].filter(Boolean).join(" · ") };
    if (kind === "job.cancelled") return { ...base, lv: "warn", msg: "ยกเลิกก่อนตัวรันงานหยิบไปทำ" };
    if (kind === "job.claimed") return { ...base, lv: "run", msg: `ตัวรันงานหยิบเคส (ครั้งที่ ${p.claim})` };
    if (kind === "job.recovering") return { ...base, lv: "warn", msg: `ทำต่อหลังระบบเปิดใหม่ (ครั้งที่ ${p.claim})` };
    if (kind.startsWith("step.")) {
      const outcome = kind.slice(5);
      const name = stepName(p.id);
      if (outcome === "succeeded") return { ...base, lv: "ok", msg: `${name} สำเร็จ · ลอง ${p.attempts}/${p.max_attempts}`, k: p.id };
      if (outcome === "failed") return { ...base, lv: "err", msg: `${name} ไม่สำเร็จ · ${ERROR_TYPE[p.error_type] || p.error_type || ""}`, k: p.id };
      if (outcome === "blocked") return { ...base, lv: "info", msg: `${name} ข้าม (ขั้นก่อนหน้าไม่สำเร็จ)`, k: p.id };
      return { ...base, lv: "info", msg: `${name}: ${outcome}`, k: p.id };
    }
    if (kind === "job.review_required") return { ...base, lv: "ok", msg: "เสร็จ · รอคนตรวจ" };
    if (kind === "job.completed") return { ...base, lv: "ok", msg: "เสร็จแล้ว" };
    if (kind === "job.failed") return { ...base, lv: "err", msg: `ไม่สำเร็จ · ${FAILURE_SHORT[p.reason] || p.reason || ""}` };
    if (kind === "job.delivery_failed") return { ...base, lv: "err", msg: "บันทึกรายงานไม่สำเร็จ" };
    return { ...base, lv: "info", msg: kind };
  }

  function renderTrace() {
    const trace = state.trace;
    const list = $("trace-list");
    const keepBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 32;
    const rows = trace.events.map(describeEvent)
      .filter((row) => state.traceFilter === "all" || row.lv === "err" || row.lv === "warn");
    list.replaceChildren(...rows.map((row) => el("li", { class: row.lv === "err" ? "err" : null, title: row.raw }, [
      el("span", { class: "t", text: row.t }),
      el("span", { class: "lv " + row.lv, text: LEVEL[row.lv] }),
      el("span", { class: "m" }, [row.msg, row.k ? el("span", { class: "k", text: row.k }) : null]),
    ])));
    const empty = $("trace-empty");
    empty.hidden = rows.length > 0;
    empty.textContent = !trace.jobId ? "เลือกเคสเพื่อดูประวัติ"
      : trace.events.length ? "ไม่มีเหตุการณ์ผิดพลาด" : "กำลังโหลดประวัติ…";
    if (keepBottom) list.scrollTop = list.scrollHeight;
  }

  // ---------- render: settings (read-only) -------------------------------------------------

  function panel(title, children, extra) {
    return el("section", { class: "panel" + (extra ? " " + extra : "") }, [el("h2", {}, title), ...children]);
  }

  function agentsPanel(status) {
    const workflows = status.workflows || [];
    const blocks = workflows.flatMap((workflow) => {
      const steps = workflow.steps || [];
      const head = el("h3", {}, [WORKFLOW[workflow.name] || workflow.description || workflow.name,
        el("span", { class: "mono muted", text: workflow.name }),
        workflow.name === status.default_workflow ? el("span", { class: "tag tag-accent", text: "ใช้กับเคสใหม่" }) : null]);
      const table = steps.length ? el("div", { class: "table-wrap" }, el("table", { class: "table" }, [
        el("thead", {}, el("tr", {}, ["ขั้นตอน", "ตัวทำงาน (agent)", "ต้องรอขั้น", "หมดเวลา", "ลองได้", "หน้าที่"].map((h) => el("th", { scope: "col", text: h })))),
        el("tbody", {}, steps.map((step) => el("tr", {}, [
          el("td", {}, [stepName(step.id), el("div", { class: "mono", text: step.id })]),
          el("td", { class: "mono", text: step.agent }),
          el("td", { text: (step.depends_on || []).length ? step.depends_on.map((dep) => STEP_SHORT[dep] || dep).join(", ") : "—" }),
          el("td", { text: limitText(step.timeout_s) }),
          el("td", { text: `${step.max_attempts} ครั้ง` }),
          el("td", {}, step.id === "classify_llm" ? el("span", { class: "tag tag-accent", text: ROLE[step.id] }) : (ROLE[step.id] || "")),
        ]))),
      ])) : el("p", { class: "lead", text: "แสดงขั้นตอนของงานนี้ไม่ได้" });
      return [head, table];
    });
    return panel("ขั้นตอนและตัวทำงาน (Agents)", [
      el("p", { class: "lead", text: "ตัวทำงานทุกตัวลงทะเบียนไว้ในโค้ด (trusted registry) เพิ่มหรือแก้จากหน้าเว็บไม่ได้ เมื่อเปลี่ยน AI หรือ prompt ระบบนับเป็นเวอร์ชันใหม่ และจะไม่รันเคสที่ค้างอยู่ต่อด้วยค่าใหม่โดยไม่บอก" }),
      ...blocks,
    ]);
  }

  function aiPanel(ai) {
    const provider = ai.provider === "mock" ? "AI จำลอง (mock) — จับคำสำคัญ ไม่ใช่ AI จริง"
      : ai.provider === "anthropic" ? "Claude (anthropic)" : (ai.provider || "—");
    return panel("AI ที่ใช้อยู่ (LLM provider)", [
      el("div", { class: "rows" }, [
        el("span", { text: "ผู้ให้บริการ" }), el("span", { text: provider }),
        el("span", { text: "รุ่น (model)" }), el("span", { class: "mono", text: ai.model || "—" }),
        el("span", { text: "สถานะ" }), ai.problem ? el("span", { class: "st-review", text: "ตั้งค่าไม่ครบ: " + ai.problem }) : el("span", { class: "st-done", text: "พร้อม" }),
        el("span", { text: "คีย์ (API key)" }), el("span", { text: "เก็บใน Render เท่านั้น หน้าเว็บนี้ไม่เห็นและไม่รับคีย์" }),
      ]),
      el("p", { class: "lead", text: "ถ้าจะเปลี่ยนเป็น Claude จริง (มีค่าใช้จ่าย เป็นการตัดสินใจของเจ้าของ):" }),
      el("ol", { class: "steps-howto" }, [
        el("li", { text: "เปิด Render → บริการ neuron-flow → แท็บ Environment" }),
        el("li", {}, ["เพิ่ม ", el("code", { text: "NEURON_FLOW_LLM_PROVIDER" }), " = ", el("code", { text: "anthropic" }), " และ ", el("code", { text: "ANTHROPIC_API_KEY" }), " (คีย์จาก Claude Console)"]),
        el("li", { text: "กด Save แล้วรอระบบรีสตาร์ท 1–2 นาที (แผนฟรี: เคสเก่าจะหาย)" }),
        el("li", { text: "กลับมาหน้านี้ ช่อง AI ต้องขึ้นว่า Claude" }),
      ]),
    ]);
  }

  function approvalPanel() {
    const policy = (on, title, desc, later) => el("div", { class: "policy" + (on ? " on" : "") + (later ? " later" : "") }, [
      el("span", { class: "radio", "aria-hidden": "true" }),
      el("div", {}, [el("div", { class: "p-title", text: title }), el("div", { class: "p-desc", text: desc })]),
    ]);
    return panel("การตัดสิน (การอนุมัติ)", [
      el("p", { class: "lead", text: "กติกานี้ล็อกไว้ในระบบ ไม่มีตัวเลือก \"ไม่ต้องถาม\"" }),
      policy(true, "ยืนยันก่อนส่งทุกเคส", "หน้าแชทแสดงขั้นตอนให้ดูก่อน แล้วค่อยส่งเข้าคิวเมื่อกดยืนยัน"),
      policy(true, "คนตัดสินทุกเคส", "ผลสุดท้ายคือ \"รอคนตรวจ\" AI เสนอได้อย่างเดียว ไม่มีสิทธิ์อนุมัติหรือเลือกคิวเอง"),
      policy(false, "ปุ่มอนุมัติ / ไม่อนุมัติ สำหรับผู้ตรวจ", "อยู่ในแผนขั้น 2.4 (ต้องมีรหัสผู้ใช้รายคนจากขั้น 2.1 ก่อน)", true),
    ]);
  }

  function systemPanel(status) {
    const runner = status.runner || {};
    const storage = status.storage || {};
    const limit = status.limits || {};
    const runnerText = runner.state === "blocked_config" ? "หยุดรอ: ตั้งค่า AI ไม่ครบ"
      : !runner.alive ? (runner.state === "unknown" ? "กำลังเริ่ม" : "ไม่ตอบ")
        : (runner.state === "running" ? "กำลังทำเคส" : "พร้อม") + (runner.heartbeat_age_s !== null && runner.heartbeat_age_s !== undefined ? ` · สัญญาณชีพล่าสุด ${runner.heartbeat_age_s} วินาทีก่อน` : "");
    return panel("ระบบและขีดจำกัด", [
      el("div", { class: "rows" }, [
        el("span", { text: "ตัวรันงาน (Runner)" }), el("span", { text: runnerText }),
        el("span", { text: "ที่เก็บข้อมูล" }), el("span", { text: storage.persistent ? "ถาวร" : "ชั่วคราว — เคสหายเมื่อระบบหลับ รีสตาร์ท หรืออัปเดต (Render แผนฟรี)" }),
        el("span", { text: "คิวรับได้สูงสุด" }), el("span", { text: `${limit.max_queued} เคสที่รออยู่` }),
        el("span", { text: "ส่งได้" }), el("span", { text: `${limit.submit_per_minute} ครั้งต่อนาที` }),
        el("span", { text: "ข้อความเคส" }), el("span", { text: `${limit.summary_min_chars}–${limit.summary_max_chars} ตัวอักษร` }),
        el("span", { text: "รุ่นของระบบ" }), el("span", { class: "mono", text: status.version || "—" }),
      ]),
      el("p", { class: "lead", text: "ใช้ข้อมูลสมมติเท่านั้น · ผลจาก \"AI จำลอง\" ไม่ใช่ความแม่นยำของ AI จริง" }),
    ]);
  }

  function renderSettings() {
    const status = state.status || {};
    const view = $("view-settings");
    const runner = status.runner || {};
    const key = JSON.stringify([status.ai, status.storage, status.limits, status.workflows, status.default_workflow,
      runner.state, runner.alive, Math.round((runner.heartbeat_age_s || 0) / 10), status.version]);
    if (view.dataset.key === key) return;
    view.dataset.key = key;
    view.replaceChildren(
      el("p", { class: "settings-intro", text: "ดูอย่างเดียว — ค่าเหล่านี้มาจากโค้ด (ผ่านการทดสอบและ PR) และจากแท็บ Environment ของ Render หน้าเว็บแก้ไม่ได้โดยตั้งใจ เพื่อไม่ให้ใครเปลี่ยนตัวทำงาน AI หรือคีย์จากหน้าเว็บ" }),
      agentsPanel(status),
      el("div", { class: "panel-grid" }, [aiPanel(status.ai || {}), approvalPanel()]),
      systemPanel(status),
    );
  }

  // ---------- views and panels -------------------------------------------------------------

  function setView(view) {
    const chat = view === "chat";
    if (state.view !== view) closePanels();
    state.view = view;
    $("app").classList.toggle("settings-mode", !chat);
    $("tab-chat").setAttribute("aria-selected", String(chat));
    $("tab-settings").setAttribute("aria-selected", String(!chat));
    $("tab-chat").tabIndex = chat ? 0 : -1;
    $("tab-settings").tabIndex = chat ? -1 : 0;
    $("view-chat").hidden = !chat;
    $("view-settings").hidden = chat;
    if (!chat) renderSettings();
    renderHeader();
  }

  function setExpanded(panelId, open) {
    const button = panelId === "sidebar" ? $("open-sidebar") : $("open-flow");
    button.setAttribute("aria-expanded", String(open));
  }

  function openPanel(panelId) {
    closePanels();
    $(panelId).classList.add("open");
    $("scrim").hidden = false;
    setExpanded(panelId, true);
    if (panelId === "flow") scheduleEdges();
    const close = $(panelId === "sidebar" ? "close-sidebar" : "close-flow");
    setTimeout(() => close.focus(), 30);
  }

  function closePanels() {
    let wasOpen = null;
    for (const id of ["sidebar", "flow"]) {
      if ($(id).classList.contains("open")) wasOpen = id;
      $(id).classList.remove("open");
      setExpanded(id, false);
    }
    $("scrim").hidden = true;
    return wasOpen;
  }

  function syncPanelsToWidth() {
    // A drawer opened on a small screen must not leave the scrim over a wide layout.
    if (window.innerWidth >= 900 && $("sidebar").classList.contains("open")) closePanels();
    if (window.innerWidth >= 1200 && $("flow").classList.contains("open")) closePanels();
    scheduleEdges();
  }

  // ---------- composer and sending ---------------------------------------------------------

  function randomToken(length) {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    const values = new Uint32Array(length);
    crypto.getRandomValues(values);
    return Array.from(values, (v) => alphabet[v % alphabet.length]).join("");
  }
  function newIdempotencyKey() {
    return "web-" + (crypto.randomUUID ? crypto.randomUUID() : randomToken(24));
  }
  function autoCaseId() {
    const now = new Date();
    const date = `${String(now.getFullYear()).slice(2)}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
    return `WEB-${date}-${randomToken(4)}`;
  }

  function updateCounter() {
    const { min, max } = limits();
    const length = $("case-summary").value.trim().length;
    const counter = $("summary-count");
    counter.textContent = `${length}/${max}`;
    counter.className = "counter" + (length > max || (length > 0 && length < min) ? " over" : "");
  }

  function autoGrow() {
    const area = $("case-summary");
    area.style.height = "auto";  // CSSOM, allowed by the Content-Security-Policy (no style attribute in markup)
    area.style.height = Math.min(area.scrollHeight + 2, Math.round(window.innerHeight * 0.4)) + "px";
  }

  function formError(message) {
    const node = $("case-error");
    node.hidden = !message;
    node.textContent = message || "";
  }

  function submitCase(event) {
    event.preventDefault();
    formError(null);
    const { min, max } = limits();
    const summary = $("case-summary").value.trim();
    const caseIdInput = $("case-id").value.trim();
    if (summary.length < min || summary.length > max) {
      formError(`ข้อความเคสต้องยาว ${min}–${max} ตัวอักษร (ตอนนี้ ${summary.length})`);
      $("case-summary").focus();
      return;
    }
    if (caseIdInput && !CASE_ID.test(caseIdInput)) {
      formError("รหัสเคสใช้ได้เฉพาะตัวอักษรอังกฤษ ตัวเลข ขีด (-) หรือขีดล่าง (_) และต้องขึ้นต้นด้วยตัวอักษรหรือตัวเลข");
      showCaseIdField(true);
      $("case-id").focus();
      return;
    }
    clearSelection();
    draftCounter += 1;
    state.draft = {
      id: draftCounter, autoId: !caseIdInput, sending: false, error: null,
      body: { workflow_type: defaultWorkflow(), idempotency_key: newIdempotencyKey(),
        input: { case_id: caseIdInput || autoCaseId(), summary } },
    };
    $("case-summary").value = "";
    $("case-id").value = "";
    showCaseIdField(false);
    updateCounter();
    autoGrow();
    setView("chat");
    renderAll();
    const confirm = $("thread").querySelector("[data-action=confirm]");
    if (confirm) confirm.focus({ preventScroll: true });
  }

  /* Sends a request body. Returns { ok, job } or { ok: false, message }. */
  async function send(body, isRepeat) {
    let result;
    try {
      result = await call("POST", "/v1/jobs", body);
    } catch (_) {
      return { ok: false, message: "ส่งไม่สำเร็จ เพราะติดต่อระบบไม่ได้ กด \"ส่งอีกครั้ง\" ได้เลย ถ้าครั้งก่อนไปถึงแล้ว ระบบจะไม่สร้างงานซ้ำ" };
    }
    if (handleAccessProblem(result)) return { ok: false, handled: true };
    if (result.status === 202 || result.status === 200) {
      const job = result.data;
      if (result.status === 202) toast(`รับเคส ${job.case_id} เข้าคิวแล้ว` + (job.queue_position ? ` · ลำดับที่ ${job.queue_position}` : ""));
      else toast(isRepeat ? "ส่งซ้ำแล้ว ระบบรู้ว่าเป็นเคสเดิม จึงไม่สร้างงานใหม่" : "ระบบมีเคสนี้อยู่แล้ว");
      return { ok: true, job };
    }
    const code = result.data.error;
    let message = API_ERROR[code] || result.data.message || `ระบบตอบกลับ ${result.status}`;
    if (code === "rate_limited") message += ` รอ ${result.data.retry_after_s || 60} วินาทีแล้วลองใหม่`;
    if (code === "invalid_input" && result.data.message) message += ` (${result.data.message})`;
    if (code === "internal_error" && result.data.request_id) message += ` · รหัสคำขอ (request id) ${result.data.request_id}`;
    return { ok: false, message };
  }

  async function confirmDraft() {
    const draft = state.draft;
    if (!draft || draft.sending) return;
    draft.sending = true;
    draft.error = null;
    renderThread();
    const outcome = await send(draft.body, false);
    if (state.draft !== draft) return;
    draft.sending = false;
    if (outcome.handled) return;
    if (!outcome.ok) {
      draft.error = outcome.message;
      renderThread();
      const retry = $("thread").querySelector("[data-action=confirm]");
      if (retry) retry.focus({ preventScroll: true });
      return;
    }
    state.draft = null;
    state.last = { jobId: outcome.job.job_id, body: draft.body };
    refreshStatus();
    await refreshQueue();
    await selectJob(outcome.job.job_id);
    $("thread").focus({ preventScroll: true });
  }

  async function resend() {
    const last = state.last;
    if (!last) return;
    const button = $("thread").querySelector("[data-action=resend]");
    if (button) button.disabled = true;
    const outcome = await send(last.body, true);
    if (button) button.disabled = false;
    if (outcome.handled) return;
    if (!outcome.ok) {
      toast(outcome.message);
      return;
    }
    await refreshQueue();
    if (outcome.job.job_id !== state.selectedId) await selectJob(outcome.job.job_id);
  }

  function editDraft() {
    const draft = state.draft;
    if (!draft) return;
    state.draft = null;
    $("case-summary").value = draft.body.input.summary;
    $("case-id").value = draft.autoId ? "" : draft.body.input.case_id;
    if (!draft.autoId) showCaseIdField(true);
    updateCounter();
    autoGrow();
    renderAll();
    $("case-summary").focus();
  }

  function cancelDraft() {
    state.draft = null;
    renderAll();
    $("case-summary").focus();
  }

  function showCaseIdField(show) {
    $("case-id-field").hidden = !show;
    $("case-id-toggle").setAttribute("aria-expanded", String(show));
  }

  function newCase() {
    dropDraft(true);
    clearSelection();
    closePanels();
    setView("chat");
    renderAll();
    $("case-summary").focus();
  }

  // ---------- timers -----------------------------------------------------------------------

  async function refreshStatus() {
    try {
      const result = await call("GET", "/v1/status");
      if (!handleAccessProblem(result) && result.status === 200) applyStatus(result.data);
    } catch (_) { /* the regular refresh tries again */ }
  }

  async function refreshAll() {
    if (document.hidden || !state.key) return;
    try {
      const result = await call("GET", "/v1/status");
      if (handleAccessProblem(result)) return;
      if (result.status === 200) applyStatus(result.data);
      await refreshQueue();
      renderHeader();
      renderThread();
      renderFlow();
    } catch (_) {
      banner("ติดต่อระบบไม่ได้ กำลังลองใหม่…");
    }
  }

  function startTimers() {
    stopTimers();
    state.refreshTimer = setInterval(refreshAll, 4000);
  }

  function stopTimers() {
    clearInterval(state.refreshTimer);
    clearTimeout(state.jobTimer);
    state.refreshTimer = null;
  }

  // ---------- wiring -----------------------------------------------------------------------

  function bind() {
    $("gate-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const key = $("gate-key").value.trim();
      if (key.length < 16) {
        const error = $("gate-error");
        error.hidden = false;
        error.textContent = "รหัสเข้าใช้ยาวอย่างน้อย 16 ตัวอักษร";
        return;
      }
      state.key = key;
      saveKey(key, $("gate-remember").checked);
      $("gate-key").value = "";
      enter();
    });
    $("lock").addEventListener("click", () => {
      forgetKey();
      clearSelection();
      state.draft = null;
      state.last = null;
      state.jobs = [];
      state.keys = { thread: null, side: null, flow: null };
      showGate(null);
    });

    $("case-form").addEventListener("submit", submitCase);
    $("case-summary").addEventListener("input", () => { updateCounter(); autoGrow(); formError(null); });
    $("case-summary").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        submitCase(event);
      }
    });
    $("case-id-toggle").addEventListener("click", () => {
      const show = $("case-id-field").hidden;
      showCaseIdField(show);
      if (show) $("case-id").focus();
    });
    for (const chip of document.querySelectorAll("[data-example]")) {
      chip.addEventListener("click", () => {
        $("case-summary").value = chip.dataset.example;
        updateCounter();
        autoGrow();
        formError(null);
        $("case-summary").focus();
      });
    }

    $("thread").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) return;
      const action = button.dataset.action;
      if (action === "confirm") confirmDraft();
      else if (action === "edit") editDraft();
      else if (action === "cancel") cancelDraft();
      else if (action === "resend") resend();
      else if (action === "cancel-job") { state.cancelAsk = state.job ? state.job.job_id : null; renderThread(); }
      else if (action === "cancel-job-keep") { state.cancelAsk = null; renderThread(); }
      else if (action === "cancel-job-confirm") cancelJob();
    });

    $("job-list").addEventListener("click", (event) => {
      const row = event.target.closest("button.job");
      if (row) selectJob(row.dataset.id);
    });
    $("queue-more").addEventListener("click", () => refreshQueue(true));
    $("new-case").addEventListener("click", newCase);

    $("tab-chat").addEventListener("click", () => setView("chat"));
    $("tab-settings").addEventListener("click", () => setView("settings"));
    for (const tab of [$("tab-chat"), $("tab-settings")]) {
      tab.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const next = state.view === "chat" ? "settings" : "chat";
        setView(next);
        $(next === "chat" ? "tab-chat" : "tab-settings").focus();
      });
    }

    $("open-sidebar").addEventListener("click", () => openPanel("sidebar"));
    $("close-sidebar").addEventListener("click", () => { closePanels(); $("open-sidebar").focus(); });
    $("open-flow").addEventListener("click", () => openPanel("flow"));
    $("flow-strip").addEventListener("click", () => openPanel("flow"));
    $("close-flow").addEventListener("click", () => { closePanels(); $("open-flow").focus(); });
    $("scrim").addEventListener("click", () => closePanels());
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const was = closePanels();
      if (was) $(was === "sidebar" ? "open-sidebar" : "open-flow").focus();
    });

    for (const button of document.querySelectorAll(".seg-opt[data-filter]")) {
      button.addEventListener("click", () => {
        state.traceFilter = button.dataset.filter;
        for (const other of document.querySelectorAll(".seg-opt[data-filter]")) {
          other.setAttribute("aria-pressed", String(other === button));
        }
        renderTrace();
      });
    }

    if (window.ResizeObserver) new ResizeObserver(scheduleEdges).observe($("graph"));
    window.addEventListener("resize", syncPanelsToWidth);
    window.addEventListener("hashchange", () => {
      const jobId = location.hash.slice(1);
      if (state.key && JOB_ID.test(jobId) && jobId !== state.selectedId) selectJob(jobId);
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });
    setInterval(() => { if (state.job && !TERMINAL.has(state.job.status)) updateClock(); }, 250);
  }

  function start() {
    bind();
    updateCounter();
    state.key = loadKey();
    if (!state.key) {
      showGate(null);
      probeSetup();
      return;
    }
    enter();
  }

  document.addEventListener("DOMContentLoaded", start);
})();
