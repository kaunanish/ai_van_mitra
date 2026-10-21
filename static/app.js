/* ======================================================================== AI Van Mitra - kiosk front end
 *
 *  STATE MACHINE
 *    IDLE ──presence──> GREETING ──greeting ends──> READY
 *    READY ──button down──> LISTENING (hold, max 10 s) ──button up──> THINKING ──answer──> SPEAKING ──ends──> READY
 *    SPEAKING/GREETING ──button down──> LISTENING   (interrupt)
 *    no person for 30 s, or no activity for 45 s ──> IDLE (attract loop)
 *  Each state change is POSTed to the backend, which sets the LED ring colour through the Arduino.
 *
 *  INPUT EVENTS arrive over Server-Sent Events from the backend (/events):
 *    production -> the Arduino (button, mmWave sensor) via the serial thread
 *    demo       -> the keyboard below, POSTed to /api/hw and echoed back over the same SSE stream
 * ====================================================================== */
(() => {
"use strict";

const $ = (id) => document.getElementById(id);
const body = document.body;
const params = new URLSearchParams(location.search);
if (params.has("kiosk")) body.classList.add("kiosk");               // production: full screen, no panel
const DEBUG = params.has("debug");                                  // "How I answered" panel: only with ?debug=1
if (DEBUG) body.classList.add("debug");

const T = { NO_PERSON_MS: 30000, NO_ACTIVITY_MS: 45000, MAX_RECORD_MS: 10000, MIN_RECORD_MS: 400 };

const HINTS = {
  IDLE: "Come closer and say hello!",
  GREETING: "Hello! Get ready to ask me a question.",
  READY: "Press and hold the green button, ask your question, then let go.",
  LISTENING: "I'm listening… let go of the button when you finish.",
  THINKING: "Let me think…",
  SPEAKING: "Press the button any time to ask something else.",
};
const SAMPLES = [
  "What does Satkosia mean?", "What does a gharial eat?", "What should I do if I see an elephant?",
  "What is the state bird of Odisha?", "What is mahua used for?", "How can I prevent forest fires?",
  "When did Satkosia become a tiger reserve?", "Who won the cricket world cup?",
];
const FALLBACK_LOCAL = {
  greeting: "Namaskar! I am Van Mitra, the friend of the forest. Press and hold the green button, ask me anything about the forests and wildlife of Angul, then let go.",
  error: "Oh! My leaves got tangled for a moment. Please ask me again.",
  nomic: "I can't hear anything. Please check that the microphone is connected and allowed.",
};

let state = "IDLE";
let presence = false;
let sseOK = false;
let lines = {};
let absentTimer = null, inactivityTimer = null, attractTimer = null, maxRecTimer = null;

/* ---------------------------------------------------------------- backend helpers */
const post = (url, data) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) });

function setState(s) {
  if (state === s) return;
  state = s;
  body.dataset.state = s;
  $("hint").textContent = HINTS[s];
  post("/api/state", { state: s }).catch(() => {});
  resetInactivity();
  if (s === "IDLE") startAttract(); else stopAttract();
}

/* ---------------------------------------------------------------- hardware events (SSE) */
function connectEvents() {
  const es = new EventSource("/events");
  es.onopen = () => { sseOK = true; renderChips(); };
  es.onerror = () => { sseOK = false; renderChips(); };
  es.onmessage = (e) => { try { onHardware(JSON.parse(e.data).event); } catch (_) {} };
}

// keyboard / on-screen sends the SAME events the Arduino would send
function sendHw(ev) {
  if (sseOK) post("/api/hw", { event: ev }).catch(() => onHardware(ev));
  else onHardware(ev);
}

function onHardware(ev) {
  switch (ev) {
    case "PRESENCE_ON": onPresence(true); break;
    case "PRESENCE_OFF": onPresence(false); break;
    case "BTN_DOWN": onButtonDown(); break;
    case "BTN_UP": onButtonUp(); break;
  }
}

