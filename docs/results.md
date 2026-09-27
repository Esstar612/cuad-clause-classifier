# Results

All figures come from pasted script output. Each table cites the command and output file that produced it. Test set figures are from a single, final evaluation per model.

## Setup
- Data: CUAD v1 (Zenodo DOI 10.5281/zenodo.4595826, `CUAD_v1.zip`, SHA-256 `88b694d99007d39777fa44cd72daf8297773d285dc3eab0091ba32078888d18e`, CC BY 4.0): 510 contracts, 41 lawyer-labeled categories, 25 contract types.
- Splits by contract, stratified by type, seed 42: train 289, validation 97, test 96, shift 28 (Franchise 15, Transportation 13; no model trains or tunes on them). Segments: validation 11,656, test 9,378, shift 4,584.
- Label set: 33 of the 41 categories (the rare and extraction-style categories are excluded; BUILD_LOG Step 1). A segment may carry several labels or none.
- Models, each evaluated once on test and shift:
  - Baseline: TF-IDF + one-vs-rest logistic regression, version 9692b04f03fb.
  - Claude: `claude-sonnet-5`, prompt v2 (hash dc2236da8a44), 10 segments per call, Rule B thresholds (hash 9b37545d9c08).
  - Gemini: `gemini-3.8-flash`, prompt v3 (hash 8ec29d0ea6ca, retrieved training examples), 10 segments per call, `seed=42`, Rule B thresholds (hash 9cf165579892).
- The LLMs return sparse scores: every label at confidence 0.1 or above, unlisted labels scored 0 (Rule D). All three models use Rule B thresholds tuned on validation.

## Label lists under the pre-registered rules
Source: `python -m src.splits | tee data/processed/splits_report.txt` (post-fix split, 2026-09-23). The counts are contracts with at least one span of the label.

**Rule A, main test table (at least 10 test contracts): 26 labels.** Every kept label except the 7 below.

**Rule A, appendix only ("insufficient support, not interpreted"): 7 labels.** Test contracts in parentheses:
- Third Party Beneficiary (3)
- Non-Disparagement (6)
- Most Favored Nation (6)
- No-Solicit Of Customers (7)
- Joint Ip Ownership (9)
- Affiliate License (9)
- Irrevocable Or Perpetual License (9)

**Rule B, per-class thresholds (at least 10 validation contracts): 28 labels.**

**Rule B, one shared threshold pooled on validation: 5 labels.** Validation contracts in parentheses:
- No-Solicit Of Customers (1)
- Non-Disparagement (5)
- Most Favored Nation (5)
- Third Party Beneficiary (7)
- Joint Ip Ownership (8)

**Rule C, per-label shift results: 17 labels** (`SHIFT_MEASURABLE_LABELS`; the shift set is unchanged by the split fix).

## Validation results
<!-- Used for model selection, tuning, and threshold choices. -->
Thresholds are tuned on the same validation set, so validation F1 is optimistic. Selection is by macro-AP (threshold-free).

| Model | Version | Macro-F1 (33) | Micro-F1 (33) | Macro-AP (33) | Macro-F1 (28 per-class) | None FP rate |
|---|---|---|---|---|---|---|
| TF-IDF + OvR logistic regression (1-2 grams, balanced, C=64, no none downsampling) | 9692b04f03fb | 0.5670 | 0.6307 | 0.5671 | 0.6107 | 0.0300 |
| Claude Sonnet 5, prompt v2, batch 10 | claude-sonnet-5 \| prompt v2 dc2236da8a44 \| thresholds 9b37545d9c08 | 0.6322 | 0.6825 | 0.5764 (sparse lower bound, not comparable) | not reported | 0.0306 |
| Gemini 3.8 Flash, prompt v3, batch 10 | gemini-3.8-flash \| prompt v3 8ec29d0ea6ca \| thresholds 9cf165579892 | 0.6795 | 0.7117 | 0.6017 (sparse lower bound, not comparable) | not reported | 0.0346 |

LLM rows: prompts were selected by micro-F1 at threshold 0.5 on the validation iteration sample (23 contracts), Rule B thresholds were then tuned on full validation, and full validation includes the prompt-selection contracts, so these rows are optimistic twice over. At threshold 0.5, before tuning, full validation gave micro-F1 0.6286 (Claude) and 0.6746 (Gemini). Sources: `python -m src.llm.run thresholds --model claude` and `--model gemini` (`data/processed/llm_thresholds_{claude,gemini}.txt`); `python -m src.llm.run val` (`data/processed/llm_val_{claude,gemini}.txt`).

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

Baseline source: `python -m src.baseline search | tee data/processed/baseline_search.txt` (round 2 of 2, 96 configurations; stopping rule triggered at C=64, reported as an edge result). The round 1 choice (C=16, none 5:1, version 7253e7a8662b, macro-AP 0.5598) was superseded.

## Test results
<!-- One run per model, after all choices were frozen on validation. -->

### TF-IDF + OvR logistic regression (version 9692b04f03fb), single test run 2026-09-24
Predictions: `data/predictions/baseline_test.parquet` (from `python -m src.baseline heldout`). Metrics and intervals: `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt` (values from `data/eval/baseline.json`). Intervals: see "Confidence intervals" below.

| Scope | Labels | Contracts | Segments | Macro-F1 [95% CI] | Micro-F1 [95% CI] | Macro-AP [95% CI] | None FP rate [95% CI] |
|---|---|---|---|---|---|---|---|
| Rule A (main table) | 26 | 96 | 9,378 | 0.6311 [0.6043, 0.6532] | 0.6659 [0.6434, 0.6907] | 0.6602 [0.6408, 0.6962] | 0.0255 [0.0218, 0.0296] |
| All labels (combined) | 33 | 96 | 9,378 | 0.5486 [0.5217, 0.5743] | 0.6543 [0.6303, 0.6792] | 0.5928 [0.5729, 0.6339] | 0.0255 [0.0218, 0.0296] |
| Rule C labels (for the shift comparison) | 17 | 96 | 9,378 | 0.6619 [0.6257, 0.6929] | 0.6902 [0.6640, 0.7180] | 0.7019 [0.6714, 0.7464] | 0.0255 [0.0218, 0.0296] |

Per-label, Rule A labels (at least 10 test contracts):

| Label | Test contracts | Test segments | Precision | Recall | F1 [95% CI] | AP [95% CI] |
|---|---|---|---|---|---|---|
| Governing Law | 81 | 87 | 0.955 | 0.966 | 0.960 [0.934, 0.983] | 0.992 [0.982, 0.999] |
| Renewal Term | 36 | 37 | 0.970 | 0.865 | 0.914 [0.838, 0.975] | 0.944 [0.881, 0.997] |
| Anti-Assignment | 71 | 91 | 0.895 | 0.747 | 0.814 [0.739, 0.893] | 0.901 [0.851, 0.954] |
| Notice Period To Terminate Renewal | 24 | 27 | 0.840 | 0.778 | 0.808 [0.688, 0.915] | 0.859 [0.760, 0.952] |
| License Grant | 46 | 112 | 0.889 | 0.714 | 0.792 [0.731, 0.850] | 0.827 [0.766, 0.890] |
| Insurance | 28 | 73 | 0.747 | 0.808 | 0.776 [0.672, 0.853] | 0.883 [0.790, 0.944] |
| Audit Rights | 39 | 77 | 0.869 | 0.688 | 0.768 [0.681, 0.855] | 0.797 [0.715, 0.889] |
| No-Solicit Of Employees | 12 | 15 | 0.786 | 0.733 | 0.759 [0.556, 0.889] | 0.837 [0.664, 0.950] |
| Expiration Date | 75 | 78 | 0.809 | 0.705 | 0.753 [0.687, 0.814] | 0.854 [0.796, 0.911] |
| Covenant Not To Sue | 20 | 33 | 0.774 | 0.727 | 0.750 [0.651, 0.836] | 0.752 [0.628, 0.876] |
| Non-Transferable License | 24 | 47 | 0.805 | 0.702 | 0.750 [0.643, 0.839] | 0.727 [0.610, 0.836] |
| Cap On Liability | 56 | 121 | 0.827 | 0.669 | 0.740 [0.686, 0.798] | 0.773 [0.703, 0.852] |
| Uncapped Liability | 19 | 25 | 0.667 | 0.640 | 0.653 [0.483, 0.784] | 0.569 [0.426, 0.762] |
| Termination For Convenience | 38 | 50 | 0.542 | 0.780 | 0.639 [0.541, 0.724] | 0.594 [0.487, 0.705] |
| Ip Ownership Assignment | 22 | 38 | 0.800 | 0.526 | 0.635 [0.476, 0.774] | 0.658 [0.510, 0.805] |
| Liquidated Damages | 14 | 30 | 0.833 | 0.500 | 0.625 [0.385, 0.784] | 0.679 [0.528, 0.831] |
| Rofr/Rofo/Rofn | 14 | 46 | 0.875 | 0.457 | 0.600 [0.400, 0.738] | 0.727 [0.533, 0.836] |
| Revenue/Profit Sharing | 32 | 83 | 0.505 | 0.554 | 0.529 [0.390, 0.656] | 0.497 [0.323, 0.694] |
| Exclusivity | 36 | 76 | 0.526 | 0.526 | 0.526 [0.437, 0.629] | 0.562 [0.450, 0.719] |
| Non-Compete | 22 | 43 | 0.633 | 0.442 | 0.521 [0.349, 0.645] | 0.552 [0.374, 0.675] |
| Change Of Control | 20 | 42 | 0.559 | 0.452 | 0.500 [0.394, 0.590] | 0.451 [0.340, 0.597] |
| Post-Termination Services | 37 | 74 | 0.414 | 0.622 | 0.497 [0.425, 0.558] | 0.553 [0.435, 0.650] |
| Warranty Duration | 17 | 44 | 0.600 | 0.273 | 0.375 [0.286, 0.500] | 0.400 [0.309, 0.559] |
| Minimum Commitment | 35 | 86 | 0.783 | 0.209 | 0.330 [0.227, 0.447] | 0.288 [0.205, 0.541] |
| Competitive Restriction Exception | 13 | 17 | 0.188 | 0.353 | 0.245 [0.121, 0.359] | 0.269 [0.116, 0.470] |
| Volume Restriction | 14 | 24 | 0.667 | 0.083 | 0.148 [0.000, 0.421] | 0.218 [0.067, 0.416] |

### Calibration, baseline on test
Every (segment, label) pair is one prediction; 10 equal-width bins. Pooled ECE: 0.0015 [0.0009, 0.0025]. Pooled ECE is dominated by the 306,899 pairs below 0.1 and understates miscalibration where it matters; read the bins above 0.1.

