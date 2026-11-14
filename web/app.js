/* Entry kiosk — v2 attempt flow.
 * Plain JS, no build step, no dependencies.
 *
 *   tap name ─► POST /attempt/start ─► first frame ─► POST /identity (not awaited)
 *                                   └► 6 frames @170ms ─► POST /liveness (awaited) ─► result
 *   next_action: MOVE_CLOSER | HOLD_STILL | IMPROVE_LIGHT  → instruction + retry (new attempt)
 *                CHALLENGE  → /challenge/start, prompts, frames @5fps → POST /challenge → result
 *                RECEPTION  → "Please see reception"
 */

// ============================================================
// CONFIG
// ============================================================
const params = new URLSearchParams(location.search);

const CONFIG = {
  // The one flag. true = local mock (always REQUEST_VERIFICATION, never ALLOW). false = real backend.
  // URL override for quick switching: ?mock=0 or ?mock=1
  USE_MOCK: params.has("mock") ? params.get("mock") !== "0" : true,

  // "" = same origin as this page. URL override: ?api=http://localhost:8000
  API_BASE: params.get("api") || "",

  // Enrolled people shown as buttons on the welcome screen. `id` is sent as user_id.
  ENROLLED: [
    { id: "akash", name: "Akash" },
    { id: "siddanth", name: "Siddanth" },
    { id: "shesh", name: "Shesh" },
    { id: "siddhant", name: "Siddhant" },
  ],

  FRAME_MAX_WIDTH: 640,
  JPEG_QUALITY: 0.85,
  LIVENESS_FRAMES: 6,          // includes the first (identity) frame
  LIVENESS_SPACING_MS: 170,
  CHALLENGE_FPS: 5,
  CHALLENGE_BASELINE_MS: 400,
  CHALLENGE_ACTION_MS: 1500,   // used if /challenge/start doesn't give one
  CHALLENGE_LEAD_IN_MS: 900,   // how long the "one more check" card shows before the challenge starts

  RESULT_RESET_MS: 5000,       // back to welcome after a final result
  RETRY_RESET_MS: 10000,       // longer window when a "Try again" button is on screen
  REQUEST_TIMEOUT_MS: 8000,
};

// ============================================================
// API ADAPTER — the only place that knows request/response shapes. Follows CONTRACT.md "v2 attempt API".
//
//   POST /attempt/start                json {user_id, consent:true}  -> {attempt_id, server_t0_ms, deadline_ms}
//   POST /attempt/{id}/identity        multipart: frame, capture_ts_ms           (fired, never awaited)
//   POST /attempt/{id}/liveness        multipart: frames[], capture_ts_ms[]      -> Decision
//   POST /attempt/{id}/challenge/start                                -> {challenge_id, actions, baseline_ms, timeout_ms}
//   POST /attempt/{id}/challenge       multipart: frames[], capture_ts_ms[], prompt_ts_ms, challenge_id -> Decision (+ total_ms)
//
// Choices the contract leaves open (change here if the API disagrees):
//  - List fields are sent as repeated keys WITHOUT "[]" (`frames`, `capture_ts_ms`), which is what FastAPI's
//    `list[...] = File()/Form()` reads — same as the existing /verify. Set ARRAY_SUFFIX = "[]" to send `frames[]`.
//  - Timestamps are epoch ms (performance.timeOrigin + performance.now(): wall-clock, but monotonic within a page).
//  - prompt_ts_ms is a JSON array of epoch ms, one per action, aligned with `actions`. The 400ms baseline starts
//    at baseline_start_ts_ms (sent as an extra field).
//  - `scenario` (operator panel) is sent with EVERY request, including the /attempt/start JSON body.
// ============================================================
const ARRAY_SUFFIX = "";
const FRAMES_KEY = "frames" + ARRAY_SUFFIX;
const TS_KEY = "capture_ts_ms" + ARRAY_SUFFIX;
const enc = encodeURIComponent;

