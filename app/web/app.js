"use strict";
/* Neuron Flow intake page. Plain JavaScript, no external requests: it only talks to this service's
 * own /v1 API. Server data is always inserted as text (never as HTML). The access key stays in
 * this browser (session storage, or local storage when "remember" is ticked). */
(function () {
  const KEY_STORAGE = "neuronflow.accessKey";
  const TERMINAL = new Set(["REVIEW_REQUIRED", "COMPLETED", "FAILED", "DELIVERY_FAILED"]);
  const CASE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;

  const STATUS = {
    QUEUED: "รอคิว", RUNNING: "กำลังทำงาน", REVIEW_REQUIRED: "รอคนตรวจ", COMPLETED: "เสร็จแล้ว",
    FAILED: "ไม่สำเร็จ", DELIVERY_FAILED: "บันทึกรายงานไม่สำเร็จ",
  };
  const CATEGORY = { access: "เข้าระบบ / บัญชี", upload: "อัปโหลดไฟล์", billing: "การเงิน / การชำระเงิน", other: "เรื่องอื่น ๆ" };
  const QUEUE = {
    access_review: "คิวตรวจเรื่องเข้าระบบ", upload_review: "คิวตรวจเรื่องอัปโหลด",
    billing_review: "คิวตรวจเรื่องการเงิน", general_review: "คิวตรวจทั่วไป",
  };
  const CONFIDENCE = { high: "สูง", medium: "กลาง", low: "ต่ำ" };
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
    step_failed: "มีขั้นตอนที่ทำไม่สำเร็จ ดูรายละเอียดเชิงเทคนิคด้านล่าง",
    configuration_changed: "ตั้งค่า AI หรือ prompt ถูกเปลี่ยนหลังรับเคส ระบบจึงไม่รันต่อด้วยค่าใหม่โดยไม่บอก ส่งเคสใหม่ได้เลย",
    runner_attempts_exhausted: "ตัวรันงานหยุดกลางคันระหว่างทำเคสนี้หลายครั้ง ระบบจึงพักเคสนี้ไว้ไม่ให้วนซ้ำ",
    runtime_error: "ระบบขัดข้องระหว่างทำงาน (แจ้งเตือนไปที่ระบบติดตามข้อผิดพลาดแล้ว ถ้าตั้งค่าไว้)",
    delivery_failed: "ทำงานครบทุกขั้น แต่บันทึกรายงานไม่สำเร็จ เพราะมีรายงานเดิมที่ไม่ตรงกัน",
    unknown_workflow_type: "ระบบไม่รู้จักประเภทงานนี้แล้ว",
  };
  const STEP = {
    classify_rules: "กฎเดิมจัดหมวด", classify_llm: "AI ให้ความเห็นที่สอง", compare: "เทียบสองความเห็น",
    prepare: "เตรียมข้อเสนอให้คนตรวจ", classify: "กฎจัดหมวด",
  };
  const STEP_STATUS = {
    SUCCEEDED: "สำเร็จ", FAILED: "ไม่สำเร็จ", BLOCKED: "ข้าม เพราะขั้นก่อนหน้าไม่สำเร็จ",
    PENDING: "ยังไม่เริ่ม", RUNNING: "กำลังทำ", RETRY_WAIT: "รอลองใหม่",
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
    idempotency_conflict: "รหัสส่งงานนี้เคยใช้กับเคสอื่นแล้ว กด \"ส่งเคสเข้าคิว\" อีกครั้งเพื่อสร้างงานใหม่",
    queue_full: "คิวเต็มแล้ว รอสักครู่แล้วลองใหม่",
    rate_limited: "ส่งถี่เกินไป",
    body_too_large: "ข้อความยาวเกินไป",
  };

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
    for (const child of [].concat(children || [])) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const state = {
    key: null, status: null, jobs: [], nextBefore: null,
    selectedId: null, selectedJob: null, pending: null,
    refreshTimer: null, jobTimer: null,
  };

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
    $("app").hidden = true;
    $("system").hidden = true;
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
    $("system").hidden = false;
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
    startTimers();
  }

  async function probeSetup() {
    try {
      const result = await call("GET", "/healthz");
      if (result.status === 200 && result.data.access_key === "not_configured") showGate(null, true);
    } catch (_) { /* the gate stays as it is */ }
  }

  // ---------- status -----------------------------------------------------------------------

  function setPill(id, text, kind, title) {
    const node = $(id);
    node.textContent = text;
    node.className = "pill" + (kind ? " " + kind : "");
    if (title) node.title = title; else node.removeAttribute("title");
  }

  function aiLabel(ai) {
    if (!ai || !ai.provider) return "AI";
    if (ai.provider === "mock") return "AI จำลอง";
    if (ai.provider === "anthropic") return `Claude (${ai.model})`;
    return `${ai.provider}/${ai.model}`;
  }

  function applyStatus(status) {
    state.status = status;
    const runner = status.runner || {};
    if (runner.state === "blocked_config") {
      setPill("pill-runner", "ตัวรันงาน: หยุดรอ ตั้งค่า AI ไม่ครบ", "warn", runner.detail);
      banner(`ตัวรันงานหยุดรอ เพราะตั้งค่า AI ไม่ครบ: ${runner.detail || ""} เคสที่ส่งจะรออยู่ในคิวจนกว่าจะแก้`, "warn");
    } else if (!runner.alive) {
      setPill("pill-runner", runner.state === "unknown" ? "ตัวรันงาน: กำลังเริ่ม" : "ตัวรันงาน: ไม่ตอบ", "bad",
        "ตัวรันงานไม่ส่งสัญญาณชีพ เคสใหม่ยังรับเข้าคิวได้ และจะถูกทำเมื่อตัวรันงานกลับมา");
      banner(null);
    } else {
      setPill("pill-runner", runner.state === "running" ? "ตัวรันงาน: กำลังทำเคส" : "ตัวรันงาน: พร้อม",
        runner.state === "running" ? "busy" : "ok");
      banner(null);
    }
    const ai = status.ai || {};
    if (ai.problem) setPill("pill-ai", "AI: ตั้งค่าไม่ครบ", "warn", ai.problem);
    else if (ai.simulated) setPill("pill-ai", "AI จำลอง (ไม่ใช่ AI จริง)", "", "ตัวจำลองแบบคำสำคัญ ใช้ทดสอบระบบโดยไม่เสียค่า API");
    else setPill("pill-ai", "AI: " + aiLabel(ai), "ok");
    const storage = status.storage || {};
    if (storage.persistent) setPill("pill-storage", storage.kind === "railway_volume" ? "ที่เก็บถาวร: Railway volume" : "ที่เก็บถาวร", "ok");
    else setPill("pill-storage", "ที่เก็บชั่วคราว: เคสหายเมื่อระบบหลับหรือรีสตาร์ท", "warn",
      "ยังไม่มีดิสก์ถาวร (Render แบบฟรีไม่มีดิสก์) ระบบยังทำงานครบทุกขั้น แต่เคสเก่าจะหายเมื่อระบบหลับหรือรีสตาร์ท");
    const limits = status.limits || {};
    if (limits.summary_max_chars) $("case-summary").maxLength = limits.summary_max_chars;
    if (limits.summary_min_chars) $("summary-hint").textContent = `อย่างน้อย ${limits.summary_min_chars} ตัวอักษร`;
    updateCounter();
    renderCounts(status.queue || {});
  }

  function renderCounts(queue) {
    const items = [
      ["QUEUED", "รอคิว", queue.QUEUED], ["RUNNING", "กำลังทำ", queue.RUNNING],
      ["REVIEW_REQUIRED", "รอคนตรวจ", queue.REVIEW_REQUIRED],
      ["FAILED", "ไม่สำเร็จ", (queue.FAILED || 0) + (queue.DELIVERY_FAILED || 0)],
    ];
    if (queue.COMPLETED) items.push(["COMPLETED", "เสร็จแล้ว", queue.COMPLETED]);
    $("counts").replaceChildren(...items.map(([cls, label, n]) => el("span", { class: "badge " + cls, text: `${label} ${n || 0}` })));
  }

  // ---------- queue list -------------------------------------------------------------------

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
    renderQueue();
  }

  function shortTime(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
  }
  function fullTime(iso) {
    return iso ? new Date(iso).toLocaleString("th-TH") : "—";
  }

  function statusBadge(status) {
    return el("span", { class: "badge " + status, text: STATUS[status] || status });
  }

  function renderQueue() {
    const list = $("queue");
    list.replaceChildren(...state.jobs.map((job) => {
      const badges = [];
      if (job.review_priority === "elevated") badges.push(el("span", { class: "badge elevated", text: "ยกให้ดูก่อน" }));
      badges.push(statusBadge(job.status));
      const row = el("button", {
        type: "button", class: "row" + (job.job_id === state.selectedId ? " selected" : ""),
        dataset: { id: job.job_id }, "aria-label": `${job.case_id} ${STATUS[job.status] || job.status}`,
      }, [
        el("span", { class: "time", text: shortTime(job.created_at) }),
        el("span", { class: "case", text: job.case_id }),
        el("span", { class: "preview", text: job.summary_preview }),
        el("span", { class: "badges" }, badges),
      ]);
      return el("li", {}, row);
    }));
    $("queue-empty").hidden = state.jobs.length > 0;
    $("queue-more").hidden = !state.nextBefore;
  }

  // ---------- one job ----------------------------------------------------------------------

  async function selectJob(jobId, reveal) {
    state.selectedId = jobId;
    renderQueue();
    clearTimeout(state.jobTimer);
    await loadJob();
    if (reveal) revealJob();
  }

  function revealJob() {
    // On narrow screens the job card sits far from the form and the queue: bring it into view.
    const card = $("job-card");
    const top = card.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      card.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }
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
    if (result.status !== 200) return;
    const job = result.data;
    const changed = !state.selectedJob || state.selectedJob.job_id !== job.job_id ||
      state.selectedJob.status !== job.status || state.selectedJob.queue_position !== job.queue_position;
    state.selectedJob = job;
    if (changed) renderJob(job);
    if (!TERMINAL.has(job.status)) state.jobTimer = setTimeout(loadJob, 1000);
    else {
      const index = state.jobs.findIndex((item) => item.job_id === job.job_id);
      if (index >= 0 && state.jobs[index].status !== job.status) refreshQueue();
    }
  }

  function seconds(fromIso, toIso) {
    if (!fromIso || !toIso) return null;
    return Math.max(0, (new Date(toIso) - new Date(fromIso)) / 1000);
  }

  function agreementShort(review) {
    if (!review || review.agreement === null || review.agreement === undefined) return "โหมดกฎอย่างเดียว";
    return { agree: "ตรงกัน", disagree: "ไม่ตรงกัน → ยกให้ดูก่อน", llm_unavailable: "AI ใช้งานไม่ได้ ใช้กฎอย่างเดียว" }[review.agreement] || review.agreement;
  }

  function stages(job) {
    const result = job.result || {};
    const review = result.review;
    const shadow = job.workflow_type === "case_triage.v2";
    const titles = ["รับเข้าคิว", shadow ? "กฎเดิม + AI วิเคราะห์" : "กฎวิเคราะห์", shadow ? "เทียบสองความเห็น" : "สรุปข้อเสนอ", "รอคนตัดสิน"];
    const status = job.status;
    let rows;
    if (status === "QUEUED") {
      rows = [["active", `รอลำดับที่ ${job.queue_position || "-"}`], ["", "ยังไม่เริ่ม"], ["", "ยังไม่เริ่ม"], ["", "ยังไม่เริ่ม"]];
    } else if (status === "RUNNING") {
      rows = [["done", "บันทึกถาวรแล้ว"], ["active", job.claims > 1 ? "กำลังทำต่อหลังระบบเปิดใหม่…" : "กำลังทำงาน…"], ["", "รอผลวิเคราะห์"], ["", "รอผลวิเคราะห์"]];
    } else if (status === "FAILED") {
      rows = [["done", "บันทึกถาวรแล้ว"], ["fail", "ไม่สำเร็จ"], ["", "ข้าม"], ["", "ไม่มีข้อเสนอ"]];
    } else if (status === "DELIVERY_FAILED") {
      rows = [["done", "บันทึกถาวรแล้ว"], ["done", "ทำครบ"], ["done", "ทำครบ"], ["fail", "บันทึกรายงานไม่สำเร็จ"]];
    } else {
      const took = seconds(job.started_at, job.finished_at);
      rows = [["done", "บันทึกถาวรแล้ว"], ["done", took === null ? "เสร็จแล้ว" : `ใช้เวลา ${took.toFixed(1)} วินาที`],
        ["done", agreementShort(review)],
        status === "REVIEW_REQUIRED" ? ["wait", "AI ไม่มีสิทธิ์ตัดสินเอง"] : ["done", "เสร็จแล้ว"]];
    }
    return el("ol", { class: "stepper", "aria-label": "ขั้นตอนของเคสนี้" }, rows.map(([cls, sub], i) =>
      el("li", { class: cls }, [el("span", { class: "n", text: String(i + 1) }), el("span", { class: "t", text: titles[i] }), el("span", { class: "s", text: sub })])));
  }

  function verdict(job) {
    const review = (job.result || {}).review;
    if (job.status === "FAILED" || job.status === "DELIVERY_FAILED") {
      const reason = (job.failure || {}).reason;
      return el("div", { class: "verdict failed" }, [
        el("div", { class: "label", text: "ผลของเคสนี้" }),
        el("div", { class: "big", text: STATUS[job.status] }),
        el("div", { text: FAILURE[reason] || reason || "" }),
      ]);
    }
    if (!review) return null;
    const elevated = review.review_priority === "elevated";
    return el("div", { class: "verdict" }, [
      el("div", { class: "label", text: "ระบบเสนอให้ส่งไปที่" }),
      el("div", { class: "big", text: QUEUE[review.suggested_queue] || review.suggested_queue }),
      el("span", { class: "badge " + (elevated ? "elevated" : "COMPLETED"), text: elevated ? "ความสำคัญ: ยกให้คนดูก่อน" : "ความสำคัญ: ปกติ" }),
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
    const agreement = {
      agree: "ตรงกัน ความสำคัญปกติ",
      disagree: "ไม่ตรงกัน ระบบจึงยกให้คนดูก่อน (ข้อเสนอหลักยังเป็นของกฎ)",
      llm_unavailable: "เทียบไม่ได้ เพราะ AI ใช้งานไม่ได้ จึงใช้ข้อเสนอของกฎ",
    }[review.agreement];
    if (agreement) rows.push(["ผลเทียบ", agreement]);
    const reasons = review.review_reasons || [];
    rows.push(["สิ่งที่ระบบบอกคนตรวจ", reasons.length
      ? el("span", { class: "reasons" }, reasons.map((code) => el("span", { class: "reason", text: REASON[code] || code })))
      : "ไม่มีข้อสังเกต"]);
    rows.push(["การตัดสิน", review.decision === "PENDING_HUMAN_REVIEW"
      ? "รอคนตรวจ — AI เสนอได้อย่างเดียว (ปุ่มอนุมัติ/ปฏิเสธจะมาในรอบถัดไป)" : review.decision]);
    return el("dl", { class: "facts" }, rows.flatMap(([term, value]) => [el("dt", { text: term }), el("dd", {}, value)]));
  }

  function technical(job) {
    const result = job.result || {};
    const children = [el("summary", { text: "รายละเอียดเชิงเทคนิค" })];
    const steps = result.steps || [];
    if (steps.length) {
      children.push(el("table", {}, [
        el("thead", {}, el("tr", {}, ["ขั้นตอน", "ผล", "ครั้งที่ลอง", "หมายเหตุ"].map((h) => el("th", { text: h })))),
        el("tbody", {}, steps.map((step) => el("tr", {}, [
          el("td", {}, [STEP[step.id] || step.id, el("div", { class: "mono muted", text: step.agent })]),
          el("td", { text: STEP_STATUS[step.status] || step.status }),
          el("td", { text: `${step.attempts}/${step.max_attempts}` }),
          el("td", { text: step.error_type ? (ERROR_TYPE[step.error_type] || step.error_type) : "" }),
        ]))),
      ]));
    }
    const kv = [["รหัสงาน (job id)", job.job_id], ["ประเภทงาน", job.workflow_type],
      ["ตัวรันงานหยิบเคสนี้", `${job.claims} ครั้ง`], ["รับเข้าคิว", fullTime(job.created_at)],
      ["เริ่มทำ", fullTime(job.started_at)], ["เสร็จ", fullTime(job.finished_at)]];
    const ai = result.ai;
    if (ai) {
      kv.push(["AI ที่ใช้", `${ai.provider}/${ai.model}` + (ai.served_model && ai.served_model !== ai.model ? ` (ตอบโดย ${ai.served_model})` : "")]);
      kv.push(["prompt", `${ai.prompt_id}@${String(ai.prompt_sha256 || "").slice(0, 12)}`]);
      if (ai.usage) kv.push(["token (เข้า/ออก)", `${ai.usage.input_tokens}/${ai.usage.output_tokens}` + (ai.usage.estimated ? " (ประมาณ)" : "")]);
      if (typeof ai.latency_ms === "number") kv.push(["เวลาที่ AI ตอบ", `${Math.round(ai.latency_ms)} ms`]);
    }
    if (result.receipt) kv.push(["ใบรับผล (SHA-256)", `${result.receipt.sha256.slice(0, 16)}… · ${result.receipt.bytes} ไบต์`]);
    children.push(el("div", { class: "kv" }, kv.flatMap(([k, v]) => [el("span", { text: k }), el("span", { text: v })])));
    const events = el("div", { class: "events" });
    children.push(el("h3", { class: "events-title", text: "ประวัติเหตุการณ์ (events)" }), events);
    const details = el("details", { class: "tech" }, children);
    details.addEventListener("toggle", () => { if (details.open) loadEvents(job.job_id, events); });
    return details;
  }

  async function loadEvents(jobId, container) {
    container.replaceChildren(el("p", { class: "muted", text: "กำลังโหลด…" }));
    let events = [];
    let after = 0;
    for (let page = 0; page < 5; page += 1) {
      const result = await call("GET", `/v1/jobs/${encodeURIComponent(jobId)}/events?after=${after}&limit=100`).catch(() => null);
      if (!result || result.status !== 200) break;
      events = events.concat(result.data.events || []);
      after = result.data.next_after;
      if (!result.data.has_more) break;
    }
    container.replaceChildren(el("table", {}, el("tbody", {}, events.map((event) => el("tr", {}, [
      el("td", { class: "mono", text: shortTime(event.at) }),
      el("td", { class: "mono", text: event.kind }),
      el("td", { class: "mono muted", text: Object.entries(event.payload || {}).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ") }),
    ])))));
  }

  function renderJob(job) {
    $("job-empty").hidden = true;
    const box = $("job-detail");
    box.hidden = false;
    const parts = [
      el("div", { class: "job-head" }, [el("span", { class: "job-case", text: job.case_id }), statusBadge(job.status)]),
      el("div", { class: "job-meta", text: `ส่งเมื่อ ${fullTime(job.created_at)}` }),
      el("div", { class: "job-summary", text: (job.input || {}).summary || "" }),
      stages(job),
    ];
    if (job.status === "QUEUED") parts.push(el("p", { class: "muted", text: "เคสถูกบันทึกถาวรแล้ว ตัวรันงานจะหยิบไปทำตามลำดับที่ส่งเข้ามา" }));
    if (job.status === "RUNNING") parts.push(el("p", { class: "muted", text: "กฎเดิมกับ AI กำลังวิเคราะห์เคสนี้คู่กัน แล้วระบบจะเทียบผล หน้านี้อัปเดตเอง" }));
    parts.push(verdict(job), facts(job));
    if (TERMINAL.has(job.status)) parts.push(technical(job));
    box.replaceChildren(...parts.filter(Boolean));
  }

  // ---------- submit -----------------------------------------------------------------------

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
    const date = `${String(now.getFullYear()).slice(2)}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    return `WEB-${date}-${randomToken(4)}`;
  }

  function limits() {
    const limit = (state.status || {}).limits || {};
    return { min: limit.summary_min_chars || 8, max: limit.summary_max_chars || 500 };
  }

  function updateCounter() {
    const { min, max } = limits();
    const length = $("case-summary").value.trim().length;
    const counter = $("summary-count");
    counter.textContent = `${length}/${max}`;
    counter.className = length > max || (length > 0 && length < min) ? "over" : "";
  }

  function formError(message) {
    const node = $("case-error");
    node.hidden = !message;
    node.textContent = message || "";
  }

  async function submitCase(event) {
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
      $("case-id").focus();
      return;
    }
    const body = {
      workflow_type: (state.status || {}).default_workflow || "case_triage.v2",
      idempotency_key: newIdempotencyKey(),
      input: { case_id: caseIdInput || autoCaseId(), summary },
    };
    state.pending = body;
    await send(body, false);
  }

  async function send(body, isRepeat) {
    const button = $("case-submit");
    button.disabled = true;
    $("case-retry").disabled = true;
    try {
      let result;
      try {
        result = await call("POST", "/v1/jobs", body);
      } catch (_) {
        formError("ส่งไม่สำเร็จ เพราะติดต่อระบบไม่ได้ กด \"ส่งซ้ำ\" ได้เลย ถ้าครั้งก่อนไปถึงแล้ว ระบบจะไม่สร้างงานซ้ำ");
        $("case-retry").hidden = false;
        return;
      }
      if (handleAccessProblem(result)) return;
      if (result.status === 202 || result.status === 200) {
        const job = result.data;
        if (result.status === 202) {
          toast(`รับเคส ${job.case_id} เข้าคิวแล้ว` + (job.queue_position ? ` · ลำดับที่ ${job.queue_position}` : ""));
        } else {
          toast(isRepeat ? "ส่งซ้ำแล้ว ระบบรู้ว่าเป็นเคสเดิม จึงไม่สร้างงานใหม่" : "ระบบมีเคสนี้อยู่แล้ว");
        }
        $("case-retry").hidden = false;
        if (!isRepeat) $("case-id").value = "";
        await refreshQueue();
        await selectJob(job.job_id, true);
        return;
      }
      const code = result.data.error;
      let message = API_ERROR[code] || result.data.message || `ระบบตอบกลับ ${result.status}`;
      if (code === "rate_limited") message += ` รอ ${result.data.retry_after_s || 60} วินาทีแล้วลองใหม่`;
      if (code === "invalid_input" && result.data.message) message += ` (${result.data.message})`;
      formError(message);
    } finally {
      button.disabled = false;
      $("case-retry").disabled = false;
    }
  }

  // ---------- timers -----------------------------------------------------------------------

  async function refreshAll() {
    if (document.hidden || !state.key) return;
    try {
      const result = await call("GET", "/v1/status");
      if (handleAccessProblem(result)) return;
      if (result.status === 200) applyStatus(result.data);
      await refreshQueue();
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
      state.selectedId = null;
      state.selectedJob = null;
      showGate(null);
    });
    $("case-form").addEventListener("submit", submitCase);
    $("case-retry").addEventListener("click", () => { if (state.pending) send(state.pending, true); });
    $("case-summary").addEventListener("input", () => { updateCounter(); formError(null); });
    for (const chip of document.querySelectorAll("[data-example]")) {
      chip.addEventListener("click", () => {
        $("case-summary").value = chip.dataset.example;
        updateCounter();
        formError(null);
        $("case-summary").focus();
      });
    }
    $("queue").addEventListener("click", (event) => {
      const row = event.target.closest("button.row");
      if (row) selectJob(row.dataset.id, true);
    });
    $("queue-more").addEventListener("click", () => refreshQueue(true));
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });
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
