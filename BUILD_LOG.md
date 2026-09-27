# Build Log

One dated entry per completed step, newest at the bottom. Every number must come from pasted output, with the command and file that produced it.

## Entry template

```
## YYYY-MM-DD: <step name>

### What we built

### Decisions made
- Decision:
  - Alternatives considered:
  - Why rejected:

### Numbers measured
- Figure:
  - Command:
  - File:

### Problems hit and how we solved them

### Surprises in the data or results

### Resume-worthy
<one line, or "none">
```

---

## 2026-09-23: Project scaffolding

### What we built
- `CLAUDE.md` with working rules.
- `BUILD_LOG.md` (this file), `docs/labeling_schema.md`, `docs/results.md`.
- `pyproject.toml` (Python 3.11+, sole dependency declaration), `requirements.txt` (generated lock file), `.env.example`, `.gitignore`.
- `src/config.py` holding the global seed and project paths.
- Folders: `data/`, `src/`, `notebooks/`, `service/`, `tests/`, `docs/`.

### Decisions made
- Dependencies declared only in `pyproject.toml`; `requirements.txt` is a generated lock file of pinned versions (`pip freeze --exclude-editable`).
  - Alternatives considered: the same unpinned list mirrored in both files; pyproject only, with no lock file.
  - Why rejected: two hand-maintained lists drift apart; no lock file means runs cannot be reproduced with the exact package versions. Pyproject also enables `pip install -e .` so `src` imports cleanly in tests and the service.
- Single `SEED` constant in `src/config.py`.
  - Alternatives considered: per-component seeds, seeds via environment variables.
  - Why rejected: one source of truth is easier to audit; derived seeds can be computed from it if independent streams are needed.
- LLM response cache at `data/llm_cache/`, gitignored.
  - Alternatives considered: committing the cache for reproducibility.
  - Why rejected: may be large and contain contract text; revisit if reproducibility of LLM runs requires sharing it.

### Numbers measured
None yet.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None yet (no data loaded).

### Resume-worthy
none

---

## 2026-09-23: Environment and lock file

### What we built
- Virtual environment at `.venv/` (Python 3.14, per the `cp314` wheels pip installed).
- Editable install of the project with the dev extra.
- `requirements.txt` generated as a pinned lock file.
- `CLAUDE.md` rule: dependencies are declared only in `pyproject.toml`; the lock file is regenerated after any change.

### Decisions made
- Lock file generated with `pip freeze --exclude-editable`.
  - Alternatives considered: pip-tools (`pip-compile`), uv, Poetry.
  - Why rejected: each adds a tool to install and learn; plain pip is enough for a single-developer project. Revisit if cross-platform or hash-pinned locks become necessary.
- Kept Python 3.14 (the system default) instead of pinning an older interpreter.
  - Alternatives considered: creating the venv with Python 3.11 or 3.12.
  - Why rejected: every dependency installed from a prebuilt 3.14 wheel with no errors, so there was no compatibility reason to downgrade.

### Numbers measured
- 53 pinned packages in `requirements.txt`; the editable project itself is excluded.
  - Command: `pip freeze --exclude-editable > requirements.txt`
  - File: `requirements.txt`
- Pinned versions of direct dependencies: anthropic 1.8.0, fastapi 0.141.1, google-genai 2.25.0, numpy 2.5.3, pandas 3.0.6, pyarrow 25.0.1, pytest 9.1.1, python-dotenv 1.2.3, scikit-learn 1.9.1, uvicorn 0.53.0.
  - Command: `pip install -e ".[dev]"`
  - File: `requirements.txt`
- pip upgraded from 25.2 to 26.2.1.
  - Command: `python -m pip install --upgrade pip`

### Problems hit and how we solved them
None. All packages installed from prebuilt wheels.

### Surprises in the data or results
- pandas resolved to 3.x. pandas 3 changes some defaults compared with 2.x (for example, copy-on-write). Keep this in mind when reading older CUAD example code.
- anthropic 1.8.0 pulls in `httpx2`/`httpcore2`, while google-genai uses `httpx`/`httpcore`. Both HTTP stacks are installed side by side.

### Resume-worthy
none

---

## 2026-09-23: Step 1a, CUAD downloaded, loaded, and inspected

### What we built
- `src/data.py`: loader and inspection report. It reads `CUAD_v1.json`, builds one row per answer span (plus one row per empty contract/category pair), maps contract types from pdf folder names, runs integrity checks, and measures cross-category span overlap. It writes `data/processed/spans.parquet` and `data/processed/contracts.parquet`.
- `src/config.py`: CUAD URL and paths.
- Source: Zenodo DOI 10.5281/zenodo.4595826, `CUAD_v1.zip`, license CC BY 4.0. Citation: Hendrycks et al., NeurIPS 2021, arXiv:2103.06268.

### Decisions made
- Use the Zenodo v1 zip, not the GitHub `data.zip` or HF `cuad-qa`.
  - Alternatives considered: the HF `cuad-qa` loader and its predefined split.
  - Why rejected: that split is a random contract split made for QA. We need our own split, stratified by contract type, with a held-out shift set. Zenodo is the versioned, DOI'd release.
- Contract type is taken from pdf folder names through an explicit mapping; nothing unmatched is dropped silently.
  - Alternatives considered: inferring type from the title string (for example "DISTRIBUTOR AGREEMENT").
  - Why rejected: titles are free text and inconsistent; the folders are the dataset authors' own assignment.
- `contract_id` is the index of the contract's NFC-normalized title in sorted order.
  - Alternatives considered: file order, a hash of the title.
  - Why rejected: file order depends on the filesystem; a hash is harder to read in logs.

### Numbers measured
All from `python -m src.data | tee data/processed/step1_inspect.txt` (output file `data/processed/step1_inspect.txt`).
- Zip SHA-256: `88b694d99007d39777fa44cd72daf8297773d285dc3eab0091ba32078888d18e` (command: `shasum -a 256 data/raw/CUAD_v1.zip`).
- Contracts: 510. Unique titles: 510. Every contract has exactly 1 paragraph (the full text) and 41 category questions.
- Categories: 41.
- (contract, category) pairs: 20,910. Pairs with at least one answer: 6,702.
- Answer spans: 13,823. Spans per non-empty pair: mean 2.06, median 1, max 55.
- Contract types: 25, all 510 pdfs mapped, 0 unmapped folders, 0 titles without a pdf.
  - Per type: Affiliate 10, Agency 13, Co-Branding 22, Collaboration/Cooperation 26, Consulting 11, Development 29, Distributor 32, Endorsement 24, Franchise 15, Hosting 20, IP 17, Joint Venture 23, License 33, Maintenance 34, Manufacturing 17, Marketing 17, Non-Compete/No-Solicit/Non-Disparagement 3, Outsourcing 18, Promotion 12, Reseller 12, Service 28, Sponsorship 31, Strategic Alliance 32, Supply 18, Transportation 13.
- Categories by number of contracts with a label, ranging from Document Name (510 contracts, 521 spans) to Source Code Escrow (13 contracts, 66 spans). The full table is in `data/processed/step1_inspect.txt`.
- Span length (characters): median 196, 25th percentile 37, 75th 365, 90th 587, 99th 1,330, max 3,884. Spans containing a newline: 467.
- Contract length (characters): min 645, median 33,143, mean 52,563, max 338,211.
- Integrity:
  - 0 spans where `context[start:end] != answer_text`.
  - 0 `is_impossible` inconsistencies.
  - 0 exact duplicate spans.
  - 510 of 510 contexts equal their `full_contract_txt` file.
- Overlapping spans within the same (contract, category): 349.
- Spans overlapping a span of a different category: 3,151 of 13,823 (22.8%). Top pairs:
  - Agreement Date / Effective Date: 265
  - License Grant / Non-Transferable License: 216
  - Irrevocable Or Perpetual License / License Grant: 155
  - Cap On Liability / Uncapped Liability: 141
  - Exclusivity / License Grant: 113
- Redaction markers:
  - `***`: in 110 contracts and 648 answer spans.
  - `_____`: in 105 contracts and 42 answer spans.
  - `<omitted>`: 0 contracts.
- `master_clauses.csv`: 510 rows by 83 columns.

### Problems hit and how we solved them
- Contract-type folders are spelled inconsistently: 28 folder names map to 25 types (for example `Affiliate_Agreements` and `Affiliate Agreement`, `Joint Venture` and `Joint Venture _ Filing`). Solved with a normalized mapping. All 510 pdfs mapped and the per-type counts match the datasheet.
- One title (`HarpoonTherapeutics..._Development Agreement`) has a pdf name with an extra `_Option Agreement` suffix. It was resolved by a unique prefix match, which the report prints.

### Surprises in the data or results
- The published figures hold up: 510 contracts, 41 categories, 25 types, and 13,823 spans (the "13,000+ labels" claim).
- The datasheet mentions `<omitted>` splices in answers, but the JSON contains none.
- 349 same-category spans overlap each other, so spans must be merged into their union before labeling segments.
- The Cap On Liability and Uncapped Liability labels overlap 141 times, though they sound mutually exclusive. The likely cause is a cap clause with carve-outs, where the same text is labeled both. This goes in `docs/labeling_schema.md`.
- 110 contracts contain `***` redactions, and 648 labeled spans include them.

### Resume-worthy
Audited CUAD (510 contracts, 41 lawyer-labeled categories, 13,823 spans) end to end: verified every span offset, reconciled 28 inconsistent contract-type folders into 25 types, and quantified 22.8% cross-category span overlap to justify a multi-label design.

---

## 2026-09-23: Step 1b, dataset design decisions

### What we built
- `docs/labeling_schema.md`: label set, span-to-segment rule, and the first ambiguous cases.
- `docs/plan.md`: roadmap, shared prediction format, and design constraints for later steps.

### Decisions made
- **Multi-label task.** Every model outputs a set of labels, each with a confidence; an empty set means none. The baseline is one-vs-rest with per-class thresholds tuned on validation.
  - Alternatives considered: single-label with a "primary" category.
  - Why rejected: 22.8% of spans overlap another category (Step 1a), and pairs like License Grant / Non-Transferable License are both true of the same text.
- **Extraction categories become none.** Document Name, Parties, Agreement Date, and Effective Date are treated as no clause type; segments whose only labels are these become none.
  - Alternatives considered: keep them as labels; remove those segments.
  - Why rejected: they are names and dates, not clause types. Removing the segments would make the none class unrealistically clean.
- **Four answer-type categories kept:** Governing Law, Expiration Date, Renewal Term, Notice Period To Terminate Renewal.
  - Alternatives considered: drop all 8 answer-type categories.
  - Why rejected: their spans are clause length (median 178 to 298 characters) and mark real clauses.
- **Rare categories.** Affiliate License-Licensor and -Licensee merged into Affiliate License. Source Code Escrow, Price Restrictions, and Unlimited/All-You-Can-Eat-License dropped, and segments carrying only those labels are removed. Result: 33 labels plus none.
  - Alternatives considered: keep them and report metrics anyway; relabel their segments as none.
  - Why rejected: 13 to 17 contracts gives about 2 to 4 validation contracts, which is noise. Relabeling real clauses as none teaches the wrong signal.
  - Caveat: the cutoff used label counts from all 510 contracts, including future test contracts. No model output was used.
