# CUAD contract clause classifier

Classifies segments of commercial contracts into 33 clause types (Anti-Assignment, Change Of Control, Governing Law, and so on) using CUAD, a dataset of 510 contracts labeled by lawyers. Six models are compared under one evaluation protocol: a TF-IDF baseline, two prompted proprietary LLMs (Claude and Gemini), an open-weights LLM served on Fireworks (DeepSeek V4.1 Flash), a fine-tuned legal-BERT, and a tuned legal-BERT successor.

The emphasis is on honest evaluation rather than a headline number:
- **Pre-registered rules.** Metrics, thresholds, selection rules and comparison families are written down in `BUILD_LOG.md` before the results they govern exist. For Steps 4b, 5, 6a, 6b and 6c the commit history shows the pre-registration commit before the results commit.
- **One look at test.** Every choice (hyperparameters, prompts, thresholds, model selection) is made on validation. Each model is run once on test.
- **Contract-level splits and a shift set.** Splits are by contract, stratified by contract type. Franchise and Transportation contracts (28) are held out entirely as a distribution-shift set.
- **Paired, contract-level bootstrap.** Model differences use 10,000 paired resamples of whole contracts, with Bonferroni-adjusted intervals across a pre-registered family of 12 comparisons. A difference is claimed only when the adjusted interval excludes zero.
- **Failures are kept.** The fine-tuned transformer (6a) came last on test. That result stays in the record as it is. A tuned successor (6c) was pre-registered afterwards as a separate, post-hoc model, with a stricter interval for the second look at test.

## Results so far

Test (Rule A labels) and shift (Rule C labels), point [95% contract-bootstrap CI], one held-out run per model. From [`docs/results.md`](docs/results.md), which cites the command behind every table.

| Scope | Metric | baseline | claude | gemini | transformer (6a) | transformer-tuned (6c) | deepseek (6b) |
|---|---|---|---|---|---|---|---|
| test \| Rule A | macro-F1 | 0.6311 [0.6043, 0.6532] | 0.6754 [0.6476, 0.7019] | 0.7237 [0.6997, 0.7455] | 0.5408 [0.5180, 0.5591] | 0.6695 [0.6422, 0.6924] | 0.6828 [0.6570, 0.7076] |
| test \| Rule A | micro-F1 | 0.6659 [0.6434, 0.6907] | 0.7156 [0.6920, 0.7404] | 0.7506 [0.7273, 0.7757] | 0.5756 [0.5550, 0.5977] | 0.6886 [0.6650, 0.7131] | 0.7136 [0.6904, 0.7398] |
| shift \| Rule C | macro-F1 | 0.4740 [0.4186, 0.5332] | 0.5246 [0.4749, 0.5853] | 0.5753 [0.5349, 0.6278] | 0.4487 [0.4052, 0.5019] | 0.5449 [0.5013, 0.5913] | 0.5552 [0.4984, 0.6199] |
| shift \| Rule C | micro-F1 | 0.5027 [0.4472, 0.5631] | 0.5688 [0.5254, 0.6224] | 0.5843 [0.5453, 0.6364] | 0.4867 [0.4467, 0.5300] | 0.5763 [0.5329, 0.6181] | 0.5842 [0.5284, 0.6440] |

- Paired comparisons (10,000 contract-level resamples, Bonferroni over each pre-registered family of 12):
  - Gemini is higher than the baseline on both metrics, on test and on shift.
  - 6a is below the baseline, Claude and Gemini on test.
  - 6c is higher than the baseline on 3 of 4 measures, cannot be distinguished from Claude, and is below Gemini on test.
  - DeepSeek (6b), run under Gemini's frozen prompt with no iteration of its own, is higher than the baseline on all 4 measures, cannot be distinguished from Claude, and is below Gemini on test. Its test and shift runs cost $1.12, against $4.53 for Gemini and $9.66 for Claude.
  - The full claim tables, including which claims are marginal, are in `docs/results.md`.
- Contamination caveat: CUAD has been public since 2021, so Claude, Gemini and DeepSeek may have seen these contracts and labels in training. The shift set is part of the same release.

## Steps

| Step | What | Where |
|---|---|---|
| 1 | Data: contract-level splits, shift set, segmentation, span-to-segment labels | BUILD_LOG Step 1, `docs/labeling_schema.md` |
| 2 | Baseline: TF-IDF + one-vs-rest logistic regression, per-class thresholds on validation | BUILD_LOG Step 2 |
| 3 | LLM classifiers: prompt iteration on validation, response cache, spend ledger with a hard cap | BUILD_LOG Step 3 |
| 4 | Evaluation harness, paired comparisons, calibration | BUILD_LOG Step 4, `docs/results.md` |
| 5 | Label-free drift monitoring, calibrated on validation | BUILD_LOG Step 5 |
| 6a | Fine-tuned transformer: three encoders, one fixed recipe, selection on validation | BUILD_LOG Step 6a |
| 6c | Tuned legal-BERT successor, post-hoc: loss-weighting and learning-rate grid, 20 checkpoints, selection on validation | BUILD_LOG Step 6c |
| 6b | Open model on Fireworks: DeepSeek V4.1 Flash under the frozen LLM protocol, judged smoke gate, no prompt iteration | BUILD_LOG Step 6b |
| 7, 8 | Service designed for human review (text or PDF) and deployment (planned) | `docs/plan.md` |
| 9, 10 | Fresh non-CUAD test set, then an ensemble evaluated only on it (planned) | `docs/plan.md` |

## Layout

```
src/            library code; src/config.py holds the seed, paths and every setting
  llm/          LLM classifiers, prompts, cache, budget
tests/          pytest suite (CPU only, no downloads, no API calls)
scripts/        review script, train-fit diagnostic
docs/           plan, results, labeling schema, saved plan reviews
data/           processed outputs, predictions, evaluation JSON (raw data is not committed)
models/         frozen model metadata and thresholds (weights are not committed)
BUILD_LOG.md    dated decisions, pre-registrations, numbers and problems, step by step
```

## Reproducing

Requires Python 3.11 or later.

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps
pytest tests -q
```

Data: download `CUAD_v1.zip` from Zenodo (DOI [10.5281/zenodo.4595826](https://doi.org/10.5281/zenodo.4595826)), unzip it into `data/raw/` so that `data/raw/CUAD_v1/CUAD_v1.json` exists, then:

```
python -m src.data
python -m src.splits
python -m src.build_segments
```

Each later step's commands, in order, are in `BUILD_LOG.md`. LLM steps need `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and `FIREWORKS_API_KEY` in `.env` (see `.env.example`) and cost money; their responses are cached locally.

## Data and license

- CUAD v1: Hendrycks et al., "CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review", NeurIPS 2021 Datasets and Benchmarks, arXiv:2103.06268. Licensed CC BY 4.0. This repository includes derived labels and model predictions keyed by segment id, not contract text.
- Code: MIT, see [`LICENSE`](LICENSE).