| Bin | Pairs | Mean predicted | Observed rate |
|---|---|---|---|
| [0.0, 0.1) | 306,899 | 0.0010 | 0.0014 |
| [0.1, 0.2) | 590 | 0.1393 | 0.1288 |
| [0.2, 0.3) | 251 | 0.2474 | 0.2191 |
| [0.3, 0.4) | 197 | 0.3482 | 0.2538 |
| [0.4, 0.5) | 125 | 0.4498 | 0.2880 |
| [0.5, 0.6) | 123 | 0.5539 | 0.3577 |
| [0.6, 0.7) | 102 | 0.6496 | 0.4118 |
| [0.7, 0.8) | 119 | 0.7494 | 0.5882 |
| [0.8, 0.9) | 127 | 0.8533 | 0.5512 |
| [0.9, 1.0] | 941 | 0.9753 | 0.7439 |

Rule A labels with the highest per-label ECE:

| Label | ECE | Mean predicted | Observed rate |
|---|---|---|---|
| Minimum Commitment | 0.0207 | 0.0272 | 0.0092 |
| Exclusivity | 0.0039 | 0.0094 | 0.0081 |
| Revenue/Profit Sharing | 0.0033 | 0.0111 | 0.0089 |
| Expiration Date | 0.0031 | 0.0109 | 0.0083 |
| License Grant | 0.0028 | 0.0137 | 0.0119 |

## Shift set (Franchise + Transportation)
<!-- One table per model: Franchise, Transportation, combined, and in-distribution test for comparison.
     Bootstrap CIs resample whole contracts. -->

### TF-IDF + OvR logistic regression (version 9692b04f03fb), single shift run 2026-09-24
Predictions: `data/predictions/baseline_shift.parquet`. Metrics and intervals: `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt` (values from `data/eval/baseline.json`). Macro averages skip labels with no support in the scope (the Labels column).

| Scope | Labels | Contracts | Segments | Macro-F1 [95% CI] | Micro-F1 [95% CI] | Macro-AP [95% CI] | None FP rate [95% CI] |
|---|---|---|---|---|---|---|---|
| Combined, Rule C | 17 | 28 | 4,584 | 0.4740 [0.4186, 0.5332] | 0.5027 [0.4472, 0.5631] | 0.5279 [0.4918, 0.6150] | 0.0340 [0.0256, 0.0415] |
| Franchise, Rule C | 17 | 15 | 2,694 | 0.4478 [0.3994, 0.5315] | 0.5141 [0.4664, 0.5709] | 0.5510 [0.5035, 0.6616] | 0.0443 [0.0359, 0.0549] |
| Transportation, Rule C | 16 | 13 | 1,890 | 0.4291 [0.3502, 0.5618] | 0.4741 [0.3320, 0.6213] | 0.5412 [0.4564, 0.6891] | 0.0207 [0.0058, 0.0352] |
| Combined, all labels | 32 | 28 | 4,584 | 0.3614 [0.3169, 0.4290] | 0.4682 [0.4213, 0.5249] | 0.4497 [0.4340, 0.5486] | 0.0340 [0.0256, 0.0415] |
| Franchise, all labels | 30 | 15 | 2,694 | 0.3534 [0.3113, 0.4355] | 0.4694 [0.4288, 0.5262] | 0.4801 [0.4470, 0.5887] | 0.0443 [0.0359, 0.0549] |
| Transportation, all labels | 24 | 13 | 1,890 | 0.3583 [0.3052, 0.4907] | 0.4646 [0.3300, 0.5949] | 0.5264 [0.4552, 0.6644] | 0.0207 [0.0058, 0.0352] |

Test minus shift on the same 17 Rule C labels (independent bootstraps of the two contract sets):

| Metric | Test minus shift [95% CI] |
|---|---|
| macro_f1 | +0.1879 [+0.1200, +0.2524] |
| micro_f1 | +0.1875 [+0.1210, +0.2511] |
| macro_ap | +0.1740 [+0.0843, +0.2287] |
| none_fp_rate | -0.0085 [-0.0171, +0.0008] |

### Per-label shift results, baseline, combined shift (17 pre-registered labels, at least 10 shift contracts each)

| Label | Shift contracts | Shift segments | Precision | Recall | F1 [95% CI] | AP [95% CI] |
|---|---|---|---|---|---|---|
| Governing Law | 23 | 24 | 0.714 | 0.833 | 0.769 [0.644, 0.917] | 0.792 [0.641, 0.957] |
| Cap On Liability | 14 | 24 | 0.833 | 0.625 | 0.714 [0.513, 0.914] | 0.705 [0.484, 0.956] |
| Audit Rights | 13 | 43 | 0.667 | 0.651 | 0.659 [0.523, 0.800] | 0.655 [0.544, 0.821] |
| Insurance | 15 | 67 | 0.588 | 0.746 | 0.658 [0.477, 0.824] | 0.761 [0.621, 0.885] |
| Expiration Date | 23 | 26 | 0.750 | 0.577 | 0.652 [0.465, 0.808] | 0.647 [0.481, 0.813] |
| Liquidated Damages | 10 | 19 | 0.688 | 0.579 | 0.629 [0.316, 0.833] | 0.492 [0.216, 0.857] |
| Covenant Not To Sue | 10 | 22 | 0.542 | 0.591 | 0.565 [0.432, 0.722] | 0.574 [0.444, 0.798] |
| Anti-Assignment | 20 | 45 | 0.667 | 0.400 | 0.500 [0.354, 0.676] | 0.542 [0.422, 0.712] |
| Renewal Term | 15 | 33 | 0.786 | 0.333 | 0.468 [0.319, 0.714] | 0.468 [0.356, 0.768] |
| Notice Period To Terminate Renewal | 11 | 14 | 0.625 | 0.357 | 0.455 [0.174, 0.706] | 0.618 [0.407, 0.867] |
| Revenue/Profit Sharing | 11 | 25 | 0.364 | 0.480 | 0.414 [0.291, 0.531] | 0.526 [0.391, 0.644] |
| Non-Compete | 11 | 53 | 0.778 | 0.264 | 0.394 [0.188, 0.600] | 0.462 [0.282, 0.686] |
| License Grant | 10 | 25 | 0.500 | 0.320 | 0.390 [0.216, 0.565] | 0.384 [0.252, 0.682] |
| Exclusivity | 10 | 22 | 0.545 | 0.273 | 0.364 [0.000, 0.604] | 0.404 [0.093, 0.649] |
| Post-Termination Services | 10 | 31 | 0.474 | 0.290 | 0.360 [0.222, 0.491] | 0.360 [0.272, 0.524] |
| Minimum Commitment | 14 | 58 | 1.000 | 0.034 | 0.067 [0.000, 0.143] | 0.335 [0.201, 0.471] |
| Volume Restriction | 11 | 31 | 0.000 | 0.000 | 0.000 [0.000, 0.000] | 0.250 [0.114, 0.425] |

Pre-registered Rule C labels: Governing Law, Expiration Date, Anti-Assignment, Insurance, Renewal Term, Cap On Liability, Minimum Commitment, Audit Rights, Non-Compete, Notice Period To Terminate Renewal, Revenue/Profit Sharing, Volume Restriction, License Grant, Exclusivity, Post-Termination Services, Covenant Not To Sue, Liquidated Damages.

### Not measurable on the shift set (16 labels, fewer than 10 shift contracts)
Termination For Convenience, Non-Transferable License, Ip Ownership Assignment, Change Of Control, Uncapped Liability, Rofr/Rofo/Rofn, Competitive Restriction Exception, Warranty Duration, Irrevocable Or Perpetual License, No-Solicit Of Employees, Affiliate License, Joint Ip Ownership, Non-Disparagement, No-Solicit Of Customers, Third Party Beneficiary, Most Favored Nation.

## Three models on test and shift
Single held-out run per model: baseline 2026-09-24, Claude and Gemini 2026-09-27. Source: `python -m src.report | tee data/processed/results_tables.md`, generated from `data/eval/{baseline,claude,gemini}.json` (`python -m src.evaluate model <name>`). Intervals: 2000 contract-level bootstrap resamples, stratified by contract type, percentile 95%, seed 42. The Labels column counts labels with defined F1 in the scope, for each model.

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

### Micro-F1, point [95% CI]
| Scope | Labels with defined F1 (baseline / claude / gemini) | baseline | claude | gemini |
|---|---|---|---|---|
| test \| Rule A | 26 / 26 / 26 | 0.6659 [0.6434, 0.6907] | 0.7156 [0.6920, 0.7404] | 0.7506 [0.7273, 0.7757] |
| test \| all | 33 / 33 / 33 | 0.6543 [0.6303, 0.6792] | 0.7060 [0.6837, 0.7306] | 0.7412 [0.7181, 0.7667] |
| test \| Rule C | 17 / 17 / 17 | 0.6902 [0.6640, 0.7180] | 0.7353 [0.7086, 0.7624] | 0.7618 [0.7385, 0.7861] |
| shift \| Rule C | 17 / 17 / 17 | 0.5027 [0.4472, 0.5631] | 0.5688 [0.5254, 0.6224] | 0.5843 [0.5453, 0.6364] |
| shift \| all | 32 / 32 / 32 | 0.4682 [0.4213, 0.5249] | 0.5487 [0.5118, 0.5933] | 0.5847 [0.5508, 0.6266] |
| shift:Franchise \| Rule C | 17 / 17 / 17 | 0.5141 [0.4664, 0.5709] | 0.5700 [0.5269, 0.6270] | 0.5837 [0.5502, 0.6283] |
| shift:Franchise \| all | 30 / 30 / 30 | 0.4694 [0.4288, 0.5262] | 0.5497 [0.5123, 0.5962] | 0.5858 [0.5593, 0.6224] |
| shift:Transportation \| Rule C | 16 / 16 / 16 | 0.4741 [0.3320, 0.6213] | 0.5654 [0.4574, 0.6863] | 0.5859 [0.4709, 0.7131] |
| shift:Transportation \| all | 24 / 24 / 24 | 0.4646 [0.3300, 0.5949] | 0.5506 [0.4478, 0.6572] | 0.5828 [0.4670, 0.7019] |

### Macro-F1, point [95% CI]
| Scope | Labels with defined F1 (baseline / claude / gemini) | baseline | claude | gemini |
|---|---|---|---|---|
| test \| Rule A | 26 / 26 / 26 | 0.6311 [0.6043, 0.6532] | 0.6754 [0.6476, 0.7019] | 0.7237 [0.6997, 0.7455] |
| test \| all | 33 / 33 / 33 | 0.5486 [0.5217, 0.5743] | 0.6440 [0.6080, 0.6746] | 0.6804 [0.6470, 0.7056] |
| test \| Rule C | 17 / 17 / 17 | 0.6619 [0.6257, 0.6929] | 0.7032 [0.6725, 0.7335] | 0.7333 [0.7077, 0.7558] |
| shift \| Rule C | 17 / 17 / 17 | 0.4740 [0.4186, 0.5332] | 0.5246 [0.4749, 0.5853] | 0.5753 [0.5349, 0.6278] |
| shift \| all | 32 / 32 / 32 | 0.3614 [0.3169, 0.4290] | 0.4486 [0.4079, 0.4874] | 0.5217 [0.4840, 0.5733] |
| shift:Franchise \| Rule C | 17 / 17 / 17 | 0.4478 [0.3994, 0.5315] | 0.4988 [0.4658, 0.5693] | 0.5642 [0.5371, 0.6293] |
| shift:Franchise \| all | 30 / 30 / 30 | 0.3534 [0.3113, 0.4355] | 0.4611 [0.4287, 0.5133] | 0.5400 [0.5142, 0.5888] |
| shift:Transportation \| Rule C | 16 / 16 / 16 | 0.4291 [0.3502, 0.5618] | 0.4744 [0.4122, 0.6025] | 0.5178 [0.4313, 0.6453] |
| shift:Transportation \| all | 24 / 24 / 24 | 0.3583 [0.3052, 0.4907] | 0.4522 [0.3617, 0.5256] | 0.5216 [0.4086, 0.6147] |

