"""Markdown tables for docs/results.md, generated from saved evaluation JSON only (Step 4b).

  python -m src.report | tee data/processed/results_tables.md

Reads data/eval/{baseline,claude,gemini}.json and the three cross-model compare files by name.
Composes no claims: claims and verdicts come from the compare files.
"""

from __future__ import annotations

import json
from pathlib import Path

from src import config

MODELS = ("baseline", "claude", "gemini")
SPARSE_NOTE = "sparse lower bound, not interpreted"
LEVEL = f"{config.CI_LEVEL:.0%}"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _cell(d: dict) -> str:
    return f"{d['point']:.4f} [{d['ci_low']:.4f}, {d['ci_high']:.4f}]"


def _diff(d: dict, lo: str = "ci_low", hi: str = "ci_high") -> str:
    return f"[{d[lo]:+.4f}, {d[hi]:+.4f}]"


def _same(values, what: str):
    values = list(values)
    if any(v != values[0] for v in values):
        raise SystemExit(f"{what} differs between files: {values}")
    return values[0]


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(lines)


def scope_tables(evals: dict) -> str:
    out = []
    scopes = _same((list(evals[m]["scopes"]) for m in MODELS), "scope list")
    labels = {s: " / ".join(str(evals[m]["scopes"][s]["n_labels"]) for m in MODELS) for s in scopes}
    for metric in ("micro_f1", "macro_f1", "none_fp_rate", "parse_failure_rate"):
        rows = [[scope, labels[scope]] + [_cell(evals[m]["scopes"][scope][metric]) for m in MODELS]
                for scope in scopes]
        out.append(f"#### {metric} by scope, point [{LEVEL} CI]\n\n"
                   + _table(["Scope", "Labels with defined F1 (" + " / ".join(MODELS) + ")"] + list(MODELS), rows))
    rows = [[scope] + [_cell(evals[m]["scopes"][scope]["macro_ap"])
                       + (f" ({SPARSE_NOTE})" if evals[m].get("sparse_scores") else "") for m in MODELS]
            for scope in scopes]
    out.append("#### macro_ap by scope (values marked sparse are lower bounds, Rule D; not compared)\n\n"
               + _table(["Scope"] + list(MODELS), rows))
    return "\n\n".join(out)


def comparison_tables(compares: dict) -> str:
    primary, verdicts, secondary = [], [], []
    for (a, b), c in compares.items():
        for key, d in c["differences"].items():
            row = [f"{a} minus {b}", key, f"{d['difference']:+.4f}", _diff(d)]
            if d.get("primary"):
                primary.append(row + [_diff(d, "adjusted_ci_low", "adjusted_ci_high"), d["claim"]])
            else:
                secondary.append(row)
        verdicts += [[f"{a} vs {b}", scope, v] for scope, v in c["verdicts"].items()]
    family = _same((c["family_size"] for c in compares.values()), "family size")
    adj = _same((d["adjusted_level"] for c in compares.values() for d in c["differences"].values()
                 if d.get("primary")), "adjusted level")
    return "\n\n".join([
        f"#### Primary comparisons (family of {family}; claims use the {adj:.3%} "
        "Bonferroni-adjusted interval)\n\n"
        + _table(["Pair", "Scope and metric", "Difference", f"{LEVEL} CI", "Adjusted CI", "Claim"], primary),
        "#### Verdicts, per scope\n\n" + _table(["Pair", "Scope", "Verdict"], verdicts),
        f"#### Secondary differences ({LEVEL} CI, reported, no claims)\n\n"
        + _table(["Pair", "Scope and metric", "Difference", f"{LEVEL} CI"], secondary)])


def per_label_tables(evals: dict) -> str:
    out = []
    for field, title, keep in (("per_label_test", "Per-label test F1, Rule A labels", lambda r: r["main_table"]),
                               ("per_label_shift_rule_c", "Per-label shift F1, Rule C labels", lambda r: True)):
        base = [r for r in evals["baseline"][field] if keep(r)]
        by_model = {m: {r["label"]: r for r in evals[m][field]} for m in MODELS}
        rows = [[r["label"], str(r["contracts"]), str(r["segments"])]
                + [_cell(by_model[m][r["label"]]["f1"]) for m in MODELS]
                for r in sorted(base, key=lambda r: -r["contracts"])]
        out.append(f"#### {title}, point [{LEVEL} CI]\n\n"
                   + _table(["Label", "Contracts", "Segments"] + list(MODELS), rows))
    return "\n\n".join(out)


def calibration_tables(evals: dict) -> str:
    rel = {m: evals[m]["calibration_test"]["reliability"] for m in MODELS}
    bins = _same(([b["bin"] for b in rel[m]] for m in MODELS), "calibration bins")
    rows = []
    for i, name in enumerate(bins):
        cells = []
        for m in MODELS:
            b = rel[m][i]
            cells.append(f"{b['count']:,}: {b['mean_predicted']:.4f} vs {b['observed_rate']:.4f}")
        rows.append([name] + cells)
    ece = [[f"Share of pairs in {bins[0]}"]
           + [f"{rel[m][0]['count'] / sum(b['count'] for b in rel[m]):.2%}" for m in MODELS],
           [f"Pooled ECE, point [{LEVEL} CI]"] + [_cell(evals[m]["calibration_test"]["pooled_ece"]) for m in MODELS]]
    return ("#### Calibration on test: pairs, mean predicted vs observed rate, per bin\n\n"
            + _table(["Bin"] + list(MODELS), rows + ece))


