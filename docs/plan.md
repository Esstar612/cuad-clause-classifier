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
3. **LLM classifiers (complete).** `claude-sonnet-5` and `gemini-3.8-flash`, prompts iterated on validation only, a response cache in `data/llm_cache/`, a persistent spend ledger with a $150 hard cap and a $100 soft checkpoint (Rule E, amended 2026-09-24), and rate limiting. Frozen Claude v2 and Gemini v3, one held-out run each (BUILD_LOG 3ag, 3ah). Design and rules: BUILD_LOG Step 3a.
4. **Evaluation.**
   - 4a (complete): model-agnostic harness `src/evaluate.py`; contract-level bootstrap CIs; paired comparison function (self-comparison exactly zero); baseline calibration on test; baseline error analysis on validation.
   - 4b (complete): pairwise model comparisons (co-primary micro- and macro-F1, Bonferroni family of 12, 10,000 paired resamples); calibration analysis across models; results in `docs/results.md`, generated tables in `data/processed/results_tables.md` (`python -m src.report`).
   - Known item for the calibration analysis: the frozen baseline (version 9692b04f03fb) uses no none downsampling, but class_weight="balanced" inflates positive-class probabilities relative to the real none rate. Step 4a confirmed it on test: in the top bin, mean predicted 0.9753 against observed 0.7439 (`data/eval/baseline.json`).
5. **Drift monitoring (complete).** Evaluate on the held-out contract-type shift set; define and test drift checks. Label-free checks on batches of 5 contracts in `src/drift.py`, calibrated on validation (`models/drift/reference.json`) and evaluated once on test and shift (`data/eval/drift.json`); results in `docs/results.md`, BUILD_LOG Step 5.
   - Shift set: Franchise (15) and Transportation (13), 28 contracts. No model trains or tunes on them.
   - Report shift results per type (Franchise, Transportation) and combined, next to in-distribution test results.
   - Bootstrap confidence intervals resample whole contracts, not segments, using the config seed.
   - Per-label shift results only for the 17 pre-registered labels in `src/labels.py:SHIFT_MEASURABLE_LABELS` (at least 10 shift contracts each). The other 16 kept labels are listed as not measurable on the shift set.
