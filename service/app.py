"""Review service (Step 7): contract text or PDF in, flagged clauses out, for a lawyer to check.

  uvicorn service.app:app --port 8000 --workers 1

One worker, so the DeepSeek spend ledger has one owner. Nothing here tunes or changes a model.
"""

from __future__ import annotations

import html
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from scipy.stats import percentileofscore

from src import config
from src.infer import DEEPSEEK, ServiceBudget, ServiceUpstream, load_predictors, records
from src.pdf_text import PdfError, extract
from src.segment import segment_text
from src.service_reference import oov_rate

POINTS = {"balanced": "Rule B thresholds, tuned on validation for F1",
          "high_recall": (f"thresholds lowered toward at least {config.HIGH_RECALL_TARGET:.0%} recall per clause type, "
                          "never above balanced; recall was measured on validation, where the thresholds were tuned, "
                          "and is not a guarantee on new contracts")}
NOTICES = ("Every flag is a suggestion for a lawyer to check; none is a decision.",
           "Unflagged text is not cleared: no model here finds every clause.",
           "Segments marked \"not classified\" were not scored and must be read.")
CONTAMINATION = ("CUAD has been public since 2021, so this model may have seen the evaluation contracts "
                 "in training; its scores may be optimistic on unseen contracts.")


class ClassifyRequest(BaseModel):
    text: str
    model: str
    operating_point: str = "balanced"


def _model_info(name: str, predictor) -> dict:
    info = {"version": predictor.version, "operating_points": sorted(predictor.thresholds),
            "notes": predictor.notes}
    path = config.EVAL_DIR / f"{name}.json"
    if path.exists():
        scopes = json.loads(path.read_text())["scopes"]
        info["held_out"] = {scope: {m: scopes[scope][m]["point"] for m in ("macro_f1", "micro_f1")}
                            for scope in ("test | Rule A", "shift | Rule C") if scope in scopes}
    repeat = config.EVAL_DIR / f"llm_repeat_{name}.json"
    info["repeat_agreement"] = (json.loads(repeat.read_text())["all_runs_exact_agreement"]
                                if repeat.exists() else "not measured")
    if name == DEEPSEEK:
        info["caveat"] = CONTAMINATION
    return info


def _oov(state: dict):
    """Vectorizer and reference rates for the per-document statistic, or the reason it is unavailable."""
    try:
        from src.baseline import load_frozen_pipeline, model_version
        from src.service_reference import load_reference
        return load_frozen_pipeline().named_steps["tfidf"], load_reference(model_version())
    except (SystemExit, Exception) as e:
        state["oov_unavailable"] = f"{type(e).__name__}: {e}"
        return None


def create_app(loader=load_predictors, models=None) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app):
        state["predictors"], state["failed"] = loader(models or config.SERVICE_MODELS)
        if config.SERVICE_REQUIRE_ALL_MODELS and state["failed"]:
            raise RuntimeError(f"models failed to load: {state['failed']}")
        state["oov"] = _oov(state)
        yield

    app = FastAPI(title="CUAD clause review", lifespan=lifespan)
    if config.SERVICE_CORS_ORIGINS:
        app.add_middleware(CORSMiddleware, allow_origins=list(config.SERVICE_CORS_ORIGINS),
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)

    def classify(text: str, model: str, point: str, extraction=None) -> dict:
        predictor = state["predictors"].get(model)
        if predictor is None:
            reason = state["failed"].get(model, "not served")
            raise HTTPException(400, f"model {model!r} unavailable: {reason}")
        if point not in POINTS:
            raise HTTPException(400, f"unknown operating point {point!r}")
        if point not in predictor.thresholds:
            raise HTTPException(400, f"{point} unavailable for {model}: {predictor.notes.get(point, '')}")
        if len(text) > config.SERVICE_MAX_TEXT_CHARS:
            raise HTTPException(413, f"text over {config.SERVICE_MAX_TEXT_CHARS:,} characters")
        segs = segment_text(text)
        if not segs:
            raise HTTPException(422, "no text to classify")
        try:
            scored = predictor.scores([s.text for s in segs])
        except ServiceBudget as e:
            raise HTTPException(402, f"spend cap: {e}") from e
        except ServiceUpstream as e:
            raise HTTPException(502, f"every model call failed: {e}") from e
        recs = records(segs, scored, predictor, point)
        note = " ".join(filter(None, (POINTS[point], predictor.notes.get(point))))
        out = {"model": model, "model_version": predictor.version, "operating_point": point,
               "operating_point_note": note, "notices": list(NOTICES),
               "segments_total": len(recs), "segments_flagged": sum(bool(r["labels"]) for r in recs),
               "segments_not_classified": sum(not r["scored"] for r in recs), "cost_usd": scored.cost_usd,
               "segments": recs}
        if state.get("oov") is not None:
            vectorizer, rates = state["oov"]
            rate = oov_rate([s.text for s in segs], vectorizer)
            out["input_check"] = {"oov_rate": rate, "validation_percentile": float(percentileofscore(rates, rate)),
                                  "note": "descriptive: the calibrated drift monitor (Step 5) works on "
                                          "batches of 5 contracts, not single documents"}
        if extraction is not None:
            out["extraction"] = {"pages": extraction.pages, "ocr_pages": extraction.ocr_pages,
                                 "warnings": extraction.warnings, "text": extraction.text,
                                 "page_starts": extraction.page_starts}
        return out

    async def read_pdf(file: UploadFile):
        data = await file.read()
        if len(data) > config.SERVICE_MAX_UPLOAD_MB * 1e6:
            raise HTTPException(413, f"file over {config.SERVICE_MAX_UPLOAD_MB:g} MB")
        try:
            return extract(data)
        except PdfError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/health")
    def health():
        return {"status": "ok", "models": sorted(state["predictors"])}

    @app.get("/models")
    def models_info():
        return {"served": {n: _model_info(n, p) for n, p in state["predictors"].items()},
                "unavailable": state["failed"], "operating_points": POINTS, "notices": list(NOTICES),
                "limits": {"max_upload_mb": config.SERVICE_MAX_UPLOAD_MB, "max_text_chars": config.SERVICE_MAX_TEXT_CHARS}}

    @app.post("/classify")
    def classify_text(req: ClassifyRequest):
        return classify(req.text, req.model, req.operating_point)

    @app.post("/classify/pdf")
    async def classify_pdf(file: UploadFile = File(...), model: str = Form(...),
                           operating_point: str = Form("balanced")):
        ex = await read_pdf(file)
        return classify(ex.text, model, operating_point, ex)

    @app.get("/", response_class=HTMLResponse)
    def page():
        return _page(state)

    @app.post("/review", response_class=HTMLResponse)
    async def review(text: str = Form(""), model: str = Form(...), operating_point: str = Form("balanced"),
                     file: UploadFile | None = File(None)):
        try:
            if file is not None and file.filename:
                ex = await read_pdf(file)
                text, result = ex.text, classify(ex.text, model, operating_point, ex)
            else:
                result = classify(text, model, operating_point)
        except HTTPException as e:
            return HTMLResponse(_page(state, error=f"{e.status_code}: {e.detail}"), status_code=e.status_code)
        return _page(state, text, result)

    return app