### None false-positive rate (parsed segments only), point [95% CI]
| Scope | Labels with defined F1 (baseline / claude / gemini) | baseline | claude | gemini |
|---|---|---|---|---|
| test \| Rule A | 26 / 26 / 26 | 0.0255 [0.0218, 0.0296] | 0.0304 [0.0261, 0.0352] | 0.0315 [0.0260, 0.0380] |
| test \| all | 33 / 33 / 33 | 0.0255 [0.0218, 0.0296] | 0.0304 [0.0261, 0.0352] | 0.0315 [0.0260, 0.0380] |
| test \| Rule C | 17 / 17 / 17 | 0.0255 [0.0218, 0.0296] | 0.0304 [0.0261, 0.0352] | 0.0315 [0.0260, 0.0380] |
| shift \| Rule C | 17 / 17 / 17 | 0.0340 [0.0256, 0.0415] | 0.0521 [0.0392, 0.0649] | 0.0497 [0.0379, 0.0613] |
| shift \| all | 32 / 32 / 32 | 0.0340 [0.0256, 0.0415] | 0.0521 [0.0392, 0.0649] | 0.0497 [0.0379, 0.0613] |
| shift:Franchise \| Rule C | 17 / 17 / 17 | 0.0443 [0.0359, 0.0549] | 0.0730 [0.0584, 0.0872] | 0.0681 [0.0537, 0.0851] |
| shift:Franchise \| all | 30 / 30 / 30 | 0.0443 [0.0359, 0.0549] | 0.0730 [0.0584, 0.0872] | 0.0681 [0.0537, 0.0851] |
| shift:Transportation \| Rule C | 16 / 16 / 16 | 0.0207 [0.0058, 0.0352] | 0.0253 [0.0166, 0.0353] | 0.0260 [0.0123, 0.0386] |
| shift:Transportation \| all | 24 / 24 / 24 | 0.0207 [0.0058, 0.0352] | 0.0253 [0.0166, 0.0353] | 0.0260 [0.0123, 0.0386] |

### Parse-failure rate, point [95% CI]
Gemini refused one shift window (contract 130, window 5, 10 segments; both attempts returned finish reason `refusal` with 0 output tokens). Under Rule D those segments count as empty predictions for F1 and are excluded from the none false-positive rate.

| Scope | Labels with defined F1 (baseline / claude / gemini) | baseline | claude | gemini |
|---|---|---|---|---|
| test \| Rule A | 26 / 26 / 26 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| test \| all | 33 / 33 / 33 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| test \| Rule C | 17 / 17 / 17 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| shift \| Rule C | 17 / 17 / 17 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0022 [0.0000, 0.0073] |
| shift \| all | 32 / 32 / 32 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0022 [0.0000, 0.0073] |
| shift:Franchise \| Rule C | 17 / 17 / 17 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| shift:Franchise \| all | 30 / 30 / 30 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| shift:Transportation \| Rule C | 16 / 16 / 16 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0053 [0.0000, 0.0175] |
| shift:Transportation \| all | 24 / 24 / 24 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0053 [0.0000, 0.0175] |

### Macro-AP (not compared)
LLM AP is computed from sparse scores (unlisted labels at 0), so it is a lower bound and not comparable to the baseline's AP (Rule D). It is reported, not interpreted.

| Scope | baseline | claude | gemini |
|---|---|---|---|
| test \| Rule A | 0.6602 [0.6408, 0.6962] | 0.6489 [0.6213, 0.6870] (sparse lower bound, not interpreted) | 0.6840 [0.6590, 0.7196] (sparse lower bound, not interpreted) |
| test \| all | 0.5928 [0.5729, 0.6339] | 0.6265 [0.5979, 0.6708] (sparse lower bound, not interpreted) | 0.6538 [0.6297, 0.6935] (sparse lower bound, not interpreted) |
| test \| Rule C | 0.7019 [0.6714, 0.7464] | 0.6749 [0.6445, 0.7124] (sparse lower bound, not interpreted) | 0.7125 [0.6874, 0.7444] (sparse lower bound, not interpreted) |
| shift \| Rule C | 0.5279 [0.4918, 0.6150] | 0.5414 [0.5060, 0.6115] (sparse lower bound, not interpreted) | 0.5726 [0.5339, 0.6481] (sparse lower bound, not interpreted) |
| shift \| all | 0.4497 [0.4340, 0.5486] | 0.4926 [0.4690, 0.5813] (sparse lower bound, not interpreted) | 0.4996 [0.4745, 0.5965] (sparse lower bound, not interpreted) |
| shift:Franchise \| Rule C | 0.5510 [0.5035, 0.6616] | 0.5258 [0.5071, 0.6118] (sparse lower bound, not interpreted) | 0.5551 [0.5311, 0.6591] (sparse lower bound, not interpreted) |
| shift:Franchise \| all | 0.4801 [0.4470, 0.5887] | 0.5074 [0.4926, 0.6049] (sparse lower bound, not interpreted) | 0.5314 [0.5069, 0.6243] (sparse lower bound, not interpreted) |
| shift:Transportation \| Rule C | 0.5412 [0.4564, 0.6891] | 0.5569 [0.4958, 0.6975] (sparse lower bound, not interpreted) | 0.5538 [0.4938, 0.6918] (sparse lower bound, not interpreted) |
| shift:Transportation \| all | 0.5264 [0.4552, 0.6644] | 0.5516 [0.4646, 0.6881] (sparse lower bound, not interpreted) | 0.5534 [0.4690, 0.6723] (sparse lower bound, not interpreted) |

### Test minus shift, Rule C labels (independent bootstraps of the two contract sets)
Sources: `python -m src.evaluate model <name>` (`data/eval/<name>.json`); baseline values as in the table above.

| Model | Macro-F1 [95% CI] | Micro-F1 [95% CI] |
|---|---|---|
| Baseline | +0.1879 [+0.1200, +0.2524] | +0.1875 [+0.1210, +0.2511] |
| Claude | +0.1787 [+0.1109, +0.2366] | +0.1666 [+0.1081, +0.2172] |
| Gemini | +0.1580 [+0.1006, +0.2035] | +0.1775 [+0.1213, +0.2225] |

All three models lose between 0.16 and 0.19 F1 from test to the unseen contract types, with every interval excluding zero.

### Per-label test F1, Rule A labels (descriptive; per-label rows are outside the comparison family)
| Label | Contracts | Segments | baseline | claude | gemini |
|---|---|---|---|---|---|
| Governing Law | 81 | 87 | 0.9600 [0.9341, 0.9829] | 0.9827 [0.9643, 1.0000] | 0.9885 [0.9724, 1.0000] |
| Expiration Date | 75 | 78 | 0.7534 [0.6875, 0.8138] | 0.8552 [0.8028, 0.9007] | 0.9020 [0.8627, 0.9383] |
| Anti-Assignment | 71 | 91 | 0.8144 [0.7394, 0.8933] | 0.8280 [0.7692, 0.8931] | 0.8098 [0.7500, 0.8727] |
| Cap On Liability | 56 | 121 | 0.7397 [0.6864, 0.7977] | 0.7426 [0.6829, 0.8039] | 0.7712 [0.7155, 0.8304] |
| License Grant | 46 | 112 | 0.7921 [0.7310, 0.8497] | 0.7926 [0.7327, 0.8440] | 0.8067 [0.7467, 0.8626] |
| Audit Rights | 39 | 77 | 0.7681 [0.6812, 0.8548] | 0.7482 [0.6610, 0.8319] | 0.7500 [0.6508, 0.8421] |
| Termination For Convenience | 38 | 50 | 0.6393 [0.5405, 0.7241] | 0.7222 [0.6333, 0.8046] | 0.8132 [0.7250, 0.9011] |
| Post-Termination Services | 37 | 74 | 0.4973 [0.4252, 0.5582] | 0.4035 [0.2617, 0.5156] | 0.4533 [0.3452, 0.5385] |
| Exclusivity | 36 | 76 | 0.5263 [0.4370, 0.6286] | 0.5914 [0.5000, 0.6900] | 0.6918 [0.6030, 0.7904] |
| Renewal Term | 36 | 37 | 0.9143 [0.8378, 0.9750] | 0.9444 [0.8928, 0.9867] | 0.9577 [0.9091, 1.0000] |
| Minimum Commitment | 35 | 86 | 0.3303 [0.2273, 0.4466] | 0.3704 [0.1856, 0.5476] | 0.5306 [0.3846, 0.6668] |
| Revenue/Profit Sharing | 32 | 83 | 0.5287 [0.3899, 0.6558] | 0.6909 [0.5629, 0.7926] | 0.7294 [0.6275, 0.8111] |
| Insurance | 28 | 73 | 0.7763 [0.6720, 0.8533] | 0.9028 [0.8547, 0.9412] | 0.9067 [0.8468, 0.9524] |
| Non-Transferable License | 24 | 47 | 0.7500 [0.6428, 0.8387] | 0.7711 [0.6667, 0.8539] | 0.7692 [0.6552, 0.8628] |
| Notice Period To Terminate Renewal | 24 | 27 | 0.8077 [0.6875, 0.9153] | 0.8400 [0.7273, 0.9362] | 0.8980 [0.8000, 0.9787] |
| Ip Ownership Assignment | 22 | 38 | 0.6349 [0.4762, 0.7742] | 0.4286 [0.2642, 0.5863] | 0.7246 [0.5756, 0.8537] |
| Non-Compete | 22 | 43 | 0.5205 [0.3492, 0.6452] | 0.6410 [0.4888, 0.7467] | 0.6286 [0.4407, 0.7532] |
| Change Of Control | 20 | 42 | 0.5000 [0.3939, 0.5902] | 0.5570 [0.4348, 0.6667] | 0.5843 [0.4557, 0.6988] |
| Covenant Not To Sue | 20 | 33 | 0.7500 [0.6512, 0.8364] | 0.7241 [0.5614, 0.8571] | 0.8000 [0.6885, 0.8861] |
| Uncapped Liability | 19 | 25 | 0.6531 [0.4827, 0.7843] | 0.4490 [0.2703, 0.6000] | 0.7273 [0.6037, 0.8235] |
| Warranty Duration | 17 | 44 | 0.3750 [0.2857, 0.5000] | 0.5278 [0.4086, 0.7038] | 0.5823 [0.4615, 0.7500] |
| Liquidated Damages | 14 | 30 | 0.6250 [0.3846, 0.7843] | 0.7797 [0.6667, 0.9444] | 0.7778 [0.6667, 0.9091] |
| Rofr/Rofo/Rofn | 14 | 46 | 0.6000 [0.4000, 0.7385] | 0.8155 [0.7077, 0.9016] | 0.8000 [0.6571, 0.8889] |
| Volume Restriction | 14 | 24 | 0.1481 [0.0000, 0.4211] | 0.1176 [0.0000, 0.2000] | 0.0645 [0.0000, 0.1481] |
| Competitive Restriction Exception | 13 | 17 | 0.2449 [0.1212, 0.3590] | 0.4848 [0.2500, 0.6452] | 0.5000 [0.3158, 0.6512] |
| No-Solicit Of Employees | 12 | 15 | 0.7586 [0.5556, 0.8889] | 0.8485 [0.6875, 0.9655] | 0.8485 [0.6667, 1.0000] |