- **Warranty Duration flagged,** not dropped (GitHub issue #23).
- **None downsampled in train only,** starting at 3:1 none to positive, with the ratio tuned on validation. Validation, test, and shift keep their natural distribution.
  - Alternatives considered: no downsampling; downsampling everywhere.
  - Why rejected: no downsampling makes training slow and dominated by none; downsampling evaluation sets would inflate precision.
- **Split 60/20/20 by contract, stratified by contract type.**
  - Alternatives considered: 70/15/15; a random segment-level split.
  - Why rejected: 70/15/15 leaves too few validation and test contracts for rare categories. A segment-level split leaks contract-specific wording.
- **Segmentation thresholds** will be frozen from statistics on train contracts only.
  - Alternatives considered: stats over all contracts.
  - Why rejected: it keeps validation and test out of every choice, even ones that use no model output.
- **Shift set:** pending the category coverage table for the candidate types.

### Planned later steps (design constraints recorded now; details in `docs/plan.md`)
- **OCR input.** The service will accept PDFs (text layer first, OCR fallback). The segmenter is therefore a standalone `segment_text(text)` with no dependency on CUAD spans. CUAD ships PDFs alongside gold text, so extraction quality can be measured.
- **More models.** A fine-tuned transformer (PyTorch, Hugging Face) and an open model on Fireworks. The shared prediction format includes model name, model version, latency, and cost per prediction from the start.
- **Docker and GKE plus Vercel.** Service config is environment-driven. To verify later: whether Vercel's bundle size limits force the transformer to be GKE-only.

### Numbers measured
None new; the decisions cite Step 1a figures.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None new.

### Resume-worthy
none

---

## 2026-09-23: Step 1c, shift set chosen, split and segmenter code placed

### What we built
- `src/segment.py`: standalone `segment_text(text)` returning character-offset segments. It rejoins hard-wrapped lines, splits blocks over `max_chars` at sentence breaks, and folds pieces under `min_chars` into the next segment.
- `src/labels.py`: category-to-label mapping, span union, span-to-segment labeling, and the pre-registered `SHIFT_MEASURABLE_LABELS`.
- `src/splits.py`: contract-level split with the shift set held out. `tests/test_splits.py`: split integrity and reproducibility tests.
- `src/segment_stats.py`: train-only segmentation statistics over a 3 by 3 threshold grid.
- `src/config.py`: `SHIFT_TYPES` and `SPLIT_FRACTIONS`.

### Decisions made
- **Shift set: Franchise (15) + Transportation (13) = 28 contracts.**
  - Franchise keeps a broad label mix with distinct vocabulary (franchisor, territory, royalties): a vocabulary shift.
  - Transportation has no License Grant contracts and is heavy on Volume Restriction (10 of 13): a label-distribution shift.
  - Alternatives considered: Franchise + Sponsorship (46 contracts); Sponsorship alone (31).
  - Why rejected:
    - Endorsement, Promotion, and Marketing would stay in training, so a Sponsorship shift is mild.
    - It would remove 31 more contracts from train, validation, and test.
    - Sponsorship is thin on Audit Rights (7), Revenue/Profit Sharing (5), and Renewal Term (4) anyway.
- **Cost of the shift set:** No-Solicit Of Customers loses 8 of its 34 contracts (Franchise 7, Transportation 1), leaving 26 for train, validation, and test. That is still above the rarity cutoff.
  - Other kept labels losing 8 or more contracts: Covenant Not To Sue 10 of 100, Volume Restriction 11 of 82, Rofr/Rofo/Rofn 9 of 85, Competitive Restriction Exception 9 of 76, No-Solicit Of Employees 8 of 59.
- **Shift reporting, pre-registered before any model exists:**
  - Results per type and combined, with bootstrap CIs resampling whole contracts.
  - Per-label results only for the 17 labels with at least 10 shift contracts.
  - The other 16 kept labels are listed as not measurable on the shift set.
  - The list is fixed now so it cannot be tuned to results later.
  - Caveat: Affiliate License's shift count comes from two pre-merge columns (Licensee 1, Licensor 1, both Franchise), so its union is 1 or 2 contracts. It is below 10 either way.
- **Split method: per-type shuffle with the config seed, then cut at 60% and 80%.**
  - Alternatives considered: two-stage `sklearn.model_selection.train_test_split` with `stratify`.
  - Why rejected: it needs at least 2 contracts per type in each stage, and Non-Compete/No-Solicit/Non-Disparagement has 3, so the second stage would fail. Grouping small types as "other" does not help because it is the only type under 10. The per-type cut keeps every type within one contract of 60/20/20 and does not depend on input row order.
- **Segmenter handles both paragraph conventions.** It unwraps hard-wrapped lines rather than assuming blank lines separate paragraphs, so the same code works for CUAD text, PDF text layers, and OCR.

### Numbers measured
From the coverage command (`python -c ...` printing per-type contract counts per category), saved as `data/processed/shift_coverage.txt`. These are contracts with at least one span in that category.
- Shift contracts per label, combined (Franchise + Transportation):
  - Governing Law 23 (11+12), Expiration Date 23 (10+13), Anti-Assignment 20 (10+10), Insurance 15 (10+5), Renewal Term 15 (7+8)
  - Cap On Liability 14 (6+8), Minimum Commitment 14 (7+7), Audit Rights 13 (10+3)
  - Non-Compete 11 (10+1), Notice Period To Terminate Renewal 11 (3+8), Revenue/Profit Sharing 11 (10+1), Volume Restriction 11 (1+10)
  - License Grant 10 (10+0), Exclusivity 10 (7+3), Post-Termination Services 10 (8+2), Covenant Not To Sue 10 (9+1), Liquidated Damages 10 (6+4)
- Below 10:
  - Change Of Control 9, Rofr/Rofo/Rofn 9, Competitive Restriction Exception 9, Ip Ownership Assignment 8, No-Solicit Of Employees 8, No-Solicit Of Customers 8, Termination For Convenience 7
  - Uncapped Liability 5, Non-Disparagement 5, Third Party Beneficiary 5, Non-Transferable License 4, Warranty Duration 2, Irrevocable Or Perpetual License 2, Affiliate License 1 or 2, Most Favored Nation 1, Joint Ip Ownership 0

### Problems hit and how we solved them
- The first attempt to share the coverage table pasted the loader output instead. Rerun with `tee` to save it.

### Surprises in the data or results
- Transportation has zero License Grant contracts, while Volume Restriction appears in 10 of its 13.

### Resume-worthy
Designed a held-out contract-type shift set (28 contracts) covering both vocabulary and label-distribution shift, with per-label reporting pre-registered before training so drift results cannot be cherry-picked.

---

## 2026-09-23: Step 1d, split produced, split tests, segment statistics

### What we built
- `data/processed/splits.parquet`: 510 contracts assigned to train, val, test, or shift.
- Segment statistics over a 3 by 3 threshold grid on train contracts only.
- Fixed the synthetic fixture in `tests/test_splits.py` and added a test that the fixture's ids are unique.

### Decisions made
- The segmentation thresholds are proposed below and not yet frozen; they will be logged when frozen.

### Numbers measured
From `python -m src.splits | tee data/processed/splits_report.txt`:
- Contracts per split: train 300, val 96, test 86, shift 28.
- Every in-distribution type is within one contract of 60/20/20. Non-Compete/No-Solicit/Non-Disparagement (3 contracts) went 2/1/0.
- Smallest per-label contract counts (train / val / test / shift):
  - No-Solicit Of Customers 18 / 2 / 6 / 8
  - Most Favored Nation 17 / 4 / 6 / 1
  - Third Party Beneficiary 18 / 7 / 2 / 5
  - Non-Disparagement 22 / 7 / 4 / 5
  - Joint Ip Ownership 30 / 9 / 7 / 0
- Largest: Governing Law 256 / 86 / 72 / 23.

From `pytest tests/test_splits.py -v` (first run):
- 12 passed and 3 failed. All failures were in the synthetic fixture; every test on real data passed, including `test_saved_splits_match_config_seed`.

From `python -m src.segment_stats | tee data/processed/segment_stats.txt` (train contracts only, 300):
- Line structure: 44,260 non-empty lines, median line length 140 characters. 57,532 of 115,079 newlines are part of a blank-line break.
- Grid:

  | max_chars | min_cov | segments | median len | p90 len | over max | none % | excluded | 1 / 2 / 3+ labels (% of positive) | span recall % |
  |---|---|---|---|---|---|---|---|---|---|
  | 1000 | 0.3 | 39,794 | 286 | 896 | 371 | 89.0 | 55 | 80.4 / 14.6 / 5.0 | 100.0 |
  | 1000 | 0.5 | 39,794 | 286 | 896 | 371 | 89.1 | 53 | 80.5 / 14.6 / 4.9 | 100.0 |
  | 1000 | 0.7 | 39,794 | 286 | 896 | 371 | 89.2 | 51 | 80.5 / 14.7 / 4.8 | 99.8 |
  | 1500 | 0.3 | 36,216 | 261 | 1163 | 184 | 88.8 | 52 | 78.4 / 15.3 / 6.3 | 100.0 |
  | 1500 | 0.5 | 36,216 | 261 | 1163 | 184 | 88.9 | 50 | 78.5 / 15.3 / 6.3 | 100.0 |
  | 1500 | 0.7 | 36,216 | 261 | 1163 | 184 | 89.0 | 48 | 78.5 / 15.2 / 6.3 | 99.9 |
  | 2500 | 0.3 | 34,225 | 246 | 1135 | 80 | 88.9 | 49 | 76.2 / 16.5 / 7.2 | 100.0 |
  | 2500 | 0.5 | 34,225 | 246 | 1135 | 80 | 88.9 | 47 | 76.4 / 16.4 / 7.2 | 100.0 |
  | 2500 | 0.7 | 34,225 | 246 | 1135 | 80 | 89.0 | 45 | 76.2 / 16.5 / 7.2 | 99.9 |

- Train segments per label at max_chars=1500, min_cov=0.5: from License Grant 492 down to Most Favored Nation 21 and Third Party Beneficiary 18.
- Segments carrying both Cap On Liability and Uncapped Liability: 96.

### Problems hit and how we solved them
- 3 synthetic-fixture test failures (duplicate ids, contracts in two splits, row-order dependence) were one bug in the test, not the splitter. The fixture built ids with `len(rows) + i` inside a generator passed to `rows.extend`, so `len(rows)` grew during the extend and produced duplicate ids (0, 2, 4, ...). Duplicate ids then broke uniqueness and made sorting ambiguous. Fixed by computing the start id once per type.

### Surprises in the data or results
- `min_coverage` barely matters: from 0.3 to 0.7, none % moves 0.2 points and span recall stays at 99.8% or higher. Spans mostly sit inside a single segment.
- Test got 86 contracts and val 96, although both targets are 20% (about 96). The per-type cut rounds in train's and val's favor (train takes positions below 0.6n, val below 0.8n). Across 23 types this moves about 10 contracts from test to val and train. It is deterministic and uses no label or model information.
- Segments longer than `max_chars` exist (184 at 1500). A short piece (under 50 characters, such as a heading) is folded into the next segment and can push it past the cap.
- The CUAD text is paragraph-per-line: about half of all newlines belong to blank-line breaks, and the median line is 140 characters.

### Resume-worthy
none

---

## 2026-09-23: Step 1e, thresholds frozen, split fix designed, evaluation rules pre-registered

### What we built
- `src/config.py`:
  - `SEGMENT_MIN_CHARS=50`, `SEGMENT_MAX_CHARS=1500`, `SEGMENT_MIN_COVERAGE=0.5`
  - `PER_LABEL_MIN_TEST_CONTRACTS=10`, `PER_LABEL_MIN_SHIFT_CONTRACTS=10`, `PER_CLASS_THRESHOLD_MIN_VAL_CONTRACTS=10`
- `segment_text()` defaults now read from config.
- `tests/test_splits.py`: tests that val and test are within one contract overall and per type, and that train is the rounded 60% share per type.
- `docs/plan.md` (pre-registered rules), `docs/results.md` (rule lists and appendix template), `docs/labeling_schema.md` (frozen thresholds and the max_chars caveat).

### Decisions made
- **Segmentation frozen at max_chars=1500, min_coverage=0.5, min_chars=50**, from train-only stats (Step 1d).
  - Alternatives considered: max_chars 1000 or 2500; min_coverage 0.3 or 0.7.
  - Why rejected:
    - 1000 splits spans longer than 1,000 characters; the 99th-percentile span is 1,330.
    - 2500 raises the multi-label share by merging adjacent clauses (23.6% vs 21.6% of positive segments).
    - min_coverage changed none % by at most 0.2 points across 0.3 to 0.7, so the midpoint was chosen.
  - `max_chars` is documented as not a hard cap (headings are folded forward).
  - Known item for the fine-tuning step: check segment token lengths against the transformer's input limit and report truncation.
- **Split fix: val and test balanced to within one contract.**
  - The original per-type cut gave val 96 and test 86 because rounding favored train and val.
  - New rule:
    - Per type, train gets `round_half_up(0.6 n)`.
    - The remainder is split evenly between val and test.
    - When the remainder is odd, the extra contract goes to whichever of val and test has fewer so far (types taken in sorted order).
    - Contracts within a type are still shuffled with `config.SEED`.
  - The fix is mechanical and outcome-blind. It uses only per-type contract counts, never labels, and was made before any model output existed. It was prompted by the size imbalance, not by any label or metric.
  - Alternatives considered: keep 96/86 and document it.
  - Why rejected: rare labels need every test contract. Nothing downstream existed yet, so the rerun cost was low.
- **Rule A (pre-registered 2026-09-23): per-label test reporting.**
  - The main table shows labels with at least 10 test contracts.
  - An appendix covers all 33 labels with test contract and segment counts and contract-bootstrap CIs; labels below the bar are marked "insufficient support, not interpreted".
- **Rule B (pre-registered 2026-09-23): thresholds.**
  - Per-class thresholds for labels with at least 10 validation contracts.
  - The remaining labels share one threshold tuned on validation pooled across them.
  - Identical for every model.
- Both rules are applied to the post-fix split. The label lists are logged after the rerun.

### Numbers measured
None new. The rerun results will be logged in the next entry.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None new.

### Resume-worthy
Pre-registered evaluation rules (support thresholds for per-label reporting and per-class threshold tuning) before any model was trained, and fixed a split imbalance with an outcome-blind rule.

---

## 2026-09-23: Step 1f, split fix applied, rule lists fixed, Step 1 complete

### What we built
- The balanced split fix in `src/splits.py`; `data/processed/splits.parquet` regenerated.
- The label lists for Rules A, B, and C, recorded in `docs/results.md`.

### Decisions made
- **Rule A lists (fixed 2026-09-23):**
  - Main test table: 26 labels.
  - Appendix only, test contracts in parentheses: Third Party Beneficiary (3), Non-Disparagement (6), Most Favored Nation (6), No-Solicit Of Customers (7), Joint Ip Ownership (9), Affiliate License (9), Irrevocable Or Perpetual License (9).
- **Rule B lists (fixed 2026-09-23):**
  - Per-class thresholds: 28 labels.
  - Shared pooled threshold, validation contracts in parentheses: No-Solicit Of Customers (1), Non-Disparagement (5), Most Favored Nation (5), Third Party Beneficiary (7), Joint Ip Ownership (8).
- **Rule C:** unchanged (17 labels); the shift set does not depend on the split.
- **Frozen segmentation settings confirmed** on the new train set; see the numbers below. No change.

### Numbers measured
From `python -m src.splits | tee data/processed/splits_report.txt`:
- Contracts per split: train 289, val 97, test 96, shift 28. Before the fix: 300 / 96 / 86 / 28.
- Per type, val and test differ by at most one contract. Non-Compete/No-Solicit/Non-Disparagement (3 contracts) went 2/1/0.
- Moved from the appendix list to the main table by the fix: No-Solicit Of Employees (9 to 12 test contracts) and Competitive Restriction Exception (9 to 13).

From `pytest tests/test_splits.py -v`: 20 passed.

From `python -m src.segment_stats | tee data/processed/segment_stats.txt` (289 train contracts):
- At the frozen settings (1500, 0.5):
  - 34,921 segments, median length 260, 90th percentile 1,168, 178 segments over 1,500.
  - 88.9% none, 50 excluded.
  - Positive segments by label count: 78.5% one label, 15.5% two, 6.1% three or more.
  - Span recall 100.0%.
- The other grid cells show the same pattern as before the fix: min_coverage moves none % by at most 0.2 points, and multi-label share rises with max_chars.
- Smallest train segment counts: Third Party Beneficiary 17, Most Favored Nation 20, No-Solicit Of Customers 22.
- Cap On Liability plus Uncapped Liability on one segment: 95.

### Problems hit and how we solved them
None.

### Surprises in the data or results
- No-Solicit Of Customers has 1 validation contract after the fix (2 before). Its threshold comes entirely from the pooled group, and its validation metrics are close to meaningless.
- The fix moved No-Solicit Of Customers test contracts from 6 to 7 and Third Party Beneficiary from 2 to 3. Both remain below the Rule A bar.

### Step 1 summary
- CUAD verified: 510 contracts, 41 categories, 25 contract types, 13,823 spans.
- Task: multi-label over 33 labels plus none, on paragraph-like segments.
- Data: contract-level 289/97/96 split, stratified by type, with a 28-contract shift set (Franchise, Transportation) held out.
- Segmentation thresholds frozen from train only. Reporting and threshold rules pre-registered before any model output.

### Resume-worthy
Built a leakage-proof evaluation setup for CUAD: contract-level stratified 289/97/96 splits with a held-out contract-type shift set, 20 passing split-integrity tests, and reporting rules pre-registered before training.

---

## 2026-09-24: Step 1g, segment dataset built (completes Step 1)

Recorded as the completion of Step 1, although it runs as part of Step 2.

### What we built
- `src/build_segments.py`: writes `data/processed/segments.parquet` (all 510 contracts, frozen segmentation settings). Excluded segments are kept with `exclude=True` and filtered at load.
- Shared modules for every model: `src/predictions.py` (shared prediction format), `src/metrics.py`, `src/thresholds.py` (Rule B).
- Tests: `tests/test_build_segments.py`, `tests/test_thresholds.py`, `tests/test_downsampling.py`, `tests/test_predictions.py`.
- `joblib` added to `pyproject.toml` as a direct dependency; lock file regenerated.

### Decisions made
- Excluded segments stay in the parquet file, flagged, rather than being deleted.
  - Alternatives considered: dropping them at build time.
  - Why rejected: keeping them lets the exclusion counts be audited and tested.
- Rule A and B lists stay defined on span-based contract counts, as pre-registered. The segment-based counts are reported alongside.

### Numbers measured
From `python -m src.build_segments | tee data/processed/build_segments_report.txt` (60,600 segments written):

| split | segments | excluded | positive | none | none from extraction-only | none % |
|---|---|---|---|---|---|---|
| train | 34,921 | 50 | 3,829 | 31,042 | 722 | 89.0 |
| val | 11,661 | 5 | 1,336 | 10,320 | 199 | 88.5 |
| test | 9,433 | 55 | 1,211 | 8,167 | 257 | 87.1 |
| shift | 4,585 | 1 | 613 | 3,971 | 74 | 86.6 |

- 33 labels present.
- For all 33 labels, contracts-with-a-labeled-segment per split equal the span-based counts in `data/processed/splits_report.txt`. No lawyer-labeled contract lost its label in segmentation.
- Test segment counts per label (Rule A appendix) are recorded in `docs/results.md`: from Cap On Liability 121 and License Grant 112 down to Third Party Beneficiary 3.

From `pytest tests -v`: 41 passed.

### Problems hit and how we solved them
None in this part. The crash in the first baseline search is logged with Step 2.

### Surprises in the data or results
- Test has 55 excluded segments against 5 in validation, so test contains noticeably more rare-dropped clause text.
- Rare labels cluster in a few contracts on the shift set: No-Solicit Of Customers has 18 shift segments from 8 contracts, against 2 validation segments from 1 contract.
- 722 train segments became none only because their sole categories were extraction ones (Parties, dates, Document Name). They are the hard negatives the extraction-to-none decision created.

### Resume-worthy
none

---

## 2026-09-24: Step 2a, baseline search on validation (test not yet touched)

### What we built
- `src/baseline.py`: TF-IDF plus one-vs-rest logistic regression.
  - `search` runs the 64-configuration grid on validation, selects by macro-AP, tunes Rule B thresholds for the chosen configuration, and saves the artifacts.
  - `heldout` is the guarded one-time test and shift run.
- Artifacts in `models/baseline/`: `model.joblib`, `thresholds.json`, `labels.json`, `config.json`, `search_log.csv`.
- Validation predictions in the shared format: `data/predictions/baseline_val.parquet`, the reference distribution for drift in Step 5.

### Decisions made
- **Chosen configuration: config 62.** Word 1-2 grams, class_weight "balanced", C = 16, none:positive = 5 in train (22,974 train segments), model_version `7253e7a8662b`.
  - Selection followed the pre-set rule exactly. The best macro-AP was config 63 (0.5632); only config 62 (0.5598) was within 0.005; config 62 has the higher macro-F1 (0.5652 vs 0.5624).
  - The selection metric changed the outcome. Selecting by validation macro-F1 would have picked config 31 (unigrams, balanced, C = 16, all none), macro-F1 0.5692 but macro-AP 0.5411. The AP rule was fixed before the search ran.
- **Serial training (`n_jobs` removed).**
  - Alternatives considered: keep parallel fitting and add a pipeline step that sorts the sparse matrix indices first.
  - Why rejected: it adds a custom step to the saved model and depends on a scipy detail. A one-time search does not need the speed. Results are identical either way, since each classifier has a fixed `random_state`.

### Numbers measured
From `python -m src.baseline search | tee data/processed/baseline_search.txt` (full per-configuration log in `models/baseline/search_log.csv`):
- Rule B pooled labels computed from data: Joint Ip Ownership, Most Favored Nation, No-Solicit Of Customers, Non-Disparagement, Third Party Beneficiary. This matches the pre-registered 5.
- Train segments before downsampling: 34,871 (3,829 positive). Validation segments: 11,656.
- Chosen configuration, validation. Thresholds were tuned on this same set, so F1 is optimistic.
  - All 33 labels: macro-F1 0.5652, micro-F1 0.6363, macro-AP 0.5598.
  - 28 per-class labels: macro-F1 0.6084, micro-F1 0.6391, macro-AP 0.5895.
  - None false-positive rate: 0.0283 of 10,320 true-none segments.
- Latency:
  - Batch-amortized: 0.0370 ms per segment.
  - Single-segment, one call per segment, n = 200 seeded validation segments: median 1.53 ms, p95 1.68 ms.
- Per-label validation F1:
  - Best: Governing Law 0.967, No-Solicit Of Employees 0.848, Anti-Assignment 0.847, Insurance 0.818.
  - Failing (F1 below 0.30 or zero recall):
    - No-Solicit Of Customers: F1 0, AP 0.010, 2 validation segments, 0 predicted.
    - Most Favored Nation: F1 0, AP 0.428, 5 validation segments, 0 predicted.
    - Competitive Restriction Exception: F1 0.219, AP 0.108, threshold 0.10.
    - Volume Restriction: F1 0.273, AP 0.211.
  - Near the failure line: Post-Termination Services 0.344, Minimum Commitment 0.358.
- Shared pooled threshold (Rule B): 0.62.

All 64 configurations (validation; thresholds tuned per configuration for the macro-F1 columns):

| config | n-gram | weighted | C | none ratio | train segs | macro-AP | macro-F1 | micro-F1 | macro-F1 (28) | none FP rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1-1 | no | 0.25 | 1 | 7658 | 0.4438 | 0.4252 | 0.2402 | 0.4916 | 0.4107 |
| 1 | 1-1 | no | 0.25 | 3 | 15316 | 0.4559 | 0.4264 | 0.5271 | 0.4948 | 0.0398 |
| 2 | 1-1 | no | 0.25 | 5 | 22974 | 0.4572 | 0.4041 | 0.5171 | 0.4640 | 0.0518 |
| 3 | 1-1 | no | 0.25 | all | 34871 | 0.4589 | 0.3955 | 0.5312 | 0.4619 | 0.0311 |
| 4 | 1-1 | no | 1 | 1 | 7658 | 0.4849 | 0.4831 | 0.5624 | 0.5537 | 0.0439 |
| 5 | 1-1 | no | 1 | 3 | 15316 | 0.4949 | 0.4873 | 0.5736 | 0.5589 | 0.0346 |
| 6 | 1-1 | no | 1 | 5 | 22974 | 0.4982 | 0.4818 | 0.5770 | 0.5528 | 0.0313 |
| 7 | 1-1 | no | 1 | all | 34871 | 0.4993 | 0.4785 | 0.5856 | 0.5493 | 0.0329 |
| 8 | 1-1 | no | 4 | 1 | 7658 | 0.5177 | 0.5334 | 0.6030 | 0.5810 | 0.0364 |
| 9 | 1-1 | no | 4 | 3 | 15316 | 0.5329 | 0.5417 | 0.6082 | 0.5867 | 0.0302 |
| 10 | 1-1 | no | 4 | 5 | 22974 | 0.5340 | 0.5421 | 0.6112 | 0.5887 | 0.0297 |
| 11 | 1-1 | no | 4 | all | 34871 | 0.5362 | 0.5426 | 0.6118 | 0.5897 | 0.0288 |
| 12 | 1-1 | no | 16 | 1 | 7658 | 0.5219 | 0.5369 | 0.6066 | 0.5851 | 0.0375 |
| 13 | 1-1 | no | 16 | 3 | 15316 | 0.5383 | 0.5457 | 0.6155 | 0.5940 | 0.0292 |
| 14 | 1-1 | no | 16 | 5 | 22974 | 0.5407 | 0.5466 | 0.6166 | 0.5941 | 0.0248 |
| 15 | 1-1 | no | 16 | all | 34871 | 0.5436 | 0.5439 | 0.6097 | 0.5924 | 0.0228 |
| 16 | 1-1 | yes | 0.25 | 1 | 7658 | 0.4894 | 0.5083 | 0.5687 | 0.5543 | 0.0416 |
| 17 | 1-1 | yes | 0.25 | 3 | 15316 | 0.5023 | 0.5168 | 0.5803 | 0.5628 | 0.0328 |
| 18 | 1-1 | yes | 0.25 | 5 | 22974 | 0.5070 | 0.5195 | 0.5829 | 0.5648 | 0.0345 |
| 19 | 1-1 | yes | 0.25 | all | 34871 | 0.5131 | 0.5241 | 0.5914 | 0.5710 | 0.0286 |
| 20 | 1-1 | yes | 1 | 1 | 7658 | 0.5069 | 0.5241 | 0.5905 | 0.5696 | 0.0365 |
| 21 | 1-1 | yes | 1 | 3 | 15316 | 0.5250 | 0.5357 | 0.6048 | 0.5824 | 0.0279 |
| 22 | 1-1 | yes | 1 | 5 | 22974 | 0.5304 | 0.5371 | 0.6037 | 0.5834 | 0.0304 |
| 23 | 1-1 | yes | 1 | all | 34871 | 0.5353 | 0.5391 | 0.6031 | 0.5855 | 0.0293 |
| 24 | 1-1 | yes | 4 | 1 | 7658 | 0.5194 | 0.5372 | 0.6065 | 0.5826 | 0.0353 |
| 25 | 1-1 | yes | 4 | 3 | 15316 | 0.5370 | 0.5660 | 0.6123 | 0.5937 | 0.0309 |
| 26 | 1-1 | yes | 4 | 5 | 22974 | 0.5427 | 0.5669 | 0.6148 | 0.5963 | 0.0297 |
| 27 | 1-1 | yes | 4 | all | 34871 | 0.5464 | 0.5637 | 0.6108 | 0.5941 | 0.0285 |
| 28 | 1-1 | yes | 16 | 1 | 7658 | 0.5233 | 0.5367 | 0.6001 | 0.5814 | 0.0420 |
| 29 | 1-1 | yes | 16 | 3 | 15316 | 0.5366 | 0.5661 | 0.6091 | 0.5933 | 0.0339 |
| 30 | 1-1 | yes | 16 | 5 | 22974 | 0.5381 | 0.5686 | 0.6165 | 0.5944 | 0.0259 |
| 31 | 1-1 | yes | 16 | all | 34871 | 0.5411 | 0.5692 | 0.6140 | 0.5950 | 0.0250 |
| 32 | 1-2 | no | 0.25 | 1 | 7658 | 0.4527 | 0.4150 | 0.2821 | 0.4816 | 0.3151 |
| 33 | 1-2 | no | 0.25 | 3 | 15316 | 0.4622 | 0.3800 | 0.5086 | 0.4411 | 0.0533 |
| 34 | 1-2 | no | 0.25 | 5 | 22974 | 0.4621 | 0.3691 | 0.5240 | 0.4350 | 0.0321 |
| 35 | 1-2 | no | 0.25 | all | 34871 | 0.4616 | 0.3312 | 0.5063 | 0.3904 | 0.0297 |
| 36 | 1-2 | no | 1 | 1 | 7658 | 0.4862 | 0.4693 | 0.4650 | 0.5406 | 0.0934 |
| 37 | 1-2 | no | 1 | 3 | 15316 | 0.4912 | 0.4655 | 0.5752 | 0.5326 | 0.0377 |
| 38 | 1-2 | no | 1 | 5 | 22974 | 0.4920 | 0.4598 | 0.5700 | 0.5260 | 0.0336 |
| 39 | 1-2 | no | 1 | all | 34871 | 0.4934 | 0.4617 | 0.5701 | 0.5272 | 0.0345 |
| 40 | 1-2 | no | 4 | 1 | 7658 | 0.5197 | 0.5303 | 0.6026 | 0.5783 | 0.0376 |
| 41 | 1-2 | no | 4 | 3 | 15316 | 0.5269 | 0.5309 | 0.5824 | 0.5815 | 0.0454 |
| 42 | 1-2 | no | 4 | 5 | 22974 | 0.5244 | 0.5304 | 0.6025 | 0.5853 | 0.0360 |
| 43 | 1-2 | no | 4 | all | 34871 | 0.5302 | 0.5344 | 0.6075 | 0.5803 | 0.0306 |
| 44 | 1-2 | no | 16 | 1 | 7658 | 0.5347 | 0.5476 | 0.6068 | 0.5925 | 0.0397 |
| 45 | 1-2 | no | 16 | 3 | 15316 | 0.5450 | 0.5486 | 0.6162 | 0.5945 | 0.0332 |
| 46 | 1-2 | no | 16 | 5 | 22974 | 0.5484 | 0.5506 | 0.6241 | 0.5969 | 0.0282 |
| 47 | 1-2 | no | 16 | all | 34871 | 0.5501 | 0.5535 | 0.6274 | 0.5980 | 0.0274 |
| 48 | 1-2 | yes | 0.25 | 1 | 7658 | 0.4920 | 0.5124 | 0.5779 | 0.5557 | 0.0343 |
| 49 | 1-2 | yes | 0.25 | 3 | 15316 | 0.5006 | 0.5200 | 0.5914 | 0.5659 | 0.0355 |
| 50 | 1-2 | yes | 0.25 | 5 | 22974 | 0.5036 | 0.5238 | 0.5871 | 0.5697 | 0.0355 |
| 51 | 1-2 | yes | 0.25 | all | 34871 | 0.5069 | 0.5303 | 0.5947 | 0.5738 | 0.0328 |
| 52 | 1-2 | yes | 1 | 1 | 7658 | 0.5128 | 0.5301 | 0.5901 | 0.5723 | 0.0399 |
| 53 | 1-2 | yes | 1 | 3 | 15316 | 0.5219 | 0.5378 | 0.6037 | 0.5820 | 0.0353 |
| 54 | 1-2 | yes | 1 | 5 | 22974 | 0.5253 | 0.5445 | 0.6082 | 0.5885 | 0.0333 |
| 55 | 1-2 | yes | 1 | all | 34871 | 0.5304 | 0.5459 | 0.6095 | 0.5877 | 0.0289 |
| 56 | 1-2 | yes | 4 | 1 | 7658 | 0.5302 | 0.5461 | 0.6070 | 0.5899 | 0.0383 |
| 57 | 1-2 | yes | 4 | 3 | 15316 | 0.5412 | 0.5507 | 0.6174 | 0.5972 | 0.0325 |
| 58 | 1-2 | yes | 4 | 5 | 22974 | 0.5460 | 0.5524 | 0.6190 | 0.5962 | 0.0326 |
| 59 | 1-2 | yes | 4 | all | 34871 | 0.5525 | 0.5552 | 0.6193 | 0.5975 | 0.0319 |
| 60 | 1-2 | yes | 16 | 1 | 7658 | 0.5416 | 0.5521 | 0.6093 | 0.5981 | 0.0396 |
| 61 | 1-2 | yes | 16 | 3 | 15316 | 0.5531 | 0.5565 | 0.6197 | 0.6021 | 0.0348 |
| 62 | 1-2 | yes | 16 | 5 | 22974 | 0.5598 | 0.5652 | 0.6363 | 0.6084 | 0.0283 |
| 63 | 1-2 | yes | 16 | all | 34871 | 0.5632 | 0.5624 | 0.6303 | 0.6067 | 0.0293 |

### Problems hit and how we solved them
- **First search run crashed on configuration 1:** `ValueError: WRITEBACKIFCOPY base is read-only`.
  - Cause: with `n_jobs=-1`, joblib passes the large TF-IDF matrix to worker processes as a read-only memory map. `LogisticRegression.fit` calls `np.max(X)`, which makes scipy sort the sparse indices in place, and that fails on read-only memory.
  - Fix: fit the 33 binary classifiers serially.
  - The unit tests did not catch it because they never fit on data large enough to trigger memory mapping.

### Surprises in the data or results
- **The chosen region is at the edge of the grid.** The top six configurations by macro-AP all use C = 16, the largest value tried, and macro-AP still rises from C = 4 to C = 16 in every bigram cell. The optimum may lie above 16. Extending the grid is a validation-only decision, pending.
- **The pooled threshold silences two labels.** At 0.62, Most Favored Nation and No-Solicit Of Customers get zero validation predictions. Most Favored Nation still ranks reasonably (AP 0.428); the shared threshold, not the ranking, is what fails it. This is the cost of pre-registered Rule B and is reported, not tuned away.
- **Several per-class thresholds sit near the grid ends:** Minimum Commitment 0.95, Anti-Assignment 0.87, Competitive Restriction Exception 0.10, No-Solicit Of Employees 0.16, Liquidated Damages 0.19. Probabilities are poorly calibrated per label, as expected with "balanced" weighting plus none downsampling. Evidence for the Step 4 calibration item.
- **Strong regularization with 1:1 none sampling is pathological.** Config 0 (unigrams, unweighted, C = 0.25, none 1:1) labels 41.1% of true-none segments, with micro-F1 0.2402.
- **Governing Law is nearly solved lexically** (F1 0.967, AP 0.988). Competitive Restriction Exception, defined only relative to other restrictions, is close to unlearnable with bag-of-words (AP 0.108).

### Resume-worthy
Built a TF-IDF plus logistic regression baseline for 33-label clause classification (validation macro-F1 0.565, micro-F1 0.636), with model selection on a threshold-free metric fixed in advance. That choice changed which model was selected.

---

## 2026-09-24: Step 2b, second (post-hoc) round of validation-only search declared

### What we built
- `src/config.py`: `BASELINE_C_VALUES` extended from (0.25, 1, 4, 16) to (0.25, 1, 4, 16, 32, 64). Grid: 2 n-gram ranges x 2 weightings x 6 C values x 4 none ratios = 96 configurations.
- Round 1 artifacts preserved for audit in `models/baseline/round1/` (`search_log.csv`, `config.json`, `thresholds.json`). The round 2 run overwrites `models/baseline/`.

### Decisions made
- **Run a second, post-hoc round of search, on validation only.** Test and shift remain untouched (no `heldout_run.json` exists).
  - Why: in round 1 the top six configurations by macro-AP all used C = 16, the largest value tried, and macro-AP rose from C = 4 to C = 16 in every bigram cell. The optimum may lie beyond the grid edge.
  - The full 96-configuration grid is rerun rather than just the new cells, so all candidates are compared under one run and one selection rule.
  - Same selection rule over all 96: best validation macro-AP; within 0.005, higher macro-F1; then the simpler configuration.
  - **Stopping rule, declared before the run:** if the winner is at C = 64, stop and report it as an edge result. No further rounds.
  - Alternatives considered: freeze round 1's config 62.
  - Why rejected: an unexplored grid edge is a predictable reviewer question, and the extension uses validation only.
  - Risk accepted: a second round slightly raises the chance of fitting validation noise. It is disclosed here.
- **Config id mapping, round 1 to round 2** (the product order is n-gram, weighting, C, ratio):
  - Round 1: `id = 32*ngram_idx + 16*weight_idx + 4*c_idx + ratio_idx`
  - Round 2: `id = 48*ngram_idx + 24*weight_idx + 4*c_idx + ratio_idx`
  - Here `ngram_idx` is 0 for (1,1) and 1 for (1,2); `weight_idx` is 0 for None and 1 for balanced; `ratio_idx` is 0..3 for 1, 3, 5, all; and `c_idx` is 0..3 for C = 0.25, 1, 4, 16.
  - C = 32 and 64 are `c_idx` 4 and 5, new in round 2.
  - Examples: round 1 config 62 becomes round 2 config 86; round 1 config 63 becomes 87; round 1 config 31 becomes 39.

### Comparison point recorded for Step 4 (LLMs)
- Most Favored Nation has baseline validation F1 0 with AP 0.428 (round 1, config 62).
- The ranking carries signal. The zero comes from the pooled Rule B threshold (0.62 shared across the 5 pooled labels), which none of its 5 validation segments reached.
- When LLMs are compared on this label, report both a threshold-free measure and F1 under Rule B, so a threshold artifact is not read as the baseline lacking signal.

### Numbers measured
None yet; round 2 results go in the next entry.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None new.

### Resume-worthy
none

---

## 2026-09-24: Step 2c, round 2 search results; stopping rule triggered; configuration frozen pending held-out run

### What we built
- Round 2 of the validation-only search: 96 configurations (C extended to 32 and 64).
- New artifacts in `models/baseline/` (model_version `9692b04f03fb`); round 1 artifacts kept in `models/baseline/round1/`.
- `data/predictions/baseline_val.parquet` regenerated from the round 2 model.

### Decisions made
- **Chosen configuration: round 2 config 95.** Word 1-2 grams, class_weight "balanced", C = 64, no none downsampling (all 34,871 train segments).
  - Selection followed the pre-set rule. The best macro-AP was config 95 (0.5671). Within 0.005 of it were configs 91 (C = 32, 0.5655) and 87 (C = 16, 0.5632; round 1's config 63). Config 95 also had the highest macro-F1 of the three (0.5670 vs 0.5647 and 0.5624).
  - Config 94 (C = 64, none 5:1, macro-AP 0.5617) fell just outside the 0.005 band.
- **Stopping rule triggered.** The winner is at C = 64, the new grid edge. As declared before the run, the search stops here and the result is reported as an edge result, with no further rounds. Macro-AP gains flattened as C grew, from 0.5632 (C = 16) to 0.5655 (C = 32) to 0.5671 (C = 64) in this cell, so any gain beyond the edge is likely small. This is an observation, not a reason to search further.
- **Round 1's choice (config 62, now config 86) is superseded.** Its validation macro-AP was 0.5598 against 0.5671.

### Numbers measured
From `python -m src.baseline search | tee data/processed/baseline_search.txt` (round 2):
- **Reproduction check.** Compared `models/baseline/round1/search_log.csv` to the round 2 `search_log.csv` through the id mapping in Step 2b (a script reading both CSVs). All 64 round 1 configurations matched with:
  - identical hyperparameters, train segment counts, and vocabulary sizes;
  - a maximum absolute difference of 0.0 on macro-AP, macro-F1, micro-F1, macro-F1 (28), and none FP rate.
  - Mapping examples: round 1 62 becomes 86, 63 becomes 87, 31 becomes 39.
- **Chosen configuration, validation.** Thresholds were tuned on this same set, so F1 is optimistic.
  - All 33 labels: macro-F1 0.5670, micro-F1 0.6307, macro-AP 0.5671.
  - 28 per-class labels: macro-F1 0.6107, micro-F1 0.6336, macro-AP 0.5979.
  - None false-positive rate: 0.0300 of 10,320 true-none segments.
- **Latency:**
  - Batch-amortized: 0.0370 ms per segment.
  - Single-segment, one call per segment, n = 200: median 1.52 ms, p95 1.66 ms.
- **Pooled Rule B threshold:** 0.42 (round 1: 0.62).
- **Failing labels** (F1 below 0.30 or zero recall):
  - No-Solicit Of Customers: F1 0, AP 0.011.
  - Most Favored Nation: F1 0, AP 0.440.
  - Competitive Restriction Exception: F1 0.222, AP 0.111, threshold 0.04.
  - Volume Restriction: F1 0.286, AP 0.230.
  - Minimum Commitment is exactly at the line: F1 0.300 as printed, not flagged. Post-Termination Services 0.356.
- **Best labels:** Governing Law 0.967, No-Solicit Of Employees 0.848, Anti-Assignment 0.844, Insurance 0.832.

All 96 configurations (round 2, validation):

| config | n-gram | weighted | C | none ratio | train segs | macro-AP | macro-F1 | micro-F1 | macro-F1 (28) | none FP rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1-1 | no | 0.25 | 1 | 7658 | 0.4438 | 0.4252 | 0.2402 | 0.4916 | 0.4107 |
| 1 | 1-1 | no | 0.25 | 3 | 15316 | 0.4559 | 0.4264 | 0.5271 | 0.4948 | 0.0398 |
| 2 | 1-1 | no | 0.25 | 5 | 22974 | 0.4572 | 0.4041 | 0.5171 | 0.4640 | 0.0518 |
| 3 | 1-1 | no | 0.25 | all | 34871 | 0.4589 | 0.3955 | 0.5312 | 0.4619 | 0.0311 |
| 4 | 1-1 | no | 1 | 1 | 7658 | 0.4849 | 0.4831 | 0.5624 | 0.5537 | 0.0439 |
| 5 | 1-1 | no | 1 | 3 | 15316 | 0.4949 | 0.4873 | 0.5736 | 0.5589 | 0.0346 |
| 6 | 1-1 | no | 1 | 5 | 22974 | 0.4982 | 0.4818 | 0.5770 | 0.5528 | 0.0313 |
| 7 | 1-1 | no | 1 | all | 34871 | 0.4993 | 0.4785 | 0.5856 | 0.5493 | 0.0329 |
| 8 | 1-1 | no | 4 | 1 | 7658 | 0.5177 | 0.5334 | 0.6030 | 0.5810 | 0.0364 |
| 9 | 1-1 | no | 4 | 3 | 15316 | 0.5329 | 0.5417 | 0.6082 | 0.5867 | 0.0302 |
| 10 | 1-1 | no | 4 | 5 | 22974 | 0.5340 | 0.5421 | 0.6112 | 0.5887 | 0.0297 |
| 11 | 1-1 | no | 4 | all | 34871 | 0.5362 | 0.5426 | 0.6118 | 0.5897 | 0.0288 |
| 12 | 1-1 | no | 16 | 1 | 7658 | 0.5219 | 0.5369 | 0.6066 | 0.5851 | 0.0375 |
| 13 | 1-1 | no | 16 | 3 | 15316 | 0.5383 | 0.5457 | 0.6155 | 0.5940 | 0.0292 |
| 14 | 1-1 | no | 16 | 5 | 22974 | 0.5407 | 0.5466 | 0.6166 | 0.5941 | 0.0248 |
| 15 | 1-1 | no | 16 | all | 34871 | 0.5436 | 0.5439 | 0.6097 | 0.5924 | 0.0228 |
| 16 | 1-1 | no | 32 | 1 | 7658 | 0.5216 | 0.5314 | 0.6031 | 0.5793 | 0.0365 |
| 17 | 1-1 | no | 32 | 3 | 15316 | 0.5366 | 0.5483 | 0.6181 | 0.5948 | 0.0260 |
| 18 | 1-1 | no | 32 | 5 | 22974 | 0.5384 | 0.5639 | 0.6156 | 0.5944 | 0.0239 |
| 19 | 1-1 | no | 32 | all | 34871 | 0.5405 | 0.5468 | 0.6051 | 0.5931 | 0.0281 |
| 20 | 1-1 | no | 64 | 1 | 7658 | 0.5196 | 0.5320 | 0.5989 | 0.5792 | 0.0377 |
| 21 | 1-1 | no | 64 | 3 | 15316 | 0.5325 | 0.5633 | 0.6136 | 0.5919 | 0.0299 |
| 22 | 1-1 | no | 64 | 5 | 22974 | 0.5345 | 0.5652 | 0.6162 | 0.5924 | 0.0244 |
| 23 | 1-1 | no | 64 | all | 34871 | 0.5359 | 0.5617 | 0.6075 | 0.5902 | 0.0235 |
| 24 | 1-1 | yes | 0.25 | 1 | 7658 | 0.4894 | 0.5083 | 0.5687 | 0.5543 | 0.0416 |
| 25 | 1-1 | yes | 0.25 | 3 | 15316 | 0.5023 | 0.5168 | 0.5803 | 0.5628 | 0.0328 |
| 26 | 1-1 | yes | 0.25 | 5 | 22974 | 0.5070 | 0.5195 | 0.5829 | 0.5648 | 0.0345 |
| 27 | 1-1 | yes | 0.25 | all | 34871 | 0.5131 | 0.5241 | 0.5914 | 0.5710 | 0.0286 |
| 28 | 1-1 | yes | 1 | 1 | 7658 | 0.5069 | 0.5241 | 0.5905 | 0.5696 | 0.0365 |
| 29 | 1-1 | yes | 1 | 3 | 15316 | 0.5250 | 0.5357 | 0.6048 | 0.5824 | 0.0279 |
| 30 | 1-1 | yes | 1 | 5 | 22974 | 0.5304 | 0.5371 | 0.6037 | 0.5834 | 0.0304 |
| 31 | 1-1 | yes | 1 | all | 34871 | 0.5353 | 0.5391 | 0.6031 | 0.5855 | 0.0293 |
| 32 | 1-1 | yes | 4 | 1 | 7658 | 0.5194 | 0.5372 | 0.6065 | 0.5826 | 0.0353 |
| 33 | 1-1 | yes | 4 | 3 | 15316 | 0.5370 | 0.5660 | 0.6123 | 0.5937 | 0.0309 |
| 34 | 1-1 | yes | 4 | 5 | 22974 | 0.5427 | 0.5669 | 0.6148 | 0.5963 | 0.0297 |
| 35 | 1-1 | yes | 4 | all | 34871 | 0.5464 | 0.5637 | 0.6108 | 0.5941 | 0.0285 |
| 36 | 1-1 | yes | 16 | 1 | 7658 | 0.5233 | 0.5367 | 0.6001 | 0.5814 | 0.0420 |
| 37 | 1-1 | yes | 16 | 3 | 15316 | 0.5366 | 0.5661 | 0.6091 | 0.5933 | 0.0339 |
| 38 | 1-1 | yes | 16 | 5 | 22974 | 0.5381 | 0.5686 | 0.6165 | 0.5944 | 0.0259 |
| 39 | 1-1 | yes | 16 | all | 34871 | 0.5411 | 0.5692 | 0.6140 | 0.5950 | 0.0250 |
| 40 | 1-1 | yes | 32 | 1 | 7658 | 0.5211 | 0.5456 | 0.6024 | 0.5781 | 0.0372 |
| 41 | 1-1 | yes | 32 | 3 | 15316 | 0.5335 | 0.5662 | 0.6119 | 0.5932 | 0.0334 |
| 42 | 1-1 | yes | 32 | 5 | 22974 | 0.5321 | 0.5650 | 0.6153 | 0.5909 | 0.0248 |
| 43 | 1-1 | yes | 32 | all | 34871 | 0.5351 | 0.5673 | 0.6118 | 0.5915 | 0.0240 |
| 44 | 1-1 | yes | 64 | 1 | 7658 | 0.5182 | 0.5507 | 0.5969 | 0.5763 | 0.0391 |
| 45 | 1-1 | yes | 64 | 3 | 15316 | 0.5284 | 0.5604 | 0.6106 | 0.5908 | 0.0302 |
| 46 | 1-1 | yes | 64 | 5 | 22974 | 0.5273 | 0.5620 | 0.6134 | 0.5881 | 0.0263 |
| 47 | 1-1 | yes | 64 | all | 34871 | 0.5308 | 0.5617 | 0.6035 | 0.5862 | 0.0258 |
| 48 | 1-2 | no | 0.25 | 1 | 7658 | 0.4527 | 0.4150 | 0.2821 | 0.4816 | 0.3151 |
| 49 | 1-2 | no | 0.25 | 3 | 15316 | 0.4622 | 0.3800 | 0.5086 | 0.4411 | 0.0533 |
| 50 | 1-2 | no | 0.25 | 5 | 22974 | 0.4621 | 0.3691 | 0.5240 | 0.4350 | 0.0321 |
| 51 | 1-2 | no | 0.25 | all | 34871 | 0.4616 | 0.3312 | 0.5063 | 0.3904 | 0.0297 |
| 52 | 1-2 | no | 1 | 1 | 7658 | 0.4862 | 0.4693 | 0.4650 | 0.5406 | 0.0934 |
| 53 | 1-2 | no | 1 | 3 | 15316 | 0.4912 | 0.4655 | 0.5752 | 0.5326 | 0.0377 |
| 54 | 1-2 | no | 1 | 5 | 22974 | 0.4920 | 0.4598 | 0.5700 | 0.5260 | 0.0336 |
| 55 | 1-2 | no | 1 | all | 34871 | 0.4934 | 0.4617 | 0.5701 | 0.5272 | 0.0345 |
| 56 | 1-2 | no | 4 | 1 | 7658 | 0.5197 | 0.5303 | 0.6026 | 0.5783 | 0.0376 |
| 57 | 1-2 | no | 4 | 3 | 15316 | 0.5269 | 0.5309 | 0.5824 | 0.5815 | 0.0454 |
| 58 | 1-2 | no | 4 | 5 | 22974 | 0.5244 | 0.5304 | 0.6025 | 0.5853 | 0.0360 |
| 59 | 1-2 | no | 4 | all | 34871 | 0.5302 | 0.5344 | 0.6075 | 0.5803 | 0.0306 |
| 60 | 1-2 | no | 16 | 1 | 7658 | 0.5347 | 0.5476 | 0.6068 | 0.5925 | 0.0397 |
| 61 | 1-2 | no | 16 | 3 | 15316 | 0.5450 | 0.5486 | 0.6162 | 0.5945 | 0.0332 |
| 62 | 1-2 | no | 16 | 5 | 22974 | 0.5484 | 0.5506 | 0.6241 | 0.5969 | 0.0282 |
| 63 | 1-2 | no | 16 | all | 34871 | 0.5501 | 0.5535 | 0.6274 | 0.5980 | 0.0274 |
| 64 | 1-2 | no | 32 | 1 | 7658 | 0.5397 | 0.5522 | 0.6158 | 0.5964 | 0.0354 |
| 65 | 1-2 | no | 32 | 3 | 15316 | 0.5493 | 0.5555 | 0.6173 | 0.5989 | 0.0330 |
| 66 | 1-2 | no | 32 | 5 | 22974 | 0.5525 | 0.5602 | 0.6294 | 0.6022 | 0.0265 |
| 67 | 1-2 | no | 32 | all | 34871 | 0.5555 | 0.5579 | 0.6351 | 0.6002 | 0.0243 |
| 68 | 1-2 | no | 64 | 1 | 7658 | 0.5414 | 0.5535 | 0.6166 | 0.5973 | 0.0357 |
| 69 | 1-2 | no | 64 | 3 | 15316 | 0.5524 | 0.5585 | 0.6236 | 0.6013 | 0.0317 |
| 70 | 1-2 | no | 64 | 5 | 22974 | 0.5570 | 0.5603 | 0.6323 | 0.6027 | 0.0266 |
| 71 | 1-2 | no | 64 | all | 34871 | 0.5616 | 0.5588 | 0.6309 | 0.6033 | 0.0268 |
| 72 | 1-2 | yes | 0.25 | 1 | 7658 | 0.4920 | 0.5124 | 0.5779 | 0.5557 | 0.0343 |
| 73 | 1-2 | yes | 0.25 | 3 | 15316 | 0.5006 | 0.5200 | 0.5914 | 0.5659 | 0.0355 |
| 74 | 1-2 | yes | 0.25 | 5 | 22974 | 0.5036 | 0.5238 | 0.5871 | 0.5697 | 0.0355 |
| 75 | 1-2 | yes | 0.25 | all | 34871 | 0.5069 | 0.5303 | 0.5947 | 0.5738 | 0.0328 |
| 76 | 1-2 | yes | 1 | 1 | 7658 | 0.5128 | 0.5301 | 0.5901 | 0.5723 | 0.0399 |
| 77 | 1-2 | yes | 1 | 3 | 15316 | 0.5219 | 0.5378 | 0.6037 | 0.5820 | 0.0353 |
| 78 | 1-2 | yes | 1 | 5 | 22974 | 0.5253 | 0.5445 | 0.6082 | 0.5885 | 0.0333 |
| 79 | 1-2 | yes | 1 | all | 34871 | 0.5304 | 0.5459 | 0.6095 | 0.5877 | 0.0289 |
| 80 | 1-2 | yes | 4 | 1 | 7658 | 0.5302 | 0.5461 | 0.6070 | 0.5899 | 0.0383 |
| 81 | 1-2 | yes | 4 | 3 | 15316 | 0.5412 | 0.5507 | 0.6174 | 0.5972 | 0.0325 |
| 82 | 1-2 | yes | 4 | 5 | 22974 | 0.5460 | 0.5524 | 0.6190 | 0.5962 | 0.0326 |
| 83 | 1-2 | yes | 4 | all | 34871 | 0.5525 | 0.5552 | 0.6193 | 0.5975 | 0.0319 |
| 84 | 1-2 | yes | 16 | 1 | 7658 | 0.5416 | 0.5521 | 0.6093 | 0.5981 | 0.0396 |
| 85 | 1-2 | yes | 16 | 3 | 15316 | 0.5531 | 0.5565 | 0.6197 | 0.6021 | 0.0348 |
| 86 | 1-2 | yes | 16 | 5 | 22974 | 0.5598 | 0.5652 | 0.6363 | 0.6084 | 0.0283 |
| 87 | 1-2 | yes | 16 | all | 34871 | 0.5632 | 0.5624 | 0.6303 | 0.6067 | 0.0293 |
| 88 | 1-2 | yes | 32 | 1 | 7658 | 0.5427 | 0.5516 | 0.6121 | 0.5982 | 0.0377 |
| 89 | 1-2 | yes | 32 | 3 | 15316 | 0.5546 | 0.5604 | 0.6281 | 0.6049 | 0.0283 |
| 90 | 1-2 | yes | 32 | 5 | 22974 | 0.5612 | 0.5657 | 0.6266 | 0.6090 | 0.0313 |
| 91 | 1-2 | yes | 32 | all | 34871 | 0.5655 | 0.5647 | 0.6291 | 0.6094 | 0.0306 |
| 92 | 1-2 | yes | 64 | 1 | 7658 | 0.5436 | 0.5551 | 0.6161 | 0.5999 | 0.0364 |
| 93 | 1-2 | yes | 64 | 3 | 15316 | 0.5554 | 0.5604 | 0.6259 | 0.6066 | 0.0313 |
| 94 | 1-2 | yes | 64 | 5 | 22974 | 0.5617 | 0.5643 | 0.6269 | 0.6082 | 0.0354 |
| 95 | 1-2 | yes | 64 | all | 34871 | 0.5671 | 0.5670 | 0.6307 | 0.6107 | 0.0300 |

### Problems hit and how we solved them
None.

### Surprises in the data or results
- **The winner uses no none downsampling at all** (ratio "all"). Class weighting ("balanced") does the rebalancing instead. The Step 4 calibration item therefore changes. Downsampling no longer applies to the chosen model, but "balanced" weighting inflates positive-class probabilities in a similar way, so the reliability check is still needed.
- **Most Favored Nation remains the clearest threshold artifact** (comparison point for Step 4). Its AP rose to 0.440 and the pooled threshold dropped to 0.42, yet none of its 5 validation segments reached 0.42, so validation F1 is still 0. Its ranking carries signal; the shared Rule B threshold is what zeroes it.
- **Competitive Restriction Exception's threshold fell to 0.04,** effectively predicting it on anything faintly similar, and it still reaches only F1 0.222. The failure is in representation, not thresholding.
- **More capacity helped bigrams but not unigrams.** Unigram macro-AP peaked at C = 4 to 16 and declined at C = 32 to 64 (for example, weighted, all: 0.5464 at C = 4 against 0.5308 at C = 64). Bigram macro-AP kept rising to C = 64.

### Resume-worthy
Ran a two-round, validation-only hyperparameter search (96 configurations) with a pre-declared stopping rule, and verified that all 64 first-round configurations reproduced bit-for-bit under the fixed seed.

---

## 2026-09-24: Step 2d, baseline one-time held-out run (test and shift); Step 2 complete

### What we built
- `data/predictions/baseline_test.parquet` (9,378 segments) and `data/predictions/baseline_shift.parquet` (4,584 segments), in the shared format.
  - Verified by reading them: all required columns, 33 labels in the file metadata, `model_version` 9692b04f03fb, `cost_usd` 0.0.
- Guard file `models/baseline/heldout_run.json`: started 2026-09-24T05:55:10Z, completed 05:55:11Z, `forced: false`. Test has been touched exactly once for this model.
- `docs/results.md`: test summary and Rule A main table; appendix metric column (point estimates, CIs pending); shift summary per type and combined; Rule C per-label table.

### Decisions made
- None. Everything was frozen before this run. The label lists for Rules A and C were computed by the code from the pre-registered cutoffs.

### Numbers measured
From `python -m src.baseline heldout | tee data/processed/baseline_heldout.txt`. Point estimates; contract-bootstrap CIs come in the evaluation step.
- **Test (96 contracts, 9,378 segments, 8,167 true-none):**
  - Rule A, 26 labels: macro-F1 0.6311, micro-F1 0.6659, macro-AP 0.6602.
  - All 33 labels: macro-F1 0.5486, micro-F1 0.6543, macro-AP 0.5928.
  - None false-positive rate: 0.0255.
  - Best main-table labels: Governing Law 0.960, Renewal Term 0.914, Anti-Assignment 0.814, Notice Period To Terminate Renewal 0.808.
  - Weakest main-table labels:
    - Volume Restriction 0.148 (recall 0.083)
    - Competitive Restriction Exception 0.245
    - Minimum Commitment 0.330 (recall 0.209)
    - Warranty Duration 0.375 (the label flagged for GitHub issue #23)
  - Appendix-only labels (insufficient support, not interpreted): Most Favored Nation F1 0 (AP 0.360), No-Solicit Of Customers 0, Third Party Beneficiary 0, Affiliate License 0.083, Non-Disparagement 0.167, Irrevocable Or Perpetual License 0.711, Joint Ip Ownership 0.733.
- **Shift (28 contracts, 4,584 segments, 3,971 true-none):**
  - Combined, Rule C (17 labels): macro-F1 0.4740, micro-F1 0.5027, macro-AP 0.5279.
  - Franchise, Rule C (17): macro-F1 0.4478, micro-F1 0.5141, macro-AP 0.5510.
  - Transportation, Rule C (16 with support): macro-F1 0.4291, micro-F1 0.4741, macro-AP 0.5412.
  - Combined, all labels (32 with support): macro-F1 0.3614.
  - None false-positive rate: combined 0.0340, Franchise 0.0443, Transportation 0.0207.
  - Largest per-label shift failures (Rule C, combined):
    - Volume Restriction: F1 0, 0 predicted for 31 true.
    - Minimum Commitment: F1 0.067, 2 predicted for 58 true.
    - Post-Termination Services 0.360, Exclusivity 0.364, License Grant 0.390, Non-Compete 0.394 (18 predicted for 53 true).
- **Validation vs test, chosen configuration, all 33 labels:**
  - Macro-F1: 0.5670 validation vs 0.5486 test.
  - Micro-F1: 0.6307 vs 0.6543.
  - Macro-AP: 0.5671 vs 0.5928.

### Problems hit and how we solved them
None.

### Surprises in the data or results
- **Test macro-AP (0.5928) and micro-F1 (0.6543) are higher than validation (0.5671, 0.6307), while macro-F1 is lower (0.5486 vs 0.5670).**
  - The lower macro-F1 fits the expected optimism of validation-tuned thresholds.
  - The higher AP and micro-F1 suggest the 96 test contracts are somewhat easier to rank than the 97 validation contracts, at least for frequent labels.
  - The contract-bootstrap CIs will show whether these gaps are within sampling noise.
- **Under shift the baseline fails mainly by under-predicting, not by over-predicting:**
  - Predicted counts collapse relative to support (Minimum Commitment 2 of 58, Volume Restriction 0 of 31, Non-Compete 18 of 53, Renewal Term 14 of 33).
  - The none false-positive rate barely moves (test 0.0255, shift combined 0.0340).
  - Implication for Step 5: a monitor on the predicted-positive rate per label should catch this kind of shift better than one on false alarms.
- **Franchise (vocabulary shift) and Transportation (label-mix shift) degrade by similar amounts** on Rule C labels: macro-F1 0.4478 and 0.4291, against 0.6311 for test Rule A labels. The comparison label sets differ, and CIs are still to come.
- **Warranty Duration**, the label with known annotation problems (issue #23), is among the weakest main-table labels at F1 0.375.

### Resume-worthy
Evaluated a TF-IDF plus logistic regression clause classifier once on a held-out test set (Rule A macro-F1 0.631 over 26 labels) and on a held-out contract-type shift set (macro-F1 0.474 on 17 pre-registered labels), showing that shift failures come from missed clauses rather than false alarms.

---

## 2026-09-24: Step 4a, evaluation harness part 1 (baseline CIs, paired comparison, calibration, error analysis)

Numbering follows the project's step numbers: the LLMs remain Step 3, and pairwise model comparisons are Step 4b.

### What we built
- `src/bootstrap.py`: contract-level resampling weights (stratified by contract type, seeded, with a named random stream); count-based F1, micro-F1, and none FP rate under resampling; weighted AP; percentile intervals; paired differences.
- `src/calibration.py`: per-contract reliability bins and ECE, so ECE bootstraps with the same weights.
- `src/evaluate.py`: reads prediction files only and never loads a model.
  - `model NAME` covers every scope with intervals, the test-minus-shift drop, calibration on test, and error analysis on validation. It writes `data/eval/NAME.json`.
  - `compare A B` produces paired differences on identical resamples.
- `tests/test_evaluate.py` (10 tests):
  - hand-computed F1, micro-F1, AP, and ECE;
  - point estimates equal `metrics.summary` (toy and real data);
  - weighted counts and AP equal explicit duplication;
  - resamples reproducible and stratified;
  - self-comparison exactly zero.
- `src/config.py`: `BOOTSTRAP_RESAMPLES=2000`, `CI_LEVEL=0.95`, `CALIBRATION_BINS=10`, `ERROR_SAMPLES_PER_LABEL=5`, `EVAL_DIR`.
- `docs/results.md`: every "CI pending" replaced by intervals from `data/eval/baseline.json`. Added a test-on-Rule-C row, the test-minus-shift table, calibration, and the error analysis section.
- `docs/labeling_schema.md`: four documented case groups from the validation error analysis (no relabeling).
- `docs/plan.md`: steps renumbered to match the project's step numbers.

### Decisions made
- **2000 resamples, percentile intervals.**
  - Alternatives considered: BCa; the basic (reverse) interval; more resamples.
  - Why rejected: BCa needs a per-scope jackknife and behaves erratically with discrete, few-contract F1. The basic interval can leave [0, 1]. More resamples mostly add runtime to the per-resample AP loop.
- **Resample contracts, stratified by contract type.**
  - Alternatives considered: segment-level resampling; unstratified contract resampling.
  - Why rejected: segments within a contract are correlated, so segment resampling understates uncertainty. Stratification mirrors the stratified split; unstratified would be slightly more conservative.
- **Named random streams** (`test`, `shift`, `shift:Franchise`, `shift:Transportation`) mixed into the seed. This was added after the first version of the code: without it, test and shift would reuse one random sequence, weakly correlating two bootstraps the drop interval treats as independent.
- **Error analysis on validation, not test,** so that test errors cannot inform Step 3 prompt design. Calibration was run on test because it is descriptive only; any recalibration would be fit on validation.
- **The labeling schema records ambiguities without relabeling.** Changing labels after seeing model errors would bias every later comparison.

### Numbers measured
From `pytest tests -v`: 51 passed.

From `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt` (baseline version 9692b04f03fb; 2000 resamples; 95% percentile intervals):
- **Test, Rule A (26 labels):** macro-F1 0.6311 [0.6043, 0.6532], micro-F1 0.6659 [0.6434, 0.6907], macro-AP 0.6602 [0.6408, 0.6962], none FP rate 0.0255 [0.0218, 0.0296].
- **Test, all 33 labels:** macro-F1 0.5486 [0.5217, 0.5743], micro-F1 0.6543 [0.6303, 0.6792], macro-AP 0.5928 [0.5729, 0.6339].
- **Test, Rule C labels (17):** macro-F1 0.6619 [0.6257, 0.6929], micro-F1 0.6902 [0.6640, 0.7180], macro-AP 0.7019 [0.6714, 0.7464].
- **Shift, Rule C:**
  - Combined: macro-F1 0.4740 [0.4186, 0.5332], micro-F1 0.5027 [0.4472, 0.5631], macro-AP 0.5279 [0.4918, 0.6150], none FP rate 0.0340 [0.0256, 0.0415].
  - Franchise: macro-F1 0.4478 [0.3994, 0.5315]. Transportation: macro-F1 0.4291 [0.3502, 0.5618].
- **Test minus shift on the same 17 Rule C labels:**
  - Macro-F1 +0.1879 [+0.1200, +0.2524]; micro-F1 +0.1875 [+0.1210, +0.2511]; macro-AP +0.1740 [+0.0843, +0.2287].
  - None FP rate -0.0085 [-0.0171, +0.0008].
- **Calibration on test:**
  - Pooled ECE 0.0015 [0.0009, 0.0025] over 309,474 segment-label pairs, of which 306,899 have probability below 0.1.
  - Upper bins, mean predicted vs observed: [0.5, 0.6) 0.5539 vs 0.3577; [0.8, 0.9) 0.8533 vs 0.5512; [0.9, 1.0] 0.9753 vs 0.7439.
  - Highest per-label ECE: Minimum Commitment 0.0207, with mean predicted probability 0.0272 against an observed rate of 0.0092.
- **Error analysis, validation:**
  - Top confused pairs (true label, wrongly predicted label): License Grant / Exclusivity 24, License Grant / Affiliate License 13, Anti-Assignment / Change Of Control 10, Non-Transferable License / Exclusivity 10.
  - Failing labels: Competitive Restriction Exception, Most Favored Nation, No-Solicit Of Customers, Volume Restriction.

From `python -m src.evaluate compare baseline baseline | tee data/processed/eval_compare_self.txt`: all 36 differences and interval bounds exactly 0 ("Self-comparison check ... True").

### Problems hit and how we solved them
- **A documentation bug introduced in Step 2d, found and fixed here.**
  - When filling the appendix after the held-out run, the fill script located each label's row by its first occurrence in `docs/results.md`. For the 26 main-table labels, that was the row in the main test table, not the appendix. So the Precision column of the main test table was overwritten with text, and those labels' appendix rows were left empty.
  - No figure in BUILD_LOG was affected; they were written from the pasted output.
  - Fix: everything from "## Test results" onward in `docs/results.md` was regenerated from `data/eval/baseline.json`. The rebuilt values were spot-checked against the pasted output (for example, Governing Law precision 0.955, test Rule A macro-F1 0.6311 [0.6043, 0.6532]).
  - Lesson: generate result tables from the saved JSON, never by string-matching rows.

### Surprises in the data or results
- **The shift drop is real, and it is misses, not false alarms.** The test-minus-shift macro-F1 interval, +0.1200 to +0.2524, excludes zero, while the none FP rate interval (-0.0171 to +0.0008) includes zero. This confirms the Step 2d reading with intervals.
- **Franchise and Transportation cannot be told apart.** Their Rule C macro-F1 intervals overlap almost entirely (0.3994 to 0.5315 vs 0.3502 to 0.5618). Transportation's are the widest in the table (micro-F1 0.3320 to 0.6213) with 13 contracts.
- **Pooled ECE (0.0015) looks excellent but hides clear overconfidence.** Above 0.1, observed rates sit well below predicted in every bin, confirming the "balanced" weighting known item. Pooled ECE alone would have hidden it.
- **Several AP intervals are asymmetric,** with the point estimate near the lower bound (shift all labels macro-AP 0.4497 [0.4340, 0.5486]; Minimum Commitment test AP 0.288 [0.205, 0.541]). F1 intervals are more centered. Claims rely on F1 intervals and intervals excluding zero; AP intervals are reported as measured.
- **Most Favored Nation has a literal "Most Favored Nation" heading in one validation segment (169_105) scored p = 0.009.** With 20 training segments, bag-of-words did not learn the phrase. This is a direct test case for the LLMs.

### Resume-worthy
Built a model-agnostic evaluation harness with contract-level stratified bootstrap CIs and paired comparisons (verified exactly zero on self-comparison). It showed a significant shift drop (macro-F1 -0.19, CI excluding zero) driven by missed clauses, and overconfidence that pooled ECE hid.

---

## 2026-09-24: Step 3a, LLM classifier design, pre-registration, and split CSV (no API calls yet)

### What we built
- `src/llm/` (the four core modules are pending review):
  - `clients.py`: Anthropic and Gemini wrappers; usage-to-cost formulas; our own retry loop; latency timing.
  - `cache.py`: per-call response cache and spend ledger with a thread-safe budget reservation.
  - `run.py`: CLI with `sample`, `estimate`, `iterate`, `compare`, `freeze`, `val`, `thresholds`, `repeat`, `heldout`.
  - Pending review: `prompt.py`, `parse.py`, `windows.py`, `selection.py`.
- `src/config.py`: model ids and prices, window size, confidence floor, iteration sample size, repeat-check settings, the $100 cap, concurrency and rate limits, estimate assumptions, `SPLITS_CSV`.
- `src/predictions.py`: optional shared-format columns `parse_failure` and `call_latency_ms`, with defaults, so baseline files still load.
- `src/bootstrap.py` and `src/evaluate.py`:
  - Parse failures count as empty predictions for F1.
  - The none false-positive rate is computed on parsed segments only.
  - The parse-failure rate is a new scope metric with an interval.
  - Evaluation output flags sparse-score AP.
- `data/splits/contract_splits.csv`: 510 rows, `contract_id,contract_type,split`. It is written by `write_contract_splits_csv()`, now called from `python -m src.splits`, and was generated once from the existing `splits.parquet` (read, not recomputed).
- `tests/test_llm.py` (no network) and a CSV test in `tests/test_splits.py`.
- `docs/plan.md`: Rule D (LLM scores) and a Limitations section.

### Decisions made
- **Models:** `claude-sonnet-5` and `gemini-3.8-flash`.
  - Claude Opus 5 was the default recommendation; Sonnet 5 was chosen at about 40% of the cost.
  - Gemini 3.1 Pro exists only as a preview, which can change without a version bump, so it was rejected for a frozen, citable result. 3.5 Flash-Lite was rejected as a cost-tier rather than like-for-like comparison.
  - The exact served model ids are recorded from each response.
- **No temperature 0, contrary to the original instruction.**
  - Claude Sonnet 5 rejects sampling parameters (400). The installed `anthropic` 1.8.0 `messages.create` does not even take `temperature`.
  - Google's Gemini 3 guide strongly recommends the default 1.0 and warns lower values can cause looping or degraded output.
  - Neither model gets a temperature. Gemini gets `seed=42`, best effort only.
  - Reproducibility comes from caching every response, and variation is measured by a repeat check: 30 fixed validation windows (about 300 segments) re-run twice more with the cache bypassed, reporting pairwise and three-way label-set agreement.
- **Thinking:** Claude adaptive (the model default) with `effort="low"`; Gemini `thinking_level="low"`. Thinking tokens are billed as output on both.
- **Output: sparse with a 0.1 floor.** Every label with confidence of at least 0.1 is listed; unlisted labels score 0.
  - Rule D is pre-registered before any LLM output: F1 under Rule B is the primary cross-model metric, and LLM AP is a flagged lower bound.
  - Alternative considered: dense scores for all 33 labels.
  - Why rejected: roughly 8x the output tokens (estimated), and verbalized scores for 33 labels tend to cluster at a few values.
- **Prompt:**
  - Category definitions are loaded verbatim from `CUAD_v1.json`. A research check confirmed they are identical to the official `category_descriptions.csv` for all 41 categories.
  - Labels are listed in CUAD's order, so the Competitive Restriction Exception definition's "above" still points at Non-Compete, Exclusivity and No-Solicit Of Customers.
  - Only the three rules `docs/labeling_schema.md` documents: extraction-only text is none; Cap On Liability and Uncapped Liability can co-occur; Most Favored Nation is not limited to price.
  - No rule for Competitive Restriction Exception or Volume Restriction: the schema says "document only", and adding rules there would contradict gold labels.
  - No contract type is given: the baseline doesn't see it, and it would reveal the shift type.
- **Fixed context windows:**
  - Each contract is cut into consecutive 10-segment windows.
  - N=10 labels a whole window per call; N=1 labels one segment per call but shows the same whole window. Context is identical, and only the number of targets per call varies.
  - The N=1 latency is labeled "one target per call, full window context".
- **Selection rules, declared before any run:**
  - Prompt versions are selected by micro-F1@0.5 on the iteration sample, with a paired contract-bootstrap adoption rule: a new version replaces the incumbent only if its micro-F1 difference has a 95% interval excluding zero. At most 5 versions.
  - Batch size: N=10 unless N=1 is better by a paired interval excluding zero.
  - Macro-F1 is reported, not used.
- **Why prompt versions are selected differently from the baseline** (macro-AP for the baseline, micro-F1@0.5 with the paired adoption rule for the LLMs)
  - With sparse output, unlisted labels tie at 0, so LLM AP is a lower bound that penalizes labels the model left out. It cannot rank prompt versions fairly.
  - Micro rather than macro, because the iteration sample's thin labels (0 to 3 positives) would dominate macro-F1.
  - A fixed threshold of 0.5 is used during iteration because Rule B thresholds are tuned once, on full validation, after freezing.
- **Unstratified bootstrap on the iteration sample.**
  - Most of the 23 validation types will have a single contract in the sample, and a stratified bootstrap always redraws a single-contract stratum, which would make intervals too narrow.
  - Full validation, test and shift keep stratified resampling. Validation's one single-contract type, Non-Compete/No-Solicit/Non-Disparagement, is negligible across 97 contracts.
- **Parse failures:**
  - An invalid response is retried once; then the segment gets an empty prediction and `parse_failure=True`.
  - It counts as empty for F1, is excluded from the none false-positive rate, and the parse-failure rate is reported separately.
- **Latency:**
  - Measured around the SDK call for the successful attempt only.
  - Rate-limiter and pool waits, backoff sleeps and failed attempts are excluded; retries and backoff are recorded separately.
  - SDK auto-retries are disabled, so every attempt is timed here. The installed google-genai 2.25.0 does not retry by default anyway (checked in `_api_client.py`).
- **Refusal fallbacks off:** a server-side fallback would silently mix model versions in one prediction file. A refusal counts as an invalid response.
- **No test sampling:** estimated costs fit the $100 cap, so test and shift run in full, keeping Rule A and C lists and contract-bootstrap intervals identical to the baseline's. If measured costs project above the cap, the fallback is a stratified sample of whole contracts.
- **Held-out guard:** a completed run blocks reruns unless forced. A started but incomplete run (budget stop or transport failure) can resume from the cache, because no predictions or metrics were shown.
- **Split CSV:**
  - `splits.parquet` was already tracked in git (commit `b832404`), and the new CSV path is not gitignored, so no `.gitignore` change was needed.
  - The CSV makes the fixed split readable on GitHub and in diffs without Python.

### Numbers measured
- Segment volumes, read from `data/processed/segments.parquet` (excluded segments removed): validation 11,656 segments / 97 contracts / 5,013,154 characters; test 9,378 / 96 / 4,258,883; shift 4,584 / 28 / 2,250,421.
- `data/splits/contract_splits.csv`: 510 rows; train 289, val 97, test 96, shift 28. This matches `splits.parquet`.
- No API calls yet, and no spend.

### Problems hit and how we solved them
- None yet.

### Surprises in the data or results
- Several assumptions in the Step 3 prompt did not hold: temperature 0, Gemini caching at our prompt size, and a `data/splits` folder. Details are under Decisions.

### Resume-worthy
none

---

## 2026-09-24: Paused mid Step 3 (resume point)

### State
- All Step 3a code, tests and docs are written but **not committed** (see `git status`).
- Four core modules await review and placement. Drafts are in `drafts/step3_llm/` (`windows.py`, `prompt.py`, `parse.py`, `selection.py`); they go into `src/llm/`. Until they are placed, `src/llm/run.py` and `tests/test_llm.py` fail to import.
- No API calls have been made and nothing has been spent. The $100 ledger starts empty.

### To resume, in order
1. Done (2026-09-24): the four drafts were reviewed and moved unchanged (byte-identical to the reviewed versions) into `src/llm/`; `drafts/` deleted.
2. Commit the split file: `git add data/splits/contract_splits.csv src/splits.py tests/test_splits.py` then `git commit -m "Add human-readable contract split file"`.
3. Put `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in `.env`; confirm the gemini-3.8-flash prices in `src/config.py` against Google's pricing page.
4. Run, and paste the output: `pytest tests -v`, `python -m src.llm.run sample | tee data/processed/llm_sample.txt`, `python -m src.llm.run estimate | tee data/processed/llm_estimate.txt`. None of these call an API.
5. Then the smoke test (3 calls per model), v1 at N=10 and N=1, the adoption and batch-size rules, freeze, full validation, thresholds, the repeat check, and held-out, per the plan.

### Numbers measured
None.

### Resume-worthy
none

---

## 2026-09-24: Step 3b, account setup and offline checks (tests, iteration sample, cost estimate; no API calls)

### What we built
- Placed the four reviewed core modules (`windows.py`, `prompt.py`, `parse.py`, `selection.py`) into `src/llm/`, byte-identical to the reviewed versions; deleted `drafts/`.
- API accounts:
  - Anthropic: key `cuad-classifier`, 30-day expiry, default workspace, prepaid credits with auto-reload off.
  - Google: a dedicated Gemini project `cuad-classifier` so its bill shows only this work; linked billing account; the setup screen confirmed "Gemini API Paid Tier activated". Prepaid credits, auto-reload off, so running out of credit is a hard stop behind the $100 ledger cap.
  - Keys live in `.env` (gitignored, confirmed with `git check-ignore`).
- Gemini prices confirmed on ai.google.dev/gemini-api/docs/pricing (page "Last updated 2026-09-24 UTC"), `gemini-3.8-flash`, Standard, paid tier, per 1M tokens: input $0.75, output including thinking $3.75, context caching $0.075. They match `src/config.py`. The config comment now records the confirmation and the price change date.

### Decisions made
- Decision: Standard (synchronous) Gemini API, not Batch.
  - Alternatives considered: the Batch API at 50% off.
  - Why rejected: batch jobs return asynchronously, so per-call latency, one of the reported figures, would not be measurable; and it would differ from the Claude setup.
- Decision: keep auto-reload off on both providers.
  - Alternatives considered: auto-reload, which the Google screen marks "Recommended".
  - Why rejected: a finite prepaid balance is a second, provider-side hard stop if our ledger cap had a bug.
- Decision: finish all Gemini runs by 2026-12-31.
  - Alternatives considered: none needed yet.
  - Why: the pricing page lists gemini-3.8-flash at $1.50 / $7.50 / $0.15 from 2027-01-01, double the current prices. Any later run needs the config updated so the ledger stays correct.

### Numbers measured
- Tests: 83 passed.
  - Command: `pytest tests -v`
- Iteration sample: 9 validation contracts, 1,668 segments, one contract each from Co-Branding, Consulting, Distributor, Hosting, IP, License, Manufacturing, Outsourcing, Reseller. Total positive label instances 229; segments with any label 166. Labels with fewer than 5 positive segments ("too thin to judge"): 15 of 33, of which 4 have zero (Most Favored Nation, No-Solicit Of Customers, Third Party Beneficiary, Non-Disparagement). Largest: License Grant 25 segments in 6 contracts, Cap On Liability 20 in 8.
  - Command: `python -m src.llm.run sample | tee data/processed/llm_sample.txt`
  - Files: `data/processed/llm_sample.txt`, `data/processed/llm_iteration_contracts.csv`
- Casebook: 14 segments (4 Most Favored Nation, 5 License Grant misread as Exclusivity, 5 Anti-Assignment misread as Change Of Control); none falls inside the iteration sample, so they run as separate calls.
  - Same command and file.
- Offline cost estimate (assumptions: 4.0 characters per token; v1 prefix about 1,823 tokens; 25 output tokens per target; 300 thinking tokens per call):

  | phase | segments | calls | runs | Claude $ | Gemini $ |
  |---|---|---|---|---|---|
  | iteration, 5 versions, N=10 | 1,668 | 171 | 5 | 6.80 | 3.60 |
  | batch-size check, v1, N=1 | 1,668 | 1,668 | 1 | 9.65 | 5.67 |
  | full validation | 11,656 | 1,212 | 1 | 9.77 | 5.15 |
  | test | 9,378 | 985 | 1 | 8.01 | 4.21 |
  | shift | 4,584 | 470 | 1 | 3.96 | 2.06 |
  | repeat check, 2 extra runs | 300 | 30 | 2 | 0.48 | 0.25 |

  Totals: Claude $38.67, Gemini $20.94, combined $59.61 against the $100 cap. Full validation is an overestimate because it reuses cached iteration calls.
  - Command: `python -m src.llm.run estimate | tee data/processed/llm_estimate.txt`
  - File: `data/processed/llm_estimate.txt`

### Problems hit and how we solved them
- The estimate leaves out the casebook calls (up to 14 extra calls per iteration run, since no case is in the sample). Small next to the totals, but the table should include them. To fix together with the sample decision below.
- The totals line prints raw floats (38.669999999999995). Cosmetic; to fix with the above.

### Surprises in the data or results
- The 1,500-segment floor was reached after only 9 contracts (about 185 segments each), so the iteration sample has 9 contract clusters and covers 9 of the 23 validation types. The paired contract bootstrap that decides prompt adoption and batch size therefore resamples only 9 units. Decision pending before any API call (see the next entry).
- The v1 system prompt is about 1,823 tokens by the character estimate, about half the 3.5k assumed in the plan. Still above Claude Sonnet 5's 1,024-token caching minimum; still below Gemini's 4,096, as expected.

### Resume-worthy
none

---

## 2026-09-24: Step 3c, iteration sample widened and budget fallback pre-registered (before any API call)

### What we built
- Pre-registered Rule E in `docs/plan.md` (dated 2026-09-24, before any API call and before any LLM output existed).
- Also moved Steps 7 and 8 in `docs/plan.md` back under "Steps"; an earlier edit had left them after Rule D.

### Decisions made
- Decision: the iteration sample takes whole validation contracts in the same seeded round-robin order until it has at least 1,500 segments **and** at least one contract from every validation type (23 types).
  - Alternatives considered: keep the 9-contract sample (the segment floor alone); a 15-contract middle ground.
  - Why rejected: with 9 contracts, the paired contract bootstrap that decides prompt adoption and batch size resamples only 9 units, so the rule would rarely fire and the intervals rest on very few clusters; 15 of 33 labels were too thin to judge; 14 of 23 types were absent. The middle ground still leaves 8 types out. The decision is outcome-blind: no model output exists.
  - Consequence: the seeded order is unchanged, so the 9 contracts already drawn (300, 285, 431, 214, 34, 91, 291, 46, 307) remain the first 9, and the new sample adds to them. The old `data/processed/llm_iteration_contracts.csv` must be deleted once so `sample` can write the new one (its guard refuses to overwrite a differing file).
- Decision: budget fallback order, applied only if the smoke test re-projects the total above the $100 cap, one at a time with a re-projection after each, until it fits:
  1. Maximum prompt versions per model from 5 to 3.
  2. The N=1 batch-size check on a seeded half of the iteration contracts (whole contracts, unstratified), logged as reduced power.
  3. Only then, the contract sample of test from the plan.
  - Alternatives considered: the plan's earlier fallback, which went straight to sampling test.
  - Why rejected: sampling test weakens every model's final numbers and the cross-model comparison; cutting iteration spend first costs only tuning power on validation.
  - Details, confirmed on 2026-09-24: "half" is rounded up (12 of 23 contracts); the N=10 side of that paired comparison is restricted to the same contracts, since `paired_micro_f1` requires identical segments. The fallback code is written only if the fallback triggers.

### Numbers measured
None yet. `sample` and `estimate` are re-run after the sampling change is placed.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
Pre-registered the iteration-sample rule and an ordered budget fallback before any API spend, so cost pressure could not bend evaluation choices after results were seen.

---

## 2026-09-24: Step 3d, widened iteration sample measured and re-estimated (no API calls)

### What we built
- Placed the Rule E stopping rule in `src/llm/windows.py` (`iteration_contracts`) and two test additions in `tests/test_llm.py` (every validation type covered; first 9 contracts unchanged).
- `estimate` now includes the casebook calls and prints rounded totals.
- Deleted the old 9-contract `data/processed/llm_iteration_contracts.csv` once so `sample` could write the new one.

### Decisions made
- Decision: proceed to the smoke test with the full plan (5 versions, N=1 check on all 23 contracts), no fallback step applied.
  - Alternatives considered: applying fallback step 1 now.
  - Why rejected: Rule E triggers the fallback on the smoke test's measured re-projection, not on the offline estimate; the estimate is under the cap.

### Numbers measured
- Tests: 84 passed (83 before plus `test_widened_sample_keeps_the_first_nine_contracts`).
  - Command: `pytest tests -v`
- Iteration sample: 23 validation contracts, 3,354 segments, one contract from each of the 23 validation types. Total positive label instances 474; segments with any label 358. Labels too thin to judge (< 5 segments): 7 of 33 (was 15 of 33 with 9 contracts): Third Party Beneficiary 1, Most Favored Nation 1, Non-Disparagement 2, No-Solicit Of Customers 2, Volume Restriction 3, Joint Ip Ownership 3, Notice Period To Terminate Renewal 4. Largest: License Grant 55 segments in 12 contracts.
  - Command: `python -m src.llm.run sample | tee data/processed/llm_sample.txt`
  - Files: `data/processed/llm_sample.txt`, `data/processed/llm_iteration_contracts.csv`
- Casebook: 2 of the 14 cases now fall inside the iteration sample (56_97, License Grant misread as Exclusivity; 56_143, Anti-Assignment misread as Change Of Control), because contract 56 was drawn. The other 12 run as separate calls.
  - Same command and file.
- Offline cost estimate (same assumptions as Step 3b: 4.0 characters per token; prefix about 1,823 tokens; 25 output tokens per target; 300 thinking tokens per call):

  | phase | segments | calls | runs | Claude $ | Gemini $ |
  |---|---|---|---|---|---|
  | iteration, 5 versions, N=10 | 3,354 | 345 | 5 | 14.35 | 7.50 |
  | casebook, 5 versions, N=10 | 120 | 12 | 5 | 0.55 | 0.27 |
  | batch-size check, v1, N=1 | 3,354 | 3,354 | 1 | 20.75 | 11.91 |
  | casebook, v1, N=1 | 12 | 12 | 1 | 0.08 | 0.04 |
  | full validation | 11,656 | 1,212 | 1 | 9.77 | 5.15 |
  | test | 9,378 | 985 | 1 | 8.01 | 4.21 |
  | shift | 4,584 | 470 | 1 | 3.96 | 2.06 |
  | repeat check, 2 extra runs | 295 | 30 | 2 | 0.53 | 0.27 |

  Totals: Claude $58.00, Gemini $31.41, combined $89.41 against the $100 cap. Full validation is still an overestimate because the frozen version's iteration calls are cached.
  - Command: `python -m src.llm.run estimate | tee data/processed/llm_estimate.txt`
  - File: `data/processed/llm_estimate.txt`

### Problems hit and how we solved them
- The rough projection before the change ($70 to $75 combined) was too low: the sample came out at 3,354 segments, not the roughly 2,800 assumed, and the N=1 check scales with it. The measured estimate ($89.41) is what counts.

### Surprises in the data or results
- Headroom under the cap is $10.59 on assumed token counts, and thinking tokens per call are the main unknown. The smoke test's measured tokens decide whether Rule E's fallback applies.
- The repeat check covers 295 segments, not 300: some of the first 30 windows are a contract's shorter last window.
- Prepaid balances ($50 Anthropic, $20 Gemini) are below the per-provider estimates ($58.00, $31.41); top-ups are sized after the smoke test re-projection.

### Resume-worthy
none

---

## 2026-09-24: Step 3e, smoke test (first API calls)

### What we built
- Nothing new; this step exercised the API path, cache, ledger, and retries on the first 3 to 6 iteration calls.
- Mechanical fix afterwards: Gemini's automatic function calling is disabled client-side (we send no tools) to silence the SDK warning. It is not part of the payload, so request hashes and cached calls are unchanged.

### Decisions made
- Decision: do not re-project the full budget from the smoke test alone.
  - Alternatives considered: re-project now, as Rule E's wording says.
  - Why rejected: all smoke calls came from the first windows of one contract (contract 15), which carry no gold labels (macro-F1 NaN: no label had support; no predictions made). Output tokens there are a floor, not a typical value. The next planned run (v1, N=10, full iteration sample) is representative and is used for the re-projection before the N=1 check, which is the largest single phase. Pending user confirmation (next entry).

### Numbers measured
Commands: `python -m src.llm.run iterate --model {claude,gemini} --prompt v1 --batch-size 10 --limit {3,6} --max-cost 1`, then `wc -l data/llm_cache/ledger.jsonl`. Output pasted in the session; smoke runs write no prediction file.
- Claude (served `claude-sonnet-5`):
  - Run 1, 3 new calls: cache_creation_input_tokens 9,339 (all 3 wrote the prefix, as expected with parallel calls), cache_read 0, input_tokens 6,232, output_tokens 450, cost $0.0403; latency per call median 3,352 ms, p95 4,455 ms.
  - Run 2, `--limit 6`, 3 new calls: cache_read_input_tokens 9,339, so each new call read the cached prefix. Prompt caching works. Cumulative cost over 6 calls $0.0618.
  - Run 3: new_calls_this_run 0. Reruns are free.
  - Derived from the above: the cached prefix is 3,113 tokens per call (9,339 / 3), against 1,823 in the character-based estimate; output was 150 tokens per 10-target call on these label-free windows; parse failures 0.
- Gemini (served `gemini-3.8-flash`):
  - Run 1: 1 of 3 calls failed after 5 attempts, each `503: This model is currently experiencing high demand`. The 2 completed calls were cached.
  - Run 2: resumed with 1 new call, which succeeded after 4 transport retries. Totals over the 3 calls: prompt_token_count 8,672, candidates_token_count 669, thoughts_token_count 0, cached_content_token_count 0, cost $0.009; latency per call median 2,470 ms, p95 19,655 ms (3 calls only).
  - Derived: 2,891 prompt tokens and 223 output tokens per call; no thinking tokens at thinking_level "low"; no implicit caching, as expected below 4,096 tokens.
- Ledger: 9 lines (6 Claude + 3 Gemini completed calls; failed 503 attempts are not billed or logged as spend).
- Parse-failure rate 0.0 for both models.

### Problems hit and how we solved them
- Gemini 503 "high demand": the backoff (1, 2, 4, 8 seconds plus jitter, about 15 s in total over 5 attempts) was too short for this capacity spike. The resume-from-cache design worked as intended: the rerun paid only for the missing call. A longer retry budget is proposed in the next entry.
- `micro_f1` printed 0.0 where it is undefined (no positives and no predictions in the smoke sample), and numpy warned "Mean of empty slice" for AP. Both come from the smoke sample having no labeled segments; neither can occur on the full iteration sample. Noted, not changed.

### Surprises in the data or results
- Claude counts about 1.7 times as many tokens as the 4-characters-per-token estimate for the prefix (3,113 against 1,823). The same 3 windows cost Gemini 2,891 prompt tokens per call including its prefix, so the gap is Claude's tokenizer and the structured-output schema, not our text.
- Neither model spent visible thinking tokens on these windows (Claude's 150 output tokens per call is about the size of the empty JSON answer; Gemini reported 0 thoughts). The estimate assumed 300 per call.

### Resume-worthy
none

---

## 2026-09-24: Step 3f, budget checkpoint, batch-size outcome rule, longer retries (before any labeled output)

### What we built
- `src/config.py`: `LLM_BUDGET_USD` 100 to 150 (hard cap); new `LLM_SOFT_CHECKPOINT_USD = 100.0`; `LLM_MAX_ATTEMPTS` 5 to 8.
- `src/llm/run.py`: `soft_checkpoint()`, run by `iterate`, `val`, `repeat` and `heldout` before any call. It counts the command's uncached calls, projects their cost, prints spend so far, the projection and its basis, and stops if the total would pass $100 unless the command carries `--past-checkpoint`. `heldout` runs it before its one-time guard is marked as started, so a stop does not use up the held-out run.
  - Projection basis: the ledger's mean cost per completed call for the same model and batch size (all attempts; errs high for Claude because early calls include cache writes); the offline estimate formula when there is no ledger history at that batch size (the first N=1 run).
  - Calls already cached project $0 and never trip the checkpoint.
- Tests: `test_soft_checkpoint_stops_before_any_call_unless_approved`, `test_soft_checkpoint_falls_back_to_the_offline_estimate`.
- `docs/plan.md` Rule E amended with the cap, the checkpoint, the fallback trigger, and the batch-size outcome rule, dated 2026-09-24.

### Decisions made
- Decision: if N=1 beats N=10 on the iteration sample, validation, test and shift still run at N=10; the N=1 gain is reported as a measured accuracy/cost trade-off.
  - Alternatives considered: drop the N=1 check (saves about $33 by the estimate, but leaves no evidence on label bleed from batching); act on a win (about $250 more at the estimate's per-segment rates: 25,618 val+test+shift segments at $20.75/3,354 per segment for Claude and $11.91/3,354 for Gemini).
  - Why rejected: acting on it is beyond any budget considered; dropping it loses a result a law firm would care about (what batching costs in accuracy).
  - Gap this closes: the original rule said "use N=10 unless N=1 wins" without saying what happens when N=1 wins but cannot be afforded. Fixed before any N=1 output exists.
- Decision: hard cap $150 with a soft checkpoint at $100 that needs explicit approval (`--past-checkpoint`) to pass; Rule E's fallback order applies only if continuing is declined.
  - Alternatives considered: keep a $100 hard cap (fallback triggers automatically); a $150 cap with no checkpoint.
  - Why rejected: the first forces cuts to iteration power even when a larger spend would be accepted to avoid them; the second removes the human decision at the point where spending passes the original plan.
  - Timing: set after the smoke test, whose only outputs were label-free windows (no metric carries information), so the change is outcome-blind.
- Decision: `LLM_MAX_ATTEMPTS` 5 to 8, so backoff runs 1, 2, 4, 8, 16, 32, 60 seconds plus jitter (about 2 minutes) before a call is left for a rerun.
  - Alternatives considered: keep 5 and rerun by hand.
  - Why rejected: the smoke test hit 9 consecutive 503s on Gemini; at full-run scale, 5 attempts would leave many calls for manual reruns. Latency is unaffected (only the successful attempt is timed).
- Note: the retry jitter uses Python's unseeded `random`. It affects only sleep timing, never a request, a prediction or a metric, so it is outside the fixed-seed rule by design.

### Numbers measured
None new. The $250 figure above is arithmetic on the Step 3d estimate, not a measurement.

### Problems hit and how we solved them
- `worst_case_cost` (the per-call reservation for the hard cap) assumes 3 characters per token, while Claude measured about 1.7 times the 4-characters-per-token count. The reservation still holds as an upper bound because its output term (8,000 max tokens, about $0.08 per Claude call) dwarfs input; measured calls cost about $0.007. Noted, not changed.

### Surprises in the data or results
None.

### Resume-worthy
Built a spend checkpoint that pauses a paid LLM run for human approval before it passes the planned budget, with projections from measured per-call costs.

---

## 2026-09-24: Step 3g, Claude v1 at N=10; parser floor; yardstick; prompt-version plan and v4 cost gate

### What we built
- `src/llm/parse.py`: labels listed below the 0.1 floor are dropped after a repeated label keeps its max, so they score as unlisted (Rule D). `build_frame` applies the same floor to records cached before this change. Test: `test_label_below_the_floor_scores_as_unlisted`.
- `python -m src.llm.run yardstick` (no API calls): the frozen baseline's saved validation predictions restricted to the 23 iteration contracts, scored with the same `score()` at its tuned Rule B thresholds and at 0.5, plus a paired unstratified bootstrap of each model's v1 N=10 against it (context only, not a selection criterion).
- `docs/plan.md` Rule E: the v2, v3, v4 plan and the v4 cost gate, dated 2026-09-24.

### Decisions made
- Decision: drop below-floor entries at parse time and in `build_frame`, applied before v1 is compared with anything.
  - Alternatives considered: keep them as small scores.
  - Why rejected: Rule D defines unlisted labels as score 0; a 0.05 kept as 0.05 would rank above unlisted positives in AP and could shift a tuned threshold. Effect on v1: none numerically, because all 338 stored below-floor scores in Claude's v1 cache are exactly 0.
- Decision: score the baseline on the iteration contracts as a yardstick before drafting v2.
  - Caveat recorded: the baseline's thresholds were tuned on full validation, which includes these 23 contracts, so its tuned-threshold figure is optimistic; the 0.5 figure has no such tuning.
- Decision: versions v2 (per-call object schema, floor instruction, Change Of Control note), v3 (v2 plus TF-IDF-retrieved train examples), v4 (v3 with dense output), each through the adoption rule.
  - Recorded limits: v2 bundles three changes, so an adoption cannot be attributed to one of them; v3's retrieved examples differ per window and therefore go in the user message, not the cached prefix, raising input cost; about 89% of segments carry no label, so nearest neighbours will mostly be none examples.
  - v4 motivation, as it can be stated truthfully: v1 spontaneously listed rejected labels at confidence 0 in 513 of 1,248 label entries (41%), a format behaviour, and Rule D's sparse-AP caveat. Not motivated by scores. v1's missing and duplicate ids are addressed by v2's schema, not by dense output. Dense verbalized confidences are coarse with many ties, so v4 would change the AP caveat rather than remove it.
- Decision: the v4 cost gate (Rule E). Why: by a rough count, dense output is about 2,300 to 2,600 output tokens per 10-segment call against about 210 in v1, so running validation, test and shift in v4 format could exceed the $150 cap. Measured by a smoke test before v4 runs.

### Numbers measured
- Claude v1, N=10, iteration sample (23 contracts, 3,354 segments), threshold 0.5: micro-F1 0.4062, macro-F1 0.3398, macro-AP (sparse, lower bound) 0.3193, none false-positive rate on parsed segments 0.0419, parse-failure rate 0.0057.
  - Usage: 345 calls, 366 attempts, 21 parse retries, 0 transport retries; tokens cache_creation 15,565, cache_read 1,123,793, input 636,636, output 80,852; cost $2.3455 for the iteration calls, $0.6993 per 1,000 segments; latency per call median 3,125 ms, p95 6,433 ms; per segment (call-amortized) median 321 ms; served `claude-sonnet-5`.
  - Checkpoint line before the run: spent $0.07, projected $3.62 (ledger mean $0.0103 per call at N=10).
  - Casebook (threshold 0.5, not a selection criterion): Most Favored Nation 0 of 4 (no labels predicted); License Grant misread as Exclusivity 3 of 5 pass (the 2 misses predicted nothing); Anti-Assignment misread as Change Of Control 2 of 5 pass (Anti-Assignment was predicted in all 5, but 3 also got Change Of Control at 0.5 to 0.7).
  - Command: `python -m src.llm.run iterate --model claude --prompt v1 --batch-size 10 --max-cost 6 | tee data/processed/llm_iter_claude_v1_n10.txt`
  - Files: `data/processed/llm_iter_claude_v1_n10.txt`, `data/predictions/iteration/claude_v1_n10.parquet`
- From the cached Claude v1 responses (read-only inspection, `data/llm_cache/claude/v1/`): all 379 attempts finished normally; 513 of 1,248 label entries had confidence below 0.1 in 152 of 357 calls; all 21 parse retries were truncated answers covering 1 or 2 ids instead of 10, often repeating S1; 3 calls failed twice (19 segments: 17_50, 300_120 to 300_129, 460_32 to 460_39); output tokens per call median 210, max 699.
- Gemini v1 N=10: still running at the time of writing; about 3 calls per minute under repeated 503s (175 of about 357 calls after 56 minutes, $0.53 spent). Logged when it finishes.

### Problems hit and how we solved them
- Gemini capacity: see above. The run continues; resumable from cache if stopped.

### Surprises in the data or results
- Claude's truncated answers (1 or 2 ids of 10) happened under a schema that allowed any array length; this is what v2's fixed-key schema targets.

### Resume-worthy
none

---

## 2026-09-24: Step 3h, baseline yardstick on the iteration sample; Gemini v1 resumes

### What we built
Nothing new; ran the parser-floor tests, rewrote Claude's v1 file from cache, ran `yardstick`, resumed Gemini v1.

### Decisions made
None.

### Numbers measured
- Tests: 87 passed. Command: `pytest tests -v`
- Claude v1 N=10 rewritten from cache with the floor applied: identical figures (micro-F1 0.4062, macro-F1 0.3398, macro-AP sparse 0.3193, none FP 0.0419, parse failures 0.0057), `new_calls_this_run: 0`, checkpoint "all calls cached".
  - Command: `python -m src.llm.run iterate --model claude --prompt v1 --batch-size 10 | tee data/processed/llm_iter_claude_v1_n10.txt`
- Baseline on the same 23 iteration contracts (3,354 segments), from its saved validation predictions:
  - At its tuned Rule B thresholds (optimistic, tuned on full validation including these contracts): micro-F1 0.6182, macro-F1 0.5512, macro-AP 0.5815, none FP 0.0317.
  - At 0.5: micro-F1 0.5831, macro-F1 0.4941, none FP 0.0280.
  - The output labels the baseline's AP "sparse_lower_bound" because `score()` names the field that way; the baseline's scores are dense, so for it this is ordinary macro-AP.
  - Claude v1 N=10 minus baseline (tuned), micro-F1, paired unstratified contract bootstrap (2,000 resamples): -0.2121 [-0.2634, -0.1616].
  - Command: `python -m src.llm.run yardstick | tee data/processed/llm_yardstick.txt`
- Gemini v1 resume: 6 of 345 calls still incomplete (8 attempts each, all 503); checkpoint projected $0.22 before the run; spend before it $3.31.
  - Command: `python -m src.llm.run iterate --model gemini --prompt v1 --batch-size 10 --max-cost 3 | tee data/processed/llm_iter_gemini_v1_n10.txt`

### Problems hit and how we solved them
- Gemini 503s continue; each rerun sends only the missing calls.

### Surprises in the data or results
- Zero-shot Claude v1 is well below the TF-IDF baseline on the same segments: 0.21 micro-F1 lower than the baseline at tuned thresholds, with an interval that excludes zero, and still 0.18 below the baseline at a plain 0.5 threshold (0.4062 against 0.5831). It also flags more true-none segments (0.0419 against 0.0317). The baseline learned CUAD's labeling conventions from 289 train contracts; v1 sees only the category definitions. This is a v1 validation result on the iteration sample, not a test result.

### Resume-worthy
Measured a zero-shot frontier LLM against a TF-IDF baseline on identical contracts with paired contract-bootstrap intervals, and found the LLM behind by 0.21 micro-F1.

---

## 2026-09-25: Step 3i, why Claude v1 under-labels: breakdown, zero-confidence finding, CoC train check, probe plan

### What we built
- `python -m src.llm.run breakdown` (per-label support, predictions, precision, recall, F1 for an iteration run next to the baseline at its tuned thresholds on the same segments; validation only).
- Read-only inspections of the Claude v1 cache and of train gold (no API calls, no model runs).

### Decisions made
- Decision: run a diagnostic probe before writing v2, with four variants: A v1 text at effort "medium"; B v1 plus a paragraph reframing the question-style definitions as clause types, effort "low"; C B plus a short `evidence` quote before each confidence; D B at effort "medium". All four reported side by side, with thinking tokens for A and D.
  - Alternatives considered: fold the likely fix straight into v2.
  - Why rejected: an adopted v2 could not say which change fixed the zero-confidence failure.
  - Discipline: the probe runs on iteration windows selected for failures and is used only to choose v2's contents. The adoption decision comes only from `compare` on the full iteration sample. Probe variants live outside `PROMPT_VERSIONS`, so they cannot be adopted or count toward the 5-version limit.
- Decision: roadmap after v2 unchanged: v3 adds retrieved train examples (nearest neighbours by the frozen baseline TF-IDF vectorizer, with gold labels); v4 tries dense output under the cost gate. If v2 only partly fixes the zero-confidence failure, retrieved examples target it directly: they show the model what CUAD's annotators labeled, which is the convention the question-style definitions leave unclear.
- Decision: keep the Change Of Control note in v2, narrowed to what train gold supports (see numbers). Draft: an assignment clause is also Change Of Control only when a party's change of control itself triggers consent, notice or a termination right (for example by being deemed an assignment); a clause that only permits or restricts assignment, including to a successor in a merger or "by operation of law", is Anti-Assignment only.

### Numbers measured
- Claude v1 N=10 against the baseline (tuned) on the 23 iteration contracts: micro precision 0.5197 vs 0.6362; micro recall 0.3333 vs 0.6013. Largest recall gaps: Governing Law 0.136 vs 0.955 (22 gold segments; Claude predicted 4), Expiration Date 0.182 vs 0.727, Revenue/Profit Sharing 0.043 vs 0.391, Irrevocable Or Perpetual License 0.143 vs 0.857, Affiliate License 0.167 vs 0.750, Competitive Restriction Exception 0.062 vs 0.250, Liquidated Damages 0 predicted (13 gold). Claude is ahead on Exclusivity (F1 0.478 vs 0.304), Rofr/Rofo/Rofn (0.643 vs 0.571), Covenant Not To Sue (0.533 vs 0.500), Joint Ip Ownership (0.400 vs 0.333).
  - Command: `python -m src.llm.run breakdown --model claude --prompt v1 | tee data/processed/llm_breakdown_claude_v1.txt`
- Zero-confidence finding (read-only, `data/llm_cache/claude/v1/`, with gold from `data/predictions/iteration/claude_v1_n10.parquet`): Claude names the correct category and gives it confidence 0.0. Example 15_213, "SECTION 13. GOVERNING LAW AND TIME. This Agreement shall be governed by and construed in accordance with the laws of the State of New York...", returned `{"label":"Governing Law","confidence":0}`; the same held for 34_268, 56_138, 91_53 and 93_38. The zero sits on the correct local id, so it is not an alignment bug, and these segments parsed normally. Labels listed below 0.1 versus at or above 0.1 in v1's final answers: License Grant 49 vs 60, Termination For Convenience 41 vs 28, Governing Law 40 vs 7, Post-Termination Services 31 vs 73, Ip Ownership Assignment 30 vs 54, Cap On Liability 26 vs 27, Competitive Restriction Exception 23 vs 5, Minimum Commitment 22 vs 19, Most Favored Nation 21 vs 7.
- Hypotheses to test: (1) CUAD's definitions are questions about the whole contract ("Which state/country's law governs the interpretation of the contract?", "On what date will the contract's initial term expire?"), while v1 asks for confidence that a category applies to a segment; (2) effort "low" produced no thinking, so the label is committed before it is weighed.
- CoC train check (train split only, read-only): 312 train Anti-Assignment segments in 209 contracts. Of the 123 that mention merger, change of/in control, operation of law or "substantially all", 28 also carry Change Of Control and 95 (77%) do not; of the 189 that mention none of these, 6 do. Among the 28 with CoC, 9 say the change is deemed or constitutes an assignment or mention termination, against 4 of the 95 without; 13 of 28 name "change of/in control" explicitly, against 17 of 95. Keyword proxies, not a reading of each clause.
- Gemini v1: 4 of 345 calls still incomplete after the latest resume (503s); spend before that run $3.51, projection $0.02.
  - Command: `python -m src.llm.run iterate --model gemini --prompt v1 --batch-size 10 --max-cost 3 | tee data/processed/llm_iter_gemini_v1_n10.txt`

### Problems hit and how we solved them
- `breakdown --model gemini` failed with FileNotFoundError because Gemini's v1 file is written only when every call has completed. Expected; rerun after the resume completes.

### Surprises in the data or results
- The low recall is not missed reading but miscalibrated reporting: the model identifies the clause type and scores it 0.

### Resume-worthy
Traced a frontier LLM's recall gap on contract clauses to a specific failure (correct category, zero confidence) by reading raw structured outputs, and set up a controlled four-variant probe to find the cause before changing the prompt.

---

## 2026-09-25: Step 3j, probe placed; Change Of Control note checked against train gold

### What we built
- Probe code placed per the Step 3i plan: `PROBE_VARIANTS` A to D, `REFRAME` and `EVIDENCE` texts, `version_spec`, `schema_for` and the optional `evidence` field in `src/llm/prompt.py`; `make_classifier(**overrides)` and a `thinking_blocks` count in Claude usage in `src/llm/clients.py`; `probe`, `probe_windows`, `probe_stats`, `_cached_records`, `_raw_entries` in `src/llm/run.py`; `LLM_PROBE_WINDOWS = 24` in `src/config.py`. v1 requests are byte-identical to before (tested: `schema_for("v1")` equals the old schema; probe_A's system prompt equals v1's), so v1's cache stays valid.
- Tests: `test_probe_variants_stay_outside_the_versions_and_leave_v1_unchanged`, `test_probe_windows_pick_only_failures_and_are_seeded`.

### Decisions made
- Decision: word the Change Of Control note as guidance, not a strict "only when" rule, after checking the 19 train CoC segments the trigger pattern missed and counting consent triggered by a change of control.
  - Proposed wording (finalized in Step 3m): "An assignment clause that mentions mergers, sales of all or substantially all assets, or assignment by operation of law only as ways an assignment can happen is usually "Anti-Assignment" only. Also label it "Change Of Control" when the clause addresses a change in a party's ownership or control as an event in its own right: for example, it names a change of control, deems one to be an assignment, or gives a right to terminate because of one."
  - Why this wording: the features that separate the 28 from the 95 are explicit naming of a change of control and treating it as an event with its own consequence; a consent requirement over an assignment "by merger, operation of law or otherwise" does not separate them (counts below).
  - Expected trade-off: some Change Of Control misses among clauses like the 19 below, in exchange for fewer false positives on the far more common clauses without the label. Judged only by the adoption rule.

### Numbers measured
All from train gold, read-only (`data/processed/segments.parquet`, split == "train"); keyword proxies, not a legal reading of each clause.
- Base: 312 train Anti-Assignment segments; 123 mention merger, change of/in control, operation of law or "substantially all"; 28 of those also carry Change Of Control (23%), 95 do not.
- The 19 of 28 without "deemed / constitutes an assignment / terminate" (read in full): mostly assignment bans that list a merger, change of control or operation of law among the prohibited forms and require consent (for example 44_249 "including by way of change of Control ... subject to the prior written consent", 103_106 and 258_47 "by operation of law, merger or otherwise, without the express written consent", 221_247 and 293_62 "by operation of law"), plus carve-outs that let a party assign on a merger or sale of assets, sometimes with notice (123_393, 173_30, 451_189, 469_126 "No transfer ... by operation of law or change in Control ... shall be considered an assignment"), and two with a dedicated change-of-control provision (330_235 "20.4 Change of Control", 334_235 "Assignment or Change of Control").
- Consent counts, per segment, 28 with CoC vs 95 without:
  - A, a sentence with a change-of-control event term and "consent" or "approval": 17 of 28 (61%) vs 66 of 95 (69%).
  - B, A excluding sentences with exception wording ("without ... consent", "need not", "shall not constitute", "may assign"): 8 of 28 (29%) vs 16 of 95 (17%).
  - X, a sentence with an event term and exception wording: 14 of 28 (50%) vs 61 of 95 (64%).
  - From Step 3i: explicit "change of/in control" 13 of 28 (46%) vs 17 of 95 (18%); "deemed / constitutes an assignment" or "terminate" 9 of 28 (32%) vs 4 of 95 (4%).
- Reading of the counts: a consent requirement tied to mergers or operation of law appears at similar rates with and without the label, so it cannot be the rule. Near-identical clauses go both ways (221_247 in train is labeled Change Of Control; the validation casebook segment 318_156, "by operation of law or otherwise, without the prior written consent", is not). CUAD's Change Of Control labeling on assignment clauses is not fully consistent, which caps what any wording can achieve.

### Problems hit and how we solved them
None.

### Surprises in the data or results
- Consent-over-merger language, the most natural rule, does not separate the labeled from the unlabeled train clauses (61% vs 69%).

### Resume-worthy
Checked a proposed prompt rule against the training annotations before using it, and found the gold labels inconsistent on near-identical clauses; worded the rule to follow the features that do separate them.

---

## 2026-09-25: Step 3k, diagnostic probe results (Claude, 24 failure-selected windows)

### What we built
Nothing new; ran the probe.

### Decisions made
- Decision (proposed): add a control variant E, v1 text at effort "low" in a fresh cache namespace, before choosing v2's contents.
  - Why: the 24 windows were selected because v1 failed on them. A plain rerun of v1 could also improve there (regression to the mean on a nondeterministic model), so A to D cannot be credited with their gains until a same-settings rerun is measured. About $0.17.
  - Alternatives considered: choose v2 contents from A to D as they stand.
  - Why rejected: the effect sizes could be partly or wholly selection plus run-to-run noise.

### Numbers measured
- Probe windows: 24 of 62 iteration windows in which v1 listed a gold label below 0.1 (seeded, stream "probe"). Diagnostic only; used to choose v2's contents; adoption comes only from `compare` on the full iteration sample.
- Results on those 24 windows (threshold 0.5):

  | variant | recall | precision | gold listed < 0.1 | any listed < 0.1 | parse-failed segments | input tokens | output tokens | thinking blocks | cost $ |
  |---|---|---|---|---|---|---|---|---|---|
  | v1 (cache), effort low | 0.1461 | 0.6500 | 33 | 63 | 0 | 146,056 | 7,024 | 0 | 0.2055 |
  | A: v1 text, effort medium | 0.7528 | 0.6442 | 0 | 0 | 0 | 124,203 | 8,090 | 3 | 0.2091 |
  | B: v1 + reframing, effort low | 0.7303 | 0.7065 | 0 | 0 | 0 | 128,019 | 6,754 | 0 | 0.1898 |
  | C: B + evidence quote, effort low | 0.7640 | 0.5913 | 0 | 0 | 0 | 129,723 | 11,641 | 0 | 0.2468 |
  | D: B at effort medium | 0.7640 | 0.7312 | 0 | 0 | 0 | 128,019 | 8,022 | 3 | 0.2024 |

- Estimated thinking tokens (output minus the same windows at effort low; also absorbs any change in answer length): A minus v1 1,066; D minus B 1,268. Only 3 of 24 calls returned a thinking block under effort "medium" in A and in D.
- Checkpoint lines: spent $3.53 before the probe; projections $0.16, $0.17, $0.17, $0.17; spent $4.17 before D. Probe cost from the table: $0.848 for A to D.
  - Command: `python -m src.llm.run probe --max-cost 2 | tee data/processed/llm_probe.txt`
- Gemini v1: 2 of 345 calls still incomplete (c300_w12, c93_w2; 503s); spent $3.52 before that run. `breakdown --model gemini` failed again for lack of the file.
- Tests: 89 passed.

### Problems hit and how we solved them
- Gemini 503s persist on two calls; rerun later.

### Surprises in the data or results
- Every variant removed below-floor listings entirely (63 to 0), including A, which changes only effort and thinks on just 3 of 24 calls. That effort changes behaviour without thinking is plausible, but so is regression to the mean; control E separates them.
- The evidence field (C) raised output tokens by about 70% over B and lowered precision (0.5913 against 0.7065).

### Resume-worthy
none

---

## 2026-09-25: Step 3l, control E added; reading rule pre-registered before running it

### What we built
- `PROBE_VARIANTS["probe_E"]`: v1 text at effort "low" in a fresh namespace (same request as v1, so the same request hash, but a new cache path and therefore a real new call). Rerunning `probe` serves A to D from cache and sends only E's 24 calls (about $0.17).

### Decisions made
- Decision, reading rule for E, fixed before E runs, on E's recall over the same 24 windows:
  - E recall <= 0.30: the gains in A to D are real; v2 = reframing + effort "medium" (D's recipe).
  - E recall >= 0.60: the probe mostly measured noise; v2 = reframing at effort "low", and effort "medium" is not adopted without evidence from the full sample.
  - Between 0.30 and 0.60: the gains are treated as partly real; v2 = D's recipe, and the log notes that the probe likely overstates the effect.
  - In all cases the evidence quote (C) is dropped, and v2 replaces v1 only under the adoption rule on the full iteration sample.
  - Why: the windows were selected for v1's failures on a nondeterministic model, so a same-settings rerun is the only way to separate the variants' effect from regression to the mean.

### Numbers measured
None yet.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
Added a same-settings rerun control to a failure-selected prompt probe and pre-registered how its result would decide the next prompt version.

---

## 2026-09-25: Step 3m, Change Of Control note for v2 finalized

### What we built
Nothing new; the wording below goes into v2's rules.

### Decisions made
- Decision: final Change Of Control note for v2:
  > An assignment clause that mentions mergers, sales of all or substantially all assets, or assignment by operation of law only as ways an assignment can happen is usually "Anti-Assignment" only. Also label it "Change Of Control" when the clause treats a change in a party's ownership or control as an event with its own consequences: for example, it deems a change of control to be an assignment, or gives a right to terminate because of one.
- Counts behind it (train gold, read-only, keyword proxies; Steps 3i and 3j), among the 123 train Anti-Assignment segments that mention merger, change of/in control, operation of law or "substantially all" (28 also labeled Change Of Control, 95 not):
  - "Usually Anti-Assignment only": 95 of 123 (77%) carry no Change Of Control label.
  - Kept as examples: "deemed / constitutes an assignment" or "terminate", 9 of 28 labeled vs 4 of 95 unlabeled. Used as a sufficient signal within this pool, it would add about 9 true positives against 4 false positives.
  - Left out, naming a change of control: 13 of 28 (46%) vs 17 of 95 (18%). Although more common among labeled clauses, as a sufficient signal it would add about 13 true positives against 17 false positives, so more false positives than true ones.
  - Left out, consent tied to a change-of-control event: 17 of 28 (61%) vs 66 of 95 (69%) in the same sentence; 8 of 28 (29%) vs 16 of 95 (17%) after excluding exception wording. It does not separate labeled from unlabeled clauses.
  - Caveat: CUAD labels near-identical clauses both ways (train 221_247 labeled Change Of Control; validation casebook 318_156 not), which caps what any wording can achieve.
- Decision: the v2 breakdown reports Change Of Control precision and recall on their own line, against v1 and the baseline, to show whether the note helped precision or cost recall. `breakdown` already prints per-label precision and recall, so this needs no code change; the log will quote that row explicitly.

### Numbers measured
None new.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-25: Step 3n, control E result; run-health rule, v1 incumbent and raw-text scoring pre-registered (before any further run)

### What we built
Nothing implemented yet. This entry fixes the rules before any further API call.

### Decisions made
- Reading-rule outcome (pre-registered in 3l): control E recall 0.7640 >= 0.60, so the probe mostly measured noise. v2 = reframing paragraph at effort "low"; effort "medium" is not adopted without full-sample evidence; the evidence quote (C) is dropped; v2 replaces its incumbent only under the adoption rule on the full iteration sample.
  - A to D's gains over v1 on the probe windows cannot be credited to their changes. On the same windows in the same period, reframing (B: 0.7303 / 0.7065) did not beat plain v1 rerun (E: 0.7640 / 0.7640).
- Decision, run-health rule, pre-registered 2026-09-25:
  - Metric: the share of calls whose raw response, in any attempt, lists any label with confidence below 0.1; computed on raw text before parsing, without gold labels; non-JSON responses counted separately and not flagged.
  - Reported for every run: iteration, rerun, validation, test, shift, repeat (per namespace), probe.
  - Scope: sparse output only. A dense format lists every label, so below-floor entries are expected; if a dense version (v4) is ever run, its own health metric is defined and logged before its first call. The code refuses to compute it for a dense version.
  - Threshold: if a held-out (test or shift) run exceeds 5% of calls, that run is declared invalid for infrastructure reasons and redone once, in a fresh cache namespace, under an explicit override; both runs are logged with this rule cited. One redo only, and the redo stands. If the redo also exceeds 5%, its results are reported with the health figure and flagged in the write-up as unreliable for infrastructure reasons, with no further reruns.
  - Descriptive companions, label-free, report only, trigger nothing: the share of target segments whose parsed list (labels at or above 0.1) is empty, and the mean number of labels listed at or above 0.1 per segment; parse-failed segments excluded and counted separately.
- Decision, incumbent: v2's adoption test compares against a contemporaneous rerun of v1 (`v1-r2`), not the original v1 run. Both comparisons are logged; v2 vs `v1-r2` decides. `v1-r2` and v2 are run back to back and both run windows are logged.
  - Why: the adoption rule compares prompts; the original run's failure mode (below) is not a property of the prompt.
- Decision, raw-text scoring: every prediction file (used by `compare`, `breakdown`, `yardstick`, threshold tuning) is built by re-parsing each record's final raw response with the current parser, not from the `scores` stored when the record was cached. So v1, v1-r2 and v2 are scored by identical rules.
  - Found: `build_frame` read stored scores and applied the 0.1 floor on top (Step 3g). For the floor rule that equals re-parsing (the parser keeps a repeated label's maximum, then applies the floor), so v1's figures should not change; a future parser change would not have reached old records.

### Numbers measured
- Control E on the 24 probe windows: recall 0.7640, precision 0.7640, gold listed below 0.1: 0, any listed below 0.1: 0, parse-failed segments 0, input tokens 124,203, output tokens 6,849, thinking blocks 0, cost $0.1967. Checkpoint: spent $4.38, projected $0.17; A to D were served from cache ("all calls cached").
  - Command: `python -m src.llm.run probe --max-cost 1 | tee data/processed/llm_probe.txt`
- Original v1 run versus the probe runs (read-only, cache timestamps and raw responses): the original v1 run (2026-09-24, records 20:20 to 20:50 UTC) has below-floor entries in 148 of 357 final answers; all probe calls (2026-09-25, 16:28 to 16:35 UTC), E included, have none. Served model `claude-sonnet-5` for all 357 v1 records.
- Correlates in the original v1 run, per attempt (379 attempts with readable JSON): attempt 1 152/357 (43%), attempt 2 18/22 (82%); cache write 0/5 and cache read 170/374 (45%), but all 5 writes were smoke-test calls, so write versus read is confounded with time; smoke-test calls 0/6; main run 94/233 (40%) in the 15 to 20 minute bin and 76/140 (54%) in the 20 to 25 minute bin after the first record; worker thread not recorded (added to records from now on). Flagged attempts were slower (median latency 3,859 ms vs 2,527 ms) and longer (median 248 vs 168 output tokens).
- Gemini v1: 1 of 345 calls still incomplete (c300_w12, 503s); spent $4.57 before that run.
- Tests: 89 passed.

### Problems hit and how we solved them
- The zero-confidence failure is tied to one run, not to the prompt; cause unknown (served model id unchanged). Handled by the health rule and a contemporaneous incumbent rather than by prompt changes.

### Surprises in the data or results
- A same-settings rerun of v1 on its worst windows lifted recall from 0.1461 to 0.7640. Run-to-run variation on this model can be as large as any prompt change we tested.

### Resume-worthy
Found that an LLM's apparent prompt failure was a transient run-level fault by adding a same-settings rerun control, then pre-registered a label-free run-health check that invalidates and redoes affected held-out runs.

---

## 2026-09-25: Step 3o, raw-text scoring, run health, reruns and the held-out rule placed

### What we built
- `src/llm/run.py`: `record_scores` (re-parses each record's final raw answer with the current parser; `build_frame` and `probe_stats` no longer read stored `scores` or `parse_failures`); `run_health`, `_label_items`, `is_sparse`; `usage_report` gains `record_window_utc` and `run_health`; `repeat` stores health per namespace; `probe` rows gain health columns; records gain `worker`; `iterate --rerun TAG`; `yardstick` includes v1 rerun files; `heldout_namespace`, `record_health`, `heldout --redo-invalid`.
- `src/config.py`: `LLM_HEALTH_MAX_SHARE = 0.05`.
- Comments and docstrings added earlier in Step 3 trimmed to one-line reasons (comments only where the why is not obvious).
- 9 new tests.

### Decisions made
None new; implements Step 3n.

### Numbers measured
- Tests: 98 passed. Command: `pytest tests -v`
- Claude v1 rebuilt from cache with raw-text scoring: identical to before (micro-F1 0.4062, macro-F1 0.3398, macro-AP sparse 0.3193, none FP 0.0419, parse failures 0.0057), confirming that flooring stored scores equalled re-parsing for the floor rule.
  - Run window (records): 2026-09-24T20:27:31 to 20:50:06 UTC.
  - Run health (iteration calls only): 143 of 345 calls listed a label below 0.1 (0.4145); unreadable attempts 0; empty-set share 0.8366; mean labels listed 0.2003; parse-failed segments 19.
  - Command: `python -m src.llm.run iterate --model claude --prompt v1 --batch-size 10 | tee data/processed/llm_iter_claude_v1_n10.txt`
- Probe, all from cache, with health columns (below-floor share / empty-set share / mean labels listed): v1 1.0 / 0.8750 / 0.1292 (1.0 by construction: windows were selected for below-floor listings); A 0.0 / 0.5583 / 0.6708; B 0.0 / 0.5833 / 0.6083; C 0.0 / 0.5708 / 0.6458; D 0.0 / 0.5958 / 0.6042; E 0.0 / 0.5625 / 0.6208.
  - Command: `python -m src.llm.run probe --max-cost 1 | tee data/processed/llm_probe.txt`

### Problems hit and how we solved them
- The expected test count was given as 99; the correct count was 98 (9 new, not 8).

### Surprises in the data or results
- The unhealthy v1 run left 83.7% of segments empty; healthy runs on the probe windows left 56% to 60% empty, and those windows were chosen for containing gold labels.

### Resume-worthy
none

---

## 2026-09-25: Step 3p, v2 placed

### What we built
- `src/llm/prompt.py`: `V2_INSTRUCTIONS` and `PROMPT_VERSIONS["v2"]` (keyed schema); `output_schema(..., target_ids)` builds `segments` as an object with exactly the call's target ids, all required, `additionalProperties: false`; `schema_for` uses the call's target ids for keyed versions and a full-window template for the prompt hash.
- `src/llm/run.py`: `_request` passes the call's local target ids; v1 ignores them, so v1 requests and cache keys are unchanged (tested).
- `src/llm/parse.py`: reads the list format and the keyed format, then applies the same checks (unexpected, duplicate and missing ids, labels, confidence range, floor).
- Tests: v2 schema requires exactly the call's targets at N=1 and N=10; keyed parsing with extra and missing keys; v2 prompt carries the additions from this entry. `drafts/` removed.

### Decisions made
- v2 = v1 plus: variant B's reframing paragraph verbatim; the floor sentence "Never list a category with confidence below 0.1."; rule 1 narrowed; the Change Of Control note (Step 3m); the return line for the keyed format. Effort "low", per the reading rule (Step 3n).
- Decision, rule 1 wording: "The names of the contract or of the parties, and the dates of signing or effectiveness, are not categories here. A segment that only states them gets an empty list unless it also contains one of the categories. Dates and periods that a category below describes, such as when the term ends or renews, the notice period to prevent renewal, or how long a warranty lasts, are labeled with that category."
  - Alternative considered: the earlier draft, "Dates on which the term ends or renews, notice periods and durations are covered by their own categories below."
  - Why rejected: "notice periods and durations" could pull in ordinary durations, such as payment or notice deadlines, that belong to no category.

### Numbers measured
None yet.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-25: Step 3q, v2 smoke test; Gemini v1 complete

### What we built
Nothing new.

### Decisions made
- Decision: keep v2's schema as placed, although Claude's cached prefix grows.
  - Alternative considered: define the label list once with `$defs`/`$ref` so it is not repeated per target key.
  - Why rejected for now: the extra cost is small (cache reads at $0.20 per million tokens; about 5,500 extra prefix tokens per call is about $0.001 per call), and schema-reference support on both providers is unverified; a change would need its own smoke test. Revisit only if cost becomes binding.

### Numbers measured
- Tests: 102 passed. Command: `pytest tests -v`
- Claude v2 smoke (`--limit 3`): 3 new calls, 0 parse failures, run health 0 of 3 below floor, empty-set share 1.0 on these label-free opening windows; tokens cache_creation 25,824 (8,608 per call, against 3,113 for v1), input 6,232, output 210 (70 per call, against 150 for v1); cost $0.0791 (mostly cache writes); latency per call median 3,619 ms.
  - v2 schema is 9,936 characters against 1,227 for v1 (the 33-label item repeats once per target key); v2 system prompt 8,632 characters against 7,291.
  - Command: `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 10 --limit 3 --max-cost 1`
- Gemini v2 smoke: 1 of 3 calls completed; 2 failed after 8 attempts (503). The completed call (c15_w0) returned a valid keyed answer with all 10 ids, finish ok, no parse errors, prompt_token_count 3,285, candidates 83. Gemini accepts the keyed schema.
  - Command: `python -m src.llm.run iterate --model gemini --prompt v2 --batch-size 10 --limit 3 --max-cost 1`
- Gemini v1, N=10, iteration sample (23 contracts, 3,354 segments), threshold 0.5, now complete: micro-F1 0.5934, macro-F1 0.5849, macro-AP (sparse, lower bound) 0.5693, none false-positive rate 0.0761, parse-failure rate 0.0.
  - Usage: 345 calls, 345 attempts, 0 parse retries, 801 transport retries (503s over several resumes); tokens prompt 911,400, candidates 97,746, thoughts 0, cached 0; cost $1.0501, $0.3131 per 1,000 segments; latency per call median 3,575 ms, p95 11,216 ms (successful attempts only, under heavy load); served `gemini-3.8-flash`.
  - Record window 2026-09-24T20:27:53 to 2026-09-25T17:23:32 UTC (spread over resumes).
  - Run health: 0 of 345 calls below floor; unreadable 0; empty-set share 0.8014; mean labels listed 0.2558; parse-failed segments 0.
  - Casebook (not a selection criterion): Most Favored Nation 4 of 4; License Grant misread as Exclusivity 4 of 5 (239_122 also got Exclusivity 0.75); Anti-Assignment misread as Change Of Control 1 of 5 (Change Of Control added at 0.65 to 0.95 in 4).
  - Command: `python -m src.llm.run iterate --model gemini --prompt v1 --batch-size 10 --max-cost 3 | tee data/processed/llm_iter_gemini_v1_n10.txt`

### Problems hit and how we solved them
- Gemini 503s: v1 needed 801 transport retries across resumes; the resume-from-cache design paid only for completed calls.

### Surprises in the data or results
- Gemini's v1 run was healthy throughout (0 below-floor calls), unlike Claude's; its micro-F1 at 0.5 (0.5934) is close to the baseline at 0.5 (0.5831) on the same segments, though it flags more true-none segments (0.0761 against 0.0280).
- Gemini's Change Of Control over-labeling on assignment clauses (4 of 5 casebook cases) is the pattern v2's note targets.

### Resume-worthy
none

---

## 2026-09-25: Step 3r, Claude v1-r2 and v2 (contemporaneous); v2 adopted; Gemini v1 yardstick and breakdown

### What we built
Nothing new.

### Decisions made
- Adoption (pre-registered rule, incumbent `v1-r2` per Step 3n): Claude v2 replaces v1. v2 minus v1-r2, micro-F1, paired unstratified contract bootstrap: +0.0280 [+0.0052, +0.0456]; the interval excludes zero.
  - v2 bundles five changes (keyed schema, reframing, floor sentence, narrowed rule 1, Change Of Control note), so the gain cannot be attributed to any one of them.
- Claude's incumbent for later versions is v2.

### Numbers measured
All on the 23 iteration contracts (3,354 segments), threshold 0.5.
- Claude v1-r2 (v1 prompt, fresh namespace): micro-F1 0.5806, macro-F1 0.5636, macro-AP sparse 0.5908, none FP 0.0751, parse failures 0.0. 345 calls, 0 parse retries, 0 transport retries; tokens cache_creation 6,226, cache_read 1,067,759, input 593,748, output 76,512, thinking blocks 0; cost $2.1817 ($0.6505 per 1,000 segments); latency per call median 2,524 ms, p95 4,186 ms. Record window 2026-09-25T17:26:56 to 17:33:52 UTC. Health: 0 of 345 below floor; empty-set share 0.7323; mean labels listed 0.3581; parse-failed segments 0. Checkpoint before: spent $4.66, projected $2.65.
  - Command: `python -m src.llm.run iterate --model claude --prompt v1 --rerun r2 --batch-size 10 --max-cost 4 > data/processed/llm_iter_claude_v1-r2_n10.txt 2>&1 &`
- Claude v2: micro-F1 0.6086, macro-F1 0.5841, macro-AP sparse 0.5693, none FP 0.0594, parse failures 0.0. 345 calls, 0 parse retries, 0 transport retries; tokens cache_creation 90,740, cache_read 2,824,108, input 593,748, output 46,570, thinking blocks 0; cost $2.4449 ($0.7289 per 1,000 segments); latency per call median 2,203 ms, p95 4,496 ms. Record window 2026-09-25T17:18:10 (the smoke calls) to 17:33:47 UTC. Health: 0 of 345 below floor; empty-set share 0.7579; mean labels listed 0.3160; parse-failed segments 0. Checkpoint before: spent $4.66, projected $2.63.
  - Command: `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 10 --max-cost 4 > data/processed/llm_iter_claude_v2_n10.txt 2>&1 &`
- Paired comparisons (Claude, micro-F1; macro-F1 reported only):
  - v2 minus v1-r2 (decisive): +0.0280 [+0.0052, +0.0456]; macro-F1 +0.0205 [-0.0061, +0.0432].
  - v2 minus v1 (original, reported): +0.2024 [+0.1548, +0.2579]; macro-F1 +0.2443 [+0.1833, +0.3224].
  - v1-r2 minus v1 (same prompt, run-to-run): +0.1744 [+0.1382, +0.2239]; macro-F1 +0.2238 [+0.1664, +0.3049].
  - Commands: `python -m src.llm.run compare --model claude --a v2:10 --b v1-r2:10`, `--b v1:10`, and `--a v1-r2:10 --b v1:10`; files in `data/eval/llm_selection/`.
- Claude v2 breakdown: micro precision 0.5790, micro recall 0.6414 (baseline 0.6362, 0.6013). Change Of Control (19 gold segments): v2 precision 0.407, recall 0.579 (27 predicted); original v1 0.250, 0.158; baseline 0.368, 0.368. v1-r2's row not yet produced, so the note's effect against the contemporaneous v1 is not yet readable.
  - Command: `python -m src.llm.run breakdown --model claude --prompt v2 | tee data/processed/llm_breakdown_claude_v2.txt`
- Casebook (not a selection criterion): v2 Most Favored Nation 4 of 4, License Grant misread as Exclusivity 4 of 5, Anti-Assignment misread as Change Of Control 0 of 5 (Change Of Control still added at 0.6 to 0.85); v1-r2 4 of 4, 3 of 5, 0 of 5.
- Yardstick: Gemini v1 minus baseline (tuned), micro-F1: -0.0248 [-0.0528, +0.0198]; Claude original v1 unchanged at -0.2121 [-0.2634, -0.1616].
  - Command: `python -m src.llm.run yardstick | tee data/processed/llm_yardstick.txt`
- Gemini v1 breakdown: micro precision 0.5147, micro recall 0.7004 (baseline 0.6362, 0.6013). Largest over-predictions: Third Party Beneficiary 22 predicted for 1 gold (precision 0.045), Post-Termination Services 67 for 29 (0.149), Competitive Restriction Exception 36 for 16 (0.250), Non-Compete 28 for 9 (0.214), Ip Ownership Assignment 23 for 9 (0.261). Change Of Control precision 0.435, recall 0.526.
  - Command: `python -m src.llm.run breakdown --model gemini --prompt v1 | tee data/processed/llm_breakdown_gemini_v1.txt`

### Problems hit and how we solved them
None.

### Surprises in the data or results
- The run-to-run difference of the same prompt (+0.1744 micro-F1, unhealthy against healthy run) is about six times the prompt effect that got v2 adopted (+0.0280). Health checks and contemporaneous incumbents are what make the adoption meaningful.
- The Change Of Control note did not change the casebook pattern (v2 still adds Change Of Control to all 5 assignment clauses); the full-sample row against v1-r2 decides whether it helped.
- v2's keyed output is shorter (46,570 output tokens against 76,512 for v1-r2) but costs more overall ($2.4449 against $2.1817) because the larger schema raises cache writes.

### Resume-worthy
Adopted a new prompt version only after a paired contract bootstrap against a same-period rerun of the incumbent, after showing that run-to-run variation of one prompt could be six times larger than the prompt effect.

---

## 2026-09-26: Step 3s, Gemini v1-r2 and v2 complete; Claude Change Of Control against v1-r2

### What we built
Nothing new. The two Gemini runs were resumed together in a loop (restart both, wait, 10 minutes between rounds, stop when both complete); they completed in round 1 on 2026-09-26.

### Decisions made
None yet; Gemini's adoption waits for `compare`.

### Numbers measured
All on the 23 iteration contracts (3,354 segments), threshold 0.5.
- Claude Change Of Control (19 gold segments), same period: v1-r2 28 predicted, precision 0.393, recall 0.579; v2 27 predicted, precision 0.407, recall 0.579. The note removed one false positive and left recall unchanged on the full sample. Claude v1-r2 micro precision 0.5247, micro recall 0.6498.
  - Command: `python -m src.llm.run breakdown --model claude --prompt v1-r2 | tee data/processed/llm_breakdown_claude_v1-r2.txt`
- Gemini v1-r2 (v1 prompt, fresh namespace): micro-F1 0.5964, macro-F1 0.5843, macro-AP sparse 0.5682, none FP 0.0731, parse failures 0.0. 345 calls, 0 parse retries, 790 transport retries; tokens prompt 911,400, candidates 97,699, thoughts 0, cached 0; cost $1.0499 ($0.3130 per 1,000 segments); latency per call median 3,803 ms, p95 12,460 ms (successful attempts, under load). Record window 2026-09-25T18:03:04 to 2026-09-26T13:48:27 UTC. Health: 0 of 345 below floor; empty-set share 0.8002; mean labels listed 0.2558; parse-failed segments 0.
- Gemini v2: micro-F1 0.6217, macro-F1 0.6045, macro-AP sparse 0.5790, none FP 0.0674, parse failures 0.0. 345 calls, 0 parse retries, 753 transport retries; tokens prompt 1,005,585, cached 131,811, candidates 49,885, thoughts 0; cost $0.8523 ($0.2541 per 1,000 segments); latency per call median 4,459 ms, p95 18,944 ms. Record window 2026-09-25T17:18:32 (smoke call) to 2026-09-26T13:46:36 UTC. Health: 0 of 345 below floor; empty-set share 0.8187; mean labels listed 0.2305; parse-failed segments 0.
  - Both runs were in progress over the same periods (resumed side by side each time); windows overlap.
  - Commands: `python -m src.llm.run iterate --model gemini --prompt v1 --rerun r2 --batch-size 10 --max-cost 3` and `... --prompt v2 ...`, outputs in `data/processed/llm_iter_gemini_v1-r2_n10.txt` and `llm_iter_gemini_v2_n10.txt`. Checkpoint before the final round: spent $10.73.
- Casebook (not a selection criterion): Gemini v2 Anti-Assignment misread as Change Of Control 4 of 5 pass (v1-r2: 1 of 5); Most Favored Nation 4 of 4 in both; License Grant misread as Exclusivity 4 of 5 in both.

### Problems hit and how we solved them
- Gemini 503s: 790 and 753 transport retries; resumed side by side until complete.

### Surprises in the data or results
- Gemini reported implicit cache hits on v2 (131,811 cached prompt tokens) although per-call prompts are below the documented 4,096-token caching minimum; v1 and v1-r2 had none. Recorded as observed; the ledger priced cached tokens at the cached rate.
- Gemini's same-prompt rerun barely moved (v1 0.5934, v1-r2 0.5964), unlike Claude's unhealthy v1.
- On the casebook, v2's Change Of Control note appears to help Gemini (4 of 5 against 1 of 5) but not Claude (0 of 5 in both); the full-sample Change Of Control row decides.

### Resume-worthy
none

---

## 2026-09-26: Step 3t, Gemini v2 not adopted; incumbents diverge

### What we built
Nothing new.

### Decisions made
- Adoption (pre-registered rule, incumbent v1-r2): Gemini v2 is not adopted. v2 minus v1-r2, micro-F1: +0.0254 [-0.0025, +0.0524]; the interval includes zero. Gemini's incumbent stays the v1 prompt; its same-period run is v1-r2.
  - v2 minus the original v1 run excludes zero (+0.0283 [+0.0008, +0.0519]) but is reported only; using it would switch the comparison after seeing results.
- Incumbents now differ by model: Claude v2, Gemini v1. v3 is still defined as v2 plus retrieved examples (Step 3i roadmap), so for Gemini, v3 against v1 also carries v2's changes; the log will say so when v3 is compared.

### Numbers measured
- Gemini paired comparisons (micro-F1; macro-F1 reported only):
  - v2 minus v1-r2 (decisive): +0.0254 [-0.0025, +0.0524]; macro-F1 +0.0203 [+0.0009, +0.0489].
  - v2 minus v1 (reported): +0.0283 [+0.0008, +0.0519]; macro-F1 +0.0196 [-0.0004, +0.0467].
  - v1-r2 minus v1 (same prompt, run-to-run): +0.0030 [-0.0082, +0.0131]; macro-F1 -0.0007 [-0.0120, +0.0079].
  - Commands: `python -m src.llm.run compare --model gemini --a v2:10 --b v1-r2:10`, `--b v1:10`, `--a v1-r2:10 --b v1:10`.
- Gemini breakdowns: v2 micro precision 0.5589, recall 0.7004; v1-r2 0.5240, 0.6920 (baseline 0.6362, 0.6013).
  - Change Of Control (19 gold): v2 20 predicted, precision 0.500, recall 0.526; v1-r2 23 predicted, 0.435, 0.526. Three fewer false positives, same recall.
  - Largest v2 over-predictions: Post-Termination Services 68 for 29 (precision 0.147), Ip Ownership Assignment 23 for 9 (0.261), Competitive Restriction Exception 22 for 16 (0.318), Third Party Beneficiary 15 for 1 (0.067).
  - Commands: `python -m src.llm.run breakdown --model gemini --prompt v2 | tee data/processed/llm_breakdown_gemini_v2.txt`; `... --prompt v1-r2 | tee data/processed/llm_breakdown_gemini_v1-r2.txt`
- Change Of Control note, both models, against the same-period v1 rerun: Claude 1 fewer false positive (28 to 27 predicted), Gemini 3 fewer (23 to 20); recall unchanged for both.

### Problems hit and how we solved them
None.

### Surprises in the data or results
- A healthy same-prompt rerun moves Gemini by only +0.0030, so its run-to-run noise is small next to Claude's unhealthy-run gap; v2's Gemini gain (+0.0254) is close to the adoption bar but not over it.

### Resume-worthy
none

---

## 2026-09-26: Step 3u, v3 design fixed before any v3 call

### What we built
- `CLAUDE.md` (Logging): BUILD_LOG entries describe decisions, numbers and problems without recording who made, wrote, placed or approved anything. Earlier entries were reworded to match; content unchanged (61 lines).

### Decisions made
- v3 = v2 plus retrieved training examples in the user message, before the window.
  - Retrieval, per target: the nearest train segment with at least one gold label, plus the nearest train segment overall (if that is the same segment, the next nearest overall). Cosine similarity on the frozen baseline TF-IDF vectorizer; ties to the lower segment by (contract_id, seg_idx); de-duplicated within a call.
  - Pool: every train segment with `exclude == False` (34,871, the set the frozen baseline was fit on). Excluded segments are never examples: shown as "none", they would teach that real clauses carry no label. Training-time none downsampling does not apply (the frozen configuration used none: `none_ratio` None).
  - Labels shown are the gold labels from `segments.parquet`, never baseline predictions.
  - Alternatives considered: 1 or 2 plain nearest neighbours per target.
  - Why rejected: 89% of train segments are unlabeled (train mean 428 characters, labeled mean 735), so plain neighbours often show only "none" examples. The chosen rule guarantees one labeled example of the convention and one realistic near-miss, which also targets Gemini's over-labeling.
  - Instruction added after the context paragraph: "Before the window you will see examples: segments from other contracts, with the categories CUAD's lawyers gave them, chosen because they resemble the targets. Use them to see how the categories are applied. They are not part of this contract; do not label them."
- Comparisons: decisive, v3 against each model's incumbent (Claude v2; Gemini v1-r2). Secondary, v3 against v2 for both. For Gemini, a v3 win cannot separate the examples from v2's changes.
- No incumbent rerun alongside v3. The run-health check covers the 2026-09-24 failure mode; it catches only that mode, and Claude's healthy run-to-run spread is not yet measured (the repeat check will). Gemini's healthy-to-healthy spread was +0.0030 [-0.0082, +0.0131].
- The N=1 batch-size check moves to each model's frozen prompt, on a seeded half of the iteration contracts (the fallback design), and comes back as its own decision before freezing. By the Step 3d estimate ($20.75 Claude, $11.91 Gemini on the full sample), half is about $16.
- Cost is estimated from the real retrieved text and each model's measured characters per token before any v3 call.

### Risks recorded before any v3 output
- Every target, including the roughly 89% with no gold label, gets a labeled example, which may prime false positives. Early signals: `mean_labels_listed` in run health, and precision in `breakdown`.
- Third Party Beneficiary, Gemini's largest over-prediction (22 predicted for 1 gold in v1), is one of the 5 pooled Rule B labels, so its tuned threshold is shared and can only partly correct it.
- Candidate for a later version, logged now: if v3 raises `mean_labels_listed` or lowers precision, include the labeled example only above a cosine-similarity cutoff, with the cutoff chosen on train or validation only.

### Numbers measured
- Read-only: `segments.parquet` train split has 34,871 segments with `exclude == False` and 50 with `exclude == True`; the frozen baseline config lists `train_segments` 34,871 and `none_ratio` None.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-26: Step 3v, v3 retrieval and prompt in place

### What we built
- `src/llm/retrieval.py`: `TrainIndex` (pool: train segments with `exclude == False`, ordered by contract_id and seg_idx; gold labels from `segments.parquet`; refuses a vectorizer without L2 norm), `neighbours` (nearest labeled, then nearest overall that is not the same segment; ties to the earlier pool row), `examples_for` (de-duplicated within a call), `train_index` (the frozen baseline's `tfidf` step, built once per process).
- `src/llm/prompt.py`: `EXAMPLES_PARAGRAPH`, `V3_INSTRUCTIONS` (v2 plus the paragraph after the context paragraph), `PROMPT_VERSIONS["v3"]` with `retrieval: True`; `user_message(call, examples=None)` returns the old message unchanged without examples and prepends `<examples>` otherwise.
- `src/llm/run.py`: `_request` adds examples for retrieval versions; `estimate-version --prompt V --base B` (no API calls) prices the real retrieved text with each model's measured characters per input token on B's cached iteration run.
- Tests: tie-breaking to the earlier segment, distinct labeled and overall examples, de-duplication, refusal of unnormalised vectors (synthetic); gold labels, no excluded segment returned, determinism, a labeled first example per target (real data); v1 and v2 messages unchanged, examples before the window, targets unchanged, v3 prompt equals v2 plus the paragraph.

### Decisions made
None new; implements Step 3u.

### Numbers measured
None yet.

### Problems hit and how we solved them
None.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-26: Step 3w, v3 cost estimate from real retrieved text (no API calls)

### What we built
- `src/baseline.py`: `load_frozen_pipeline()`; `src/llm/retrieval.py` now loads the frozen baseline through it.
- `estimate-version` measures Claude's rate on the uncached user message only.

### Decisions made
None new.

### Numbers measured
- Tests: 107 passed. Command: `pytest tests -v`
- v3 retrieval on the iteration sample: 17.2 examples per call on average (max 20); labeled share 0.515; mean example length 524 characters.
- Claude: 2.92 characters per uncached user-message token on the cached v2 run (1,734,022 characters over 593,748 input tokens). v2 iteration cost $2.44 (345 calls). v3 iteration: examples add $2.32, projected $4.76. If v3 were adopted, examples add $16.44 to validation, test and shift (2,667 calls) on top of about $18.90 at v2's measured cost per call.
- Gemini: 4.69 characters per prompt token on v2. v2 iteration cost $0.85. v3 iteration: examples add $0.54, projected $1.39. If adopted, examples add $3.84 on top of about $6.59.
  - Command: `python -m src.llm.run estimate-version --prompt v3 --base v2 | tee data/processed/llm_estimate_v3.txt`
- Ledger check against the provider console: ledger Claude spend $8.2943; Anthropic console for the `cuad-classifier` key $8.29. Ledger Gemini spend $3.0709; total $11.3652.
- Projection of the remaining Step 3 plan from these figures (arithmetic, not measured): v3 iteration both models about $6.15; validation, test and shift at v3 for both models about $45.77; N=1 check on half the iteration contracts about $16; repeat check about $1. Total about $80, under the $100 checkpoint.

### Problems hit and how we solved them
- `train_index()` failed with `AttributeError: module '__main__' has no attribute 'preprocess'`: `models/baseline/model.joblib` was pickled under `python -m src.baseline`, so it refers to `__main__.preprocess`, the only `__main__` reference in the file. `load_frozen_pipeline()` supplies that name before loading; the frozen file is unchanged. The frozen model had never been loaded outside `src.baseline` before.
- The first estimate measured Claude at 1.34 characters per input token and projected $5.04 and $35.74 for the examples. It divided system and user characters by all billed input tokens, which on Claude include the output schema (sent as a request parameter, about 9,900 characters of JSON) in the cached prefix. The examples add only uncached user-message tokens, so the rate is now user characters over `input_tokens`.

### Surprises in the data or results
- The Anthropic account's prepaid balance is shared with another project's key (console: $6.56 on that key). The ledger and caps count only this project's key; the shared balance is checked in the console before large runs.

### Resume-worthy
Reconciled a self-built LLM cost ledger with the provider's billing to the cent ($8.2943 against $8.29).

---

## 2026-09-26: Step 3x, first independent code review (Cursor CLI) and fixes

### What we built
- `scripts/review.sh`: a read-only review of a diff (`cursor-agent -p --mode ask`, no `--force`) against the rules in `CLAUDE.md`, reporting findings with file:line and a failure scenario.
- Fixes in `src/llm/run.py` for all four findings of the first review (all Step 3 LLM code since commit 78f10a7):
  1. Budget checkpoint: projects only from ledger history of the same namespace (prompt version); without history, the offline estimate is built from the real request, retrieved examples included (`_messages`). A cached record still awaiting its retry counts as not cached.
  2. Paid attempt kept: if the retry fails (budget stop or transport failure) after a paid first attempt, the record is saved with `retry_pending`; a resume sends only the retry.
  3. Best attempt kept: scores merge across attempts, a later attempt overriding an earlier one only for segments it parsed (`_merged_scores`, used by `_run_one` and `record_scores`).
  4. Freeze pins run settings: `prompt.json` records `run_settings` (model_id, effort or thinking_level, max_tokens); `load_frozen` refuses if the current config differs.
- Four tests, one per fix.

### Decisions made
- All four findings accepted: each was confirmed against the code before any change.

### Numbers measured
- Impact check before fixing (read-only): no ledger entry pays the same (model, namespace, call, attempt) twice, so finding 2 has not cost anything; of the 22 retried calls (all in Claude's original v1 run), none had an earlier attempt that parsed more targets than the final one, so finding 3 changes no existing result; nothing is frozen yet (finding 4); spend is $11.37, far below the $100 checkpoint (finding 1).
  - Review command: `scripts/review.sh 78f10a7 src/llm src/baseline.py src/config.py tests/test_llm.py`

### Problems hit and how we solved them
- See the four findings above.

### Surprises in the data or results
None.

### Resume-worthy
Added an independent automated code review step for LLM pipeline changes and fixed its four findings, each first checked against the code and the cost ledger for real impact.

---

## 2026-09-26: Step 3y, second code-review round; plan review loop

### What we built
- `src/llm/run.py`, `_run_one`: on resume, whether a `retry_pending` call still needs its retry is decided by re-parsing the saved attempt with the current parser, not from the `parse_errors` stored at the time; a call counts toward `new_calls` only if a request was sent in that call (`sent_before`).
- Tests: `test_checkpoint_projects_calls_still_awaiting_their_retry` (a pending record exists, the checkpoint projects its ledger rate of $0.001, and $0 after a successful resume); `test_pending_record_that_now_parses_resumes_without_a_retry` (0 requests sent, `retry_pending` False, no new call counted); `test_retrieval_version_estimate_includes_the_examples` (v3's offline estimate exceeds v2's by the example text priced as uncached input plus the longer prompt priced as a cache read).
- `CLAUDE.md` (Process): a plan review loop before any plan is shown: plan file path at the top, `/plan-review`, each finding verified against the code, up to 3 rounds, a stop for questions of user decision, clause meaning or pre-registered rules, every round saved to `docs/reviews/`, and the final verdict with findings applied and rejected.

### Decisions made
- Second Cursor review of commit ac1169c (`scripts/review.sh HEAD~1`), four findings, all confirmed against the code:
  1. Resume decision from stored `parse_errors`: fixed as above.
  2. `_raw_entries` (probe only) reads the last attempt while scoring merges attempts: kept as is. `probe_windows` depends on it, so a change would alter which windows a rerun of the finished probe selects; the Step 3x check found no retried call where an earlier attempt parsed more targets than the final one (it compared counts, not target sets).
  3. The checkpoint's handling of `retry_pending` records was untested: test added.
  4. No test that a retrieval version's estimate includes the examples: test added.
- Plan review of this step: three rounds (`docs/reviews/2026-09-26-3y-r1.md`, `-r2.md`, `-r3.md`), each "Approve with changes". Round 3's single change (the estimate test compares with `pytest.approx` and divides by 1e6) was applied without a fourth round, as the loop allows at most three.
  - Rejected in part: round 2's point that the 0.6086 figure was not verifiable. It is from pasted output (below); the plan was reworded to state that source.

### Numbers measured
- After the Step 3x fixes: tests 111 passed; Claude v2 rebuilt from cache with merged scoring, identical to Step 3r (micro-F1 0.6086, macro-F1 0.5841, `new_calls_this_run: 0`), then committed as ac1169c.
  - Commands: `pytest tests -v`; `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 10 | tee data/processed/llm_iter_claude_v2_n10.txt`

### Problems hit and how we solved them
- See the four findings above.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-26: Step 3z, clean code review; v3 smoke test

### What we built
- `scripts/review.sh`: `REVIEW_MODEL` variable passed as `--model`. Set to `auto` because Cursor's free plan allows no named models; the intended non-Claude model is `gpt-5.6-sol-high` once the plan allows it. Under Auto the reviewer may be a Claude model, so for now the code review is independent but not necessarily a different model family.
- `.claude/agents/plan-reviewer.md`: `model: claude-fable-5-1` (the building session runs on Claude Opus 5.5; the Claude Code subagent docs accept a full model ID in this field).

### Decisions made
None new.

### Numbers measured
- Tests: 114 passed. Command: `pytest tests -v`
- Code review of the Step 3y fix and the script changes (`scripts/review.sh HEAD~4 src tests scripts`, Auto): no findings.
- v3 smoke, `--limit 3` (the first three windows of contract 15, no gold labels), threshold 0.5:
  - Claude: 3 new calls, 0 parse retries, 0 transport retries; tokens input 16,156 (v2 on the same calls: 6,232), cache_creation 17,366, cache_read 8,683, output 210; cost $0.0796; latency per call median 2,192 ms; health 0 of 3 below floor, empty-set share 1.0, parse-failed segments 0. Checkpoint projected $0.04 from the offline estimate (no v3 history), spent $11.37 before.
  - Gemini: 3 new calls, 0 transport retries; prompt tokens 16,133 for the 3 calls; c15_w0 prompt tokens 5,457 (v2: 3,285); candidates 249; cost $0.0130; latency per call median 1,850 ms; health 0 of 3 below floor, empty-set share 1.0. Checkpoint projected $0.02, spent $11.44 before.
  - Commands: `python -m src.llm.run iterate --model {claude,gemini} --prompt v3 --batch-size 10 --limit 3 --max-cost 1`; c15_w0 read from `data/llm_cache/gemini/v3/c15_w0_n10_15_0_*.json`.
- Examples reached the request: Claude's uncached input rose by 9,924 tokens over 3 calls (about 3,300 per call; Step 3w implied about 3,000); Gemini's c15_w0 prompt rose by 2,172 tokens.

### Problems hit and how we solved them
- The checkpoint's offline estimate ($0.04) was about half Claude's actual smoke cost ($0.0796): the estimate assumes 4 characters per token and a cached prefix, while Claude runs at about 2.92 characters per user token and the first calls of a new version write the prefix cache. From now on v3 has its own ledger history, which the checkpoint uses in preference.

### Surprises in the data or results
- On these label-free opening windows neither model labeled anything despite every target being shown a labeled example (empty-set share 1.0 on 30 segments); too small to say anything about priming.

### Resume-worthy
none

---

## 2026-09-26: Step 3aa, v3 results; v4 (dense) rules fixed before any v4 call

### What we built
- `docs/plan.md` Rule E: the v4 gate amendment (below), dated.
- `cmd_yardstick` now compares every iteration run with the baseline (`{model}_v*_n10.parquet`).
- Plan review of this step: four rounds (`docs/reviews/2026-09-26-3aa-r1.md` to `-r4.md`). Rounds 1 to 3 "approve with changes"; rounds beyond the 3-round limit were authorised as an exception (up to 3 more); round 4 "approve".

### Decisions made
- Adoption (pre-registered rule):
  - Claude v3 not adopted: v3 minus v2, micro-F1, +0.0080 [-0.0193, +0.0335]; macro-F1 -0.0012 [-0.0208, +0.0277]. Claude's incumbent stays v2.
  - Gemini v3 adopted: v3 minus v1-r2, micro-F1, +0.0480 [+0.0140, +0.0798]; macro-F1 +0.0276 [-0.0003, +0.0599]. Gemini's incumbent becomes v3. Secondary v3 minus v2: +0.0227 [-0.0039, +0.0491]; the win cannot separate the retrieved examples from v2's changes (recorded in 3u).
- Priming risk (3u) did not materialise, so the similarity-cutoff candidate is not triggered: mean labels listed fell (Claude v2 0.3160 to v3 0.2743; Gemini v1-r2 0.2558 and v2 0.2305 to v3 0.2105); precision Claude 0.5790 to 0.5799, Gemini v1-r2 0.5240 and v2 0.5589 to v3 0.6029.
- v4 ("v3 with dense output", Rule E) handled by its pre-registered cost gate, with these rules fixed before any v4 call:
  - A `--limit 3` gate smoke on both models.
  - Gate applied per model: both options fit, v4 for both; only Gemini-only fits, v4 for Gemini and Claude stays on v2; neither fits, no v4. Reason: Gemini's v4 against its incumbent v3 changes one variable (dense output); Claude's v4 against v2 changes two (examples and dense output), and Claude's v4 would also be compared against v3 as a secondary.
  - A model whose smoke fails is excluded (schema rejected; fewer than 3 smoke records; output above 6,000 tokens or latency above 90 s on any call; any `retry_errors` entry starting `connection:`, `408` or `504`; a segment unparsed after its retry). Gemini excluded means no v4 for either model; Claude excluded leaves Gemini-only at most.
  - Above $100 and under $150: decided when the gate prints, before any full v4 run. If the combined option is declined and Gemini-only is under $100, fall back to Gemini-only; if Gemini-only is also above $100 and declined, the Rule E fallback applies (removes v4).
  - Dense health is descriptive only (degenerate-call share, zero-confidence share, mean labels at or above 0.5 per segment), with no held-out invalidation rule, because no label-free signal separates an obvious clause scored 0 from a window with no clause when every label is scored.
  - Alternatives considered: skip v4 and freeze now; an all-or-nothing gate; an invalidation rule on degenerate dense calls; a Claude-only branch. Rejected because they depart from the pre-registered roadmap, lose the one-variable Gemini test, or would raise false alarms on legitimately empty windows.

### Numbers measured
All on the 23 iteration contracts (3,354 segments), threshold 0.5.
- Claude v3: micro-F1 0.6166, macro-F1 0.5829, macro-AP sparse 0.5897, none FP 0.0607, parse failures 0.0. 345 calls, 0 parse retries, 0 transport retries; tokens cache_creation 83,032, cache_read 2,857,691, input 1,738,961, output 43,577; cost $4.6928 ($1.3992 per 1,000 segments); latency per call median 2,019 ms, p95 3,378 ms. Record window 2026-09-26T16:55:26 (smoke) to 20:13:44 UTC. Health 0 of 345 below floor; empty-set share 0.7826; mean labels listed 0.2743. Checkpoint before: spent $11.46, projected $9.39 (v3 ledger mean $0.0265 per call, inflated by the smoke's cache writes).
  - Command: `python -m src.llm.run iterate --model claude --prompt v3 --batch-size 10 --max-cost 7 > data/processed/llm_iter_claude_v3_n10.txt 2>&1 &`
  - Files: `data/processed/llm_iter_claude_v3_n10.txt`, `data/predictions/iteration/claude_v3_n10.parquet`
- Gemini v3: micro-F1 0.6444, macro-F1 0.6118, macro-AP sparse 0.5921, none FP 0.0561, parse failures 0.0. 345 calls, 0 parse retries, 181 transport retries; tokens prompt 1,745,430, cached 387,100, candidates 47,967, thoughts 0; cost $1.2277 ($0.3660 per 1,000 segments); latency per call median 3,475 ms, p95 11,223 ms. Record window 2026-09-26T16:55:35 (smoke) to 20:20:37 UTC. Health 0 of 345 below floor; empty-set share 0.8342; mean labels listed 0.2105. Checkpoint before: projected $1.54.
  - Command: `python -m src.llm.run iterate --model gemini --prompt v3 --batch-size 10 --max-cost 3 > data/processed/llm_iter_gemini_v3_n10.txt 2>&1 &`
  - Files: `data/processed/llm_iter_gemini_v3_n10.txt`, `data/predictions/iteration/gemini_v3_n10.parquet`
- Casebook (not a selection criterion): Claude v3 Most Favored Nation 4 of 4, License Grant misread as Exclusivity 4 of 5, Anti-Assignment misread as Change Of Control 1 of 5; Gemini v3 4 of 4, 4 of 5, 3 of 5.
- Comparisons: commands `python -m src.llm.run compare --model claude --a v3:10 --b v2:10`, `--model gemini --a v3:10 --b v1-r2:10`, `--model gemini --a v3:10 --b v2:10`; files in `data/eval/llm_selection/`.
- Breakdowns: Claude v3 micro precision 0.5799, recall 0.6582; Gemini v3 0.6029, 0.6920 (baseline 0.6362, 0.6013). Change Of Control (19 gold): Claude v3 24 predicted, precision 0.417, recall 0.526; Gemini v3 18 predicted, 0.556, 0.526. Gemini Third Party Beneficiary 8 predicted, 0 correct.
  - Commands: `python -m src.llm.run breakdown --model {claude,gemini} --prompt v3 | tee data/processed/llm_breakdown_{claude,gemini}_v3.txt`
- Yardstick (paired, against the baseline at tuned thresholds 0.6182): Claude v1-r2 -0.0376 [-0.0666, +0.0021]; Gemini v1-r2 -0.0219 [-0.0527, +0.0241]; v1 figures unchanged. Incumbent runs are not yet in this file (the glob change above adds them on the next run, written to a new file).
  - Command: `python -m src.llm.run yardstick | tee data/processed/llm_yardstick.txt`

### Problems hit and how we solved them
- The first launch of the Step 3aa plan review read the previous plan because the plan file had not been saved; that review was stopped and restarted on the saved file.

### Surprises in the data or results
- Retrieved examples lowered the number of labels each model listed rather than raising it, the opposite of the recorded priming risk.

### Resume-worthy
Showed that retrieved training examples raised Gemini's micro-F1 by 0.048 [+0.014, +0.080] over a same-period incumbent while cutting over-labeling, and kept a pre-registered cost gate in front of the next, more expensive prompt variant.

---

## 2026-09-26: Step 3ab, v4 code in place; code review and pre-smoke verification

### What we built
- v4 as approved in 3aa: `V4_INSTRUCTIONS` (v3 with four checked edits), the dense schema through `schema_for`, the dense parser (exactly the 33 labels, no floor), dense-aware scoring at every parse site (`_merged_scores`, `_record`, `_run_one`, `record_scores`), `_raw_entries` refusing dense records, `scores_note`, descriptive `dense_health`, `heldout_health` (no invalidation for dense), and `gate-v4` with `smoke_check`, `dense_call_cost`, `n1_call_cost`, `project` and `gate_branch`.
- `src/config.py`: `LLM_V4_STOP_OUTPUT_TOKENS = 6000`, `LLM_V4_STOP_LATENCY_S = 90.0`.
- `scripts/review.sh`: reviewer pinned to `gpt-5.6-sol-high` (Cursor plan upgraded); the review prompt ends with an optional "Simplification" section (at most 3 items; nothing touching results or cache keys without a test proving identical output; never blocking).
- Tests: 16 new (v4 prompt edits, dense schema and unchanged v1 to v3 hashes, dense parser, stub v4 run, dense health, the heldout dense notes, scores notes, timeout strings, smoke stop condition, gate arithmetic and branches, reference completeness, AP naming).

### Decisions made
- Code review of the v4 diff (`scripts/review.sh HEAD src tests`, gpt-5.6-sol-high), three findings, each confirmed against the code and fixed:
  1. The three v4 smoke calls were counted in spend and again in the iteration projection: the projection now charges `iteration_calls_left(v4_smoke)` (357 minus smoke calls).
  2. `gate-v4` did not check that its reference runs were complete (a partial cache biased means, a missing smoke match zeroed the input difference, an empty cache divided by zero): `_complete` now stops the gate unless the v3 iteration run (345), the v3 smoke (3) and Claude's v2 iteration run (345) are fully cached.
  3. `score()` labelled every AP as "sparse lower bound", false for dense output and for the baseline: `score(..., sparse=)` names it `macro_ap` for dense scores; the yardstick passes `sparse=False` for the baseline.
  - Re-review: "No correctness findings." Two optional simplifications deferred to the next change to `gate-v4`, since neither alters a result: the 357-call total is defined twice (`V4_ITERATION_CALLS` and `project()`'s default); the v3 smoke records are loaded separately from the full v3 cache.

### Numbers measured
- Tests: 130 passed. Command: `pytest tests -v`
- Guarded rebuilds from cache (`--max-cost 0.01`, no paid calls; spend $17.52 before and after):
  - Claude v2: micro-F1 0.6086, macro-F1 0.5841, `new_calls_this_run: 0`; identical to the logged file (no diff).
    - Command: `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 10 --max-cost 0.01 | tee data/processed/llm_rebuild_claude_v2_n10.txt`
  - Gemini v3: micro-F1 0.6444, macro-F1 0.6118; the only difference from the logged file is `new_calls_this_run` (354 in the original run, 0 from cache), as expected.
    - Command: `python -m src.llm.run iterate --model gemini --prompt v3 --batch-size 10 --max-cost 0.01 | tee data/processed/llm_rebuild_gemini_v3_n10.txt`

### Problems hit and how we solved them
- See the three review findings above.

### Surprises in the data or results
None.

### Resume-worthy
none

---

## 2026-09-26: Step 3ac, v4 gate: dense schema rejected by both providers; v4 not run

### What we built
Nothing new; ran the v4 gate smoke and `gate-v4`.

### Decisions made
- v4 is recorded as not runnable for both models, as pre-registered in 3aa and Rule E: a provider that rejects the dense schema excludes that model, and Gemini excluded means no v4 for either model. The gate printed "neither: Gemini failed the smoke, so no v4 for either model".
- Incumbents stand: Claude v2, Gemini v3. Iteration on prompt versions ends here (4 of the 5 allowed versions used, v4 unrunnable).

### Numbers measured
- Claude v4 smoke: all 3 calls rejected with `400 invalid_request_error: The compiled grammar is too large, which would cause performance issues. Simplify your tool schemas or reduce the number of strict tools.` (request ids req_011CfSrGpScgtNU5W6m94aDt, req_011CfSrGu8eJmpkdXWeibj33, req_011CfSrGzFidJXctp8hMYKWQ). The dense schema has 33 required properties per target, 330 per 10-target call.
  - Command: `python -m src.llm.run iterate --model claude --prompt v4 --batch-size 10 --limit 3 --max-cost 1`
- Gemini v4 smoke: all 3 calls rejected with `400 INVALID_ARGUMENT: Request contains an invalid argument.` (no further detail; the schema size is the likely cause, not confirmed).
  - Command: `python -m src.llm.run iterate --model gemini --prompt v4 --batch-size 10 --limit 3 --max-cost 1`
- `gate-v4`: both models "smoke FAIL, 0 of 3 smoke records"; projections NaN (no smoke records to measure); N=1 upper bound 2,658 calls per model (segments of the 12 largest iteration contracts); spent $17.52; branch "neither".
  - Command: `python -m src.llm.run gate-v4 | tee data/processed/llm_gate_v4.txt`
- Spend unchanged: rejected requests are not billed and never reached the ledger (no v4 ledger entries).

### Problems hit and how we solved them
- The dense schema exceeds what both structured-output implementations accept. Not worked around: a different dense encoding would be a new, post-hoc version, not the pre-registered v4.

### Surprises in the data or results
- Both providers reject a schema of 330 required numeric properties per call, while v2 and v3's keyed sparse schema (10 required arrays over a 33-label enum) is accepted.

### Resume-worthy
none

---

## 2026-09-26: Step 3ad, N=1 batch-size check designed and drawn (before any N=1 call)

### What we built
- `src/llm/run.py` `_messages`: retrieved examples now come from the whole window (`call.texts`) rather than only the call's targets. At N=10 every window segment is a target, so every N=10 request is unchanged; at N=1 the example block equals the N=10 call's block for the same window.
- `src/llm/windows.py` `n1_half_contracts`: the seeded half of the iteration contracts, rounded up; whole contracts, unstratified; `np.random.default_rng([config.SEED, crc32(b"n1-half")])`.
- `src/llm/run.py`: `n1-sample` (saves the draw to `data/processed/llm_n1_contracts.csv`, refuses a differing saved file); `iterate --subset n1-half` (batch size 1 only, no `--rerun` or `--limit`, refuses unless the saved draw equals the seeded one, no casebook calls, output `{model}_{prompt}-n1half_n1.parquet`, cache namespace unchanged); `compare --restrict-b-to-a` (restricts B to A's segments, refuses if any are missing); `config.LLM_N1_CONTRACTS`.
- 6 tests (draw determinism and shape; window-level examples leave N=10 unchanged and match at N=1; subset calls match the full-sample N=1 calls and the N=10 windows; refusals for other batch sizes, `--rerun`, `--limit`; refusals for a missing or differing saved draw; `restrict_to`).
- Plan review: three rounds (`docs/reviews/2026-09-26-3ad-r1.md` to `-r3.md`); rounds 1 and 2 "approve with changes", round 3 "approve".

### Decisions made
- The check follows the pre-registered design (docs/plan.md:77; adopted for the N=1 check in 3u): a seeded half of the iteration contracts, rounded up, whole contracts, unstratified, on each model's prompt to be frozen (Claude v2, Gemini v3); the N=10 side is restricted to the same contracts so the pair is matched.
- Retrieved examples at N=1 are chosen for the whole window, so for Gemini v3 the example block is identical to N=10's and only the number of targets per call varies (3a's design). v3's examples paragraph says the examples "resemble the targets"; at N=1 they are chosen for the whole window, which is what each target sees at N=10.
  - Alternative considered: per-target examples at N=1.
  - Why rejected: Gemini's N=1 calls would show 2 examples against up to 20 at N=10, changing batch size and example count together.
- Reading rule (docs/plan.md:90, 3f), restated before any N=1 output: validation, test and shift run at N=10 whatever the check shows. If N=1 beats N=10 (paired unstratified contract bootstrap, 95% interval excluding zero, micro-F1), the gain is reported as a measured accuracy and cost trade-off on validation, not acted on.
- Caveats fixed now: reduced power (12 contracts); the N=10 runs (Claude v2 2026-09-25, Gemini v3 2026-09-26) and the N=1 runs are not contemporaneous; healthy run-to-run variance is not in the interval (the bootstrap resamples contracts, not reruns).
- Cost caps: `--max-cost 18` (Claude) and `--max-cost 10` (Gemini) stand. Re-projected from the drawn count (arithmetic, not measured): Claude about $0.0058 per call, up to about $0.0071 if none of each call's roughly 135 fixed output tokens is shared at N=1, so about $8.5 and at most about $10.4 for 1,467 calls; Gemini about $0.0031 per call (slightly high), about $4.5. The checkpoint has no N=1 history and uses the offline estimate, so `--max-cost` is the real guard.

### Numbers measured
- Tests: 136 passed. Command: `pytest tests -v`
- Guarded rebuilds before any N=1 run (no paid calls, spend $17.52): Claude v2 micro-F1 0.6086, macro-F1 0.5841, identical to the logged file; Gemini v3 micro-F1 0.6444, macro-F1 0.6118, `new_calls_this_run: 0` (the window-level change left every v3 N=10 request unchanged), the only diff against the logged file being `new_calls_this_run` 354 against 0.
  - Commands: `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 10 --max-cost 0.01 | tee data/processed/llm_rebuild2_claude_v2_n10.txt`; the Gemini v3 equivalent to `llm_rebuild2_gemini_v3_n10.txt`.
- The draw: 12 of 23 iteration contracts, 1,467 segments (N=1 calls per model): 56 Collaboration/Cooperation (156), 91 Consulting (81), 93 Sponsorship (47), 99 Maintenance (31), 140 Development (139), 287 Marketing (191), 291 License (24), 300 Distributor (154), 307 Outsourcing (295), 335 Strategic Alliance (284), 368 Non-Compete/No-Solicit/Non-Disparagement (26), 438 Service (39).
  - Command: `python -m src.llm.run n1-sample | tee data/processed/llm_n1_sample.txt`
  - File: `data/processed/llm_n1_contracts.csv`

### Problems hit and how we solved them
- Code review (`scripts/review.sh`): the half-draw test compared against a hardcoded seed 7, which would fail if `config.SEED` were 7; it now uses `config.SEED + 1`. Optional simplification taken: `iterate --subset n1-half` no longer loads the casebook it discards.

### Surprises in the data or results
None.

### Resume-worthy
none

## 2026-09-27: Step 3ae, N=1 batch-size check results (validation only; reported, not acted on)

### What we built
Nothing new. The N=1 runs used the Step 3ad code (commit 0d02646).

### Decisions made
- Batch size stays at 10 for the freeze, validation, test and shift, as pre-registered (docs/plan.md:90, 3f). N=1 did not beat N=10 for either model; the point estimates favor N=10, but neither interval excludes zero.

### Numbers measured
- Claude v2, N=1 against N=10 on the 12 drawn contracts (1,467 segments; unstratified paired contract bootstrap, 2,000 resamples, seed 42, stream "iteration"):
  - micro-F1: N=1 0.6100, N=10 0.6364, difference -0.0264 [-0.0561, +0.0052]
  - macro-F1 (reported only): N=1 0.5820, N=10 0.5990, difference -0.0170 [-0.0432, +0.0474]
  - Command: `python -m src.llm.run compare --model claude --a v2-n1half:1 --b v2:10 --restrict-b-to-a`
  - File: `data/eval/llm_selection/claude_v2-n1halfn1_vs_v2n10.json`
- Gemini v3, same design:
  - micro-F1: N=1 0.6680, N=10 0.6876, difference -0.0197 [-0.0486, +0.0080]
  - macro-F1 (reported only): N=1 0.6173, N=10 0.6375, difference -0.0203 [-0.0448, +0.0478]
  - Command: `python -m src.llm.run compare --model gemini --a v3-n1half:1 --b v3:10 --restrict-b-to-a`
  - File: `data/eval/llm_selection/gemini_v3-n1halfn1_vs_v3n10.json`
- Claude v2 N=1 run: 1,467 calls, 0 parse retries, 27 transport retries; tokens cache_creation 512,080, cache_read 4,563,740, input 2,488,544, output 35,900, thinking blocks 0; cost $7.529 ($5.1323 per 1,000 segments); latency per call median 1,394 ms, p95 1,938 ms (one target per call, full window context). Record window 2026-09-27T01:50:38 to 07:01:17 UTC. Health 0 of 1,467 below floor; empty-set share 0.7055; mean labels listed 0.3940; parse-failed segments 0. Checkpoint before: spent $17.52, projected $9.17 (offline estimate).
  - Command: `python -m src.llm.run iterate --model claude --prompt v2 --batch-size 1 --subset n1-half --max-cost 18`
  - File: `data/processed/llm_iter_claude_v2-n1half_n1.txt`
- Gemini v3 N=1 run: 1,467 calls, 0 parse retries, 599 transport retries; tokens prompt 7,531,335, cached 132,374, candidates 39,271, thoughts 0; cost $5.7064 ($3.8899 per 1,000 segments); latency per call median 2,757 ms, p95 9,011 ms (one target per call, full window context). Record window 2026-09-27T01:54:50 to 07:41:15 UTC. Health 0 of 1,467 below floor; empty-set share 0.7873; mean labels listed 0.2693; parse-failed segments 0. Checkpoint before the first attempt projected $8.46 (offline estimate); before the resume, spent $30.75.
  - Command: the Gemini equivalent with `--prompt v3 --max-cost 10`, then the same command again to resume
  - Files: `data/processed/llm_iter_gemini_v3-n1half_n1.txt` (first attempt), `data/processed/llm_iter_gemini_v3-n1half_n1_resume.txt` (resume and final metrics)
- For reference, the N=10 iteration runs over all 23 iteration contracts (not restricted to the 12): Claude v2 $0.7289 per 1,000 segments, latency per call median 2,203 ms (227 ms per segment, call-amortized); Gemini v3 $0.366 per 1,000 segments, latency per call median 3,475 ms (357 ms per segment, call-amortized).
  - Files: `data/processed/llm_iter_claude_v2_n10.txt`, `data/processed/llm_iter_gemini_v3_n10.txt`

### Problems hit and how we solved them
- Gemini's first N=1 run finished 1,466 of 1,467 calls; `c300_w7_n1_300_79` returned 503 "high demand" on all 8 attempts. The resume sent only that call (`new_calls_this_run: 1`); the other 1,466 came from cache.

### Surprises in the data or results
- Both models score lower at N=1 than at N=10 on the same windows, with the same context and, for Gemini, the same examples. The intervals include zero, so this is a direction, not a finding. Claude at N=1 lists more labels per segment (0.3940) and has a higher none false-positive rate (0.1032) than its full N=10 iteration run (0.3160 and 0.0594); those N=10 figures cover all 23 contracts, so this is indicative only.

### Caveats
- Reduced power: 12 contracts.
- Not contemporaneous: the N=10 runs are from 2026-09-25 (Claude v2) and 2026-09-26 (Gemini v3); the N=1 runs are from 2026-09-27.
- The contract bootstrap resamples contracts, not reruns, so healthy run-to-run variance is not in the intervals.
- The N=10 cost and latency figures above cover all 23 iteration contracts, not the 12.

### Resume-worthy
- Measured the batch-size trade-off on matched windows: one target per call cost about 7 times (Claude) and 11 times (Gemini) as much per segment as ten targets per call, with no accuracy gain.
