// Static front end for the review API (Step 8). Response text is only ever set through textContent.
const api = (window.API_URL || "").replace(/\/$/, "");
const $ = (id) => document.getElementById(id);
let served = {};

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

async function load() {
  if (!api) return showError("API_URL is not set in config.js.");
  try {
    const info = await (await fetch(`${api}/models`)).json();
    served = info.served;
    for (const n of info.notices) $("notices").appendChild(el("div", n));
    for (const name of Object.keys(served).sort()) $("model").appendChild(el("option", name));
    points();
  } catch (e) {
    showError(`Could not reach the service: ${e}`);
  }
}

function points() {
  const model = served[$("model").value];
  $("point").replaceChildren(...(model ? model.operating_points : []).map((p) => el("option", p)));
}

function render(text, result) {
  const chars = Array.from(text);  // code points, as the service's offsets are
  const out = $("result");
  out.replaceChildren(el("h2", `${result.model}, ${result.operating_point}`), el("p", result.operating_point_note),
    el("p", `${result.segments_flagged} of ${result.segments_total} segments flagged; ` +
            `${result.segments_not_classified} not classified.`));
  if (result.extraction) {
    const ex = result.extraction;
    out.appendChild(el("p", `PDF: ${ex.pages} pages, OCR on ${ex.ocr_pages.length}.` +
                            (ex.warnings.length ? ` ${ex.warnings.join(" ")}` : "")));
  }
  if (result.input_check) {
    out.appendChild(el("p", `Vocabulary check: ${(100 * result.input_check.oov_rate).toFixed(1)}% unknown words, ` +
      `percentile ${result.input_check.validation_percentile.toFixed(0)} of validation contracts ` +
      `(${result.input_check.note}).`));
  }
  for (const s of result.segments) {
    const box = el("div", undefined, "seg" + (!s.scored ? " unscored" : s.labels.length ? " flag" : ""));
    if (!s.scored) box.appendChild(el("div", "not classified", "labels"));
    if (s.labels.length) {
      box.appendChild(el("div", s.labels.map((l) => `${l.label} ${l.confidence.toFixed(2)}`).join(", "), "labels"));
    }
    box.appendChild(el("div", chars.slice(s.start, s.end).join("")));
    out.appendChild(box);
  }
}

$("model").addEventListener("change", points);

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("error").hidden = true;
  $("submit").disabled = true;
  const model = $("model").value, point = $("point").value, file = $("file").files[0];
  try {
    let resp;
    if (file) {
      const body = new FormData();
      body.append("file", file);
      body.append("model", model);
      body.append("operating_point", point);
      resp = await fetch(`${api}/classify/pdf`, { method: "POST", body });
    } else {
      resp = await fetch(`${api}/classify`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: $("text").value, model, operating_point: point }),
      });
    }
    const result = await resp.json();
    if (!resp.ok) return showError(`${resp.status}: ${result.detail}`);
    render(file ? result.extraction.text : $("text").value, result);
  } catch (e) {
    showError(`Request failed: ${e}`);
  } finally {
    $("submit").disabled = false;
  }
});

load();