### Per-label shift F1, Rule C labels (descriptive)
| Label | Contracts | Segments | baseline | claude | gemini |
|---|---|---|---|---|---|
| Expiration Date | 23 | 26 | 0.6522 [0.4650, 0.8077] | 0.7500 [0.6341, 0.8627] | 0.8302 [0.7200, 0.9231] |
| Governing Law | 23 | 24 | 0.7692 [0.6441, 0.9167] | 0.8571 [0.7719, 0.9600] | 0.7667 [0.6216, 0.9259] |
| Anti-Assignment | 20 | 45 | 0.5000 [0.3541, 0.6757] | 0.4662 [0.3664, 0.5743] | 0.4516 [0.3590, 0.5750] |
| Insurance | 15 | 67 | 0.6579 [0.4769, 0.8245] | 0.7778 [0.6733, 0.8591] | 0.7651 [0.6250, 0.8857] |
| Renewal Term | 15 | 33 | 0.4681 [0.3188, 0.7143] | 0.5217 [0.3404, 0.7858] | 0.5333 [0.3673, 0.8000] |
| Cap On Liability | 14 | 24 | 0.7143 [0.5128, 0.9143] | 0.6792 [0.5294, 0.8445] | 0.7059 [0.5556, 0.8728] |
| Minimum Commitment | 14 | 58 | 0.0667 [0.0000, 0.1429] | 0.2571 [0.0968, 0.4286] | 0.3421 [0.1667, 0.5061] |
| Audit Rights | 13 | 43 | 0.6588 [0.5231, 0.8000] | 0.5778 [0.4415, 0.7027] | 0.6500 [0.5957, 0.7164] |
| Non-Compete | 11 | 53 | 0.3944 [0.1875, 0.6000] | 0.6792 [0.5789, 0.7879] | 0.6582 [0.5397, 0.7843] |
| Notice Period To Terminate Renewal | 11 | 14 | 0.4545 [0.1739, 0.7061] | 0.3077 [0.0869, 0.5455] | 0.6957 [0.5000, 0.8421] |
| Revenue/Profit Sharing | 11 | 25 | 0.4138 [0.2909, 0.5306] | 0.3226 [0.0741, 0.6208] | 0.4878 [0.2778, 0.6667] |
| Volume Restriction | 11 | 31 | 0.0000 [0.0000, 0.0000] | 0.0625 [0.0000, 0.1935] | 0.0000 [0.0000, 0.0000] |
| Covenant Not To Sue | 10 | 22 | 0.5652 [0.4324, 0.7222] | 0.6667 [0.5937, 0.7692] | 0.6818 [0.6032, 0.8125] |
| Exclusivity | 10 | 22 | 0.3636 [0.0000, 0.6038] | 0.6038 [0.3590, 0.7917] | 0.5357 [0.3478, 0.7165] |
| License Grant | 10 | 25 | 0.3902 [0.2162, 0.5652] | 0.5455 [0.3333, 0.7743] | 0.6207 [0.4400, 0.7907] |
| Liquidated Damages | 10 | 19 | 0.6286 [0.3156, 0.8333] | 0.6522 [0.4865, 0.7778] | 0.6842 [0.5217, 0.8206] |
| Post-Termination Services | 10 | 31 | 0.3600 [0.2221, 0.4906] | 0.1905 [0.0000, 0.3333] | 0.3714 [0.2222, 0.4938] |

## Model comparisons (paired, Step 4b)
Pre-registered 2026-09-27 before any paired interval was computed (BUILD_LOG Step 4b): micro-F1 and macro-F1 under Rule B thresholds are co-primary; the primary family is 3 pairs x 2 scopes (test Rule A, shift Rule C) x 2 metrics = 12 comparisons; a difference is claimed only if its Bonferroni-adjusted interval (99.583%) excludes zero; verdicts are per scope. Each model's marginal results were already known when these rules were fixed. Macro-AP is not compared (Rule D).

Method: 10000 contract-level bootstrap resamples, stratified by contract type, percentile 95% intervals, seed 42; paired (identical resamples for both models). Commands: `python -m src.evaluate compare claude baseline`, `compare gemini baseline`, `compare gemini claude` (printouts `data/processed/eval_compare_{claude_baseline,gemini_baseline,gemini_claude}.txt`, files `data/eval/compare_*.json`).

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

### Primary comparisons (A minus B)
| Pair | Scope and metric | Difference | 95% CI | Adjusted CI | Claim |
|---|---|---|---|---|---|
| claude minus baseline | test \| Rule A \| macro_f1 | +0.0443 | [+0.0148, +0.0767] | [+0.0004, +0.0919] | A higher |
| claude minus baseline | test \| Rule A \| micro_f1 | +0.0496 | [+0.0287, +0.0713] | [+0.0180, +0.0819] | A higher |
| claude minus baseline | shift \| Rule C \| macro_f1 | +0.0506 | [+0.0010, +0.1003] | [-0.0215, +0.1230] | none |
| claude minus baseline | shift \| Rule C \| micro_f1 | +0.0661 | [+0.0223, +0.1118] | [+0.0016, +0.1323] | A higher |
| gemini minus baseline | test \| Rule A \| macro_f1 | +0.0926 | [+0.0618, +0.1250] | [+0.0466, +0.1432] | A higher |
| gemini minus baseline | test \| Rule A \| micro_f1 | +0.0847 | [+0.0600, +0.1091] | [+0.0484, +0.1208] | A higher |
| gemini minus baseline | shift \| Rule C \| macro_f1 | +0.1013 | [+0.0558, +0.1527] | [+0.0365, +0.1736] | A higher |
| gemini minus baseline | shift \| Rule C \| micro_f1 | +0.0817 | [+0.0373, +0.1267] | [+0.0173, +0.1460] | A higher |
| gemini minus claude | test \| Rule A \| macro_f1 | +0.0483 | [+0.0305, +0.0655] | [+0.0218, +0.0753] | A higher |
| gemini minus claude | test \| Rule A \| micro_f1 | +0.0350 | [+0.0202, +0.0498] | [+0.0140, +0.0571] | A higher |
| gemini minus claude | shift \| Rule C \| macro_f1 | +0.0508 | [+0.0184, +0.0838] | [+0.0018, +0.0966] | A higher |
| gemini minus claude | shift \| Rule C \| micro_f1 | +0.0155 | [-0.0101, +0.0439] | [-0.0203, +0.0577] | none |

### Verdicts, per scope
| Pair | Scope | Verdict |
|---|---|---|
| claude vs baseline | test \| Rule A | claude higher on both co-primary metrics |
| claude vs baseline | shift \| Rule C | per metric: micro_f1 claude higher, macro_f1 none |
| gemini vs baseline | test \| Rule A | gemini higher on both co-primary metrics |
| gemini vs baseline | shift \| Rule C | gemini higher on both co-primary metrics |
| gemini vs claude | test \| Rule A | gemini higher on both co-primary metrics |
| gemini vs claude | shift \| Rule C | per metric: micro_f1 none, macro_f1 gemini higher |

Reading:
- Gemini is higher than the baseline on both co-primary metrics on test and on shift.
- Gemini is higher than Claude on both metrics on test. On shift, Gemini's macro-F1 is higher and the micro-F1 difference is not claimed.
- Claude is higher than the baseline on both metrics on test. On shift, Claude's micro-F1 is higher; its macro-F1 difference is not claimed (the 95% interval excludes zero, the adjusted interval does not).
- Three claims rest on adjusted lower bounds within 0.002 of zero: Claude minus baseline on test macro-F1 (+0.0004), Claude minus baseline on shift micro-F1 (+0.0016), and Gemini minus Claude on shift macro-F1 (+0.0018). They meet the pre-registered rule and are marginal: each adjusted bound is a percentile over about 21 of the 10,000 resamples in its tail, so it carries Monte Carlo error of the same order.

Secondary rows (unadjusted 95%, no claims) are in the appendix "All paired differences".

## Drift monitoring (Step 5)
Question: would a monitor with no labels notice the contract-type shift that costs every model 0.16 to 0.19 F1? Rules pre-registered in BUILD_LOG Step 5 before any drift statistic was computed; thresholds frozen from validation (`python -m src.drift calibrate | tee data/processed/drift_calibrate.txt`, `models/drift/reference.json`, freeze_id 5f2143f3067c) and committed before one evaluation run (`python -m src.drift evaluate | tee data/processed/drift_evaluate.txt`, `data/eval/drift.json`). Tables: `python -m src.report`.

Setup:
- Monitoring unit: a batch of 5 contracts. Reference: the 97 validation contracts.
- Input statistics (model-free): out-of-vocabulary unigram rate against the frozen baseline vocabulary (minus the reference rate), 1 minus the cosine of summed TF-IDF vectors, PSI of segment lengths.
- Model statistics, per model: Jensen-Shannon distance of the predicted label mix, difference in the share of segments predicted none, PSI of the per-segment maximum confidence.
- Alarms: each statistic alone, and four families (input, baseline, Claude, Gemini) on the minimum p-value of their statistics. Thresholds come from 2,000 leave-batch-out validation batches, with a null alarm rate of at most 1% (exact rates: 0.0100 for every single statistic and for the input and baseline families; 0.0090 Claude, 0.0095 Gemini, below 1% because of ties).
- Test measures the false-alarm rate; Franchise and Transportation measure detection. 1,000 batches per set; intervals from 10,000 contract-level bootstrap resamples within each set x 100 batches, with the reference and thresholds held fixed.
- Primary rule: a family detects a shift type when its detection-rate lower bound exceeds its test upper bound, both at 99.375% (Bonferroni over 4 families x 2 types).

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

