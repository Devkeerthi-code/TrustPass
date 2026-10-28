// TrustPass TP-1 front panel. Live data from server.py's /api; on a static host it falls back
// to web/snapshot.json (the same pipeline, precomputed). Every number shown comes from a run.

const MODES = [
  ["honest", "Honest"], ["trojan-overt", "Trojan visible"], ["trojan-masked", "Trojan in noise"],
  ["trojan-dormant", "Trojan dormant"], ["saboteur", "Saboteur"],
];
const CIRCUITS = [["grover", "Grover"], ["qaoa", "QAOA"], ["vqe", "VQE"]];
const BACKENDS = ["FakeBrisbane", "FakeTorino"];
// Detent angles (degrees clockwise from 12 o'clock) and legend positions measured off the comp.
const SOURCE_DETENTS = [[39.7, 128, 74], [62, 138, 112], [86.6, 140, 151], [112, 138, 190], [136.6, 128, 228]];
const SOURCE_CENTER = [68, 160], SOURCE_RIM = 66;
const CIRCUIT_DETENTS = [[54.7, 122, 46], [89, 126, 86], [124, 122, 126]];
const CIRCUIT_CENTER = [62, 87], CIRCUIT_RIM = 50;
const WIRE_COLORS = ["#f2cf1d", "#42daea", "#d86aa0", "#7ddf8a", "#f39a4b", "#b9a2ff"];
const COL_W = 57;
const LAMP = { pass: "assets/plates/lamp-green.png", caught: "assets/plates/lamp-red.png" };
const $ = (s) => document.querySelector(s);
const panel = $(".panel");

const params = new URLSearchParams(location.search);
const state = {
  circuit: pick(params.get("circuit"), CIRCUITS.map((c) => c[0]), "grover"),
  mode: pick(params.get("mode"), MODES.map((m) => m[0]), "saboteur"),
  backend: pick(params.get("backend"), BACKENDS, "FakeBrisbane"),
  view: "locked", win: 0, report: null, snapshot: null, token: 0,
};
function pick(v, allowed, dflt) { return allowed.includes(v) ? v : dflt; }

// ---------- data ----------
const matrixCache = new Map();
let sourcing = null;  // one probe, shared by the run and matrix requests that race for it
function source() {
  return (sourcing ??= (async () => {
    // GitHub Pages can never host the API, so don't probe there (it only adds console 404s).
    if (!location.hostname.endsWith("github.io")) {
      try {
        if ((await fetch("/api/meta", { cache: "no-store" })).ok) return (state.snapshot = false);
      } catch {}
    }
    state.snapshot = await (await fetch("web/snapshot.json")).json();
    $("#hint").hidden = false;
    return state.snapshot;
  })());
}
async function getRun() {
  const snap = await source();
  const { circuit, mode, backend } = state;
  if (snap) return snap.runs[`${circuit}|${mode}|${backend}`];
  const r = await fetch(`/api/run?circuit=${circuit}&mode=${mode}&backend=${backend}`);
  if (!r.ok) throw new Error((await r.json()).error || r.statusText);
  return r.json();
}
async function getMatrix() {
  const key = `${state.circuit}|${state.backend}`;
  if (!matrixCache.has(key)) {
    const snap = await source();
    matrixCache.set(key, snap ? snap.matrices[key]
      : await (await fetch(`/api/matrix?circuit=${state.circuit}&backend=${state.backend}`)).json());
  }
  return matrixCache.get(key);
}

// ---------- controls ----------
function buildDetents(listSel, ctlSel, detents, center, rim, labels, onPick) {
  const list = $(listSel), ctl = $(ctlSel);
  detents.forEach(([deg, x, y], i) => {
    const li = document.createElement("li");
    li.style.left = `calc(${x} * var(--u))`;
    li.style.top = `calc(${y - 11} * var(--u))`;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = labels[i];
    b.addEventListener("click", () => onPick(i));
    li.append(b);
    list.append(li);
    const rad = (deg * Math.PI) / 180;
    const sx = center[0] + rim * Math.sin(rad), sy = center[1] - rim * Math.cos(rad);
    const len = Math.hypot(x - sx, y - sy), ang = (Math.atan2(y - sy, x - sx) * 180) / Math.PI;
    const t = document.createElement("span");
    t.className = "tick";
    Object.assign(t.style, { left: `calc(${sx} * var(--u))`, top: `calc(${sy} * var(--u))`,
      width: `calc(${len - 2} * var(--u))`, transform: `rotate(${ang}deg)` });
    list.append(t);
  });
  return list;
}