/* ---------------------------------------------------------------- state transitions */
function onPresence(on) {
  presence = on;
  $("presence-state").textContent = "Visitor present: " + (on ? "yes" : "no");
  clearTimeout(absentTimer);
  if (on) {
    if (state === "IDLE") greet();
  } else {
    absentTimer = setTimeout(() => { if (!presence && ["READY", "GREETING", "IDLE"].includes(state)) goIdle(); }, T.NO_PERSON_MS);
  }
}

async function greet() {
  post("/api/visitor").catch(() => {});
  setState("GREETING");
  $("asked").textContent = "";
  const g = lines.greeting || { text: FALLBACK_LOCAL.greeting, audio_url: null };
  await speak(g.text, g.audio_url);
  if (state === "GREETING") setState("READY");
}

function onButtonDown() {
  if (state === "LISTENING" || state === "THINKING") return;
  if (state === "IDLE") post("/api/visitor").catch(() => {});
  stopSpeaking();
  startListening();
}

function onButtonUp() {
  if (state === "LISTENING") stopListening();
}

function goIdle() {
  stopSpeaking();
  setState("IDLE");
  $("asked").textContent = "";
}

function resetInactivity() {
  clearTimeout(inactivityTimer);
  inactivityTimer = setTimeout(() => { if (state === "READY") goIdle(); }, T.NO_ACTIVITY_MS);
}

/* ---------------------------------------------------------------- attract loop (IDLE) */
function startAttract() {
  stopAttract();
  let i = 0;
  const show = () => {
    const said = $("said");
    said.className = "said attract";
    said.style.removeProperty("--said-size");
    said.innerHTML = i % 2 === 0
      ? "I'm <b>Van Mitra</b>, and I know a lot about the forests, rivers and animals of Angul."
      : `Try asking me: <b>“${SAMPLES[(i >> 1) % (SAMPLES.length - 1)]}”</b>`;
    if (i % 4 === 0) { body.classList.add("wave"); setTimeout(() => body.classList.remove("wave"), 2400); }
    i++;
  };
  show();
  attractTimer = setInterval(show, 6000);
}
function stopAttract() { clearInterval(attractTimer); attractTimer = null; }

/* ---------------------------------------------------------------- microphone -> 16 kHz WAV
 * The mic stays open; samples flow continuously. While the button is held we keep them,
 * and we also keep ~0.2 s from just BEFORE the press so the first syllable is never cut. */
let actx = null, micStream = null, micReady = false, recording = false, recBufs = [], preroll = [], recStart = 0;

async function audioCtx() {
  if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
  if (actx.state === "suspended") { try { await actx.resume(); } catch (_) {} }
  return actx;
}

async function initMic() {
  if (micReady) return true;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const ctx = await audioCtx();
    const src = ctx.createMediaStreamSource(micStream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const mute = ctx.createGain(); mute.gain.value = 0;
    src.connect(proc); proc.connect(mute); mute.connect(ctx.destination);
    proc.onaudioprocess = (e) => {
      const d = new Float32Array(e.inputBuffer.getChannelData(0));
      if (recording) {
        recBufs.push(d);
        let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] * d[i];
        micLevel = Math.min(1, Math.sqrt(s / (d.length / 4)) * 6);
      } else {
        preroll.push(d); if (preroll.length > 2) preroll.shift();
      }
    };
    micReady = true;
  } catch (err) {
    console.warn("mic", err);
    micReady = false;
  }
  renderChips();
  return micReady;
}

async function startListening() {
  if (!(await initMic())) {
    setState("SPEAKING");
    await speak(FALLBACK_LOCAL.nomic, null);
    if (state === "SPEAKING") setState("READY");
    return;
  }
  recBufs = preroll.slice();
  recording = true;
  recStart = performance.now();
  $("asked").textContent = "";
  const said = $("said"); said.className = "said"; said.textContent = "";
  setState("LISTENING");
  clearTimeout(maxRecTimer);
  maxRecTimer = setTimeout(stopListening, T.MAX_RECORD_MS);
}