### Family alarm rates
| Family | Set | Alarm rate | 95% CI | Adjusted CI |
|---|---|---|---|---|
| input | test | 0.0580 | [0.0000, 0.1800] | [0.0000, 0.2275] |
| input | shift | 0.0320 | [0.0000, 0.2100] | [0.0000, 0.3200] |
| input | shift:Franchise | 0.0910 | [0.0000, 0.4800] | [0.0000, 0.7200] |
| input | shift:Transportation | 0.0460 | [0.0000, 0.5400] | [0.0000, 0.7900] |
| baseline | test | 0.0500 | [0.0000, 0.1700] | [0.0000, 0.2100] |
| baseline | shift | 0.0200 | [0.0000, 0.1400] | [0.0000, 0.2200] |
| baseline | shift:Franchise | 0.0020 | [0.0000, 0.0800] | [0.0000, 0.1875] |
| baseline | shift:Transportation | 0.1280 | [0.0000, 0.6800] | [0.0000, 0.9075] |
| claude | test | 0.0080 | [0.0000, 0.0500] | [0.0000, 0.0600] |
| claude | shift | 0.0040 | [0.0000, 0.0800] | [0.0000, 0.1375] |
| claude | shift:Franchise | 0.0020 | [0.0000, 0.0900] | [0.0000, 0.2075] |
| claude | shift:Transportation | 0.0080 | [0.0000, 0.2100] | [0.0000, 0.4100] |
| gemini | test | 0.0200 | [0.0000, 0.0900] | [0.0000, 0.1275] |
| gemini | shift | 0.0230 | [0.0000, 0.1700] | [0.0000, 0.2600] |
| gemini | shift:Franchise | 0.0160 | [0.0000, 0.2000] | [0.0000, 0.3800] |
| gemini | shift:Transportation | 0.1520 | [0.0200, 0.7800] | [0.0000, 0.9900] |

### Pre-registered rule
| Family | Shift type | Adjusted lower bound | Test adjusted upper bound | Detects |
|---|---|---|---|---|
| input | shift:Franchise | 0.0000 | 0.2275 | no |
| input | shift:Transportation | 0.0000 | 0.2275 | no |
| baseline | shift:Franchise | 0.0000 | 0.2100 | no |
| baseline | shift:Transportation | 0.0000 | 0.2100 | no |
| claude | shift:Franchise | 0.0000 | 0.0600 | no |
| claude | shift:Transportation | 0.0000 | 0.0600 | no |
| gemini | shift:Franchise | 0.0000 | 0.1275 | no |
| gemini | shift:Transportation | 0.0000 | 0.1275 | no |

Result: no family detects either shift type under the pre-registered rule. Every shift detection interval has an adjusted lower bound of 0. With 13 or 15 contracts per shift type, a contract-level resample often leaves out the few contracts that trigger alarms, and that resample's rate is 0. The rule could not be met at this sample size, and no power check was made before it was fixed. It is reported as written.

Calibration check (not a claim): each family's test false-alarm rate against the nominal 1%. The 95% intervals all contain 1%, but the input (0.0580) and baseline (0.0500) point rates are about five times it; Claude 0.0080, Gemini 0.0200. Validation and test are less alike for these statistics than the null assumed (TF-IDF centroid distance alarms on 0.0720 of test batches, length PSI on 0.0460, the baseline's confidence PSI on 0.0550), as the pre-registration allowed for.

### Per-statistic alarm rates (point, no claims)
| Statistic | test | shift | shift:Franchise | shift:Transportation |
|---|---|---|---|---|
| oov_rate_diff | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| tfidf_centroid_distance | 0.0720 | 0.0880 | 0.2340 | 0.1750 |
| length_psi | 0.0460 | 0.0270 | 0.0990 | 0.0000 |
| baseline:label_mix_js | 0.0050 | 0.0450 | 0.0030 | 0.3100 |
| baseline:none_share_diff | 0.0120 | 0.0000 | 0.0050 | 0.0000 |
| baseline:confidence_psi | 0.0550 | 0.0000 | 0.0020 | 0.0000 |
| claude:label_mix_js | 0.0080 | 0.0090 | 0.0000 | 0.0420 |
| claude:none_share_diff | 0.0140 | 0.0010 | 0.0020 | 0.0000 |
| claude:confidence_psi | 0.0100 | 0.0060 | 0.0150 | 0.0100 |
| gemini:label_mix_js | 0.0100 | 0.0450 | 0.0010 | 0.3340 |
| gemini:none_share_diff | 0.0320 | 0.0030 | 0.0420 | 0.0000 |
| gemini:confidence_psi | 0.0280 | 0.0020 | 0.0060 | 0.0070 |

### Mean statistic values (NaN batches in parentheses)
| Statistic | test | shift | shift:Franchise | shift:Transportation |
|---|---|---|---|---|
| oov_rate_diff | -0.0011 (0) | -0.0016 (0) | -0.0046 (0) | 0.0025 (0) |
| tfidf_centroid_distance | 0.2959 (0) | 0.3513 (0) | 0.3998 (0) | 0.3697 (0) |
| length_psi | 0.2165 (0) | 0.1575 (0) | 0.3017 (0) | 0.1026 (0) |
| baseline:label_mix_js | 0.3765 (0) | 0.4722 (0) | 0.4604 (0) | 0.5750 (0) |
| baseline:none_share_diff | 0.0264 (0) | 0.0223 (0) | 0.0206 (0) | 0.0467 (0) |
| baseline:confidence_psi | 0.0954 (0) | 0.0394 (0) | 0.0467 (0) | 0.0754 (0) |
| claude:label_mix_js | 0.3996 (0) | 0.4470 (0) | 0.4379 (0) | 0.5442 (0) |
| claude:none_share_diff | 0.0357 (0) | 0.0332 (0) | 0.0654 (0) | 0.0425 (0) |
| claude:confidence_psi | 0.0639 (0) | 0.0533 (0) | 0.0916 (0) | 0.0927 (0) |
| gemini:label_mix_js | 0.3895 (0) | 0.4279 (0) | 0.4098 (0) | 0.5775 (0) |
| gemini:none_share_diff | 0.0377 (0) | 0.0320 (0) | 0.0603 (0) | 0.0485 (0) |
| gemini:confidence_psi | 0.0927 (0) | 0.0440 (0) | 0.0698 (0) | 0.0845 (0) |

Reading (secondary, descriptive):
- Transportation's label-distribution shift shows in the predicted label mix: the baseline's and Gemini's label-mix statistics alarm on 0.3100 and 0.3340 of Transportation batches, against 0.0050 and 0.0100 on test. Claude's label mix moves less (0.0420).
- The vocabulary shift shows in TF-IDF weights, not in unknown words: centroid distance alarms on 0.2340 of Franchise and 0.1750 of Transportation batches (test 0.0720), while the out-of-vocabulary rate never alarms and is lower on Franchise than on validation (mean difference -0.0046). Franchise terms were already in the train vocabulary.
- Gemini on Transportation is the only family whose 95% interval excludes 0 ([0.0200, 0.7800]); secondary, no claim.

### Parse failures (operational counter, not calibrated)
| Model | test | shift | shift:Franchise | shift:Transportation |
|---|---|---|---|---|
| baseline | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| claude | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| gemini | 0.0000 | 0.1740 | 0.0000 | 0.3860 |

Gemini's parse failures come from one refused Transportation window (contract 130). A batch of 5 contains a given contract with probability 5/13 = 0.385 among the 13 Transportation contracts and 5/28 = 0.179 among all 28 shift contracts, matching the observed 0.3860 and 0.1740.

### Do drift statistics track accuracy? (descriptive)
Spearman rank correlation between each statistic and each model's batch micro-F1 on the 17 Rule C labels, over the 1,000 test batches, the 1,000 shift batches, and both pooled. The full table is in the appendix "Drift correlations".
- Pooled, the TF-IDF centroid distance correlates -0.363 (baseline), -0.406 (Claude) and -0.406 (Gemini) with batch F1, and the baseline's label-mix distance -0.541, -0.489 and -0.474. Pooled figures mostly restate the known test-versus-shift gap.
- Within test, no correlation exceeds 0.37 in absolute value, and the largest are positive (LLM confidence PSI with LLM F1: +0.286 to +0.368), so more drift went with higher F1 there. Within one population these statistics do not track accuracy.
- Within shift, the baseline's label-mix distance correlates -0.443 with its own F1.

### What this means for the service (Step 7)
- A per-batch monitor on 5 contracts, calibrated on 97 validation contracts, is noisy: in-distribution batches alarm on up to about 6% of batches for the input and baseline families.
- The signals that move under shift are the TF-IDF centroid distance and the predicted label mix; the OOV rate does not.
- Establishing detection power with intervals needs more shifted contracts than this dataset holds for any one type; with 13 to 15, the contract-level uncertainty dominates.

## Calibration across models, test
Every (segment, label) pair is one prediction; 10 equal-width bins. Each cell: pairs, mean predicted vs observed positive rate. Source: `python -m src.report | tee data/processed/results_tables.md`, generated from `data/eval/{baseline,claude,gemini}.json` (`python -m src.evaluate model <name>`).

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

| Bin | baseline | claude | gemini |
|---|---|---|---|
| [0.0, 0.1) | 306,899: 0.0010 vs 0.0014 | 306,360: 0.0000 vs 0.0011 | 307,333: 0.0000 vs 0.0010 |
| [0.1, 0.2) | 590: 0.1393 vs 0.1288 | 268: 0.1267 vs 0.0112 | 23: 0.1422 vs 0.0000 |
| [0.2, 0.3) | 251: 0.2474 vs 0.2191 | 486: 0.2000 vs 0.0329 | 102: 0.2255 vs 0.0784 |
| [0.3, 0.4) | 197: 0.3482 vs 0.2538 | 548: 0.3001 vs 0.1606 | 130: 0.3342 vs 0.1308 |
| [0.4, 0.5) | 125: 0.4498 vs 0.2880 | 236: 0.4000 vs 0.2119 | 153: 0.4111 vs 0.2222 |
| [0.5, 0.6) | 123: 0.5539 vs 0.3577 | 307: 0.5000 vs 0.3648 | 68: 0.5154 vs 0.3088 |
| [0.6, 0.7) | 102: 0.6496 vs 0.4118 | 306: 0.6000 vs 0.5229 | 64: 0.6266 vs 0.2031 |
| [0.7, 0.8) | 119: 0.7494 vs 0.5882 | 187: 0.7029 vs 0.6310 | 157: 0.7385 vs 0.3248 |
| [0.8, 0.9) | 127: 0.8533 vs 0.5512 | 365: 0.8314 vs 0.8137 | 401: 0.8365 vs 0.4713 |
| [0.9, 1.0] | 941: 0.9753 vs 0.7439 | 411: 0.9139 vs 0.9513 | 1,043: 0.9523 vs 0.8917 |
| Share of pairs in [0.0, 0.1) | 99.17% | 98.99% | 99.31% |
| Pooled ECE, point [95% CI] | 0.0015 [0.0009, 0.0025] | 0.0021 [0.0018, 0.0024] | 0.0022 [0.0019, 0.0025] |