function knob(sel, detents, center, getIndex, setIndex, labels) {
  const el = $(sel), img = el.querySelector("img");
  const show = () => {
    const i = getIndex();
    img.style.transform = `rotate(${detents[i][0]}deg)`;
    el.setAttribute("aria-valuenow", i);
    el.setAttribute("aria-valuetext", labels[i]);
  };
  const nearest = (clientX, clientY) => {
    const r = el.getBoundingClientRect();
    const deg = (Math.atan2(clientX - (r.left + r.width / 2), -(clientY - (r.top + r.height / 2))) * 180) / Math.PI;
    let best = 0;
    detents.forEach(([d], i) => { if (Math.abs(d - deg) < Math.abs(detents[best][0] - deg)) best = i; });
    return best;
  };
  let dragging = false;
  const turnTo = (e) => { const i = nearest(e.clientX, e.clientY); if (i !== getIndex()) setIndex(i); };
  // A click turns the knob to the detent nearest the pointer; holding the button drags it on.
  el.addEventListener("pointerdown", (e) => { dragging = true; el.setPointerCapture(e.pointerId); turnTo(e); });
  el.addEventListener("pointermove", (e) => { if (dragging) turnTo(e); });
  el.addEventListener("pointerup", () => { dragging = false; });
  el.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (e.key === "Home") setIndex(0);
    else if (e.key === "End") setIndex(detents.length - 1);
    else if (step) setIndex(Math.max(0, Math.min(detents.length - 1, getIndex() + step)));
    else return;
    e.preventDefault();
  });
  el.addEventListener("wheel", (e) => {  // at an end stop the wheel scrolls the page instead
    const i = Math.max(0, Math.min(detents.length - 1, getIndex() + Math.sign(e.deltaY)));
    if (i === getIndex()) return;
    e.preventDefault();
    setIndex(i);
  }, { passive: false });
  return show;
}

const modeIndex = () => MODES.findIndex((m) => m[0] === state.mode);
const circuitIndex = () => CIRCUITS.findIndex((c) => c[0] === state.circuit);
const setMode = (i) => { state.mode = MODES[i][0]; acquire(); };
const setCircuit = (i) => { state.circuit = CIRCUITS[i][0]; state.win = 0; acquire(); };
buildDetents("#det-source", ".source", SOURCE_DETENTS, SOURCE_CENTER, SOURCE_RIM, MODES.map((m) => m[1]), setMode);
buildDetents("#det-circuit", ".circuit", CIRCUIT_DETENTS, CIRCUIT_CENTER, CIRCUIT_RIM, CIRCUITS.map((c) => c[1]), setCircuit);
const showSource = knob("#knob-source", SOURCE_DETENTS, SOURCE_CENTER, modeIndex, setMode, MODES.map((m) => m[1]));
const showCircuit = knob("#knob-circuit", CIRCUIT_DETENTS, CIRCUIT_CENTER, circuitIndex, setCircuit, CIRCUITS.map((c) => c[1]));

const lever = $("#lever");
lever.addEventListener("click", () => {
  state.backend = state.backend === "FakeBrisbane" ? "FakeTorino" : "FakeBrisbane";
  acquire();
});

function syncControls() {
  showSource();
  showCircuit();
  document.querySelectorAll("#det-source button").forEach((b, i) => b.setAttribute("aria-pressed", i === modeIndex()));
  document.querySelectorAll("#det-circuit button").forEach((b, i) => b.setAttribute("aria-pressed", i === circuitIndex()));
  const torino = state.backend === "FakeTorino";
  lever.setAttribute("aria-checked", torino);
  lever.setAttribute("aria-label", `Backend: ${torino ? "Torino" : "Brisbane"}`);
  history.replaceState(null, "", `?circuit=${state.circuit}&mode=${state.mode}&backend=${state.backend}`);
}

// ---------- acquisition: chase light through the pipeline, then reveal ----------
const keys = [...document.querySelectorAll(".key")];
let chaseTimer = 0;  // one chase light at a time: a superseded run never got to stop its own
function chase() {
  let i = 0;
  const tick = () => { keys.forEach((k, j) => k.classList.toggle("lit", j === i)); i = (i + 1) % keys.length; };
  clearInterval(chaseTimer);
  tick();
  chaseTimer = setInterval(tick, 170);
  return () => { clearInterval(chaseTimer); keys.forEach((k) => k.classList.toggle("lit", k.dataset.stage === "verify")); };
}

async function acquire() {
  syncControls();
  const token = ++state.token;
  panel.classList.add("acquiring");
  const stop = chase();
  const started = performance.now();
  try {
    // Measure only where the knob lands: spinning through detents queues no runs on the server.
    await new Promise((r) => setTimeout(r, 350));
    if (token !== state.token) return;
    const [run, matrix] = await Promise.all([getRun(), getMatrix()]);
    await new Promise((r) => setTimeout(r, Math.max(0, 850 - (performance.now() - started))));
    if (token !== state.token) return;
    state.report = run;
    render(run, matrix);
    log(run);
  } catch (err) {
    if (token !== state.token) return;
    $("#reason").textContent = `Could not measure: ${err.message}. Check that server.py is running, then turn a control to retry.`;
  } finally {
    if (token === state.token) {
      stop();
      panel.classList.remove("acquiring");
      panel.classList.add("revealing");
      setTimeout(() => panel.classList.remove("revealing"), 1200);
    }
  }
}

// ---------- rendering ----------
const fmt = (v, d = 3) => Number(v).toFixed(d);
const pad = (n) => String(n).padStart(3, "0");