async function stopListening() {
  if (!recording) return;
  recording = false; micLevel = 0;
  clearTimeout(maxRecTimer);
  const wav = encodeWav(recBufs, actx.sampleRate);
  recBufs = [];
  setState("THINKING");
  const fd = new FormData();
  fd.append("audio", wav, "question.wav");
  try {
    const r = await fetch("/api/ask", { method: "POST", body: fd });
    await deliver(await r.json());
  } catch (e) {
    console.warn(e);
    await deliver({ transcript: "", answer: FALLBACK_LOCAL.error, audio_url: null, status: "error" });
  }
}

function encodeWav(buffers, inRate) {
  const total = buffers.reduce((n, b) => n + b.length, 0);
  const all = new Float32Array(total);
  let o = 0; for (const b of buffers) { all.set(b, o); o += b.length; }
  const outRate = 16000, ratio = inRate / outRate, n = Math.floor(total / ratio);
  const pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {               // average the samples that fall into each output sample
    const a = Math.floor(i * ratio), b = Math.min(total, Math.floor((i + 1) * ratio));
    let s = 0; for (let j = a; j < b; j++) s += all[j];
    const v = Math.max(-1, Math.min(1, s / Math.max(1, b - a)));
    pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
  const w = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, outRate, true);
  v.setUint32(28, outRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data");
  v.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: "audio/wav" });
}

/* ---------------------------------------------------------------- typed question (demo backup) */
async function askText(q) {
  q = (q || "").trim();
  if (!q || state === "THINKING" || state === "LISTENING") return;
  stopSpeaking();
  if (state === "IDLE") post("/api/visitor").catch(() => {});
  $("asked").textContent = q;
  const said = $("said"); said.className = "said"; said.textContent = "";
  setState("THINKING");
  try {
    const r = await post("/api/ask_text", { text: q });
    await deliver(await r.json());
  } catch (e) {
    await deliver({ transcript: q, answer: FALLBACK_LOCAL.error, audio_url: null, status: "error" });
  }
}

async function deliver(d) {
  $("asked").textContent = d.transcript || "";
  renderTrace(d);
  setState("SPEAKING");
  await speak(d.answer, d.audio_url);
  if (state === "SPEAKING") setState("READY");
}

/* ---------------------------------------------------------------- speaking: audio + mouth + subtitles */
const player = new Audio();
player.preload = "auto";
let analyser = null, playerWired = false, speakResolve = null, speakingKind = null, words = [], micLevel = 0;

async function wirePlayer() {
  if (playerWired) return;
  const ctx = await audioCtx();
  const src = ctx.createMediaElementSource(player);
  analyser = ctx.createAnalyser(); analyser.fftSize = 1024;
  src.connect(analyser); analyser.connect(ctx.destination);
  playerWired = true;
}

function showSubtitle(text) {
  const said = $("said");
  said.className = "said karaoke";
  said.innerHTML = "";
  words = text.split(/\s+/).filter(Boolean).map((w) => {
    const s = document.createElement("span"); s.className = "w"; s.textContent = w + " "; said.appendChild(s); return s;
  });
  fitSubtitle();
}
// shrink long answers until they fit the subtitle area
function fitSubtitle() {
  const said = $("said"), box = said.parentElement;
  let size = 3.0;
  said.style.setProperty("--said-size", size + "cqh");
  while (box.scrollHeight > box.clientHeight + 1 && size > 1.8) {
    size -= 0.15;
    said.style.setProperty("--said-size", size.toFixed(2) + "cqh");
  }
}
function highlightUpTo(frac) {
  const n = Math.ceil(frac * words.length);
  words.forEach((w, i) => w.classList.toggle("on", i < n));
}

function speak(text, url) {
  stopSpeaking();
  showSubtitle(text);
  return new Promise(async (resolve) => {
    speakResolve = resolve;
    body.classList.add("talking");
    if (url) {
      try {
        await wirePlayer();
        player.src = url + (url.includes("?") ? "" : "?v=1");
        speakingKind = "audio";
        player.onended = () => finishSpeaking();
        player.onerror = () => { speakingKind = null; browserSpeak(text); };
        await player.play();
        return;
      } catch (e) { console.warn("audio play failed, using browser voice", e); }
    }
    browserSpeak(text);
  });
}