const realApi = {
  startAttempt: ({ user_id }) => postJson("/attempt/start", { user_id, consent: true, scenario: state.scenario }),

  identity: ({ attempt_id, frame }) =>
    postForm(`/attempt/${enc(attempt_id)}/identity`, [
      ["frame", frame.blob, "frame_0.jpg"],
      ["capture_ts_ms", frame.ts],
    ]),

  liveness: ({ attempt_id, frames }) =>
    postForm(`/attempt/${enc(attempt_id)}/liveness`, [
      ...frames.map((f, i) => [FRAMES_KEY, f.blob, `frame_${i}.jpg`]),
      ...frames.map((f) => [TS_KEY, f.ts]),
    ]),

  challengeStart: ({ attempt_id }) => postForm(`/attempt/${enc(attempt_id)}/challenge/start`, []),

  challenge: ({ attempt_id, challenge_id, frames, prompt_ts, baseline_ts }) =>
    postForm(`/attempt/${enc(attempt_id)}/challenge`, [
      ...frames.map((f, i) => [FRAMES_KEY, f.blob, `c_${i}.jpg`]),
      ...frames.map((f) => [TS_KEY, f.ts]),
      ["prompt_ts_ms", JSON.stringify(prompt_ts)],
      ["baseline_start_ts_ms", baseline_ts],
      ["challenge_id", challenge_id],
    ]),
};

/** entries: [key, value] or [key, blob, filename]. `scenario` is always appended. */
function postForm(path, entries) {
  const fd = new FormData();
  for (const [k, v, name] of entries) {
    if (v === undefined || v === null) continue;
    if (v instanceof Blob) fd.append(k, v, name); else fd.append(k, String(v));
  }
  fd.append("scenario", state.scenario);
  return request(path, { method: "POST", body: fd });
}

function postJson(path, body) {
  return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

async function request(path, init) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), CONFIG.REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(CONFIG.API_BASE + path, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(`${path} returned ${res.status}`);
    const text = await res.text();
    return text ? JSON.parse(text) : {};
  } finally {
    clearTimeout(timer);
  }
}

/** Epoch ms with sub-ms precision, monotonic within the page. */
const nowEpochMs = () => round(performance.timeOrigin + performance.now(), 1);

// ============================================================
// MOCK — always REQUEST_VERIFICATION, never ALLOW. Cycles next_action so every screen can be seen.
// ============================================================
const MOCK_CYCLE = ["CHALLENGE", "MOVE_CLOSER", "HOLD_STILL", "IMPROVE_LIGHT", "RETRY", "RECEPTION", "NONE"];
let mockCycleIdx = 0;
const MOCK_REASON = {
  CHALLENGE: "LIVENESS_UNCERTAIN",
  MOVE_CLOSER: "QUALITY_TOO_SMALL",
  HOLD_STILL: "QUALITY_BLUR",
  IMPROVE_LIGHT: "QUALITY_DARK",
  RETRY: "TRACKING_LOST",
  RECEPTION: "MANUAL_REVIEW",
  NONE: "LIVENESS_UNAVAILABLE",
};

const mockApi = {
  async startAttempt(f) {
    log("mock /attempt/start", { ...f, scenario: state.scenario });
    await sleep(rand(40, 90));
    const t0 = Date.now();
    return { attempt_id: "mock-" + uuid(), server_t0_ms: t0, deadline_ms: t0 + 1700 };
  },
  async identity(f) {
    log("mock identity", { attempt_id: f.attempt_id, capture_ts_ms: f.frame.ts, bytes: f.frame.blob.size, scenario: state.scenario });
    await sleep(rand(200, 400));
    return { identity: "UNKNOWN", similarity: null, ms: 0 };
  },
  async liveness(f) {
    log("mock liveness", { attempt_id: f.attempt_id, frames: f.frames.length, capture_ts_ms: f.frames.map((x) => x.ts), scenario: state.scenario });
    await sleep(rand(250, 600));
    let next = els.mockNext.value;
    if (next === "auto") { next = MOCK_CYCLE[mockCycleIdx % MOCK_CYCLE.length]; mockCycleIdx++; }
    return mockDecision(f.attempt_id, MOCK_REASON[next], next);
  },
  async challengeStart(f) {
    log("mock challenge/start", { ...f, scenario: state.scenario });
    await sleep(rand(60, 120));
    const actions = shuffle(["SMILE", "OPEN_MOUTH", "TURN_LEFT", "TURN_RIGHT"]).slice(0, 2);
    return { challenge_id: "mockc-" + uuid(), actions, baseline_ms: 400, timeout_ms: 5000 };
  },
  async challenge(f) {
    log("mock challenge", { attempt_id: f.attempt_id, frames: f.frames.length, prompt_ts_ms: f.prompt_ts, scenario: state.scenario });
    await sleep(rand(300, 600));
    return mockDecision(f.attempt_id, "MANUAL_REVIEW", "RECEPTION");
  },
};