function render(r, matrix) {
  const c = r.checks, conf = r.confidentiality;
  $("#prov").textContent = `${r.backend.name} · ${r.backend.qubits}q · seed ${r.seed} · run ${pad(r.run)}`;
  $("#disp-keys").textContent = conf.key_angles;
  const ls = r.stats.locked;
  $("#disp-foot").textContent = `${ls.ops} ops · depth ${ls.depth}`;
  drawTraces($("#traces"), r.views.locked, { x0: 107, x1: 752, y0: 60, y1: 404, win: state.win, axis: true });

  $("#r1-val").textContent = fmt(c.naive.tvd);
  status("#r1-st", c.naive.passed);
  const eq = c.equivalence.verdict;
  $("#r2-val").textContent = eq.startsWith("equivalent") ? "EQUIVALENT" : eq.startsWith("unverifiable") ? "UNVERIFIABLE" : eq.replace(/_/g, " ").toUpperCase();
  status("#r2-st", c.equivalence.passed);
  $("#r3-val").innerHTML = `${fmt(c.fidelity.esp)} <small>vs</small> ${fmt(c.fidelity.esp_baseline)}`;
  status("#r3-st", c.fidelity.passed);

  const v = $("#verdict");
  v.className = `mod verdict ${r.verdict === "ACCEPT" ? "accept" : "reject"}`;
  $("#verdict-word").textContent = r.verdict;
  $("#reason").textContent = r.reason;

  const body = $("#matrix tbody");
  body.innerHTML = "";
  const checks = ["naive_test", "equivalence", "fidelity_audit"];
  matrix.forEach((row, ri) => {
    const tr = document.createElement("tr");
    const label = MODES.find((m) => m[0] === row.mode)[1];
    tr.innerHTML = `<th scope="row"${row.mode === state.mode ? ' aria-current="true"' : ""}>${label}</th>` +
      checks.map((k, ci) => `<td><img class="lamp" style="transition-delay:${(ri * 3 + ci) * 45}ms" src="${row[k] ? LAMP.pass : LAMP.caught}" alt="${row[k] ? "pass" : "caught"}"></td>`).join("");
    body.append(tr);
  });
  const attacks = matrix.filter((m) => m.mode !== "honest");
  setCounter("#cnt-naive", attacks.filter((m) => !m.naive_test).length, attacks.length);
  setCounter("#cnt-tp", attacks.filter((m) => m.verdict === "REJECT").length, attacks.length);

  renderBench(r);
}
function status(sel, ok) {
  const el = $(sel);
  el.textContent = ok ? "PASS" : "FAIL";
  el.className = `st ${ok ? "pass" : "fail"}`;
}
function setCounter(sel, n, d) { $(`${sel} .val`).textContent = `${n}/${d}`; }