- Pooled ECE is near zero for every model because 98.99% to 99.31% of pairs fall in the lowest bin; the bins above 0.1 carry the calibration evidence.
- Gemini is overconfident from 0.6 to 0.9: mean predicted 0.7385 against observed 0.3248 in [0.7, 0.8), and 0.8365 against 0.4713 in [0.8, 0.9) (401 pairs). Its Rule B thresholds, above 0.5 for 19 of 28 labels (BUILD_LOG 3ag), are consistent with this.
- Claude tracks the observed rate above 0.7 (0.8314 against 0.8137, 0.9139 against 0.9513) and is overconfident from 0.1 to 0.4 (for example 0.2000 against 0.0329). Its bin means fall on exact tenths (0.2000, 0.4000, 0.5000, 0.6000), consistent with rounded verbal confidences.
- The baseline is overconfident at the top: 0.9753 against 0.7439 in [0.9, 1.0] (class_weight="balanced", docs/plan.md Step 4).
- LLM confidences are stated by the model, not estimated probabilities; the reliability table measures how well those statements track outcomes on this test set.

## LLM runs: cost, latency and repeatability
Sources: `python -m src.llm.run heldout --model <name>` (`data/processed/llm_heldout_{claude,gemini}.txt`), `python -m src.llm.run repeat --model <name>` (`data/processed/llm_repeat_{claude,gemini}.txt`). Latency is per call of 10 segments.

| Model | Split | Calls | Cost | Cost per 1,000 segments | Latency median | Latency p95 |
|---|---|---|---|---|---|---|
| Claude | test | 985 | $6.4095 | $0.6835 | 2,017 ms | 3,445 ms |
| Claude | shift | 470 | $3.2500 | $0.7090 | 2,171 ms | 3,860 ms |
| Gemini | test | 985 | $3.0320 | $0.3233 | 1,242 ms | 1,844 ms |
| Gemini | shift | 470 | $1.4930 | $0.3257 | 1,394 ms | 3,429 ms |

- The baseline runs locally; its cost is 0.
- Total API spend for Step 3, including prompt iteration, validation and the repeat check: about $53.70 of the $150 cap.
- Repeat check (first 30 iteration windows, 295 validation segments; three runs; Rule B thresholds): Claude's exact label-set agreement across all three runs was 0.9763, with a none-versus-some flip rate of 0.0136 to 0.0169 between pairs of runs (Claude takes no temperature or seed). Gemini's three runs, with `seed=42`, were identical (agreement 1.0); this is measured on 30 windows and is not a guarantee of determinism.

## Confidence intervals
- Method: 2000 contract-level bootstrap resamples, stratified by contract type, percentile 95% intervals, seed 42.
- Resampling unit: the contract; within each contract type, as many contracts as the type has are drawn with replacement. Resamples depend only on the seed, a stream name (test, shift, shift:Franchise, shift:Transportation), and the contract ids and types, so every model evaluated later sees identical resamples (paired comparisons).
- F1, micro-F1, and none FP rate are recomputed from contract-weighted counts; AP uses scikit-learn with each segment weighted by its contract's draw count.
- A label with no support in a resample is left out of that resample's macro average; the "Resamples with support" column in the appendix shows how many of the 2000 resamples each per-label interval rests on.
- Test and shift intervals come from independent bootstraps; the test-minus-shift interval subtracts their resample distributions.
- Sanity check: `python -m src.evaluate compare baseline baseline` gave every difference and interval bound exactly 0 at 2000 resamples (Step 4a, `data/processed/eval_compare_self.txt`) and again at 10000 resamples with the adjusted bounds (Step 4b, `data/processed/eval_compare_self_10k.txt`).
- Paired comparisons (Step 4b) use their own bootstrap of 10000 resamples, same seed and streams, so the Bonferroni tails (0.208% each) rest on about 21 resamples rather than about 4. Marginal intervals stay at 2000. Both models in a comparison are evaluated on identical resamples, which `compare` checks before computing anything.
- The baseline's evaluation file was regenerated in Step 4b to add the parse-failure rate (0 everywhere); every 4a value is unchanged.
- Caveat: several AP intervals are asymmetric, with the point estimate near the lower bound (for example, shift all labels macro-AP 0.4497 [0.4340, 0.5486]). Percentile intervals report that asymmetry as measured; claims in this project rely on F1 intervals and on intervals that exclude zero.

## Appendix: all 33 labels on test
Labels with fewer than 10 test contracts are marked "insufficient support, not interpreted". Metrics: baseline version 9692b04f03fb, `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt` (values from `data/eval/baseline.json`). Counts cross-checked against `python -m src.build_segments | tee data/processed/build_segments_report.txt`.

| Label | Test contracts | Test segments | F1 [95% CI] | AP [95% CI] | Resamples with support | Status |
|---|---|---|---|---|---|---|
| Governing Law | 81 | 87 | 0.960 [0.934, 0.983] | 0.992 [0.982, 0.999] | 2000 | main table |
| Expiration Date | 75 | 78 | 0.753 [0.687, 0.814] | 0.854 [0.796, 0.911] | 2000 | main table |
| Anti-Assignment | 71 | 91 | 0.814 [0.739, 0.893] | 0.901 [0.851, 0.954] | 2000 | main table |
| Cap On Liability | 56 | 121 | 0.740 [0.686, 0.798] | 0.773 [0.703, 0.852] | 2000 | main table |
| License Grant | 46 | 112 | 0.792 [0.731, 0.850] | 0.827 [0.766, 0.890] | 2000 | main table |
| Audit Rights | 39 | 77 | 0.768 [0.681, 0.855] | 0.797 [0.715, 0.889] | 2000 | main table |
| Termination For Convenience | 38 | 50 | 0.639 [0.541, 0.724] | 0.594 [0.487, 0.705] | 2000 | main table |
| Post-Termination Services | 37 | 74 | 0.497 [0.425, 0.558] | 0.553 [0.435, 0.650] | 2000 | main table |
| Exclusivity | 36 | 76 | 0.526 [0.437, 0.629] | 0.562 [0.450, 0.719] | 2000 | main table |
| Renewal Term | 36 | 37 | 0.914 [0.838, 0.975] | 0.944 [0.881, 0.997] | 2000 | main table |
| Minimum Commitment | 35 | 86 | 0.330 [0.227, 0.447] | 0.288 [0.205, 0.541] | 2000 | main table |
| Revenue/Profit Sharing | 32 | 83 | 0.529 [0.390, 0.656] | 0.497 [0.323, 0.694] | 2000 | main table |
| Insurance | 28 | 73 | 0.776 [0.672, 0.853] | 0.883 [0.790, 0.944] | 2000 | main table |
| Non-Transferable License | 24 | 47 | 0.750 [0.643, 0.839] | 0.727 [0.610, 0.836] | 2000 | main table |
| Notice Period To Terminate Renewal | 24 | 27 | 0.808 [0.688, 0.915] | 0.859 [0.760, 0.952] | 2000 | main table |
| Ip Ownership Assignment | 22 | 38 | 0.635 [0.476, 0.774] | 0.658 [0.510, 0.805] | 2000 | main table |
| Non-Compete | 22 | 43 | 0.521 [0.349, 0.645] | 0.552 [0.374, 0.675] | 2000 | main table |
| Change Of Control | 20 | 42 | 0.500 [0.394, 0.590] | 0.451 [0.340, 0.597] | 2000 | main table |
| Covenant Not To Sue | 20 | 33 | 0.750 [0.651, 0.836] | 0.752 [0.628, 0.876] | 2000 | main table |
| Uncapped Liability | 19 | 25 | 0.653 [0.483, 0.784] | 0.569 [0.426, 0.762] | 2000 | main table |
| Warranty Duration | 17 | 44 | 0.375 [0.286, 0.500] | 0.400 [0.309, 0.559] | 2000 | main table |
| Liquidated Damages | 14 | 30 | 0.625 [0.385, 0.784] | 0.679 [0.528, 0.831] | 2000 | main table |
| Rofr/Rofo/Rofn | 14 | 46 | 0.600 [0.400, 0.738] | 0.727 [0.533, 0.836] | 2000 | main table |
| Volume Restriction | 14 | 24 | 0.148 [0.000, 0.421] | 0.218 [0.067, 0.416] | 2000 | main table |
| Competitive Restriction Exception | 13 | 17 | 0.245 [0.121, 0.359] | 0.269 [0.116, 0.470] | 2000 | main table |
| No-Solicit Of Employees | 12 | 15 | 0.759 [0.556, 0.889] | 0.837 [0.664, 0.950] | 2000 | main table |
| Affiliate License | 9 | 14 | 0.083 [0.000, 0.250] | 0.069 [0.020, 0.166] | 2000 | insufficient support, not interpreted |
| Irrevocable Or Perpetual License | 9 | 18 | 0.711 [0.524, 0.840] | 0.760 [0.514, 0.903] | 2000 | insufficient support, not interpreted |
| Joint Ip Ownership | 9 | 19 | 0.733 [0.476, 0.941] | 0.652 [0.379, 0.952] | 2000 | insufficient support, not interpreted |
| No-Solicit Of Customers | 7 | 10 | 0.000 [0.000, 0.000] | 0.181 [0.081, 0.419] | 2000 | insufficient support, not interpreted |
| Most Favored Nation | 6 | 8 | 0.000 [0.000, 0.000] | 0.360 [0.100, 0.622] | 1997 | insufficient support, not interpreted |
| Non-Disparagement | 6 | 11 | 0.167 [0.000, 0.444] | 0.294 [0.043, 0.669] | 1998 | insufficient support, not interpreted |
| Third Party Beneficiary | 3 | 3 | 0.000 [0.000, 0.000] | 0.080 [0.009, 0.250] | 1948 | insufficient support, not interpreted |

## Error analysis
### Baseline, validation only (test errors are not examined, so they cannot inform Step 3 prompt design)
Source: `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt` (values from `data/eval/baseline.json`). Ambiguous cases found here are documented in `docs/labeling_schema.md` (no relabeling).

Top confused pairs (segment truly labeled A, also predicted B, B wrong):

| True label | Also predicted (wrong) | Segments |
|---|---|---|
| License Grant | Exclusivity | 24 |
| License Grant | Affiliate License | 13 |
| Anti-Assignment | Change Of Control | 10 |
| Non-Transferable License | Exclusivity | 10 |
| Audit Rights | Post-Termination Services | 9 |
| License Grant | Irrevocable Or Perpetual License | 9 |
| Expiration Date | Renewal Term | 8 |
| Expiration Date | Termination For Convenience | 8 |
| Affiliate License | Exclusivity | 6 |
| Irrevocable Or Perpetual License | Affiliate License | 6 |
| License Grant | Non-Transferable License | 6 |
| Expiration Date | Notice Period To Terminate Renewal | 5 |
| Expiration Date | Post-Termination Services | 5 |
| Irrevocable Or Perpetual License | Exclusivity | 5 |
| Non-Compete | Exclusivity | 5 |