def check_versions(evals: dict, compares: dict) -> None:
    for (a, b), c in compares.items():
        for name, key in ((a, "a_version"), (b, "b_version")):
            if c.get(key) != evals[name]["model_version"]:
                raise SystemExit(f"compare_{a}_vs_{b}.json was made from {name} version {c.get(key)!r}, "
                                 f"but {name}.json is version {evals[name]['model_version']!r}; rerun the compare")


def drift_tables(drift: dict, evals: dict) -> str:
    for m, v in drift["versions"].items():
        if evals[m]["model_version"] != v:
            raise SystemExit(f"drift.json was made from {m} version {v!r}, but {m}.json is version "
                             f"{evals[m]['model_version']!r}; rerun the drift evaluation")
    sets = list(drift["sets"])
    fams = list(drift["sets"]["test"]["ci_adjusted"])
    stats = [g for g in drift["sets"]["test"]["point"] if g not in fams]
    adj = f"{drift['adjusted_level']:.3%}"
    fam_rows = [[f, key, f"{drift['sets'][key]['point'][f]:.4f}", f"[{drift['sets'][key]['ci95'][f][0]:.4f}, "
                 f"{drift['sets'][key]['ci95'][f][1]:.4f}]",
                 "[{:.4f}, {:.4f}]".format(*drift["sets"][key]["ci_adjusted"][f])] for f in fams for key in sets]
    rule_rows = [[c["family"], c["set"], f"{c['lower']:.4f}", f"{c['test_upper']:.4f}",
                  "yes" if c["detects"] else "no"] for c in drift["rule"]]
    stat_rows = [[st] + [f"{drift['sets'][key]['point'][st]:.4f}" for key in sets] for st in stats]
    mean_rows = [[st] + [f"{drift['sets'][key]['mean_value'][st]:.4f} ({drift['sets'][key]['nan_batches'][st]})"
                         for key in sets] for st in stats]
    pf_rows = [[m] + [f"{drift['sets'][key]['parse_failure_batches'][m]:.4f}" for key in sets]
               for m in drift["versions"]]
    corr_rows = [[name, m, st, f"{v:+.3f}"] for name, by_model in drift["degradation"].items()
                 for m, by_stat in by_model.items() for st, v in by_stat.items()]
    return "\n\n".join([
        f"#### Family alarm rate by set, point [{LEVEL} CI] [{adj} adjusted CI]\n\n"
        + _table(["Family", "Set", "Alarm rate", f"{LEVEL} CI", "Adjusted CI"], fam_rows),
        f"#### Pre-registered rule: a family detects a shift type when its adjusted lower bound exceeds "
        f"its adjusted upper bound on test ({adj})\n\n"
        + _table(["Family", "Shift type", "Adjusted lower bound", "Test adjusted upper bound", "Detects"],
                 rule_rows),
        "#### Per-statistic alarm rate by set (point, no claims)\n\n" + _table(["Statistic"] + sets, stat_rows),
        "#### Mean statistic value by set (NaN batches in parentheses)\n\n" + _table(["Statistic"] + sets, mean_rows),
        "#### Share of batches with a parse failure (operational counter, not calibrated)\n\n"
        + _table(["Model"] + sets, pf_rows),
        "#### Spearman correlation with batch micro-F1, Rule C labels (descriptive)\n\n"
        + _table(["Batches", "Model", "Statistic", "Spearman"], corr_rows)])


def render(eval_dir: Path = config.EVAL_DIR) -> str:
    evals = {m: _load(eval_dir / f"{m}.json") for m in MODELS}
    compares = {(a, b): _load(eval_dir / f"compare_{a}_vs_{b}.json") for a, b in config.COMPARE_PAIRS}
    check_versions(evals, compares)
    methods = [evals[m]["method"] for m in MODELS] + [c["method"] for c in compares.values()]
    if not all(f"percentile {LEVEL} intervals" in m for m in methods):
        raise SystemExit(f"a method string does not state percentile {LEVEL} intervals: {methods}")
    header = (f"Generated by `python -m src.report` from data/eval. Model intervals: "
              f"{_same((evals[m]['method'] for m in MODELS), 'model method')}. Paired comparisons: "
              f"{_same((c['method'] for c in compares.values()), 'compare method')}.")
    parts = [header, "### Scopes", scope_tables(evals), "### Model comparisons",
             comparison_tables(compares), "### Per-label", per_label_tables(evals),
             "### Calibration", calibration_tables(evals)]
    if (eval_dir / "drift.json").exists():
        parts += ["### Drift monitoring", drift_tables(_load(eval_dir / "drift.json"), evals)]
    return "\n\n".join(parts)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