// Circuit as traces: wires per qubit, keyed blocks as hatched pulses, CX as connectors.
const SVG = "http://www.w3.org/2000/svg";
function el(tag, attrs, parent) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}
function drawTraces(svg, view, o) {
  svg.innerHTML = "";
  const vb = svg.viewBox.baseVal;
  const n = view.wires.length;
  const span = Math.min(o.y1 - o.y0 - 60, n <= 3 ? 205 : 230);
  const ys = view.wires.map((_, i) => (n === 1 ? (o.y0 + o.y1) / 2 : o.y0 + 67 - (n > 3 ? 17 : 0) + (i * span) / (n - 1)));
  const defs = el("defs", {}, svg);
  view.wires.forEach((_, i) => {
    const pat = el("pattern", { id: `${svg.id}-h${i}`, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    el("rect", { width: 8, height: 8, fill: "rgba(0,0,0,0.35)" }, pat);
    el("line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: WIRE_COLORS[i % WIRE_COLORS.length], "stroke-width": 2.4, opacity: 0.75 }, pat);
  });
  const grid = el("g", { class: "grid" }, svg);
  for (let x = 50, k = 0; x <= vb.width - 20; x += 28.5, k++)
    el("line", { x1: x, y1: o.y0 - 10, x2: x, y2: o.y1, stroke: k % 4 === 0 ? "#34404a" : "#253038", "stroke-width": k % 4 === 0 ? 1.2 : 0.8 }, grid);
  for (let y = o.y0 - 10, k = 0; y <= o.y1; y += 28.5, k++)
    el("line", { x1: 50, y1: y, x2: vb.width - 20, y2: y, stroke: k % 4 === 0 ? "#34404a" : "#253038", "stroke-width": k % 4 === 0 ? 1.2 : 0.8 }, grid);

  const x1 = o.x1 ?? vb.width - 22;
  view.wires.forEach((w, i) => {
    const col = WIRE_COLORS[i % WIRE_COLORS.length];
    el("line", { x1: 50, y1: ys[i], x2: x1, y2: ys[i], stroke: col, "stroke-width": 2.6 }, svg);
    el("circle", { cx: x1, cy: ys[i], r: 3, fill: col }, svg);
    const t = el("text", { x: 12, y: ys[i] + 8, fill: col, "font-size": 23 }, svg);
    t.textContent = w;
  });

  const pulses = el("g", { class: "pulses" }, svg);
  const cols = view.cols;
  const first = Math.max(0, Math.min(o.win || 0, Math.max(0, cols.length - 1)));
  for (let c = first; c < cols.length; c++) {
    const cx = o.x0 + (c - first) * COL_W;
    if (cx > x1 - 30) break;
    for (const g of cols[c]) drawElement(pulses, g, cx, ys, svg.id);
  }
  if (o.axis) {  // one tick every two columns, at the column centres, labelled with the real column index
    const ax = el("g", { class: "axis" }, svg);
    for (let c = first; c < cols.length; c += 2) {
      const x = o.x0 + (c - first) * COL_W;
      if (x > x1 - 30) break;
      el("line", { x1: x, y1: o.y1 - 6, x2: x, y2: o.y1, stroke: "#8fa3b0", "stroke-width": 1.5 }, ax);
      const t = el("text", { x, y: o.y1 + 22, fill: "#8fa3b0", "font-size": 18, "text-anchor": "middle" }, ax);
      t.textContent = c;
    }
  }
}
function drawElement(g, e, cx, ys, id) {
  const qs = e.q, col = (q) => WIRE_COLORS[q % WIRE_COLORS.length];
  if (e.t === "block" || e.t === "gate") {
    const q = qs[0], y = ys[q];
    const keyed = e.t === "block" && e.keys.length;
    const label = keyed ? e.keys[0] : e.t === "block" ? `${e.n}g` : e.label;
    const w = Math.max(80, label.length * 11 + 22);
    const r = el("rect", { x: cx - w / 2, y: y - 18, width: w, height: 36, fill: keyed ? `url(#${id}-h${q})` : "#121a20", stroke: col(q), "stroke-width": 2.2 }, g);
    if (keyed) el("title", {}, r).textContent = `${e.keys.join(" · ")}: ${e.keys.length} hidden angles`;
    const t = el("text", { x: cx, y: y + 7, fill: keyed ? "#f4f1e6" : col(q), "font-size": 19, "text-anchor": "middle",
      stroke: "#121a20", "stroke-width": keyed ? 4 : 0, "paint-order": "stroke" }, g);
    t.textContent = label;
  } else if (e.t === "multi") {
    const ylist = qs.map((q) => ys[q]), top = Math.min(...ylist), bot = Math.max(...ylist);
    const name = e.label.replace(/\(.*/, "");
    if (["CX", "CCX", "MCX", "CNOT"].includes(name)) {
      el("line", { x1: cx, y1: top, x2: cx, y2: bot, stroke: "#eef2f4", "stroke-width": 2.4 }, g);
      qs.slice(0, -1).forEach((q) => el("circle", { cx, cy: ys[q], r: 7, fill: "#eef2f4" }, g));
      const ty = ys[qs[qs.length - 1]];
      el("circle", { cx, cy: ty, r: 13, fill: "#121a20", stroke: "#eef2f4", "stroke-width": 2.4 }, g);
      el("line", { x1: cx - 13, y1: ty, x2: cx + 13, y2: ty, stroke: "#eef2f4", "stroke-width": 2.4 }, g);
      el("line", { x1: cx, y1: ty - 13, x2: cx, y2: ty + 13, stroke: "#eef2f4", "stroke-width": 2.4 }, g);
    } else if (["CZ", "ECR"].includes(name)) {
      el("line", { x1: cx, y1: top, x2: cx, y2: bot, stroke: "#eef2f4", "stroke-width": 2.4 }, g);
      qs.forEach((q) => (name === "CZ" ? el("circle", { cx, cy: ys[q], r: 7, fill: "#eef2f4" }, g)
        : el("rect", { x: cx - 8, y: ys[q] - 8, width: 16, height: 16, fill: "#eef2f4" }, g)));
    } else {
      el("rect", { x: cx - 44, y: top - 18, width: 88, height: bot - top + 36, fill: "#121a20", stroke: "#eef2f4", "stroke-width": 2 }, g);
      const t = el("text", { x: cx, y: (top + bot) / 2 + 7, fill: "#eef2f4", "font-size": 16, "text-anchor": "middle" }, g);
      t.textContent = e.label;
    }
  } else if (e.t === "meas") {
    const y = ys[qs[0]];
    el("rect", { x: cx - 18, y: y - 15, width: 36, height: 30, fill: "#121a20", stroke: "#cfd8dd", "stroke-width": 2 }, g);
    el("path", { d: `M${cx - 11} ${y + 7} A 11 11 0 0 1 ${cx + 11} ${y + 7}`, fill: "none", stroke: "#cfd8dd", "stroke-width": 2 }, g);
    el("line", { x1: cx, y1: y + 7, x2: cx + 8, y2: y - 8, stroke: "#cfd8dd", "stroke-width": 2 }, g);
  }
}

// Pan the display through the whole circuit (the scope's horizontal position) on a horizontal
// wheel or Shift+wheel; a plain vertical wheel scrolls the page.
const screen = $(".display .screen");
screen.addEventListener("wheel", (e) => {
  if (!state.report) return;
  const d = e.shiftKey ? e.deltaX || e.deltaY : Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : 0;
  if (!d) return;
  const cols = state.report.views.locked.cols.length;
  const next = Math.max(0, Math.min(cols - 4, state.win + Math.sign(d) * 2));
  if (next === state.win) return;
  e.preventDefault();
  state.win = next;
  drawTraces($("#traces"), state.report.views.locked, { x0: 107, x1: 752, y0: 60, y1: 404, win: state.win, axis: true });
}, { passive: false });

// ---------- the bench: evidence, inspection, ledger ----------
function renderBench(r) {
  const c = r.checks, ev = r.evidence, conf = r.confidentiality, ov = r.overhead, fd = c.fidelity;
  drawHist($("#hist"), ev);
  $("#ev-specs").innerHTML = spec([
    ["ESP", `<span class="big ${fd.passed ? "good" : "bad"}">${fmt(fd.esp)}</span> returned<br>${fmt(fd.esp_baseline)} honest compile`],
    ["Ratio", `${fmt(fd.ratio, 2)} (needs ≥ ${fd.threshold})`],
    ["Noisy run", `${fmt(ev.fidelity.returned, 2)} returned vs ${fmt(ev.fidelity.baseline, 2)} honest (1 − TVD to ideal)`],
    ["Qubits", `${fd.qubits.join(", ")} on ${r.backend.name}`],
    ["Readout", `${(fd.readout_err_used * 100).toFixed(1)}% used vs ${(fd.readout_err_device_median * 100).toFixed(1)}% device median`],
  ]);
  showView();
  const b = r.blind;
  $("#ins-specs").innerHTML = spec([
    ["Key", `${conf.key_angles} angles stay on your machine`],
    ["Skeleton", `${conf.visible_2q_gates} CX, ${conf.decoy_share_of_2q ? `${Math.round(conf.decoy_share_of_2q * 100)}% decoys; every qubit pair carries the same count`
      : "no decoys needed: every qubit pair already carries the same count"}${conf.pair_count_spread ? ` (spread ${conf.pair_count_spread})` : ""}`],
    ["Secret", b.same ? `<span class="good">${b.total} different secrets → 1 identical view</span>` : `<span class="bad">view changes with the secret</span>`],
    ["Wrong key", `output error ${conf.wrong_key_tvd_random_inputs} vs ${conf.know_nothing_tvd} for a random state`],
    ["Cost", `2q gates ${ov["2q_plain"]} → ${ov["2q_locked"]} · depth ${ov.depth_plain} → ${ov.depth_locked}`],
  ]);
  plantReset(r);
  $("#cost-line").textContent = `Locking adds two-qubit gates after compilation: ${r.circuit.name.split(" ")[0]} goes from ${ov["2q_plain"]} to ${ov["2q_locked"]} on ${r.backend.name}, and depth from ${ov.depth_plain} to ${ov.depth_locked}.`;
}
const spec = (rows) => rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

function drawHist(svg, ev) {
  svg.innerHTML = "";
  const L = 70, R = 880, T = 40, B = 300, keys = ev.outcomes, gw = (R - L) / keys.length;
  for (let k = 0; k <= 4; k++) {
    const y = B - (k / 4) * (B - T);
    el("line", { x1: L, y1: y, x2: R, y2: y, stroke: k ? "#253038" : "#5b6a75", "stroke-width": 1 }, svg);
    const t = el("text", { x: L - 12, y: y + 5, fill: "#8fa3b0", "font-size": 15, "text-anchor": "end" }, svg);
    t.textContent = (k / 4).toFixed(2);
  }
  const series = [["ideal", "none", "#e8eef1"], ["baseline", "#42daea", "#42daea"], ["returned", "#d86aa0", "#d86aa0"]];
  keys.forEach((key, i) => {
    const gx = L + i * gw + gw * 0.18, bw = (gw * 0.64) / 3;
    series.forEach(([s, fill, stroke], j) => {
      const v = ev[s][key] || 0, h = v * (B - T), x = gx + j * bw;
      el("rect", { x: x + 1, y: B - h, width: bw - 3, height: h, fill, stroke, "stroke-width": 2 }, svg);
      if (v >= 0.15) {
        const t = el("text", { x: x + bw / 2, y: B - h - 6, fill: "#c9d3d8", "font-size": 13, "text-anchor": "middle" }, svg);
        t.textContent = v.toFixed(2);
      }
    });
    const t = el("text", { x: L + i * gw + gw / 2, y: B + 24, fill: "#e8eef1", "font-size": 17, "text-anchor": "middle" }, svg);
    t.textContent = key;
  });
  [["Ideal (no noise)", "none", "#e8eef1"], ["Honest compile, noisy device", "#42daea", "#42daea"], ["Returned circuit, noisy device", "#d86aa0", "#d86aa0"]]
    .forEach(([label, fill, stroke], i) => {
      const x = L + i * 270;
      el("rect", { x, y: B + 42, width: 18, height: 14, fill, stroke, "stroke-width": 2 }, svg);
      const t = el("text", { x: x + 26, y: B + 54, fill: "#c9d3d8", "font-size": 15 }, svg);
      t.textContent = label;
    });
}

const VIEW_TITLE = { original: "Your circuit", locked: "Compiler view", final: "Returned, unlocked" };
document.querySelectorAll(".softkeys button").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; showView(); }));
function showView() {
  const r = state.report;
  if (!r) return;
  document.querySelectorAll(".softkeys button").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === state.view));
  const view = r.views[state.view], st = r.stats[state.view];
  $("#ins-title").textContent = `${VIEW_TITLE[state.view]} · ${st.ops} ops · depth ${st.depth}`;
  const svg = $("#ins-traces");
  const width = Math.max(1200, 160 + view.cols.length * COL_W);
  svg.setAttribute("viewBox", `0 0 ${width} 300`);
  svg.style.width = `calc(${width} * var(--u))`;
  drawTraces(svg, view, { x0: 120, x1: width - 30, y0: 30, y1: 270, win: 0, axis: false });
}

