# Results

All figures come from pasted script output. Each table cites the command and output file that produced it. Test set figures are from a single, final evaluation per model.

## Setup
<!-- Data version, split sizes, seed, label set. -->

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

Source: `python -m src.baseline search | tee data/processed/baseline_search.txt` (round 2 of 2, 96 configurations; stopping rule triggered at C=64, reported as an edge result). The round 1 choice (C=16, none 5:1, version 7253e7a8662b, macro-AP 0.5598) was superseded.

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

## Confidence intervals
- Method: 2000 contract-level bootstrap resamples, stratified by contract type, percentile 95% intervals, seed 42.
- Resampling unit: the contract; within each contract type, as many contracts as the type has are drawn with replacement. Resamples depend only on the seed, a stream name (test, shift, shift:Franchise, shift:Transportation), and the contract ids and types, so every model evaluated later sees identical resamples (paired comparisons).
- F1, micro-F1, and none FP rate are recomputed from contract-weighted counts; AP uses scikit-learn with each segment weighted by its contract's draw count.
- A label with no support in a resample is left out of that resample's macro average; the "Resamples with support" column in the appendix shows how many of the 2000 resamples each per-label interval rests on.
- Test and shift intervals come from independent bootstraps; the test-minus-shift interval subtracts their resample distributions.
- Sanity check: `python -m src.evaluate compare baseline baseline` gave every difference and interval bound exactly 0 (`data/processed/eval_compare_self.txt`).
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
