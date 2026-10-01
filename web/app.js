// Clause Review front end (Step 8). Static; talks to the review API. Text from the API or the user
// only ever reaches the page through text nodes; innerHTML is used for the constant icons below.
const API = (window.API_URL || "").replace(/\/$/, "");
const REPO = "https://github.com/Esstar612/cuad-clause-classifier";
const DEFAULT_LIMITS = { max_upload_mb: 20, max_text_chars: 1000000 };  // until /models reports the service's
const MODELS = {
  "transformer-tuned": { name: "Tuned legal-BERT", desc: "Fine-tuned transformer. The stronger local model." },
  "baseline": { name: "Baseline", desc: "TF-IDF and logistic regression. Fast and simple." },
  "fireworks-deepseek": { name: "DeepSeek V4.1 Flash", desc: "Open-weights LLM on Fireworks. Sends the text to Fireworks." },
};
const POINT_NAMES = { balanced: "Balanced", high_recall: "High recall" };
const POINT_DESC = {
  balanced: "Best balance of precision and recall. Recommended.",
  high_recall: "Catches more clauses, with many more false flags.",
};
// Micro precision on validation at each operating point (docs/results.md, Service (Step 7)).
const VAL_PRECISION = {
  "baseline": { balanced: 0.6667, high_recall: 0.1734 },
  "transformer-tuned": { balanced: 0.6883, high_recall: 0.0454 },
  "fireworks-deepseek": { balanced: 0.6806, high_recall: 0.4724 },
};
const FALLBACK_NOTICES = [
  "Every flag is a suggestion for a lawyer to check; none is a decision.",
  "Unflagged text is not cleared: no model here finds every clause.",
  "Segments marked \"not classified\" were not scored and must be read.",
];

const ICONS = {
  logo: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"><path d="M8 4H5v16h3"/><path d="M16 4h3v16h-3"/><path d="M9.5 9h5M9.5 12h5M9.5 15h3"/></svg>',
  info: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/></svg>',
  file: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/></svg>',
  upload: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>',
  rerun: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  compare: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>',
  up: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
  check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg>',
  alert: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  back: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>',
};

const S = {
  info: null, clauses: { label_order: [], definitions: {} }, loadError: null,
  mode: "pdf", file: null, text: "", model: null, point: "balanced",
  view: "start", error: null, results: {}, docText: "", docName: "", extraction: null,
  active: 0, showAll: false, expanded: new Set(), nfOpen: false, menuOpen: false,
  cmpPick: null, abort: null, started: 0, timer: null, loadingFor: null,
};

const $ = (id) => document.getElementById(id);

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

function icon(name, cls) {
  const span = h("span", { class: cls || null, "aria-hidden": "true", style: "display:inline-flex" });
  span.innerHTML = ICONS[name];  // constant markup, never data
  return span;
}

const modelName = (m) => (MODELS[m] ? MODELS[m].name : m);
const fmt = (x, d = 2) => Number(x).toFixed(d);
const clip = (t, n) => (t.length > n ? `${t.slice(0, n)}…` : t);
// PDFs keep the printed page's line breaks; for reading, join lines and keep blank lines as paragraphs.
const reflow = (t) => t.split(/\n[ \t]*\n\s*/).map((p) => p.replace(/[ \t]*\n[ \t]*/g, " ")).join("\n\n");
const key = (m, p) => `${m}|${p}`;
const result = () => S.results[key(S.model, S.point)];
const limits = () => (S.info && S.info.limits) || DEFAULT_LIMITS;

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.hidden = true; }, 2200);
}

function servedModels() {
  if (!S.info) return [];
  const order = Object.keys(MODELS);
  const rank = (m) => (order.includes(m) ? order.indexOf(m) : order.length);  // unknown models last
  return Object.keys(S.info.served).sort((a, b) => rank(a) - rank(b));
}

const pointsFor = (m) => (S.info && S.info.served[m] ? S.info.served[m].operating_points : ["balanced"]);

function heldOutF1(m) {
  const s = S.info && S.info.served[m] && S.info.served[m].held_out && S.info.served[m].held_out["test | Rule A"];
  return s ? s.macro_f1 : null;
}

function belowTarget(note) {
  const m = /Below the target on validation: (.*)\.$/.exec(note || "");
  return m ? m[1].split(", ") : [];
}

// Text slicing in code points, the unit of the service's offsets.
function segText(s) {
  if (!S.chars) S.chars = Array.from(S.docText);
  return S.chars.slice(s.start, s.end).join("");
}

/* ---------- API ---------- */

async function apiError(resp) {
  let detail = "";
  try { detail = (await resp.json()).detail; } catch (e) { detail = resp.statusText; }
  return { status: resp.status, detail: typeof detail === "string" ? detail : JSON.stringify(detail) };
}

async function classify(model, point, signal) {
  const useFile = S.mode === "pdf" && S.file && !S.extraction;
  let resp;
  if (useFile) {
    const body = new FormData();
    body.append("file", S.file);
    body.append("model", model);
    body.append("operating_point", point);
    resp = await fetch(`${API}/classify/pdf`, { method: "POST", body, signal });
  } else {
    const text = S.extraction ? S.extraction.text : S.docText || S.text;
    resp = await fetch(`${API}/classify`, {
      method: "POST", signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, model, operating_point: point }),
    });
  }
  if (!resp.ok) throw await apiError(resp);
  const out = await resp.json();
  if (out.extraction) S.extraction = out.extraction;
  return out;
}

function explain(err) {
  if (err && err.name === "AbortError") return null;
  if (!err || err.status === undefined) {
    return { where: "global", title: "We could not reach the model server",
             body: "Your contract is still here. Check your connection and try again in a moment." };
  }
  const d = err.detail || "";
  if (err.status === 413 && /file/.test(d)) {
    return { where: "input", title: "This file is too large", body: `${d}. Try a compressed copy, or paste the text.` };
  }
  if (err.status === 413) {
    return { where: "input", title: "This text is too long", body: `${d}. Split the contract and review each part.` };
  }
  if (err.status === 400 && /PDF/i.test(d)) {
    return { where: "input", title: "We could not open this PDF",
             body: "It may be password protected or damaged. Remove the password or export a fresh copy." };
  }
  if (err.status === 422) {
    return { where: "input", title: "No text found",
             body: "Nothing readable came out, even after OCR. Check the pages are not blank, or try a clearer scan." };
  }
  return { where: "global", title: `The review failed (${err.status})`, body: d };
}