function log(r) {
  let tape = [];
  try { tape = JSON.parse(localStorage.getItem("tp-ledger") || "[]"); } catch {}
  const ok = (t) => t && Number.isInteger(t.run) && MODES.some((m) => m[0] === t.mode) && CIRCUITS.some((c) => c[0] === t.circuit)
    && BACKENDS.includes(t.backend) && ["ACCEPT", "REJECT"].includes(t.verdict);
  tape = Array.isArray(tape) ? tape.filter(ok) : [];  // stored by this page, but never trusted into innerHTML
  if (!tape.some((t) => t.run === r.run && t.mode === r.mode && t.circuit === r.circuit.id && t.backend === r.backend.name))
    tape.unshift({ run: r.run, circuit: r.circuit.id, mode: r.mode, backend: r.backend.name, verdict: r.verdict });
  tape = tape.slice(0, 30);
  try { localStorage.setItem("tp-ledger", JSON.stringify(tape)); } catch {}
  $("#tape").innerHTML = tape.length ? tape.map((t) => `<li class="${t.verdict === "ACCEPT" ? "acc" : "rej"}"><b>#${pad(t.run)} ${t.verdict}</b>${MODES.find((m) => m[0] === t.mode)[1]} · ${CIRCUITS.find((c) => c[0] === t.circuit)[1]} · ${t.backend.replace("Fake", "")}</li>`).join("")
    : `<li class="empty">Turn the SOURCE knob to make a run.</li>`;
}