def _page(state: dict, text: str | None = None, result: dict | None = None, error: str | None = None) -> str:
    e = html.escape
    options = "".join(f'<option value="{e(n)}">{e(n)}</option>' for n in sorted(state["predictors"]))
    points = "".join(f'<option value="{e(p)}">{e(p)}</option>' for p in POINTS)
    parts = ["<!doctype html><html><head><meta charset='utf-8'><title>Clause review</title><style>"
             "body{font-family:system-ui,sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem}"
             ".notice{background:#fff4d6;padding:.5rem 1rem;border-left:4px solid #c90}"
             ".flag{background:#dff0ff;border-left:4px solid #06c;display:block;margin:.4rem 0;padding:.3rem}"
             ".unscored{background:#fde2e2;border-left:4px solid #c00;display:block;margin:.4rem 0;padding:.3rem}"
             ".labels{font-size:.85rem;font-weight:600;color:#034}"
             "pre{white-space:pre-wrap;font-family:inherit}</style></head><body>",
             "<h1>Contract clause review</h1>",
             '<div class="notice">' + "<br>".join(e(n) for n in NOTICES) + "</div>",
             '<form method="post" action="/review" enctype="multipart/form-data">'
             '<p><textarea name="text" rows="8" cols="90" placeholder="Paste contract text"></textarea></p>'
             '<p>or PDF: <input type="file" name="file" accept="application/pdf"></p>'
             f'<p>Model <select name="model">{options}</select> '
             f'Operating point <select name="operating_point">{points}</select> '
             '<button type="submit">Review</button></p></form>']
    if state["failed"]:
        parts.append("<p>Unavailable models: " + "; ".join(f"{e(k)} ({e(v)})" for k, v in state["failed"].items())
                     + "</p>")
    if DEEPSEEK in state["predictors"]:
        parts.append(f"<p>{e(DEEPSEEK)} sends the document text to Fireworks.</p>")
    if error:
        parts.append(f'<p class="notice">{e(error)}</p>')
    if result is not None and text is not None:
        parts.append(f"<h2>{e(result['model'])}, {e(result['operating_point'])}</h2>"
                     f"<p>{e(result['operating_point_note'])}</p>"
                     f"<p>{result['segments_flagged']} of {result['segments_total']} segments flagged; "
                     f"{result['segments_not_classified']} not classified.</p>")
        if "input_check" in result:
            ic = result["input_check"]
            parts.append(f"<p>Out-of-vocabulary rate {ic['oov_rate']:.4f}, at the "
                         f"{ic['validation_percentile']:.0f}th percentile of validation contracts "
                         f"({e(ic['note'])}).</p>")
        if "extraction" in result:
            ex = result["extraction"]
            parts.append(f"<p>PDF: {ex['pages']} pages, OCR on {len(ex['ocr_pages'])}. "
                         + " ".join(e(w) for w in ex["warnings"]) + "</p>")
        parts.append("<pre>")
        pos = 0
        for r in result["segments"]:
            parts.append(e(text[pos:r["start"]]))
            body = e(text[r["start"]:r["end"]])
            if not r["scored"]:
                parts.append(f'<span class="unscored"><span class="labels">not classified</span>\n{body}</span>')
            elif r["labels"]:
                tags = ", ".join(f"{e(l['label'])} {l['confidence']:.2f}" for l in r["labels"])
                parts.append(f'<span class="flag"><span class="labels">{tags}</span>\n{body}</span>')
            else:
                parts.append(body)
            pos = r["end"]
        parts.append(e(text[pos:]) + "</pre>")
    parts.append("</body></html>")
    return "".join(parts)


app = create_app()