async function run(model, point, then) {
  S.error = null;
  if (S.abort) S.abort.abort();
  const ctrl = new AbortController();
  S.abort = ctrl;
  S.loadingFor = { model, point };
  S.started = Date.now();
  const prevView = S.view === "loading" ? S.returnView || "results" : S.view;
  S.returnView = prevView;
  S.view = "loading";
  clearInterval(S.timer);
  render();
  S.timer = setInterval(() => { const el = $("elapsed"); if (el) el.textContent = elapsed(); }, 500);
  try {
    const out = await classify(model, point, ctrl.signal);
    if (S.abort !== ctrl) return;
    S.results[key(model, point)] = out;
    if (!S.docText) {
      S.docText = S.extraction ? S.extraction.text : S.text;
      S.chars = null;
    }
    S.view = prevView === "compare" ? "compare" : "results";
    if (then) then(out);
  } catch (err) {
    if (S.abort !== ctrl) return;
    const e = explain(err);
    S.error = e;
    S.view = (e && e.where === "input") || !result() ? "start" : prevView === "compare" ? "compare" : "results";
  } finally {
    if (S.abort === ctrl) {
      clearInterval(S.timer);
      S.abort = null;
      S.loadingFor = null;
      render();
    }
  }
}

function elapsed() {
  const s = Math.floor((Date.now() - S.started) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ---------- Flags ---------- */

function indices(list, pred) {
  return list.map((x, i) => (pred(x) ? i : -1)).filter((i) => i >= 0);
}

function flagIndex(res) {
  return indices(res.segments, (s) => s.labels.length);
}

function typeCounts(res) {
  const counts = {};
  for (const s of res.segments) for (const l of s.labels) counts[l.label] = (counts[l.label] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function select(i, scroll = true) {
  S.active = i;
  render();
  if (scroll) {
    const el = $(`seg-${i}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function step(dir) {
  S.pickedType = null;
  const res = result();
  if (!res) return;
  const flags = flagIndex(res);
  if (!flags.length) return;
  const pos = flags.indexOf(S.active);
  const next = pos < 0 ? (dir > 0 ? 0 : flags.length - 1) : (pos + dir + flags.length) % flags.length;
  select(flags[next]);
}

function jumpToType(label) {
  const res = result();
  const hits = indices(res.segments, (s) => s.labels.some((l) => l.label === label));
  const after = hits.find((i) => i > S.active);
  S.pickedType = label;
  select(after !== undefined && hits.includes(S.active) ? after : hits[0]);
}

function clauseLines(i) {
  const s = result().segments[i];
  const labels = s.labels.map((l) => `${l.label} ${fmt(l.confidence)}`).join(", ");
  return `Segment ${i + 1} | ${labels}\n${segText(s)}`;
}

async function copy(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done); } catch (e) { toast("Copy failed: the browser blocked the clipboard"); }
}

function exportRows() {
  const res = result();
  const rows = [];
  res.segments.forEach((s, i) => {
    for (const l of s.labels) {
      rows.push({ segment: i + 1, start: s.start, end: s.end, clause_type: l.label, confidence: l.confidence,
                  model: res.model, model_version: res.model_version, operating_point: res.operating_point, text: segText(s) });
    }
    if (!s.scored) {
      rows.push({ segment: i + 1, start: s.start, end: s.end, clause_type: "NOT CLASSIFIED", confidence: "",
                  model: res.model, model_version: res.model_version, operating_point: res.operating_point, text: segText(s) });
    }
  });
  return rows;
}

function download(name, type, body) {
  const a = h("a", { href: URL.createObjectURL(new Blob([body], { type })), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

function exportCsv() {
  const rows = exportRows();
  const cols = ["segment", "start", "end", "clause_type", "confidence", "model", "model_version", "operating_point", "text"];
  const esc = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))];
  download("clause-review.csv", "text/csv", lines.join("\n"));
}

function exportJson() {
  const res = result();
  const body = { document: S.docName, model: res.model, model_version: res.model_version, operating_point: res.operating_point,
                 notices: res.notices, flags: exportRows() };
  download("clause-review.json", "application/json", JSON.stringify(body, null, 2));
}

/* ---------- Header and notices ---------- */

function renderTop() {
  const top = $("top");
  const brand = h("button", { class: "brand", type: "button", "aria-label": "Clause Review, start over", onclick: () => { S.view = "start"; S.error = null; render(); } },
    h("span", { class: "logo" }, icon("logo")), h("span", null, "Clause Review"));
  if (S.view === "start" || !result()) {
    top.replaceChildren(brand, h("span", { class: "pill", style: "margin-left:4px" }, "Review aid"),
      h("nav", { class: "top-right links", "aria-label": "Project" },
        h("a", { href: `${REPO}/blob/main/docs/results.md`, class: "hide-sm" }, "How it was evaluated"),
        h("a", { href: REPO }, "Code and evaluation")));
    return;
  }
  const res = result();
  const pages = S.extraction ? `${S.extraction.pages} pages, ` : "";
  const chip = h("span", { class: "chip" }, icon("file"), h("span", { class: "name" }, S.docName),
    h("span", { class: "faint", style: "white-space:nowrap" }, `${pages}${res.segments_total} segments`));
  const modelSel = h("select", { class: "sel", "aria-label": "Model", onchange: (e) => switchTo(e.target.value, S.point) },
    servedModels().map((m) => h("option", { value: m, selected: m === S.model }, modelName(m))));
  const sw = h("div", { class: "sw", role: "group", "aria-label": "Operating point" },
    ["balanced", "high_recall"].map((p) => h("button", {
      type: "button", class: p === "high_recall" ? "warn" : null, "aria-pressed": String(p === S.point),
      disabled: !pointsFor(S.model).includes(p), onclick: () => switchTo(S.model, p),
    }, POINT_NAMES[p])));
  const exportMenu = h("div", { class: "menu" },
    h("button", { class: "btn btn-p", type: "button", "aria-haspopup": "true", "aria-expanded": String(S.menuOpen),
                  onclick: () => { S.menuOpen = !S.menuOpen; render(); } }, icon("download"), "Export"),
    S.menuOpen ? h("div", { class: "menu-list", role: "menu" },
      h("button", { type: "button", role: "menuitem", onclick: () => { S.menuOpen = false; exportCsv(); render(); } }, "Download CSV"),
      h("button", { type: "button", role: "menuitem", onclick: () => { S.menuOpen = false; exportJson(); render(); } }, "Download JSON"),
      h("button", { type: "button", role: "menuitem", onclick: () => { S.menuOpen = false; copyAll(); render(); } }, "Copy all flags")) : null);
  const canCompare = compareModels().length === 2;
  top.replaceChildren(brand, h("span", { class: "divider" }), chip,
    h("div", { class: "top-right" },
      h("label", { style: "display:inline-flex;align-items:center;gap:8px" }, h("span", { class: "label" }, "Model"), modelSel),
      sw,
      h("button", { class: "btn", type: "button", onclick: () => rerun() }, icon("rerun"), "Re-run"),
      S.view === "compare"
        ? h("button", { class: "btn", type: "button", onclick: () => { S.view = "results"; render(); } }, icon("back"), "Back to document")
        : h("button", { class: "btn", type: "button", disabled: !canCompare, onclick: () => openCompare() }, icon("compare"), "Compare"),
      exportMenu));
}

function renderNotices() {
  const notices = (S.info && S.info.notices) || FALLBACK_NOTICES;
  $("notices").replaceChildren(...notices.map((n) => {
    const lead = /^(.*?:|.*?(?= for | were ))/.exec(n);
    const cut = lead ? lead[0].length : 0;
    return h("span", null, icon("info", "ic"), h("span", null, h("b", null, n.slice(0, cut)), n.slice(cut)));
  }));
}

/* ---------- Start ---------- */

function errorBox(e, actions) {
  return h("div", { class: "err", role: "alert" }, icon("alert", "ic"),
    h("div", null, h("b", null, e.title), h("span", null, e.body), actions ? h("div", { class: "acts" }, actions) : null));
}

function chooseFile(file) {
  S.error = null;
  if (file && file.size > limits().max_upload_mb * 1e6) {
    S.error = { where: "input", title: "This file is too large",
                body: `${file.name} is ${(file.size / 1e6).toFixed(1)} MB; the limit is ${limits().max_upload_mb} MB. Try a compressed copy, or paste the text.` };
    S.file = null;
  } else {
    S.file = file || null;
  }
  render();
}

function startReview() {
  const chars = Array.from(S.text).length;  // code points, as the service counts
  if (S.mode === "paste" && chars > limits().max_text_chars) {
    S.error = { where: "input", title: "This text is too long",
                body: `It has ${chars.toLocaleString()} characters; the limit is ${limits().max_text_chars.toLocaleString()}. Split the contract and review each part.` };
    return render();
  }
  S.results = {};
  S.extraction = null;
  S.docText = "";
  S.chars = null;
  S.docName = S.mode === "pdf" ? S.file.name : "Pasted text";
  S.expanded = new Set();
  S.showAll = false;
  run(S.model, S.point, (out) => { S.active = flagIndex(out)[0] ?? 0; S.pickedType = null; });
}

const ready = () => !!(S.info && S.model && (S.mode === "pdf" ? S.file : S.text.trim()));

function renderStart() {
  const isReady = ready();
  const inputErr = S.error && S.error.where === "input" ? S.error : null;
  const globalErr = S.error && S.error.where !== "input" ? S.error : null;
  const fileInput = h("input", { type: "file", accept: "application/pdf", id: "file", class: "sr", onchange: (e) => chooseFile(e.target.files[0]) });
  const drop = h("div", {
    class: `drop${S.file ? " has" : ""}`, role: "button", tabindex: "0", "aria-label": "Choose a PDF",
    onclick: () => fileInput.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } },
    ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add("over"); },
    ondragleave: (e) => e.currentTarget.classList.remove("over"),
    ondrop: (e) => { e.preventDefault(); chooseFile(e.dataTransfer.files[0]); },
  }, h("span", { class: "big" }, icon("upload")),
    S.file ? [h("strong", null, S.file.name), h("span", null, `${(S.file.size / 1e6).toFixed(1)} MB. Click to choose another file.`)]
           : [h("strong", null, "Drop a PDF here"), h("span", null, "or browse your files"),
              h("span", { class: "faint", style: "font-size:12.5px" }, `PDF up to ${limits().max_upload_mb} MB. Scanned pages are read with OCR.`)]);
  const paste = h("textarea", { class: "paste", placeholder: "Paste the contract text", "aria-label": "Contract text",
    oninput: (e) => { S.text = e.target.value; S.error = null; updateReady(); } });
  paste.value = S.text;
  const tabs = h("div", { class: "tabs", role: "tablist" },
    [["pdf", "Upload PDF"], ["paste", "Paste text"]].map(([m, label]) => h("button", {
      type: "button", role: "tab", "aria-selected": String(S.mode === m), onclick: () => { S.mode = m; S.error = null; render(); } }, label)));
  const models = servedModels();
  const modelCards = models.map((m) => {
    const f1 = heldOutF1(m);
    return h("label", { class: `opt${S.model === m ? " on" : ""}` },
      h("input", { type: "radio", name: "model", checked: S.model === m, onchange: () => { S.model = m; if (!pointsFor(m).includes(S.point)) S.point = "balanced"; render(); } }),
      h("div", null, h("div", { class: "t" }, modelName(m), f1 !== null ? h("span", { class: "pill" }, "Test macro-F1 ", h("span", { class: "num" }, fmt(f1, 4))) : null),
        h("div", { class: "d" }, MODELS[m] ? MODELS[m].desc : ""),
        S.info.served[m].caveat ? h("div", { class: "d", style: "color:var(--warn)" }, S.info.served[m].caveat) : null));
  });
  const pointCards = ["balanced", "high_recall"].map((p) => h("label", {
    class: `opt${S.point === p ? " on" : ""}${p === "high_recall" ? " warnopt" : ""}`,
    style: pointsFor(S.model).includes(p) ? null : "opacity:.5;cursor:not-allowed" },
  h("input", { type: "radio", name: "point", checked: S.point === p, disabled: !pointsFor(S.model).includes(p), onchange: () => { S.point = p; render(); } }),
  h("div", null, h("div", { class: "t" }, POINT_NAMES[p], p === "high_recall" ? h("span", { class: "pill warn" }, "Noisy") : null),
    h("div", { class: "d" }, POINT_DESC[p]))));
  const labels = S.clauses.label_order;
  const featured = ["Governing Law", "Anti-Assignment", "Change Of Control", "Cap On Liability", "Non-Compete", "Expiration Date",
                    "License Grant", "Exclusivity", "Termination For Convenience", "Audit Rights"].filter((l) => labels.includes(l));
  $("app").replaceChildren(h("div", { class: "start" },
    h("section", { class: "hero" },
      h("h1", null, "Find the clauses worth ", h("span", { class: "grad" }, "a second look.")),
      h("p", null, `Add a commercial contract and Clause Review highlights where ${labels.length || 33} clause types from CUAD may appear, so a lawyer knows where to read first. CUAD is 510 contracts labeled by lawyers; the models were trained on its training split and scored once on held-out contracts.`)),
    h("section", { style: "display:flex;flex-direction:column;gap:14px" },
      h("p", { class: "label" }, "Contract"), tabs,
      S.mode === "pdf" ? [drop, fileInput] : paste,
      inputErr ? errorBox(inputErr, [h("button", { class: "btn", type: "button", onclick: () => { S.error = null; render(); } }, "Dismiss")]) : null,
      globalErr ? errorBox(globalErr, [h("button", { class: "btn", type: "button", onclick: () => startReview() }, "Try again")]) : null,
      S.loadError ? errorBox({ title: "We could not reach the model server", body: S.loadError },
                             [h("button", { class: "btn", type: "button", onclick: () => init() }, "Try again")]) : null),
    h("aside", { class: "side" },
      h("section", { style: "display:flex;flex-direction:column;gap:10px" }, h("p", { class: "label" }, "Model"),
        models.length ? modelCards : h("p", { class: "faint" }, S.loadError ? "Models unavailable." : "Loading models...")),
      h("section", { style: "display:flex;flex-direction:column;gap:10px" }, h("p", { class: "label" }, "Sensitivity"), pointCards),
      h("button", { class: "btn btn-p lg", type: "button", id: "review", disabled: !isReady, onclick: startReview },
        isReady ? "Review contract" : S.info && !S.model ? "No model available" : "Add a contract to start"),
      h("section", { style: "display:flex;flex-direction:column;gap:10px" }, h("p", { class: "label" }, "What it looks for"),
        h("div", { class: "chips" }, featured.map((l) => h("span", { title: S.clauses.definitions[l] || "" }, l)),
          labels.length > featured.length ? h("span", { class: "faint" }, `+ ${labels.length - featured.length} more`) : null)))));
}

function updateReady() {
  const btn = $("review");
  if (!btn) return;
  btn.disabled = !ready();
  btn.textContent = ready() ? "Review contract" : "Add a contract to start";
}

/* ---------- Loading ---------- */

function renderLoading() {
  const { model, point } = S.loadingFor || { model: S.model, point: S.point };
  const first = !Object.keys(S.results).length;
  $("app").replaceChildren(h("div", { class: "loading" }, h("div", { class: "card" },
    h("div", { style: "display:flex;gap:16px;align-items:center" }, h("div", { class: "spinner", "aria-hidden": "true" }),
      h("div", null, h("h2", { style: "font-size:20px;letter-spacing:-.01em" }, first ? "Reviewing your contract" : `Running ${modelName(model)}`),
        h("p", { class: "muted", style: "margin-top:4px;line-height:1.5" },
          "The server starts on demand, so the first review after a quiet spell can take up to a minute. After that, reviews take seconds."))),
    h("ol", { class: "steps" },
      h("li", null, h("span", { class: "dot done" }, icon("check")),
        h("div", null, h("div", null, S.mode === "pdf" && !S.extraction ? "PDF sent" : "Text sent"), h("div", { class: "faint" }, S.docName))),
      h("li", null, h("span", { class: "dot now", "aria-hidden": "true" }),
        h("div", null, h("div", null, `${modelName(model)}, ${POINT_NAMES[point].toLowerCase()}`),
          h("div", { class: "faint" }, S.mode === "pdf" && !S.extraction ? "Reading the PDF, then classifying each segment" : "Classifying each segment")))),
    h("div", { style: "display:flex;align-items:center;justify-content:space-between;gap:12px" },
      h("div", null, h("span", { class: "elapsed num", id: "elapsed", "aria-live": "off" }, elapsed()), h("span", { class: "faint" }, " so far")),
      h("button", { class: "btn", type: "button", onclick: () => { if (S.abort) S.abort.abort(); } }, "Cancel")),
    h("p", { class: "faint", style: "font-size:12.5px" }, "Your document stays in this tab; it is sent only to the review server."))));
}

/* ---------- Results ---------- */

function switchTo(model, point) {
  if (!pointsFor(model).includes(point)) point = "balanced";
  S.menuOpen = false;
  const apply = (out) => {
    S.model = model;
    S.point = point;
    const flags = flagIndex(out);
    S.active = flags.includes(S.active) ? S.active : flags[0] ?? 0;
  };
  const cached = S.results[key(model, point)];
  if (cached) {
    apply(cached);
    if (S.view === "compare") openCompare(); else render();
    return;
  }
  run(model, point, (out) => { apply(out); if (S.view === "compare") setTimeout(openCompare); });
}

function rerun() {
  run(S.model, S.point, (out) => {
    const flags = flagIndex(out);
    S.active = flags.includes(S.active) ? S.active : flags[0] ?? 0;
  });
}

function copyAll() {
  const flags = flagIndex(result());
  copy(flags.map(clauseLines).join("\n\n"), `Copied ${flags.length} flagged segments`);
}

function tagClass(c) { return c >= 0.8 ? "tag t-hi" : c >= 0.5 ? "tag t-mid" : "tag t-lo"; }

function renderLeft(res) {
  const flags = flagIndex(res);
  const nc = indices(res.segments, (s) => !s.scored);
  const types = typeCounts(res);
  const found = new Set(types.map(([t]) => t));
  const notFound = S.clauses.label_order.filter((l) => !found.has(l));
  const strip = h("div", { class: "strip", role: "img", "aria-label": "Where flags sit in the document" },
    res.segments.map((s, i) => h("span", { class: !s.scored ? "nc" : s.labels.length ? `f${i === S.active ? " on" : ""}` : null })));
  const ic = res.input_check;
  return h("nav", { class: "left", "aria-label": "Flags" },
    h("section", { style: "display:flex;flex-direction:column;gap:8px" },
      h("p", { class: "label" }, `${modelName(res.model)}, ${POINT_NAMES[res.operating_point].toLowerCase()}`),
      h("div", { style: "display:flex;align-items:baseline;gap:10px" }, h("span", { class: "stat num" }, flags.length),
        h("span", { class: "muted" }, "flagged of ", h("span", { class: "num" }, res.segments_total), " segments")),
      h("div", { style: "display:flex;flex-direction:column;gap:6px" }, strip,
        h("div", { class: "faint", style: "display:flex;justify-content:space-between;font-size:11px" }, h("span", null, "Start"), h("span", null, "Where flags sit"), h("span", null, "End"))),
      h("div", { style: "display:flex;flex-wrap:wrap;gap:6px" },
        h("span", { class: `pill ${nc.length ? "bad" : "ok"}` }, nc.length ? null : icon("check"), h("span", { class: "num" }, nc.length), " not classified"),
        h("span", { class: "pill" }, h("span", { class: "num" }, types.length), " clause types"),
        S.extraction && S.extraction.ocr_pages.length ? h("span", { class: "pill warn" }, h("span", { class: "num" }, S.extraction.ocr_pages.length), " pages OCR") : null),
      h("p", { class: "faint", style: "font-size:12.5px;line-height:1.5" }, S.info.operating_points[res.operating_point])),
    nc.length ? h("section", { style: "display:flex;flex-direction:column;gap:4px" },
      h("p", { class: "label", style: "padding:0 10px 6px;color:var(--bad-ink)" }, "Must read"),
      nc.map((i) => h("button", { type: "button", class: `ct${i === S.active ? " on" : ""}`, onclick: () => select(i) },
        h("span", null, `Not classified, segment ${i + 1}`)))) : null,
    h("section", { style: "display:flex;flex-direction:column;gap:4px" },
      h("p", { class: "label", style: "padding:0 10px 6px" }, "Found ", h("span", { class: "num" }, types.length)),
      types.length ? h("div", { class: "found-list", style: "display:flex;flex-direction:column;gap:4px" },
        types.map(([t, n]) => {
          const on = res.segments[S.active] && res.segments[S.active].labels.some((l) => l.label === t) && S.pickedType === t;
          return h("button", { type: "button", class: `ct${on ? " on" : ""}`, "aria-pressed": String(!!on), title: S.clauses.definitions[t] || "", onclick: () => jumpToType(t) },
            h("span", null, t), h("span", { class: "cnt" }, n));
        })) : h("p", { class: "faint", style: "padding:0 10px;font-size:13px" }, "No clause types flagged at this operating point.")),
    S.clauses.label_order.length ? h("section", { class: "nf-sec", style: "display:flex;flex-direction:column;gap:4px" },
      h("button", { type: "button", class: "ct", "aria-expanded": String(S.nfOpen), onclick: () => { S.nfOpen = !S.nfOpen; render(); } },
        h("span", { class: "label" }, "Not found ", h("span", { class: "num" }, notFound.length)), h("span", { class: "faint", style: "font-size:12px" }, S.nfOpen ? "Hide" : "Show")),
      S.nfOpen ? [h("ul", { class: "nf" }, notFound.map((l) => h("li", { title: S.clauses.definitions[l] || "" }, l))),
                  h("p", { style: "padding:8px 10px 0;font-size:12.5px;color:var(--warn);line-height:1.45" }, "Not found is not the same as absent. Read the contract.")] : null) : null,
    h("section", { class: "about", style: "display:flex;flex-direction:column;gap:12px;margin-top:auto" },
      h("p", { class: "label" }, "About this document"),
      ic ? h("div", { style: "display:flex;flex-direction:column;gap:6px" },
        h("div", { style: "display:flex;justify-content:space-between;gap:8px;font-size:13px" }, h("span", { class: "muted" }, "Unknown words"), h("span", { class: "num" }, `${fmt(100 * ic.oov_rate, 1)}%`)),
        h("div", { class: "meter", "aria-hidden": "true" }, h("div", { class: "fill", style: `width:${ic.validation_percentile}%` }),
          h("div", { class: "mark", style: `left:calc(${ic.validation_percentile}% - 1px)` })),
        h("p", { class: "faint", style: "font-size:12px;line-height:1.45" }, "Percentile ", h("span", { class: "num" }, fmt(ic.validation_percentile, 0)),
          " of validation contracts. Descriptive only: the calibrated drift monitor works on batches of 5 contracts.")) : null,
      S.extraction ? h("div", { class: "kv" },
        h("span", { class: "muted" }, "PDF pages"), h("span", { class: "num" }, S.extraction.pages),
        h("span", { class: "muted" }, "Read with OCR"), h("span", { class: "num" }, S.extraction.ocr_pages.length),
        h("span", { class: "muted" }, "Warnings"), h("span", { class: "num" }, S.extraction.warnings.length)) : null,
      S.extraction && S.extraction.warnings.length ? h("ul", { class: "nf", style: "padding:0;color:var(--warn)" },
        S.extraction.warnings.map((w) => h("li", null, w))) : null));
}

function pageOf(start) {
  const starts = (S.extraction && S.extraction.page_starts) || [];
  let p = 0;
  while (p + 1 < starts.length && starts[p + 1] <= start) p++;
  return p + 1;
}

// One filled dot per correct flag: about 1 in N flags is right.
function dots(precision) {
  const per = 1 / precision;
  const [n, filled] = per < 2 ? [3, Math.round(3 * precision)] : [Math.min(Math.round(per), 30), 1];
  return h("span", { class: "dots", "aria-hidden": "true" },
    Array.from({ length: n }, (_, i) => h("span", { class: i < filled ? "on" : null })));
}

function renderPaper(res) {
  const flags = flagIndex(res);
  const ordinal = new Map(flags.map((i, n) => [i, n + 1]));
  const out = [];
  let lastPage = 0;
  const pageMark = (s) => {
    if (!S.extraction || !S.extraction.page_starts) return;
    const p = pageOf(s.start);
    if (p !== lastPage) {
      if (lastPage) out.push(h("div", { class: "pgbreak" }, `Page ${p}${S.extraction.ocr_pages.includes(p) ? ", read with OCR" : ""}`));
      lastPage = p;
    }
  };
  const segEl = (s, i) => {
    pageMark(s);
    if (!s.scored) {
      return h("div", { id: `seg-${i}`, class: `seg nc${i === S.active ? " on" : ""}`, onclick: () => select(i, false) },
        h("div", { class: "tags" }, h("span", { class: "sn" }, `Seg ${i + 1}`), h("span", { class: "tag t-nc" }, "Not classified: read this")),
        h("p", { class: "doc" }, reflow(segText(s))));
    }
    if (s.labels.length) {
      const labels = [...s.labels].sort((a, b) => b.confidence - a.confidence);
      return h("div", { id: `seg-${i}`, class: `seg f${i === S.active ? " on" : ""}`, onclick: () => select(i, false) },
        h("div", { class: "tags" }, h("span", { class: "mk" }, ordinal.get(i)), h("span", { class: "sn" }, `Seg ${i + 1}`),
          labels.map((l) => h("span", { class: tagClass(l.confidence) }, l.label, " ", h("span", { class: "num" }, fmt(l.confidence))))),
        h("p", { class: "doc" }, reflow(segText(s))));
    }
    return h("div", { id: `seg-${i}`, class: "seg dim" }, h("p", { class: "doc" }, reflow(segText(s))));
  };
  let i = 0;
  const segs = res.segments;
  while (i < segs.length) {
    const s = segs[i];
    if (s.labels.length || !s.scored) { out.push(segEl(s, i)); i++; continue; }
    let j = i;
    while (j < segs.length && segs[j].scored && !segs[j].labels.length) j++;
    const runId = `${i}-${j}`;
    if (S.showAll || S.expanded.has(runId)) {
      for (let k = i; k < j; k++) out.push(segEl(segs[k], k));
      if (!S.showAll) out.push(h("button", { type: "button", class: "gap", onclick: () => { S.expanded.delete(runId); render(); } }, h("b", null, "Hide"), h("span", null, `segments ${i + 1} to ${j}`)));
    } else {
      pageMark(segs[i]);
      const n = j - i;
      out.push(h("button", { type: "button", class: "gap", onclick: () => { S.expanded.add(runId); render(); } },
        h("span", null, `${n} segment${n > 1 ? "s" : ""} without flags (${n > 1 ? `${i + 1} to ${j}` : i + 1})`), h("b", null, "Show")));
    }
    i = j;
  }
  const below = belowTarget(res.operating_point_note);
  const prec = VAL_PRECISION[res.model];
  return h("main", { class: "center" },
    res.operating_point === "high_recall" ? h("div", { class: "banner warn", role: "note" },
      h("div", { style: "display:flex;gap:12px;align-items:flex-start" }, icon("alert", "warn-ic"),
        h("div", { style: "display:flex;flex-direction:column;gap:10px;min-width:0" },
          h("h3", null, "A wide net: many more flags, each less likely to be right"),
          h("p", { style: "line-height:1.5" }, "Use this pass to make sure nothing slipped through, then read each flag with care.",
            prec ? ` On validation data, ${modelName(res.model)}'s precision drops ${prec.high_recall < prec.balanced / 2 ? "sharply" : ""}:`.replace(" :", ":") : ""),
          prec ? h("div", { class: "prec" },
            ["balanced", "high_recall"].map((p) => [h("span", null, POINT_NAMES[p]),
              h("span", { class: "precrow" }, dots(prec[p]), h("span", null, `about 1 in ${fmt(1 / prec[p], 1).replace(/\.0$/, "")} flags correct`))])) : null,
          below.length ? h("div", { class: "below" }, h("b", null, "Still below the 90% recall target:"),
            below.map((l) => h("span", { class: "pill warn", title: S.clauses.definitions[l] || "" }, l)),
            h("span", null, "Read for these yourself.")) : null))) : null,
    S.error && S.error.where === "global" ? h("div", { class: "banner" }, errorBox(S.error, [h("button", { class: "btn", type: "button", onclick: () => { S.error = null; render(); } }, "Dismiss")])) : null,
    h("article", { class: "paper", "aria-label": "Contract" },
      h("p", { class: "dtitle" }, S.docName),
      h("p", { class: "dsub" }, `${modelName(res.model)}, ${POINT_NAMES[res.operating_point].toLowerCase()} · model ${res.model_version}`),
      h("div", { style: "display:flex;justify-content:center;margin:-6px 0 8px" },
        h("button", { type: "button", class: "btn btn-g", onclick: () => { S.showAll = !S.showAll; render(); } },
          S.showAll ? "Collapse text without flags" : "Show all text", " ", h("span", { class: "kbd" }, "U"))),
      out,
      h("p", { class: "end" }, "End of document")));
}

function renderRight(res) {
  const flags = flagIndex(res);
  const s = res.segments[S.active];
  const keys = h("div", { class: "keys" },
    h("span", null, h("span", { class: "kbd" }, "J"), " ", h("span", { class: "kbd" }, "K")), h("span", { class: "muted" }, "Next and previous flag"),
    h("span", null, h("span", { class: "kbd" }, "U")), h("span", { class: "muted" }, "Show text without flags"),
    h("span", null, h("span", { class: "kbd" }, "C")), h("span", { class: "muted" }, "Copy this clause"));
  if (s && !s.scored) {
    return h("aside", { class: "right", "aria-label": "Selected segment" },
      h("p", { class: "label" }, `Segment ${S.active + 1}${S.extraction && S.extraction.page_starts ? `, page ${pageOf(s.start)}` : ""}`),
      h("h2", { style: "font-size:24px;letter-spacing:-.02em;color:var(--bad-ink)" }, "Not classified"),
      h("p", { class: "muted", style: "line-height:1.5" }, "The model did not score this segment, so it cannot say whether a clause is here. Read it in full."),
      h("div", { class: "card excerpt-card" }, h("span", { class: "label" }, "Text"), h("p", { class: "excerpt" }, reflow(segText(s)))), keys);
  }
  if (!flags.length || !s || !s.labels.length) {
    return h("aside", { class: "right", "aria-label": "Selected flag" },
      h("p", { class: "label" }, "No flag selected"),
      h("p", { class: "muted", style: "line-height:1.5" }, flags.length
        ? "Pick a flag in the document or the list, or press J."
        : "No clause flagged at this operating point. Unflagged text is not cleared: read the contract, or try high recall."), keys);
  }
  const labels = [...s.labels].sort((a, b) => b.confidence - a.confidence);
  const pick = labels.find((l) => l.label === S.pickedType) || labels[0];
  const others = labels.filter((l) => l !== pick);
  const pct = Math.round(100 * pick.confidence);
  const text = segText(s);
  return h("aside", { class: "right", "aria-label": "Selected flag" },
    h("div", { style: "display:flex;align-items:center;justify-content:space-between;gap:8px" },
      h("p", { class: "label" }, "Flag ", h("span", { class: "num" }, flags.indexOf(S.active) + 1), " of ", h("span", { class: "num" }, flags.length),
        ", segment ", h("span", { class: "num" }, S.active + 1)),
      h("div", { style: "display:flex;gap:6px" },
        h("button", { class: "btn icon", type: "button", "aria-label": "Previous flag", onclick: () => step(-1) }, icon("up")),
        h("button", { class: "btn icon", type: "button", "aria-label": "Next flag", onclick: () => step(1) }, icon("down")))),
    h("div", { style: "display:flex;flex-direction:column;gap:8px" },
      h("h2", { style: "font-size:24px;font-weight:600;letter-spacing:-.02em;line-height:1.15" }, pick.label),
      h("p", { class: "muted", style: "font-size:13.5px;line-height:1.5" }, S.clauses.definitions[pick.label] || ""),
      S.clauses.source ? h("p", { class: "faint", style: "font-size:11.5px" }, `Definition: ${S.clauses.source}`) : null),
    h("div", { class: "card", style: "flex-direction:row;align-items:center;gap:16px" },
      h("div", { class: "ring", style: `background:conic-gradient(var(--accent) 0 ${pct}%, #E6E8EE ${pct}% 100%)` },
        h("div", { class: "ring-in" }, h("span", { class: "num" }, fmt(pick.confidence)))),
      h("div", { style: "display:flex;flex-direction:column;gap:3px;min-width:0" }, h("span", { class: "label" }, "Model score"),
        h("span", { class: "faint", style: "font-size:12.5px;line-height:1.45" }, "How sure the model is, not the chance it is right."))),
    others.length ? h("div", { class: "card also-wrap" }, h("span", { class: "label" }, "Also flagged in this segment"),
      h("div", { class: "also" }, others.map((l) => h("div", null,
        h("div", { class: "row" }, h("button", { type: "button", class: "btn btn-g", style: "height:auto;padding:0;font-weight:500;color:var(--ink)",
          onclick: () => { S.pickedType = l.label; render(); } }, l.label), h("span", { class: "num" }, fmt(l.confidence))),
        h("div", { class: "bar" }, h("div", { style: `width:${Math.round(100 * l.confidence)}%` })))))) : null,
    h("div", { class: "card excerpt-card" }, h("span", { class: "label" }, "Excerpt"),
      h("p", { class: "excerpt" }, clip(reflow(text), 420))),
    h("div", { class: "copy-row", style: "display:flex;flex-wrap:wrap;gap:8px" },
      h("button", { class: "btn", type: "button", onclick: () => copy(clauseLines(S.active), "Copied this clause") }, icon("copy"), "Copy clause"),
      h("button", { class: "btn", type: "button", onclick: copyAll }, icon("copy"), `Copy all ${flags.length}`)),
    keys);
}

function renderResults() {
  const res = result();
  $("app").replaceChildren(h("div", { class: "shell" }, renderLeft(res), renderPaper(res), renderRight(res)));
}

/* ---------- Compare ---------- */

function compareModels() {
  const other = servedModels().find((m) => m !== S.model && pointsFor(m).includes(S.point));
  return other ? [S.model, other] : [];
}

function openCompare() {
  const pair = compareModels();
  if (pair.length < 2) {
    S.view = "results";
    return render();
  }
  const missing = pair.filter((m) => !S.results[key(m, S.point)]);
  if (missing.length) {
    return run(missing[0], S.point, () => setTimeout(openCompare));
  }
  S.view = "compare";
  S.cmpPick = null;
  S.cmpFilter = "all";
  render();
}

const KINDS = { both: "Agree", a: "Disagree", b: "Disagree", neither: "Neither" };

function compareRows(a, b) {
  const by = (res) => {
    const out = {};
    res.segments.forEach((s, i) => s.labels.forEach((l) => {
      const e = out[l.label] || (out[l.label] = { segs: [], max: 0 });
      e.segs.push(i);
      e.max = Math.max(e.max, l.confidence);
    }));
    return out;
  };
  const A = by(a), B = by(b);
  const types = [...new Set([...S.clauses.label_order, ...Object.keys(A), ...Object.keys(B)])];
  const kind = (t) => (A[t] && B[t] ? "both" : A[t] ? "a" : B[t] ? "b" : "neither");
  const order = { a: 0, b: 0, both: 1, neither: 2 };
  return types.map((t) => ({ type: t, a: A[t], b: B[t], kind: kind(t) }))
    .sort((x, y) => order[x.kind] - order[y.kind] || x.type.localeCompare(y.type));
}

function renderCompare() {
  const [ma, mb] = compareModels();
  const ra = S.results[key(ma, S.point)], rb = S.results[key(mb, S.point)];
  const all = compareRows(ra, rb);
  const count = (k) => all.filter((r) => r.kind === k).length;
  const filter = S.cmpFilter || "all";
  const rows = filter === "all" ? all : all.filter((r) => r.kind === filter);
  const disagree = count("a") + count("b");
  const pick = rows.find((r) => r.type === S.cmpPick) || rows[0];
  const cell = (e) => (e ? [`Seg ${e.segs.map((i) => i + 1).join(", ")}`, " ", h("span", { class: "num faint" }, fmt(e.max))] : h("span", { class: "faint" }, "Not flagged"));
  const head = (m) => { const f1 = heldOutF1(m); return [modelName(m), f1 !== null ? h("span", { class: "num faint" }, ` ${fmt(f1, 4)}`) : null]; };
  const pickRow = (t) => { S.cmpPick = t; render(); };
  let detail;
  if (!pick) {
    detail = h("aside", { class: "card" }, h("p", { class: "muted" }, "No clause types in this group."));
  } else if (pick.kind === "neither") {
    detail = h("aside", { class: "card", style: "position:sticky;top:80px" },
      h("span", { class: "label" }, "Neither model flags this"),
      h("h2", { style: "font-size:20px;letter-spacing:-.01em" }, pick.type),
      h("p", { class: "muted", style: "font-size:13px;line-height:1.5" }, S.clauses.definitions[pick.type] || ""),
      h("p", { style: "font-size:13px;line-height:1.5;color:var(--warn)" }, "Not flagged is not the same as absent. Read the contract."));
  } else {
    const flagger = pick.a ? ma : mb;
    const seg = (pick.a || pick.b).segs[0];
    const res = S.results[key(flagger, S.point)];
    detail = h("aside", { class: "card", style: "position:sticky;top:80px" },
      h("span", { class: "label" }, pick.kind === "both" ? "Both flag" : "Disagreement", ", segment ", h("span", { class: "num" }, seg + 1)),
      h("h2", { style: "font-size:20px;letter-spacing:-.01em" }, pick.type),
      h("p", { class: "muted", style: "font-size:13px;line-height:1.5" }, S.clauses.definitions[pick.type] || ""),
      h("div", { class: "kv" }, h("span", null, modelName(ma)), h("span", { class: "num" }, pick.a ? fmt(pick.a.max) : "No flag"),
        h("span", null, modelName(mb)), h("span", { class: "num" }, pick.b ? fmt(pick.b.max) : "No flag")),
      h("p", { class: "excerpt" }, clip(reflow(segText(res.segments[seg])), 500)),
      h("button", { class: "btn", type: "button", onclick: () => { S.model = flagger; S.view = "results"; S.pickedType = pick.type; select(seg); } }, "Open in document"));
  }
  const groups = [["all", "All clause types", all.length], ["both", "Both flag", count("both")], ["a", `${modelName(ma)} only`, count("a")],
                  ["b", `${modelName(mb)} only`, count("b")], ["neither", "Neither", count("neither")]];
  $("app").replaceChildren(h("div", { class: "compare" },
    h("div", { class: "head" },
      h("div", null, h("p", { class: "label" }, `Both models, ${POINT_NAMES[S.point].toLowerCase()}`),
        h("h1", { style: "font-size:30px;letter-spacing:-.02em;margin-top:6px" }, `${disagree} disagreement${disagree === 1 ? "" : "s"}`),
        h("p", { class: "muted", style: "margin-top:6px" }, "Agreement does not prove either model right. Disagreements are a good place to start reading.")),
      h("div", { class: "counts", role: "group", "aria-label": "Filter clause types" },
        groups.map(([k, label, n]) => h("button", { type: "button", class: `card count${filter === k ? " on" : ""}`, "aria-pressed": String(filter === k),
          onclick: () => { S.cmpFilter = k; S.cmpPick = null; render(); } },
        h("span", { class: "faint", style: "font-size:12px" }, label), h("span", { class: "num" }, n))))),
    h("div", null,
      h("table", { class: "cmp" },
        h("thead", null, h("tr", null, h("th", null, "Clause type"), h("th", null, head(ma)), h("th", null, head(mb)), h("th", null, "Result"))),
        h("tbody", null, rows.length ? rows.map((r) => h("tr", { class: `pick${pick && r.type === pick.type ? " on" : ""}`, onclick: () => pickRow(r.type) },
          h("td", null, h("button", { type: "button", class: "rowbtn", onclick: (e) => { e.stopPropagation(); pickRow(r.type); } }, r.type)),
          h("td", null, cell(r.a)), h("td", null, cell(r.b)),
          h("td", null, h("span", { class: `pill ${r.kind === "both" ? "ok" : r.kind === "neither" ? "" : "warn"}` }, KINDS[r.kind]))))
          : h("tr", null, h("td", { colspan: "4", class: "faint" }, "No clause types in this group.")))),
      h("p", { class: "faint", style: "font-size:12px;margin-top:8px" }, "Numbers next to model names are held-out test macro-F1. Agreement is per clause type, not per segment.")),
    detail));
}

/* ---------- Shell ---------- */

function render() {
  renderTop();
  renderNotices();
  const pair = compareModels();
  const compareReady = pair.length === 2 && pair.every((m) => S.results[key(m, S.point)]);
  if (S.view === "loading") renderLoading();
  else if (S.view === "compare" && compareReady) renderCompare();
  else if ((S.view === "results" || S.view === "compare") && result()) renderResults();
  else renderStart();
}

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (S.view !== "results" || !result()) return;
  const k = e.key.toLowerCase();
  if (k === "j") step(1);
  else if (k === "k") step(-1);
  else if (k === "u") { S.showAll = !S.showAll; render(); }
  else if (k === "c" && result().segments[S.active] && result().segments[S.active].labels.length) copy(clauseLines(S.active), "Copied this clause");
  else if (k === "escape" && S.menuOpen) { S.menuOpen = false; render(); }
});

document.addEventListener("click", (e) => {
  if (S.menuOpen && !e.target.closest(".menu")) { S.menuOpen = false; render(); }
});

async function init() {
  S.loadError = null;
  if (!API) S.loadError = "API_URL is not set in config.js.";
  render();
  if (!API) return;
  const clauses = fetch("clauses.json").then((r) => (r.ok ? r.json() : null)).then((c) => {
    if (c && Array.isArray(c.label_order) && c.definitions && typeof c.definitions === "object") S.clauses = c;
  }).catch(() => {});
  try {
    const resp = await fetch(`${API}/models`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    S.info = await resp.json();
    const models = servedModels();
    if (!models.includes(S.model)) S.model = models[0] || null;
  } catch (err) {
    S.loadError = `Your contract is still here. Try again in a moment. (${err.message || err})`;
  }
  await clauses;
  render();
}

init();