// Shape matches the contract's /liveness response. Never ALLOW.
function mockDecision(attempt_id, reason_code, next_action) {
  return {
    decision: "REQUEST_VERIFICATION",
    reason_code,
    message: "MOCK",
    next_action,
    attempt_id,
    signals: { quality: null, passive: { status: "UNAVAILABLE", score: null }, identity: { status: "UNKNOWN", similarity: null } },
    stage_ms: { quality: 0, passive: 0, identity_wait: 0, decide: 0 },
    first_pass_server_ms: Math.round(rand(300, 700)),
  };
}

const api = CONFIG.USE_MOCK ? mockApi : realApi;

// ============================================================
// Copy
// ============================================================
const DECISION = {
  ALLOW: { label: "ALLOW", cls: "allow" },
  REQUEST_VERIFICATION: { label: "REQUEST VERIFICATION", cls: "review" },
  DENY: { label: "DENY", cls: "deny" },
};

// v2 reason codes. Unknown codes fall back to the server `message`, then a humanised code.
const REASON_TEXT = {
  OK_LIVE_MATCH: "Live person detected and identity confirmed.",
  SPOOF_PASSIVE: "This looks like a photo, screen or replay, not a live person.",
  ID_MISMATCH: "The face does not match the enrolled photo.",
  ID_UNAVAILABLE: "Identity could not be checked right now.",
  LIVENESS_UNCERTAIN: "We could not confirm a live person from the first check.",
  LIVENESS_UNAVAILABLE: "The live-person check is unavailable right now.",
  QUALITY_TOO_SMALL: "Your face was too far from the camera.",
  QUALITY_BLUR: "The image was blurred by movement.",
  QUALITY_DARK: "The image was too dark to check.",
  MULTI_FACE: "More than one face was in view.",
  NO_FACE: "No face was found in view.",
  TRACKING_LOST: "We lost track of your face during the check.",
  TIMEOUT: "The check took too long to complete.",
  CHALLENGE_FAILED: "The on-screen prompts were not completed.",
  MANUAL_REVIEW: "This entry needs a manual check.",
};

