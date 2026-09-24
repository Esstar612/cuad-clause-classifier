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
- `src/config.py`: `SHIFT_TYPES` and `SPLIT_FRACTIONS` (placed by the user).

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
- The segmentation thresholds are proposed below and not yet frozen; they will be logged when approved.

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
- The balanced split fix in `src/splits.py` (placed by the user); `data/processed/splits.parquet` regenerated.
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
- **The chosen region is at the edge of the grid.** The top six configurations by macro-AP all use C = 16, the largest value tried, and macro-AP still rises from C = 4 to C = 16 in every bigram cell. The optimum may lie above 16. Extending the grid is a validation-only decision, pending with the user.
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
- **Reproduction check.** I compared `models/baseline/round1/search_log.csv` to the round 2 `search_log.csv` through the id mapping in Step 2b (a script reading both CSVs). All 64 round 1 configurations matched with:
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

Numbering follows the user's prompts: the LLMs remain Step 3, and pairwise model comparisons are Step 4b.

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
- `docs/plan.md`: steps renumbered to match the user's numbering.

### Decisions made
- **2000 resamples, percentile intervals.**
  - Alternatives considered: BCa; the basic (reverse) interval; more resamples.
  - Why rejected: BCa needs a per-scope jackknife and behaves erratically with discrete, few-contract F1. The basic interval can leave [0, 1]. More resamples mostly add runtime to the per-resample AP loop.
- **Resample contracts, stratified by contract type.**
  - Alternatives considered: segment-level resampling; unstratified contract resampling.
  - Why rejected: segments within a contract are correlated, so segment resampling understates uncertainty. Stratification mirrors the stratified split; unstratified would be slightly more conservative.
- **Named random streams** (`test`, `shift`, `shift:Franchise`, `shift:Transportation`) mixed into the seed. This was added after the code was approved: without it, test and shift would reuse one random sequence, weakly correlating two bootstraps the drop interval treats as independent.
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
- **A documentation bug I introduced in Step 2d, found and fixed here.**
  - When filling the appendix after the held-out run, my script located each label's row by its first occurrence in `docs/results.md`. For the 26 main-table labels, that was the row in the main test table, not the appendix. So the Precision column of the main test table was overwritten with text, and those labels' appendix rows were left empty.
  - No figure in BUILD_LOG was affected; they were written from the pasted output.
  - Fix: everything from "## Test results" onward in `docs/results.md` was regenerated from `data/eval/baseline.json`. I spot-checked the rebuilt values against the pasted output (for example, Governing Law precision 0.955, test Rule A macro-F1 0.6311 [0.6043, 0.6532]).
  - Lesson: generate result tables from the saved JSON, never by string-matching rows.

### Surprises in the data or results
- **The shift drop is real, and it is misses, not false alarms.** The test-minus-shift macro-F1 interval, +0.1200 to +0.2524, excludes zero, while the none FP rate interval (-0.0171 to +0.0008) includes zero. This confirms the Step 2d reading with intervals.
- **Franchise and Transportation cannot be told apart.** Their Rule C macro-F1 intervals overlap almost entirely (0.3994 to 0.5315 vs 0.3502 to 0.5618). Transportation's are the widest in the table (micro-F1 0.3320 to 0.6213) with 13 contracts.
- **Pooled ECE (0.0015) looks excellent but hides clear overconfidence.** Above 0.1, observed rates sit well below predicted in every bin, confirming the "balanced" weighting known item. Pooled ECE alone would have hidden it.
- **Several AP intervals are asymmetric,** with the point estimate near the lower bound (shift all labels macro-AP 0.4497 [0.4340, 0.5486]; Minimum Commitment test AP 0.288 [0.205, 0.541]). F1 intervals are more centered. Claims rely on F1 intervals and intervals excluding zero; AP intervals are reported as measured.
- **Most Favored Nation has a literal "Most Favored Nation" heading in one validation segment (169_105) scored p = 0.009.** With 20 training segments, bag-of-words did not learn the phrase. This is a direct test case for the LLMs.

### Resume-worthy
Built a model-agnostic evaluation harness with contract-level stratified bootstrap CIs and paired comparisons (verified exactly zero on self-comparison). It showed a significant shift drop (macro-F1 -0.19, CI excluding zero) driven by missed clauses, and overconfidence that pooled ECE hid.