function browserSpeak(text) {
  if (!("speechSynthesis" in window)) { speakingKind = "timer"; setTimeout(finishSpeaking, 350 * words.length); return; }
  speakingKind = "browser";
  const u = new SpeechSynthesisUtterance(text);
  const vs = speechSynthesis.getVoices();
  u.voice = vs.find((v) => v.lang === "en-IN") || vs.find((v) => v.lang && v.lang.startsWith("en")) || null;
  u.rate = 0.95;
  u.onboundary = (e) => { if (e.name === "word" || e.charIndex) highlightUpTo(Math.min(1, (e.charIndex + 1) / text.length)); };
  u.onend = () => finishSpeaking();
  u.onerror = () => finishSpeaking();
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

function finishSpeaking() {
  highlightUpTo(1);
  body.classList.remove("talking");
  speakingKind = null;
  const r = speakResolve; speakResolve = null;
  if (r) r();
}

function stopSpeaking() {
  if (speakingKind === "audio") { player.onended = null; player.pause(); }
  if (speakingKind === "browser") { speechSynthesis.cancel(); }
  if (speakResolve) finishSpeaking();
}

// animation loop: mouth opening follows the loudness of the voice; rings follow the mic level
const timeData = new Uint8Array(1024);
let mouth = 0.08;
function frame(t) {
  let target = 0.08;
  if (speakingKind === "audio" && analyser) {
    analyser.getByteTimeDomainData(timeData);
    let s = 0; for (let i = 0; i < timeData.length; i += 2) { const x = (timeData[i] - 128) / 128; s += x * x; }
    const rms = Math.sqrt(s / (timeData.length / 2));
    target = Math.min(1, 0.08 + rms * 5.5);
    if (player.duration) highlightUpTo(Math.min(1, (player.currentTime + 0.25) / player.duration));
  } else if (speakingKind === "browser" || speakingKind === "timer") {
    target = 0.35 + 0.35 * Math.abs(Math.sin(t / 95)) * (0.6 + 0.4 * Math.sin(t / 310));
  }
  mouth += (target - mouth) * 0.45;
  body.style.setProperty("--mouth", mouth.toFixed(3));
  body.style.setProperty("--mic", micLevel.toFixed(3));
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

/* ---------------------------------------------------------------- keyboard (demo hardware) */
let spaceDown = false;
document.addEventListener("keydown", (e) => {
  audioCtx();                                    // first key press unlocks audio in the browser
  if (e.target.tagName === "INPUT") { if (e.key === "Escape") e.target.blur(); return; }
  if (e.code === "Space") { e.preventDefault(); if (!e.repeat && !spaceDown) { spaceDown = true; sendHw("BTN_DOWN"); } return; }
  if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "p") sendHw(presence ? "PRESENCE_OFF" : "PRESENCE_ON");
  else if (k === "h" && DEBUG) togglePanel();
  else if (k === "t" && DEBUG) { e.preventDefault(); body.classList.add("panel-open"); $("ask-input").focus(); }
  else if (k === "f") { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {}); }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && spaceDown) { e.preventDefault(); spaceDown = false; sendHw("BTN_UP"); }
});
window.addEventListener("blur", () => { if (spaceDown) { spaceDown = false; sendHw("BTN_UP"); } });

// the on-screen button glyph also works with mouse / touch (handy when testing)
const glyph = document.querySelector(".btn-glyph");
glyph.addEventListener("pointerdown", (e) => { e.preventDefault(); audioCtx(); glyph.setPointerCapture(e.pointerId); sendHw("BTN_DOWN"); });
glyph.addEventListener("pointerup", () => sendHw("BTN_UP"));
glyph.addEventListener("pointercancel", () => sendHw("BTN_UP"));