Failing labels on validation (F1 below 0.30 or zero recall): Competitive Restriction Exception, Most Favored Nation, No-Solicit Of Customers, Volume Restriction.

### Claude and Gemini, validation only (Rule B thresholds)
Source: `python -m src.evaluate model <name>` (`data/eval/{claude,gemini}.json`, field `error_analysis_val`). Test errors are not examined.

> Contamination caveat: CUAD has been public since 2021, so Claude and Gemini may have seen these contracts and labels in training, and their scores may be optimistic relative to unseen contracts. The shift set is part of the same release (docs/plan.md, Limitations).

Top confused pairs (segment truly labeled A, also predicted B, B wrong):

| True label | Also predicted (wrong) | Claude segments | Gemini segments |
|---|---|---|---|
| License Grant | Affiliate License | 3 | 11 |
| Irrevocable Or Perpetual License | Affiliate License | 3 | 9 |
| Cap On Liability | Uncapped Liability | 7 | 8 |
| Anti-Assignment | Change Of Control | 7 | 2 |
| Non-Transferable License | Affiliate License | not in top 15 | 7 |
| Anti-Assignment | Non-Transferable License | 5 | 4 |
| Expiration Date | Termination For Convenience | 5 | not in top 15 |
| Exclusivity | Minimum Commitment | 4 | 5 |
| Non-Compete | Exclusivity | 4 | 5 |
| Competitive Restriction Exception | Exclusivity | 4 | not in top 15 |
| Expiration Date | Renewal Term | 4 | 4 |
| No-Solicit Of Employees | Competitive Restriction Exception | 4 | not in top 15 |

Labels with the most false negatives on validation (segments where the model predicted nothing at all in parentheses):

| Claude | Gemini |
|---|---|
| License Grant: 67 (53) | Post-Termination Services: 56 (40) |
| Post-Termination Services: 64 (44) | License Grant: 53 (42) |
| Minimum Commitment: 36 (30) | Exclusivity: 34 (17) |
| Exclusivity: 35 (20) | Revenue/Profit Sharing: 28 (27) |
| Expiration Date: 33 (23) | Non-Transferable License: 27 (9) |

Failing labels on validation (F1 below 0.30 or zero recall): Claude: Competitive Restriction Exception, Post-Termination Services, Volume Restriction; Gemini: Post-Termination Services.

- Both LLMs confuse Cap On Liability with Uncapped Liability and Exclusivity with Minimum Commitment; Gemini over-predicts Affiliate License on license clauses. Most false negatives are segments where the model listed no label at all: 437 of 599 for Claude (73%) and 358 of 514 for Gemini (70%), summed over all 33 labels.

## Appendix: all paired differences (Step 4b)
Primary rows carry claims only through the adjusted interval in "Model comparisons"; the rest are secondary (unadjusted 95%, reported, no claims). Source: `python -m src.report | tee data/processed/results_tables.md`, generated from `data/eval/{baseline,claude,gemini}.json` (`python -m src.evaluate model <name>`).

| Pair | Scope and metric | Difference | 95% CI | Adjusted CI | Claim |
|---|---|---|---|---|---|
| claude minus baseline | test \| Rule A \| macro_f1 | +0.0443 | [+0.0148, +0.0767] | [+0.0004, +0.0919] | A higher |
| claude minus baseline | test \| Rule A \| micro_f1 | +0.0496 | [+0.0287, +0.0713] | [+0.0180, +0.0819] | A higher |
| claude minus baseline | shift \| Rule C \| macro_f1 | +0.0506 | [+0.0010, +0.1003] | [-0.0215, +0.1230] | none |
| claude minus baseline | shift \| Rule C \| micro_f1 | +0.0661 | [+0.0223, +0.1118] | [+0.0016, +0.1323] | A higher |
| gemini minus baseline | test \| Rule A \| macro_f1 | +0.0926 | [+0.0618, +0.1250] | [+0.0466, +0.1432] | A higher |
| gemini minus baseline | test \| Rule A \| micro_f1 | +0.0847 | [+0.0600, +0.1091] | [+0.0484, +0.1208] | A higher |
| gemini minus baseline | shift \| Rule C \| macro_f1 | +0.1013 | [+0.0558, +0.1527] | [+0.0365, +0.1736] | A higher |
| gemini minus baseline | shift \| Rule C \| micro_f1 | +0.0817 | [+0.0373, +0.1267] | [+0.0173, +0.1460] | A higher |
| gemini minus claude | test \| Rule A \| macro_f1 | +0.0483 | [+0.0305, +0.0655] | [+0.0218, +0.0753] | A higher |
| gemini minus claude | test \| Rule A \| micro_f1 | +0.0350 | [+0.0202, +0.0498] | [+0.0140, +0.0571] | A higher |
| gemini minus claude | shift \| Rule C \| macro_f1 | +0.0508 | [+0.0184, +0.0838] | [+0.0018, +0.0966] | A higher |
| gemini minus claude | shift \| Rule C \| micro_f1 | +0.0155 | [-0.0101, +0.0439] | [-0.0203, +0.0577] | none |

| Pair | Scope and metric | Difference | 95% CI |
|---|---|---|---|
| claude minus baseline | test \| Rule A \| none_fp_rate | +0.0049 | [+0.0002, +0.0103] |
| claude minus baseline | test \| Rule A \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | test \| all \| macro_f1 | +0.0955 | [+0.0618, +0.1265] |
| claude minus baseline | test \| all \| micro_f1 | +0.0518 | [+0.0311, +0.0738] |
| claude minus baseline | test \| all \| none_fp_rate | +0.0049 | [+0.0002, +0.0103] |
| claude minus baseline | test \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | test \| Rule C \| macro_f1 | +0.0413 | [+0.0074, +0.0785] |
| claude minus baseline | test \| Rule C \| micro_f1 | +0.0451 | [+0.0222, +0.0691] |
| claude minus baseline | test \| Rule C \| none_fp_rate | +0.0049 | [+0.0002, +0.0103] |
| claude minus baseline | test \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift \| Rule C \| none_fp_rate | +0.0181 | [+0.0059, +0.0299] |
| claude minus baseline | shift \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift \| all \| macro_f1 | +0.0872 | [+0.0113, +0.1370] |
| claude minus baseline | shift \| all \| micro_f1 | +0.0805 | [+0.0359, +0.1227] |
| claude minus baseline | shift \| all \| none_fp_rate | +0.0181 | [+0.0059, +0.0299] |
| claude minus baseline | shift \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift:Franchise \| Rule C \| macro_f1 | +0.0511 | [+0.0011, +0.1115] |
| claude minus baseline | shift:Franchise \| Rule C \| micro_f1 | +0.0559 | [+0.0064, +0.1072] |
| claude minus baseline | shift:Franchise \| Rule C \| none_fp_rate | +0.0287 | [+0.0120, +0.0430] |
| claude minus baseline | shift:Franchise \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift:Franchise \| all \| macro_f1 | +0.1078 | [+0.0234, +0.1591] |
| claude minus baseline | shift:Franchise \| all \| micro_f1 | +0.0803 | [+0.0300, +0.1276] |
| claude minus baseline | shift:Franchise \| all \| none_fp_rate | +0.0287 | [+0.0120, +0.0430] |
| claude minus baseline | shift:Franchise \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift:Transportation \| Rule C \| macro_f1 | +0.0453 | [-0.0185, +0.1156] |
| claude minus baseline | shift:Transportation \| Rule C \| micro_f1 | +0.0913 | [-0.0055, +0.1750] |
| claude minus baseline | shift:Transportation \| Rule C \| none_fp_rate | +0.0046 | [-0.0062, +0.0171] |
| claude minus baseline | shift:Transportation \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| claude minus baseline | shift:Transportation \| all \| macro_f1 | +0.0939 | [-0.0254, +0.1424] |
| claude minus baseline | shift:Transportation \| all \| micro_f1 | +0.0860 | [-0.0138, +0.1661] |
| claude minus baseline | shift:Transportation \| all \| none_fp_rate | +0.0046 | [-0.0062, +0.0171] |
| claude minus baseline | shift:Transportation \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | test \| Rule A \| none_fp_rate | +0.0060 | [+0.0003, +0.0124] |
| gemini minus baseline | test \| Rule A \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | test \| all \| macro_f1 | +0.1318 | [+0.1023, +0.1569] |
| gemini minus baseline | test \| all \| micro_f1 | +0.0869 | [+0.0634, +0.1104] |
| gemini minus baseline | test \| all \| none_fp_rate | +0.0060 | [+0.0003, +0.0124] |
| gemini minus baseline | test \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | test \| Rule C \| macro_f1 | +0.0714 | [+0.0366, +0.1080] |
| gemini minus baseline | test \| Rule C \| micro_f1 | +0.0716 | [+0.0439, +0.0987] |
| gemini minus baseline | test \| Rule C \| none_fp_rate | +0.0060 | [+0.0003, +0.0124] |
| gemini minus baseline | test \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | shift \| Rule C \| none_fp_rate | +0.0157 | [+0.0072, +0.0247] |
| gemini minus baseline | shift \| Rule C \| parse_failure_rate | +0.0022 | [+0.0000, +0.0073] |
| gemini minus baseline | shift \| all \| macro_f1 | +0.1603 | [+0.0887, +0.2235] |
| gemini minus baseline | shift \| all \| micro_f1 | +0.1165 | [+0.0701, +0.1549] |
| gemini minus baseline | shift \| all \| none_fp_rate | +0.0157 | [+0.0072, +0.0247] |
| gemini minus baseline | shift \| all \| parse_failure_rate | +0.0022 | [+0.0000, +0.0073] |
| gemini minus baseline | shift:Franchise \| Rule C \| macro_f1 | +0.1165 | [+0.0630, +0.1871] |
| gemini minus baseline | shift:Franchise \| Rule C \| micro_f1 | +0.0696 | [+0.0133, +0.1261] |
| gemini minus baseline | shift:Franchise \| Rule C \| none_fp_rate | +0.0237 | [+0.0119, +0.0361] |
| gemini minus baseline | shift:Franchise \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | shift:Franchise \| all \| macro_f1 | +0.1867 | [+0.1065, +0.2500] |
| gemini minus baseline | shift:Franchise \| all \| micro_f1 | +0.1164 | [+0.0568, +0.1640] |
| gemini minus baseline | shift:Franchise \| all \| none_fp_rate | +0.0237 | [+0.0119, +0.0361] |
| gemini minus baseline | shift:Franchise \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus baseline | shift:Transportation \| Rule C \| macro_f1 | +0.0887 | [+0.0324, +0.1544] |
| gemini minus baseline | shift:Transportation \| Rule C \| micro_f1 | +0.1118 | [+0.0339, +0.1684] |
| gemini minus baseline | shift:Transportation \| Rule C \| none_fp_rate | +0.0053 | [-0.0014, +0.0140] |
| gemini minus baseline | shift:Transportation \| Rule C \| parse_failure_rate | +0.0053 | [+0.0000, +0.0171] |
| gemini minus baseline | shift:Transportation \| all \| macro_f1 | +0.1633 | [+0.0292, +0.2180] |
| gemini minus baseline | shift:Transportation \| all \| micro_f1 | +0.1182 | [+0.0471, +0.1696] |
| gemini minus baseline | shift:Transportation \| all \| none_fp_rate | +0.0053 | [-0.0014, +0.0140] |
| gemini minus baseline | shift:Transportation \| all \| parse_failure_rate | +0.0053 | [+0.0000, +0.0171] |
| gemini minus claude | test \| Rule A \| none_fp_rate | +0.0011 | [-0.0027, +0.0053] |
| gemini minus claude | test \| Rule A \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus claude | test \| all \| macro_f1 | +0.0363 | [+0.0151, +0.0568] |
| gemini minus claude | test \| all \| micro_f1 | +0.0351 | [+0.0209, +0.0489] |
| gemini minus claude | test \| all \| none_fp_rate | +0.0011 | [-0.0027, +0.0053] |
| gemini minus claude | test \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus claude | test \| Rule C \| macro_f1 | +0.0301 | [+0.0097, +0.0506] |
| gemini minus claude | test \| Rule C \| micro_f1 | +0.0265 | [+0.0092, +0.0433] |
| gemini minus claude | test \| Rule C \| none_fp_rate | +0.0011 | [-0.0027, +0.0053] |
| gemini minus claude | test \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus claude | shift \| Rule C \| none_fp_rate | -0.0024 | [-0.0088, +0.0049] |
| gemini minus claude | shift \| Rule C \| parse_failure_rate | +0.0022 | [+0.0000, +0.0073] |
| gemini minus claude | shift \| all \| macro_f1 | +0.0731 | [+0.0338, +0.1208] |
| gemini minus claude | shift \| all \| micro_f1 | +0.0360 | [+0.0113, +0.0615] |
| gemini minus claude | shift \| all \| none_fp_rate | -0.0024 | [-0.0088, +0.0049] |
| gemini minus claude | shift \| all \| parse_failure_rate | +0.0022 | [+0.0000, +0.0073] |
| gemini minus claude | shift:Franchise \| Rule C \| macro_f1 | +0.0654 | [+0.0297, +0.1047] |
| gemini minus claude | shift:Franchise \| Rule C \| micro_f1 | +0.0138 | [-0.0195, +0.0505] |
| gemini minus claude | shift:Franchise \| Rule C \| none_fp_rate | -0.0049 | [-0.0130, +0.0074] |
| gemini minus claude | shift:Franchise \| Rule C \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus claude | shift:Franchise \| all \| macro_f1 | +0.0789 | [+0.0133, +0.1368] |
| gemini minus claude | shift:Franchise \| all \| micro_f1 | +0.0361 | [+0.0045, +0.0666] |
| gemini minus claude | shift:Franchise \| all \| none_fp_rate | -0.0049 | [-0.0130, +0.0074] |
| gemini minus claude | shift:Franchise \| all \| parse_failure_rate | +0.0000 | [+0.0000, +0.0000] |
| gemini minus claude | shift:Transportation \| Rule C \| macro_f1 | +0.0434 | [-0.0171, +0.0925] |
| gemini minus claude | shift:Transportation \| Rule C \| micro_f1 | +0.0205 | [-0.0217, +0.0587] |
| gemini minus claude | shift:Transportation \| Rule C \| none_fp_rate | +0.0007 | [-0.0075, +0.0070] |
| gemini minus claude | shift:Transportation \| Rule C \| parse_failure_rate | +0.0053 | [+0.0000, +0.0171] |
| gemini minus claude | shift:Transportation \| all \| macro_f1 | +0.0694 | [+0.0178, +0.1155] |
| gemini minus claude | shift:Transportation \| all \| micro_f1 | +0.0322 | [-0.0093, +0.0746] |
| gemini minus claude | shift:Transportation \| all \| none_fp_rate | +0.0007 | [-0.0075, +0.0070] |
| gemini minus claude | shift:Transportation \| all \| parse_failure_rate | +0.0053 | [+0.0000, +0.0171] |

