# Project Plan

Living roadmap. Steps are built in order; design constraints for later steps are recorded now so early code does not block them.

## Shared prediction format (all models)
Every model returns one record per segment:

```
{
  "segment_id": str,          # contract/document id + segment index
  "start": int, "end": int,   # character offsets into the source text
  "labels": [                 # empty list means "none"
    {"label": str, "confidence": float}   # confidence in [0, 1]
  ],
  "model_name": str,          # e.g. "tfidf-ovr-logreg", "claude", "gemini", "transformer", "fireworks-<model>"
  "model_version": str,       # model id / artifact hash / prompt version
  "latency_ms": float,        # wall-clock per prediction (or per batch divided by batch size, stated)
  "cost_usd": float           # per prediction; 0.0 for local models, API usage x published price for hosted ones
}
```
- Every model's confidences are thresholded per class on validation only.
- For LLMs, confidence needs a documented method (for example, a verbalized score or agreement across samples). This is decided in the LLM step.

## Steps
Numbering follows the user's prompts (BUILD_LOG uses the same numbers).

1. **Data (complete).** Load CUAD, choose the label set, hold out a shift set, split 60/20/20 by contract, stratified by type; segment text with the standalone `segment_text()` and label segments from spans (thresholds frozen from train-contract stats). The segment dataset (Step 1g) completes this step.
2. **Baseline (complete).** TF-IDF plus one-vs-rest logistic regression; per-class thresholds (Rule B) tuned on validation; two-round validation-only search; one-time test and shift run.
3. **LLM classifiers.** Claude and Gemini, with prompts iterated on validation only, a response cache in `data/llm_cache/`, and rate limiting. Error analysis feeding prompt design uses validation only.
4. **Evaluation.**
   - 4a (complete): model-agnostic harness `src/evaluate.py`; contract-level bootstrap CIs; paired comparison function (self-comparison exactly zero); baseline calibration on test; baseline error analysis on validation.
   - 4b: pairwise model comparisons once the LLM prediction files exist; calibration analysis across models.
   - Known item for the calibration analysis: the frozen baseline (version 9692b04f03fb) uses no none downsampling, but class_weight="balanced" inflates positive-class probabilities relative to the real none rate. Step 4a confirmed it on test: in the top bin, mean predicted 0.9753 against observed 0.7439 (`data/eval/baseline.json`).
5. **Drift monitoring.** Evaluate on the held-out contract-type shift set; define and test drift checks.
   - Shift set: Franchise (15) and Transportation (13), 28 contracts. No model trains or tunes on them.
   - Report shift results per type (Franchise, Transportation) and combined, next to in-distribution test results.
   - Bootstrap confidence intervals resample whole contracts, not segments, using the config seed.
   - Per-label shift results only for the 17 pre-registered labels in `src/labels.py:SHIFT_MEASURABLE_LABELS` (at least 10 shift contracts each). The other 16 kept labels are listed as not measurable on the shift set.
6. **Additional models.**
   - A fine-tuned transformer (PyTorch, Hugging Face).
     - Known item: check segment length in tokens against the model's input limit before training. Segments reach 1,500 characters and more (max_chars is not a hard cap). Report how many are truncated, or use a sliding window.
   - An open model served on Fireworks.
   - Both use the shared prediction format; dependencies are added to `pyproject.toml` and the lock file is regenerated.

## Pre-registered evaluation rules (fixed 2026-09-23, before any model output existed)
- **Rule A, per-label test reporting.**
  - The main table shows per-label test results only for labels with at least `PER_LABEL_MIN_TEST_CONTRACTS` (10) test contracts.
  - An appendix lists all 33 labels with test contract count, test segment count, and bootstrap CIs. Labels below the bar are marked "insufficient support, not interpreted".
  - Both tables show segment counts next to contract counts.
  - All labels count toward the combined metrics.
- **Rule B, thresholds.**
  - Per-class thresholds are tuned on validation for labels with at least `PER_CLASS_THRESHOLD_MIN_VAL_CONTRACTS` (10) validation contracts.
  - The remaining labels share one threshold, tuned on validation pooled across them.
  - Every model implements this identically.
- **Rule C, shift reporting.** Per-label shift results only for labels with at least `PER_LABEL_MIN_SHIFT_CONTRACTS` (10) shift contracts (`SHIFT_MEASURABLE_LABELS`).
- **Bootstrap.** All bootstrap CIs resample whole contracts, using `config.SEED`.
7. **Service.** FastAPI, accepting text or PDF.
   - PDF path: extract the text layer first, fall back to OCR, run `segment_text()`, then classify.
   - CUAD ships each contract as both PDF and gold text, so text-extraction and OCR quality can be measured against the gold text and reported as its own source of degradation.
8. **Deployment.** Docker image, deployed to GKE and Vercel from the same code.
   - All config comes from environment variables: API keys, model artifact location, enabled models, rate limits.
   - Constraint to verify when we get there: Vercel's Python functions have bundle size limits, so the PyTorch transformer may be GKE-only while Vercel serves the baseline and API-backed models. Record the outcome in BUILD_LOG.

## Design rules that follow from later steps
- `segment_text(text)` takes plain text and returns character-offset segments, with no dependency on CUAD's span format.
- Model code produces the shared prediction record; evaluation code consumes only that record.
- No hardcoded paths, keys, or model names in `service/`. Everything is read from the environment, with defaults in `src/config.py`.