/* ---------------------------------------------------------------- demo panel */
function togglePanel() { body.classList.toggle("panel-open"); }
$("panel-open").onclick = togglePanel;
$("panel-close").onclick = togglePanel;
$("ask-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("ask-input"); askText(i.value); i.select(); });
SAMPLES.forEach((q) => {
  const b = document.createElement("button"); b.type = "button"; b.textContent = q;
  b.onclick = () => { $("ask-input").value = q; askText(q); };
  $("samples").appendChild(b);
});

let sysStatus = null;
async function pollStatus() {
  try { sysStatus = await (await fetch("/api/status")).json(); } catch (_) { sysStatus = null; }
  renderChips();
}
function renderChips() {
  const s = sysStatus;
  const chip = (cls, name, detail) => `<li class="${cls}"><span>${name}<small>${esc(detail)}</small></span></li>`;
  const items = [];
  items.push(chip(micReady ? "ok" : "warn", "Microphone", micReady ? "on" : "press Space once to allow"));
  items.push(chip(sseOK ? "ok" : "", "Hardware link", s ? `${s.hardware.mode}${sseOK ? "" : ", events offline"}` : "…"));
  if (s) {
    items.push(chip(s.stt.ok ? "ok" : "", "Speech to text", s.stt.ok ? `Whisper ${s.stt.model}` : s.stt.detail));
    items.push(chip(s.knowledge.mode === "hybrid" ? "ok" : "warn", "Knowledge search",
      `${s.knowledge.chunks} passages, ${s.knowledge.files.length} docs, ${s.knowledge.mode}`));
    items.push(chip(s.llm.ok ? "ok" : "warn", "Language model", s.llm.ok ? `${s.llm.model}, local` : `${s.llm.detail}; using exact sentences`));
    items.push(chip(s.tts.ok ? "ok" : "warn", "Voice", `${s.tts.engine} (${s.tts.voice})`));
  } else {
    items.push(chip("", "Server", "not reachable"));
  }
  $("chips").innerHTML = items.join("");
}

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function renderTrace(d) {
  const t = d.trace || {};
  const tm = t.timings || {};
  const h = [];
  h.push(`<p class="heard">“${esc(d.transcript || "(nothing heard)")}”</p>`);
  const meta = [];
  if (t.source) meta.push(t.source === "voice" ? "spoken" : "typed");
  if (t.stt) meta.push(`audio ${t.stt.duration_s}s` + (t.stt.no_speech_prob != null ? `, no-speech ${t.stt.no_speech_prob}, confidence ${t.stt.avg_logprob}` : ""));
  meta.push(`total ${((tm.total_ms || 0) / 1000).toFixed(2)} s`);
  h.push(`<p class="meta">${esc(meta.join(" · "))}</p>`);

  // the route through the pipeline
  const steps = t.steps || [];
  const find = (n) => steps.find((s) => s.step.startsWith(n));
  const row = (cls, name, txt) => `<li class="${cls}"><b>${name}</b><span>${esc(txt)}</span></li>`;
  const flow = [];
  if (t.stt) flow.push(row(d.status === "not_heard" ? "block" : "pass", "1 Speech to text", d.status === "not_heard" ? `rejected (${t.stt_reason || "unclear"})` : `“${t.stt.text}”`));
  const r = find("rules");
  if (r) flow.push(row(d.status === "rule" ? "pass" : "skip", "2 Small talk", r.result));
  const p = find("pinned");
  if (p) flow.push(row(p.hit ? "pass" : "skip", "3 Pinned answers", p.hit ? `matched “${p.matched_question}” (${p.score})` : `closest “${p.matched_question}” ${p.score} < ${p.threshold}`));
  const s = find("search");
  if (s) flow.push(row("pass", "4 Search", s.result));
  const g = find("gate 1");
  if (g) flow.push(row(g.passed ? "pass" : "block", "5 Relevance gate", `${g.method} ${g.value} ${g.passed ? "≥" : "<"} ${g.threshold}: ${g.passed ? "passed" : "LLM not called"}`));
  const g2 = find("gate 2");
  if (g2) flow.push(row(d.status === "rag" ? "pass" : "block", "6 Answer + check", `${g2.mode === "llm" ? "language model" : "exact sentences"}: ${g2.result}`));
  if (d.status === "fallback") flow.push(row("block", "Result", "honest fallback: not in the approved documents"));
  if (t.tts) flow.push(row("pass", "7 Voice", `${t.tts.engine}${t.tts.cached ? " (cached)" : ""}`));
  h.push(`<ul class="flow">${flow.join("")}</ul>`);

  // gate meter
  const ret = t.retrieval;
  if (ret && ret.gate) {
    const G = ret.gate, max = 1;
    h.push(`<div class="gate"><span>Gate</span><div class="meter ${G.passed ? "" : "no"}"><i style="width:${Math.min(100, (G.value / max) * 100)}%"></i><u style="left:${(G.threshold / max) * 100}%"></u></div><span>${G.value} / ${G.threshold}</span></div>`);
  }
  // passages
  if (ret && ret.results && ret.results.length) {
    h.push(`<h3>Passages found (${esc(ret.mode)})</h3><div class="passages">`);
    const maxBm = Math.max(...ret.results.map((x) => x.bm25), 0.001);
    ret.results.forEach((x, i) => {
      h.push(`<article class="psg"><header><b>#${i + 1} ${esc(x.section || x.file)}</b><span>${esc(x.file)}${x.page ? " p." + x.page : ""}</span></header>
        <p>${esc(x.text)}</p>
        <div class="scores">${x.cosine != null ? `<span>meaning ${x.cosine}<span class="bar"><i style="width:${Math.max(0, x.cosine) * 100}%"></i></span></span>` : ""}
        <span>keywords ${x.bm25}<span class="bar"><i style="width:${(x.bm25 / maxBm) * 100}%"></i></span></span><span>fused ${x.rrf}</span></div></article>`);
    });
    h.push(`</div>`);
  }
  // model output
  if (t.llm) {
    h.push(`<h3>${t.llm.mode === "llm" ? "Language model output (" + esc(t.llm.model) + ")" : "Exact sentences picked (no language model running)"}</h3>`);
    h.push(`<div class="llmout">${esc(t.llm.raw || "(empty)")}</div>`);
  }
  // timings
  const parts = [["stt_ms", "#4FA3C7", "hearing"], ["pinned_ms", "#9AA79F", "pinned"], ["retrieval_ms", "#6FA84B", "search"],
                 ["llm_ms", "#E9A93B", "thinking"], ["tts_ms", "#B07CC6", "voice"]];
  const total = parts.reduce((n, [k]) => n + (tm[k] || 0), 0);
  if (total > 0) {
    h.push(`<h3>Time taken</h3><div class="timing">${parts.map(([k, c]) => tm[k] ? `<span style="width:${(tm[k] / total) * 100}%;background:${c}"></span>` : "").join("")}</div>`);
    h.push(`<div class="legend">${parts.filter(([k]) => tm[k] != null).map(([k, c, n]) => `<span><i style="background:${c}"></i>${n} ${tm[k]} ms</span>`).join("")}</div>`);
  }
  $("trace").innerHTML = h.join("");
  $("trace").querySelectorAll(".psg").forEach((a) => a.addEventListener("click", () => a.classList.toggle("open")));
}

/* ---------------------------------------------------------------- start */
async function loadLines() {
  try { lines = await (await fetch("/api/lines")).json(); } catch (_) { lines = {}; }
  if (!lines.greeting) setTimeout(loadLines, 3000);   // server still generating the voice
}

body.dataset.state = "IDLE";
startAttract();
connectEvents();
loadLines();
pollStatus(); setInterval(pollStatus, 8000);
post("/api/state", { state: "IDLE" }).catch(() => {});
initMic();   // asks for microphone permission once, at start
if ("speechSynthesis" in window) speechSynthesis.getVoices();
})();