// ---------- measured on real IBM hardware (web/hardware.json, written by bench/compare.py) ----------
fetch("web/hardware.json").then((r) => (r.ok ? r.json() : null)).then((hw) => {
  if (!hw?.runs?.length) return;
  const v = (w) => (w ? `<span class="${w === "ACCEPT" ? "good" : "bad"}">${w}</span>` : "–");  // a panel job's baseline has no verdict
  $("#hw-rows").innerHTML = hw.runs.map((r) => `<tr><td>${r.device}</td><td>${r.circuit}</td>`
    + `<td>${v(r.honest.verdict)} / ${v(r.saboteur.verdict)}</td><td>${fmt(r.honest.measured)}</td><td>${fmt(r.saboteur.measured)}</td></tr>`).join("");
  $("#hw").hidden = false;
}).catch(() => {});

// ---------- plant your own Trojan: /api/plant, or web/plant.json (FakeBrisbane) on a static host ----------
const GATE_LABEL = { x: "X", z: "Z", s: "S", rz: "RZ(0.35)", cx: "CX" };
const POS_LABEL = { start: "at the start", middle: "in the middle", end: "right before measurement" };
let plantSnap = null, plantShown = "";
function plantReset(r) {
  const sel = $("#pl-qubit"), n = r.circuit.qubits;
  $("#plant-form button").disabled = false;  // disabled until the first run says how many qubits there are
  if (sel.options.length !== n) sel.innerHTML = Array.from({ length: n }, (_, i) => `<option value="${i}">q${i}</option>`).join("");
  if (plantShown && plantShown !== `${r.circuit.id}|${r.backend.name}`) {  // the circuit or backend changed under the result
    plantShown = "";
    $("#pl-specs").innerHTML = spec([["Result", "Plant a gate to see what each check says."]]);
    $("#pl-note").textContent = "";
  }
  if (!plantShown) ibm.planted = null;
  ibmSync();
}
async function getPlant(gate, qubit, pos) {
  const snap = await source();
  if (snap) {
    plantSnap ??= await (await fetch("web/plant.json")).json();
    const r = plantSnap.runs[`${state.circuit}|${gate}|${qubit}|${pos}`];
    if (!r || r.error) throw new Error(r ? r.error : "not precomputed");
    return { ...r, backend: { name: plantSnap.backend } };
  }
  const r = await fetch(`/api/plant?circuit=${state.circuit}&backend=${state.backend}&gate=${gate}&qubit=${qubit}&pos=${pos}`);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
$("#plant-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button"), [gate, qubit, pos] = ["#pl-gate", "#pl-qubit", "#pl-pos"].map((s) => $(s).value);
  btn.disabled = true;
  $("#pl-note").textContent = "Measuring…";
  try {
    const p = await getPlant(gate, qubit, pos), c = p.checks;
    const st = (ok) => ` · <b class="${ok ? "good" : "bad"}">${ok ? "PASS" : "FAIL"}</b>`;
    $("#pl-specs").innerHTML = spec([
      ["Planted", `${GATE_LABEL[gate]} on q${qubit} (physical ${p.planted.physical.join(", ")}) ${POS_LABEL[pos]}`],
      ["CH1 Naive", `TVD ${fmt(c.naive.tvd)} (needs < ${c.naive.tol})${st(c.naive.passed)}`],
      ["CH2 QCEC", `${c.equivalence.verdict.replace(/_/g, " ")}${st(c.equivalence.passed)}`],
      ["CH3 Audit", `ESP ratio ${fmt(c.fidelity.ratio, 2)} (needs ≥ ${c.fidelity.threshold})${st(c.fidelity.passed)}`],
      ["Verdict", `<span class="big ${p.verdict === "ACCEPT" ? "good" : "bad"}">${p.verdict}</span>`],
      ["Why", ""],
    ]);
    $("#pl-specs dd:last-of-type").textContent = p.reason;
    plantShown = `${state.circuit}|${state.backend}`;
    ibm.planted = state.snapshot ? null : { gate, qubit, pos };
    $("#pl-note").textContent = state.snapshot ? `Precomputed run of the real pipeline on ${p.backend.name}; run server.py to plant live.` : "";
  } catch (err) {
    plantShown = "";
    ibm.planted = null;
    $("#pl-specs").innerHTML = spec([["Result", "No run: nothing was planted."]]);
    $("#pl-note").textContent = `Could not plant: ${err.message}.`;
  } finally {
    btn.disabled = false;
    ibmSync();
  }
});