6. **Additional models.**
   - 6a (complete): a fine-tuned transformer (PyTorch, Hugging Face). Three encoders (legal-BERT, BERT, DeBERTa-v3) trained locally on MPS with one fixed recipe. legal-BERT was selected on validation by the pre-registered rule and evaluated once on test and shift. Truncation at 512 tokens is counted per split (4 test and 3 shift segments). Results in `docs/results.md` and BUILD_LOG Step 6a; it is below the baseline on test and cannot be distinguished from it on shift.
   - 6c (complete): a tuned legal-BERT successor, post-hoc (designed after 6a's validation, diagnostic and test results). A 2x2 grid (loss weighting x learning rate) over a 5-epoch schedule with a checkpoint per epoch gave 20 validation candidates; `w-lr2e-5/epoch-4` was selected by the baseline's macro-AP rule and evaluated once on test and shift. It is higher than the baseline on three of four co-primary measures, cannot be distinguished from Claude, and is below Gemini on test (family of 12, with a 24-comparison sensitivity check for the second test look). It does not replace the 6a result. Results in `docs/results.md` and BUILD_LOG Step 6c.
   - 6b (complete): DeepSeek V4.1 Flash served on Fireworks (`accounts/fireworks/models/deepseek-v4p1-flash`), prompted with Gemini's frozen v3 protocol (same instructions and retrieved examples, sparse scoring, batch size 10, Rule B) with no iteration of its own. The smoke gate passed on its first judged invocation, so the GLM fallback was not used. One held-out run: higher than the baseline on all four co-primary measures, cannot be distinguished from Claude, below Gemini on test (family of 12). Results in `docs/results.md` and BUILD_LOG Step 6b.
   - Both use the shared prediction format; dependencies are added to `pyproject.toml` and the lock file is regenerated.
7. **Service, designed for human review.** FastAPI, accepting text or PDF.
   - The output is a review aid, not a decision: highlighted clauses with their confidence, so a lawyer checks every flag. No model's F1 supports unreviewed use.
   - A high-recall operating point (thresholds tuned on validation only) as an option, since a missed clause costs a reviewer more than a false flag.
   - Run-to-run variation (Step 3 and 6b repeat checks) and the label-free drift statistics (Step 5) are surfaced, not hidden.
   - PDF path: extract the text layer first, fall back to OCR, run `segment_text()`, then classify.
   - CUAD ships each contract as both PDF and gold text, so text-extraction and OCR quality can be measured against the gold text and reported as its own source of degradation.
8. **Deployment.** Docker image, deployed to GKE and Vercel from the same code.
   - All config comes from environment variables: API keys, model artifact location, enabled models, rate limits.
   - Constraint to verify when we get there: Vercel's Python functions have bundle size limits, so the PyTorch transformer may be GKE-only while Vercel serves the baseline and API-backed models. Record the outcome in BUILD_LOG.
9. **Fresh test set (non-CUAD).** Contracts from outside the CUAD release, labeled with the Step 1 label schema, as a new held-out set.
   - It removes the contamination caveat for Claude, Gemini and DeepSeek, and gives every frozen model a first look at unseen contracts.
   - Its size, sourcing, labeling protocol and pre-registered comparisons are fixed before any model sees it.
10. **Ensemble.** For example the tuned legal-BERT (6c) with Gemini or DeepSeek, designed on validation only.
   - Evaluated only on Step 9's set. The CUAD test set has already been seen by every component, so it cannot judge a combination chosen after those results.

## Limitations
- **Possible training-data contamination (LLMs).** CUAD and its labels have been public since 2021, so Claude, Gemini and DeepSeek (Step 6b) may have seen them in training. Their scores may therefore be optimistic relative to unseen contracts. The shift set does not avoid this: Franchise and Transportation contracts are part of the same public release. This caveat goes next to every LLM score in the results.
- **No sampling control on current LLMs.** Claude Sonnet 5 rejects temperature; Gemini 3 guidance is to keep the default temperature of 1.0. Run-to-run variation is measured by the Step 3 repeat check and reported, not assumed away.

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
- **Rule D, LLM scores (fixed 2026-09-24, before any LLM output existed).**
  - LLMs return sparse scores: every label with confidence of at least 0.1, with unlisted labels scored 0.
  - The primary cross-model metric is therefore F1 under Rule B thresholds: Rule A labels on test, Rule C labels on shift.
  - LLM AP is reported but flagged "sparse scores, lower bound, not comparable to the baseline's AP".
  - Parse failures count as empty predictions for F1. The none false-positive rate uses successfully parsed segments only. The parse-failure rate is reported as its own line.
- **Rule E, LLM iteration sample and budget fallback (fixed 2026-09-24, before any API call).**
  - Iteration sample: whole validation contracts in the seeded round-robin order, taken until the sample has at least `LLM_ITERATION_MIN_SEGMENTS` (1,500) segments **and** at least one contract from every validation type. Replaces the segment floor alone, which stopped at 9 contracts covering 9 of 23 types.
  - Budget (amended 2026-09-24, after the smoke test and before any labeled output): hard cap $150 (`LLM_BUDGET_USD`), enforced from the ledger. Soft checkpoint at $100 (`LLM_SOFT_CHECKPOINT_USD`): before each paid command, if the ledger total plus that command's projected cost would pass $100, the command stops before any call, prints spend so far and the projection, and runs only after the user approves (`--past-checkpoint`).
  - Budget fallback: applies only if the user declines to continue past the $100 checkpoint. Then these are applied in order, re-projecting after each, until the remaining plan fits under $100:
    1. Maximum prompt versions per model goes from 5 to 3.
    2. The N=1 batch-size check runs on a seeded half of the iteration contracts, rounded up (whole contracts, unstratified), and the N=10 side of that comparison is restricted to the same contracts so the pair stays matched. Logged as a reduced-power check.
    3. Only then, the contract sample of test: whole contracts, stratified by type, saved to `data/processed/llm_eval_contracts.csv`, with every model evaluated on those contracts.
  - Prompt versions (fixed 2026-09-24, after v1 and before any later version ran), each through the adoption rule against the incumbent:
    - v2: per-call output schema, `segments` an object with one required key per target id (S1..Sn) and `additionalProperties: false`; instructions to list only labels at or above 0.1; a Change Of Control note.
    - v3: v2 plus retrieved few-shot examples, the most similar train segments to each window by the frozen baseline TF-IDF vectorizer, with their gold labels. Train only.
    - v4: v3 with dense output (a confidence for all 33 labels per segment).
    - Each version's cost is estimated before it runs; the $100 checkpoint applies.
  - v4 cost gate: before the v4 iteration run, a `--limit 3` smoke test measures its tokens and the remaining plan is re-projected with validation, test and shift run in v4's dense format. If that total cannot fit under the $150 hard cap, v4 is not run at all (rather than run with a result that could not be adopted). The decision is logged either way.
  - v4 gate amendment (2026-09-26, after the v3 results and before any v4 call):
    - Applied per model. Both options fit under $150: v4 for both. Only the Gemini-only option fits (Gemini at v4, Claude's remaining runs at v2): v4 for Gemini, Claude stays on v2. Neither fits: no v4. Reason: Gemini's v4 against its incumbent v3 changes one variable (dense output); Claude's v4 against its incumbent v2 changes two (examples and dense output).
    - A model whose smoke fails is excluded. Failure means: the dense schema is rejected; fewer than 3 smoke records; any smoke call's output above 6,000 tokens or latency above 90 s; any smoke attempt's `retry_errors` entry starting with `connection:`, `408` or `504`; or a smoke segment still unparsed after its retry. Gemini excluded means no v4 for either model (a Claude-only v4 counts as "neither"). Claude excluded leaves at most the Gemini-only branch.
    - If the chosen option projects above the $100 soft checkpoint but under $150, the decision is taken when the gate prints, before any full v4 run, and logged. If the combined option is declined while Gemini-only projects under $100, the gate falls back to Gemini-only. If Gemini-only is also above $100 and is declined, the Rule E fallback applies as written (5 versions to 3, which removes v4).
    - Dense runs have descriptive health only (degenerate-call share, zero-confidence share, mean labels at or above 0.5 per segment) and no held-out invalidation rule: no label-free signal separates an obvious clause scored 0 from a window with no clause when every label is scored.
  - Batch-size outcome (fixed 2026-09-24, before any N=1 output): validation, test and shift run at N=10 whatever the N=1 check shows, because running them at N=1 would cost roughly $250 more by the offline estimate's per-segment rates. If N=1 beats N=10 on the iteration sample (paired unstratified bootstrap, 95% interval excluding zero), that gain is reported as a measured accuracy/cost trade-off on validation, not acted on.

## Design rules that follow from later steps
- `segment_text(text)` takes plain text and returns character-offset segments, with no dependency on CUAD's span format.
- Model code produces the shared prediction record; evaluation code consumes only that record.
- No hardcoded paths, keys, or model names in `service/`. Everything is read from the environment, with defaults in `src/config.py`.
