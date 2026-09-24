"""Single source of truth for the random seed and project paths."""

from pathlib import Path

# Every source of randomness (splits, sampling, bootstrap, model training) uses this.
SEED = 42

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LLM_CACHE_DIR = DATA_DIR / "llm_cache"
DOCS_DIR = ROOT_DIR / "docs"

# CUAD v1 (CC BY 4.0), Zenodo DOI 10.5281/zenodo.4595826
CUAD_ZIP_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip?download=1"
CUAD_DIR = RAW_DIR / "CUAD_v1"
CUAD_JSON = CUAD_DIR / "CUAD_v1.json"
CUAD_TXT_DIR = CUAD_DIR / "full_contract_txt"
CUAD_PDF_DIR = CUAD_DIR / "full_contract_pdf"
CUAD_MASTER_CSV = CUAD_DIR / "master_clauses.csv"

# Shift types never enter train, val, or test.
SHIFT_TYPES = ("Franchise", "Transportation")
SPLIT_FRACTIONS = (0.6, 0.2, 0.2)

# Segmentation (frozen 2026-09-23 from train-only stats, data/processed/segment_stats.txt).
# max_chars is not a hard cap: a piece shorter than min_chars (e.g. a heading) is folded
# into the next segment and can push it past max_chars.
SEGMENT_MIN_CHARS = 50
SEGMENT_MAX_CHARS = 1500
SEGMENT_MIN_COVERAGE = 0.5

# Pre-registered evaluation rules (fixed 2026-09-23, before any model output existed).
PER_LABEL_MIN_TEST_CONTRACTS = 10   # main test table; lower-support labels go to the appendix
PER_LABEL_MIN_SHIFT_CONTRACTS = 10  # per-label shift results
PER_CLASS_THRESHOLD_MIN_VAL_CONTRACTS = 10  # below this, labels share one pooled threshold

# Model artifacts and predictions
PREDICTIONS_DIR = DATA_DIR / "predictions"
MODELS_DIR = ROOT_DIR / "models"
BASELINE_DIR = MODELS_DIR / "baseline"

# Rule B threshold grid, shared by every model
THRESHOLD_GRID_STEP = 0.01

# Baseline search (Step 2). Selection by validation macro-AP; ties within
# BASELINE_SELECTION_TIE go to higher macro-F1, then the simpler configuration.
BASELINE_NGRAM_RANGES = ((1, 1), (1, 2))
BASELINE_CLASS_WEIGHTS = (None, "balanced")
BASELINE_C_VALUES = (0.25, 1.0, 4.0, 16.0, 32.0, 64.0)  # 32, 64 added in round 2 (edge extension)
BASELINE_NONE_RATIOS = (1, 3, 5, None)  # none:positive in train; None keeps every none segment
BASELINE_SELECTION_TIE = 0.005
LATENCY_SAMPLE_SIZE = 200  # validation segments timed one call at a time

# Evaluation harness (Step 4a)
EVAL_DIR = DATA_DIR / "eval"
BOOTSTRAP_RESAMPLES = 2000  # contract-level, stratified by contract type; percentile intervals
CI_LEVEL = 0.95
CALIBRATION_BINS = 10
ERROR_SAMPLES_PER_LABEL = 5  # per failing label and error kind, on validation only