const ICON = {
  left: '<path d="M15 5l-7 7 7 7M8 12h13"/>',
  right: '<path d="M9 5l7 7-7 7M16 12H3"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  smile: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2.5 4 2.5 4-2.5 4-2.5M9 9h.01M15 9h.01"/>',
  mouth: '<circle cx="12" cy="12" r="10"/><ellipse cx="12" cy="15.5" rx="2.6" ry="3"/><path d="M9 9h.01M15 9h.01"/>',
  retry: '<path d="M3 12a9 9 0 0115.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 01-15.5 6.2L3 16M3 21v-5h5"/>',
  closer: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><circle cx="12" cy="12" r="3"/>',
  still: '<path d="M7 11V6a2 2 0 014 0v5M11 10V4a2 2 0 014 0v7M15 9a2 2 0 014 0v5a7 7 0 01-7 7h-1a7 7 0 01-6-3.5L3 14a2 2 0 013.4-2L7 13"/>',
  light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  desk: '<circle cx="12" cy="7" r="3.5"/><path d="M5 21v-2a5 5 0 015-5h4a5 5 0 015 5v2M2 21h20"/>',
  shield: '<path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5l8-3z"/><path d="M9 12l2 2 4-4"/>',
};
const svg = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[name] || ICON.eye}</svg>`;

const ACTION_UI = {
  BASELINE: { word: "Look at the camera", icon: "eye" },
  TURN_LEFT: { word: "Turn left", icon: "left" },
  TURN_RIGHT: { word: "Turn right", icon: "right" },
  SMILE: { word: "Smile", icon: "smile" },
  OPEN_MOUTH: { word: "Open your mouth", icon: "mouth" },
};

const NEXT_UI = {
  MOVE_CLOSER: { icon: "closer", text: "Move closer", sub: "Fill the oval with your face.", retry: true },
  HOLD_STILL: { icon: "still", text: "Hold still", sub: "Keep your head steady while we check.", retry: true },
  IMPROVE_LIGHT: { icon: "light", text: "Find better light", sub: "Face the light and avoid strong light behind you.", retry: true },
  RETRY: { icon: "retry", text: "Let's try that again", sub: "Look at the camera and keep your face in the oval.", retry: true },
  CHALLENGE: { icon: "shield", text: "One more quick check", sub: "Follow the prompts on screen." },
  RECEPTION: { icon: "desk", text: "Please see reception for manual review", sub: "A member of staff will help you." },
};

// ============================================================
// DOM + state
// ============================================================
const $ = (id) => document.getElementById(id);
const els = {
  video: $("video"), canvas: $("canvas"), names: $("names"),
  camStatus: $("camStatus"), camMessage: $("camMessage"), clock: $("clock"), mockBadge: $("mockBadge"),
  capLabel: $("capLabel"), capName: $("capName"), stopwatch: $("stopwatch"),
  prompt: $("prompt"), promptIcon: $("promptIcon"), promptWord: $("promptWord"),
  resultCard: $("resultCard"), decision: $("decision"), reason: $("reason"),
  decisionTime: $("decisionTime"), firstPass: $("firstPass"), total: $("total"),
  nextAction: $("nextAction"), nextIcon: $("nextIcon"), nextText: $("nextText"), nextSub: $("nextSub"),
  retryBtn: $("retryBtn"), resultMock: $("resultMock"), resetHint: $("resetHint"),
  attemptInfo: $("attemptInfo"),
  operator: $("operator"), scenario: $("scenario"), mockNext: $("mockNext"), mockNextRow: $("mockNextRow"),
  opBackend: $("opBackend"), opAttempt: $("opAttempt"),
};

const state = {
  scenario: "genuine",
  cameraReady: false,
  flow: 0,                 // bumps on every new attempt / reset; stale async work checks it and bails
  usedAttemptIds: new Set(),
  user: null,
  t0: 0,                   // performance.now() at the tap
  attemptId: null,
  firstPassS: null,
  stopwatchRaf: 0,
  resetTimer: 0,
  resetTick: 0,
};

class Cancelled extends Error {}
const guard = (flow) => { if (flow !== state.flow) throw new Cancelled(); };

// ============================================================
// Camera
// ============================================================
async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) return cameraFailed("Camera needs a secure context (https or localhost).");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false,
    });
    els.video.srcObject = stream;
    await els.video.play().catch(() => {});
    state.cameraReady = true;
    setCamStatus("ok", "Camera ready");
    els.camMessage.hidden = true;
  } catch (err) {
    cameraFailed(err?.name === "NotAllowedError"
      ? "Camera permission was denied. Allow camera access and reload."
      : "No camera found. Connect a camera and reload.");
  }
  renderNames();
}

function cameraFailed(msg) {
  state.cameraReady = false;
  setCamStatus("err", "Camera offline");
  els.camMessage.textContent = CONFIG.USE_MOCK ? `${msg}\n\nMock mode: continuing with blank frames.` : msg;
  els.camMessage.hidden = false;
  renderNames();
}

function setCamStatus(kind, text) {
  els.camStatus.className = `status ${kind}`;
  els.camStatus.querySelector(".status-text").textContent = text;
}

/** Grab one JPEG frame. ts = epoch ms at the moment of capture; perf = performance.now() for local scheduling. */
function grabFrame() {
  const perf = performance.now();
  const ts = nowEpochMs();
  const v = els.video;
  const srcW = v.videoWidth || 640, srcH = v.videoHeight || 480;
  const w = Math.min(CONFIG.FRAME_MAX_WIDTH, srcW);
  const h = Math.round((srcH / srcW) * w);
  const c = els.canvas;
  c.width = w; c.height = h;
  const ctx = c.getContext("2d");
  if (state.cameraReady) ctx.drawImage(v, 0, 0, w, h);
  else { ctx.fillStyle = "#000"; ctx.fillRect(0, 0, w, h); }
  return new Promise((resolve) => c.toBlob((blob) => resolve({ blob, ts, perf }), "image/jpeg", CONFIG.JPEG_QUALITY));
}

// ============================================================
// Attempt flow
// ============================================================
async function beginAttempt(user) {
  if (!state.cameraReady && !CONFIG.USE_MOCK) return;
  clearReset();
  const flow = ++state.flow;
  state.t0 = performance.now();        // timer starts at the tap
  state.user = user;
  state.attemptId = null;
  state.firstPassS = null;

  showScreen("capture");
  els.capLabel.textContent = "Checking";
  els.capName.textContent = user.name;
  els.prompt.hidden = true;
  startStopwatch();

  try {
    // Claim + consent + attempt start, and grab the first frame at the same time.
    const startP = api.startAttempt({ user_id: user.id });
    const first = await grabFrame();
    const start = await startP;
    guard(flow);

    const attemptId = start?.attempt_id;
    if (!attemptId) throw new Error("No attempt_id from /attempt/start");
    if (state.usedAttemptIds.has(attemptId)) throw new Error(`attempt_id reused by server: ${attemptId}`);
    state.usedAttemptIds.add(attemptId);
    state.attemptId = attemptId;
    showAttempt(attemptId);

    // Identity: fire and forget.
    api.identity({ attempt_id: attemptId, frame: first }).catch((e) => log("identity failed", e));

    // Liveness: first frame + 5 more, spaced ~170ms apart from the first capture.
    let frames = [first];
    for (let i = 1; i < CONFIG.LIVENESS_FRAMES; i++) {
      await sleepUntil(first.perf + i * CONFIG.LIVENESS_SPACING_MS);
      guard(flow);
      frames.push(await grabFrame());
    }
    els.capLabel.textContent = "Verifying";
    const decision = await api.liveness({ attempt_id: attemptId, frames });
    frames = null; // drop references; nothing is retained
    guard(flow);

    await handleDecision(decision, flow, "first");
  } catch (err) {
    if (err instanceof Cancelled) return;
    log("attempt failed", err);
    if (flow === state.flow) await showFailure(flow);
  }
}

async function handleDecision(d, flow, phase) {
  if (d && d.next_action === "NONE") d.next_action = null;
  if (d?.attempt_id && d.attempt_id !== state.attemptId) throw new Error(`Response for another attempt: ${d.attempt_id}`);
  log("decision", { attempt: state.attemptId, ...d });
  const next = d?.next_action || null;

  if (next === "CHALLENGE" && phase === "first") {
    await renderResult(d, flow, { phase });
    await sleep(CONFIG.CHALLENGE_LEAD_IN_MS);
    guard(flow);
    return runChallenge(flow);
  }
  await renderResult(d, flow, { phase: phase === "first" ? "only" : "final" });

  const retry = !!NEXT_UI[next]?.retry;
  scheduleReset(retry ? CONFIG.RETRY_RESET_MS : CONFIG.RESULT_RESET_MS);
}

async function runChallenge(flow) {
  stopStopwatch();
  showScreen("challenge");
  els.capLabel.textContent = "Extra check";
  els.capName.textContent = state.user.name;
  startStopwatch();

  const cs = await api.challengeStart({ attempt_id: state.attemptId });
  guard(flow);
  const actions = Array.isArray(cs?.actions) ? cs.actions : [];
  const baselineMs = Number(cs?.baseline_ms) || CONFIG.CHALLENGE_BASELINE_MS;
  // Fit the prompts inside the server's timeout, leaving ~600ms for upload + decision.
  const budget = Number(cs?.timeout_ms) ? (cs.timeout_ms - baselineMs - 600) / Math.max(1, actions.length) : Infinity;
  const actionMs = Math.max(800, Math.min(CONFIG.CHALLENGE_ACTION_MS, budget));

  const frames = [];
  const prompt_ts = [];   // epoch ms per action, aligned with `actions`
  let baseline_ts = null;
  let recording = true;
  const interval = 1000 / CONFIG.CHALLENGE_FPS;
  const recorder = (async () => {
    let nextAt = performance.now();
    while (recording && flow === state.flow) {
      frames.push(await grabFrame());
      nextAt += interval;
      await sleepUntil(nextAt);
    }
  })();

  const showPrompt = (action) => {
    const ts = nowEpochMs();
    if (action === "BASELINE") baseline_ts = ts; else prompt_ts.push(ts);
    const ui = ACTION_UI[action] || { word: humanize(action), icon: "eye" };
    els.promptIcon.innerHTML = svg(ui.icon);
    els.promptWord.textContent = ui.word;
    els.prompt.hidden = false;
    els.prompt.classList.remove("pop"); void els.prompt.offsetWidth; els.prompt.classList.add("pop");
  };

  try {
    showPrompt("BASELINE");
    await sleep(baselineMs);
    for (const a of actions) {
      guard(flow);
      showPrompt(a);
      await sleep(actionMs);
    }
  } finally {
    recording = false;
    await recorder;
  }
  guard(flow);

  els.prompt.hidden = true;
  els.capLabel.textContent = "Verifying";
  const d = await api.challenge({ attempt_id: state.attemptId, challenge_id: cs?.challenge_id, frames, prompt_ts, baseline_ts });
  frames.length = 0;
  guard(flow);
  await handleDecision(d, flow, "final");
}

// ============================================================
// Rendering
// ============================================================
/**
 * phase: "first" (first pass, challenge to follow) | "only" (first pass is final) | "final" (after challenge)
 * Time is measured tap -> render: DOM is updated, then measured in the next requestAnimationFrame.
 */
async function renderResult(d, flow, { phase }) {
  const dec = DECISION[d?.decision];
  if (!dec) throw new Error(`Unexpected decision: ${d?.decision}`);

  stopStopwatch();
  els.resultCard.className = `result ${dec.cls}`;
  els.decision.textContent = dec.label;
  els.reason.textContent = REASON_TEXT[d.reason_code]
    || (d.message && d.message !== "MOCK" ? d.message : "")
    || humanize(d.reason_code || "unknown");
  renderNext(d.next_action);
  els.resultMock.hidden = !CONFIG.USE_MOCK;
  els.resetHint.textContent = "";
  showScreen("result");

  await nextFrame();
  guard(flow);
  const s = (performance.now() - state.t0) / 1000;

  if (phase === "first" || phase === "only") state.firstPassS = s;
  els.decisionTime.textContent = s.toFixed(2);
  els.firstPass.textContent = `${state.firstPassS.toFixed(2)} s`;
  els.total.textContent = phase === "first" ? "…" : `${s.toFixed(2)} s`;
  log(`render ${phase}`, { decision: d.decision, reason: d.reason_code, next: d.next_action, s: s.toFixed(3) });
}

function renderNext(next) {
  const ui = NEXT_UI[next];
  els.nextAction.hidden = !ui;
  if (!ui) return;
  els.nextIcon.innerHTML = svg(ui.icon);
  els.nextText.textContent = ui.text;
  els.nextSub.textContent = ui.sub;
  els.retryBtn.hidden = !ui.retry;
}

async function showFailure(flow) {
  stopStopwatch();
  els.resultCard.className = "result";
  els.decision.textContent = "UNAVAILABLE";
  els.reason.textContent = "The verification service could not be reached.";
  renderNext("RECEPTION");
  els.resultMock.hidden = !CONFIG.USE_MOCK;
  els.decisionTime.textContent = "—";
  els.firstPass.textContent = "—";
  els.total.textContent = "—";
  showScreen("result");
  scheduleReset(CONFIG.RESULT_RESET_MS);
}

function renderNames() {
  els.names.innerHTML = "";
  for (const u of CONFIG.ENROLLED) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "name-btn";
    b.textContent = u.name;
    b.disabled = !state.cameraReady && !CONFIG.USE_MOCK;
    b.addEventListener("click", () => beginAttempt(u));
    els.names.appendChild(b);
  }
}

function showScreen(name) {
  document.body.dataset.screen = name;
}

function showAttempt(id) {
  els.attemptInfo.textContent = `attempt ${id}`;
  els.opAttempt.textContent = id;
}

// ============================================================
// Reset
// ============================================================
function scheduleReset(ms) {
  clearReset();
  const until = performance.now() + ms;
  const tick = () => {
    const left = Math.ceil((until - performance.now()) / 1000);
    els.resetHint.textContent = left > 0 ? `Returning to start in ${left} s` : "";
  };
  tick();
  state.resetTick = setInterval(tick, 250);
  state.resetTimer = setTimeout(goWelcome, ms);
}

function clearReset() {
  clearTimeout(state.resetTimer);
  clearInterval(state.resetTick);
  els.resetHint.textContent = "";
}

function goWelcome() {
  clearReset();
  state.flow++;              // cancel anything still in flight
  state.user = null;
  state.attemptId = null;    // never reused: a new tap always calls /attempt/start
  stopStopwatch();
  els.attemptInfo.textContent = "";
  showScreen("welcome");
}

// ============================================================
// Stopwatch
// ============================================================
function startStopwatch() {
  stopStopwatch();
  const tick = () => {
    els.stopwatch.textContent = ((performance.now() - state.t0) / 1000).toFixed(2);
    state.stopwatchRaf = requestAnimationFrame(tick);
  };
  tick();
}
function stopStopwatch() { cancelAnimationFrame(state.stopwatchRaf); }

// ============================================================
// Operator panel (press "o")
// ============================================================
function setupOperator() {
  try { state.scenario = localStorage.getItem("kiosk.scenario") || "genuine"; } catch {}
  els.scenario.value = state.scenario;
  if (els.scenario.value !== state.scenario) { state.scenario = "genuine"; els.scenario.value = "genuine"; }
  els.scenario.addEventListener("change", () => {
    state.scenario = els.scenario.value;
    try { localStorage.setItem("kiosk.scenario", state.scenario); } catch {}
  });

  els.mockNextRow.hidden = !CONFIG.USE_MOCK;
  els.opBackend.textContent = CONFIG.USE_MOCK ? "MOCK" : (CONFIG.API_BASE || location.origin);

  document.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLSelectElement) return;
    if (e.key === "o" || e.key === "O") els.operator.hidden = !els.operator.hidden;
    if (e.key === "Escape") els.operator.hidden = true;
  });
}

// ============================================================
// Utils
// ============================================================
function sleep(ms) { return new Promise((r) => setTimeout(r, Math.max(0, ms))); }
function sleepUntil(t) { return sleep(t - performance.now()); }
function nextFrame() { return new Promise((r) => requestAnimationFrame(() => r())); }
function rand(a, b) { return a + Math.random() * (b - a); }
function round(n, d) { const f = 10 ** d; return Math.round(n * f) / f; }
function shuffle(a) { return a.map((v) => [Math.random(), v]).sort((x, y) => x[0] - y[0]).map((x) => x[1]); }
function uuid() { return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36); }
function humanize(code) { const s = String(code).toLowerCase().replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1) + "."; }
function log(...a) { console.log("[kiosk]", ...a); }

function startClock() {
  const fmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
  const update = () => { els.clock.textContent = fmt.format(new Date()); };
  update();
  setInterval(update, 10000);
}

// ============================================================
// Boot
// ============================================================
els.mockBadge.hidden = !CONFIG.USE_MOCK;
els.retryBtn.addEventListener("click", () => { if (state.user) beginAttempt(state.user); });
setupOperator();
startClock();
renderNames();
showScreen("welcome");
startCamera();