## Appendix: drift correlations (Step 5)
Spearman rank correlation of each drift statistic with each model's batch micro-F1 on Rule C labels; descriptive, no claims. Source: `data/eval/drift.json` via `python -m src.report`.

| Batches | Model | Statistic | Spearman |
|---|---|---|---|
| test | baseline | oov_rate_diff | -0.038 |
| test | baseline | tfidf_centroid_distance | +0.079 |
| test | baseline | length_psi | -0.102 |
| test | baseline | baseline:label_mix_js | +0.058 |
| test | baseline | baseline:none_share_diff | -0.005 |
| test | baseline | baseline:confidence_psi | +0.030 |
| test | baseline | claude:label_mix_js | +0.052 |
| test | baseline | claude:none_share_diff | +0.009 |
| test | baseline | claude:confidence_psi | +0.144 |
| test | baseline | gemini:label_mix_js | +0.051 |
| test | baseline | gemini:none_share_diff | -0.020 |
| test | baseline | gemini:confidence_psi | +0.142 |
| test | claude | oov_rate_diff | -0.021 |
| test | claude | tfidf_centroid_distance | -0.012 |
| test | claude | length_psi | -0.059 |
| test | claude | baseline:label_mix_js | +0.135 |
| test | claude | baseline:none_share_diff | +0.048 |
| test | claude | baseline:confidence_psi | +0.203 |
| test | claude | claude:label_mix_js | +0.124 |
| test | claude | claude:none_share_diff | +0.093 |
| test | claude | claude:confidence_psi | +0.286 |
| test | claude | gemini:label_mix_js | +0.186 |
| test | claude | gemini:none_share_diff | +0.078 |
| test | claude | gemini:confidence_psi | +0.338 |
| test | gemini | oov_rate_diff | -0.121 |
| test | gemini | tfidf_centroid_distance | -0.098 |
| test | gemini | length_psi | +0.003 |
| test | gemini | baseline:label_mix_js | +0.197 |
| test | gemini | baseline:none_share_diff | +0.109 |
| test | gemini | baseline:confidence_psi | +0.290 |
| test | gemini | claude:label_mix_js | +0.165 |
| test | gemini | claude:none_share_diff | +0.177 |
| test | gemini | claude:confidence_psi | +0.301 |
| test | gemini | gemini:label_mix_js | +0.192 |
| test | gemini | gemini:none_share_diff | +0.127 |
| test | gemini | gemini:confidence_psi | +0.368 |
| shift | baseline | oov_rate_diff | -0.045 |
| shift | baseline | tfidf_centroid_distance | +0.053 |
| shift | baseline | length_psi | +0.085 |
| shift | baseline | baseline:label_mix_js | -0.443 |
| shift | baseline | baseline:none_share_diff | -0.067 |
| shift | baseline | baseline:confidence_psi | -0.215 |
| shift | baseline | claude:label_mix_js | -0.091 |
| shift | baseline | claude:none_share_diff | +0.156 |
| shift | baseline | claude:confidence_psi | +0.074 |
| shift | baseline | gemini:label_mix_js | +0.146 |
| shift | baseline | gemini:none_share_diff | +0.157 |
| shift | baseline | gemini:confidence_psi | +0.200 |
| shift | claude | oov_rate_diff | +0.058 |
| shift | claude | tfidf_centroid_distance | -0.091 |
| shift | claude | length_psi | -0.013 |
| shift | claude | baseline:label_mix_js | -0.293 |
| shift | claude | baseline:none_share_diff | -0.087 |
| shift | claude | baseline:confidence_psi | -0.111 |
| shift | claude | claude:label_mix_js | -0.177 |
| shift | claude | claude:none_share_diff | +0.123 |
| shift | claude | claude:confidence_psi | +0.044 |
| shift | claude | gemini:label_mix_js | -0.015 |
| shift | claude | gemini:none_share_diff | +0.118 |
| shift | claude | gemini:confidence_psi | +0.162 |
| shift | gemini | oov_rate_diff | -0.119 |
| shift | gemini | tfidf_centroid_distance | +0.092 |
| shift | gemini | length_psi | +0.150 |
| shift | gemini | baseline:label_mix_js | -0.243 |
| shift | gemini | baseline:none_share_diff | -0.042 |
| shift | gemini | baseline:confidence_psi | +0.003 |
| shift | gemini | claude:label_mix_js | -0.115 |
| shift | gemini | claude:none_share_diff | +0.133 |
| shift | gemini | claude:confidence_psi | +0.075 |
| shift | gemini | gemini:label_mix_js | -0.129 |
| shift | gemini | gemini:none_share_diff | +0.150 |
| shift | gemini | gemini:confidence_psi | +0.203 |
| pooled | baseline | oov_rate_diff | +0.001 |
| pooled | baseline | tfidf_centroid_distance | -0.363 |
| pooled | baseline | length_psi | +0.157 |
| pooled | baseline | baseline:label_mix_js | -0.541 |
| pooled | baseline | baseline:none_share_diff | +0.020 |
| pooled | baseline | baseline:confidence_psi | +0.156 |
| pooled | baseline | claude:label_mix_js | -0.313 |
| pooled | baseline | claude:none_share_diff | +0.033 |
| pooled | baseline | claude:confidence_psi | +0.170 |
| pooled | baseline | gemini:label_mix_js | -0.170 |
| pooled | baseline | gemini:none_share_diff | +0.078 |
| pooled | baseline | gemini:confidence_psi | +0.426 |
| pooled | claude | oov_rate_diff | +0.035 |
| pooled | claude | tfidf_centroid_distance | -0.406 |
| pooled | claude | length_psi | +0.148 |
| pooled | claude | baseline:label_mix_js | -0.489 |
| pooled | claude | baseline:none_share_diff | +0.029 |
| pooled | claude | baseline:confidence_psi | +0.232 |
| pooled | claude | claude:label_mix_js | -0.315 |
| pooled | claude | claude:none_share_diff | +0.052 |
| pooled | claude | claude:confidence_psi | +0.203 |
| pooled | claude | gemini:label_mix_js | -0.169 |
| pooled | claude | gemini:none_share_diff | +0.100 |
| pooled | claude | gemini:confidence_psi | +0.465 |
| pooled | gemini | oov_rate_diff | -0.035 |
| pooled | gemini | tfidf_centroid_distance | -0.406 |
| pooled | gemini | length_psi | +0.207 |
| pooled | gemini | baseline:label_mix_js | -0.474 |
| pooled | gemini | baseline:none_share_diff | +0.056 |
| pooled | gemini | baseline:confidence_psi | +0.277 |
| pooled | gemini | claude:label_mix_js | -0.298 |
| pooled | gemini | claude:none_share_diff | +0.073 |
| pooled | gemini | claude:confidence_psi | +0.206 |
| pooled | gemini | gemini:label_mix_js | -0.199 |
| pooled | gemini | gemini:none_share_diff | +0.115 |
| pooled | gemini | gemini:confidence_psi | +0.480 |