// ---------- run on real IBM hardware: only on a live server started with --allow-ibm (403 hides it) ----------
const ibm = { dev: "ibm_fez", status: null, job: null, what: "", timer: 0, planted: null };
const QUEUED_LONG = 10 * 60;  // s: after this, say the queue is slow and point at the recorded runs
const mins = (s) => `${Math.floor(s / 60)} min ${Math.floor(s % 60)} s`;
function ibmWhat() {
  const c = CIRCUITS.find((x) => x[0] === state.circuit)[1], p = ibm.planted;
  return p ? { label: `${c} with your planted ${GATE_LABEL[p.gate]} on q${p.qubit} ${POS_LABEL[p.pos]}`,
               query: `circuit=${state.circuit}&mode=plant&gate=${p.gate}&qubit=${p.qubit}&pos=${p.pos}` }
    : { label: `${c} from the ${MODES.find((m) => m[0] === state.mode)[1]} compiler`, query: `circuit=${state.circuit}&mode=${state.mode}` };
}
function ibmSync() { $("#ibm-what").textContent = ibmWhat().label; }
function ibmNote(text, fallback) {
  const n = $("#ibm-note");
  n.textContent = text;
  if (fallback) {
    const a = document.createElement("a");
    a.href = "#hw";
    a.textContent = "Fallback: see our recorded hardware runs.";
    n.append(" ", a);
  }
}
async function ibmStatus() {
  const r = await fetch(`/api/ibm/status?backend=${ibm.dev}`, { cache: "no-store" });
  if (r.status === 403) return false;
  const s = await r.json(), btn = $("#ibm-form button");
  if (!r.ok) {
    btn.disabled = true;
    $("#ibm-dev").textContent = `Could not read ${ibm.dev}: ${s.error}`;
    return true;
  }
  ibm.status = s;
  const low = s.remaining_seconds != null && s.remaining_seconds < s.min_seconds;
  $("#ibm-dev").textContent = `${s.device} · ${s.operational ? "online" : `offline (${s.status_msg})`} · ${s.pending_jobs} jobs in its queue · `
    + `${s.remaining_seconds == null ? "QPU time not capped" : `${mins(s.remaining_seconds)} QPU time left`} · calibrated ${s.calibration_utc.replace("T", " ").replace("+00:00", " UTC")}`;
  btn.disabled = low || !s.operational || s.submits_left <= 0 || s.in_flight || !!ibm.job;
  if (ibm.job) return true;  // the job's own notes stay up
  if (low) ibmNote(`Quota low: under ${s.min_seconds / 60} minutes of QPU time left, so nothing can be submitted.`, true);
  else if (!s.operational) ibmNote(`${s.device} is not taking jobs right now.`, true);
  else if (s.submits_left <= 0) ibmNote("This server run has used all its submits; restart server.py --allow-ibm for more.", true);
  else if (s.in_flight) ibmNote("A job from this server is still in flight; one at a time.");
  else ibmNote(`Sends one job: 2 circuits × 2000 shots. ${s.submits_left} submits left in this server run.`);
  return true;
}
function ibmShow(j) {
  const fd = j.checks.fidelity, pr = j.predicted_one_minus_tvd, res = j.results, ok = j.verdict === "ACCEPT";
  const st = (pass) => ` · <b class="${pass ? "good" : "bad"}">${pass ? "PASS" : "FAIL"}</b>`;
  const waited = (Date.now() - Date.parse(j.submitted_utc)) / 1000;
  const rows = [
    ["Sent", ""],
    ["Verdict", `<span class="big ${ok ? "good" : "bad"}">${ok ? "ACCEPT" : "REJECT"}</span> decided before the job ran`],
    ["Predicted", `ESP ratio ${fmt(fd.ratio, 2)} (needs ≥ ${j.fidelity_threshold}) · noisy copy 1 − TVD ${fmt(pr.judge)} vs ${fmt(pr.baseline)} honest`],
    ["Job", ""],
    ["Status", j.status === "done" ? `done${j.qpu_seconds != null ? ` · ${fmt(j.qpu_seconds, 0)} s QPU` : ""}${j.queue_seconds != null ? ` · queued ${mins(j.queue_seconds)}` : ""}`
      : j.status === "error" ? '<b class="bad">failed</b>' : `${j.status} · ${mins(Math.max(0, waited))} since submit`],
  ];
  if (res) {
    rows.push(["Measured", `1 − TVD ${fmt(res.judge.one_minus_tvd)} sent vs ${fmt(res.baseline.one_minus_tvd)} honest baseline (ratio ${fmt(res.measured_ratio, 2)})`],
      ["Naive test", `on the real histogram: TVD ${fmt(res.judge.naive_tvd)} (needs < ${j.naive_tol})${st(res.judge.naive_passed)}`]);
    if (res.judge.p_secret != null) rows.push(["P(secret)", `${fmt(res.judge.p_secret)} sent vs ${fmt(res.baseline.p_secret)} honest baseline`]);
  }
  rows.push(["Why", ""]);
  $("#ibm-specs").innerHTML = spec(rows);
  const dd = $("#ibm-specs").querySelectorAll("dd");
  dd[0].textContent = `${ibm.what} on ${j.device}, plus an honest compile of the same lock`;
  const a = document.createElement("a");
  a.href = j.url.startsWith("https://quantum.cloud.ibm.com/") ? j.url : "https://quantum.cloud.ibm.com/workloads";
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "open on IBM Quantum ↗";
  dd[3].append(`${j.job_id} · `, a);
  dd[dd.length - 1].textContent = j.reason;
  if (j.status === "error") ibmNote(`IBM reports the job failed: ${j.error || "no reason given"}.`, true);
  else if (j.status === "queued" && waited > QUEUED_LONG)
    ibmNote(`Queued for ${mins(waited)}: IBM's queue time is unpredictable. The verdict above stands; results appear here when the job runs.`, true);
}
async function ibmPoll() {
  try {
    const r = await fetch(`/api/ibm/job?id=${ibm.job.job_id}`, { cache: "no-store" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    ibmShow(j);
    if (j.status === "done" || j.status === "error") {
      clearInterval(ibm.timer);
      ibm.job = null;
      await ibmStatus();
      if (j.status === "done") ibmNote(`Done. Saved to bench/live_ibm/${j.job_id}.json.`);
      else ibmNote(`IBM reports the job failed: ${j.error || "no reason given"}.`, true);
    }
  } catch (err) {
    ibmNote(`Could not read the job: ${err.message}. Trying again in 10 s.`, true);
  }
}
document.querySelectorAll("#ibm [data-dev]").forEach((b) => b.addEventListener("click", () => {
  ibm.dev = b.dataset.dev;
  document.querySelectorAll("#ibm [data-dev]").forEach((x) => x.setAttribute("aria-checked", x === b));
  $("#ibm-dev").textContent = "Reading the device…";
  ibmStatus().catch((err) => { $("#ibm-dev").textContent = `Could not read ${ibm.dev}: ${err.message}`; });
}));
$("#ibm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button"), what = ibmWhat(), dev = ibm.dev, s = ibm.status;
  if (!s || s.device !== dev || btn.disabled) return;
  if (!confirm(`Submit 2 circuits × 2000 shots to ${dev}?\n\n${what.label}, plus an honest baseline.\n`
    + `${s.pending_jobs} jobs in its queue · ${s.remaining_seconds == null ? "QPU time not capped" : `${mins(s.remaining_seconds)} QPU time left`}.`)) return;
  const tab = window.open("about:blank", "_blank");  // opened inside the click, so no popup blocker
  btn.disabled = true;
  ibmNote("Locking, compiling and verifying on the device's live calibration, then submitting…");
  try {
    const r = await fetch(`/api/ibm/submit?${what.query}&backend=${dev}`, { cache: "no-store" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    ibm.job = j;
    ibm.what = what.label;
    if (tab) { tab.opener = null; tab.location = j.url; }
    ibmShow({ ...j, status: "queued" });
    ibmNote(`Submitted. Checking the job every 10 s. ${j.submits_left} submits left in this server run.`);
    ibm.timer = setInterval(ibmPoll, 10000);
  } catch (err) {
    tab?.close();
    await ibmStatus().catch(() => { btn.disabled = false; });
    ibmNote(`Not submitted: ${err.message}.`, true);
  }
});
source().then((snap) => (snap ? false : ibmStatus())).then((on) => { $("#ibm").hidden = !on; }).catch(() => {});

acquire();
