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
BOOTSTRAP_RESAMPLES_COMPARE = 10_000   # paired comparisons (Step 4b): enough resamples for Bonferroni tails
COMPARE_PRIMARY_SCOPES = (("test", "Rule A"), ("shift", "Rule C"))
COMPARE_PRIMARY_METRICS = ("micro_f1", "macro_f1")
COMPARE_FAMILY_SIZE = 12               # 3 model pairs x 2 scopes x 2 metrics, pre-registered 2026-09-27
COMPARE_FAMILIES = {
    "4b": (("claude", "baseline"), ("gemini", "baseline"), ("gemini", "claude")),
    "6a": (("transformer", "baseline"), ("transformer", "claude"), ("transformer", "gemini")),
}
COMPARE_PAIRS = tuple(p for pairs in COMPARE_FAMILIES.values() for p in pairs)
assert all(len(p) * len(COMPARE_PRIMARY_SCOPES) * len(COMPARE_PRIMARY_METRICS) == COMPARE_FAMILY_SIZE
           for p in COMPARE_FAMILIES.values())
CALIBRATION_BINS = 10
ERROR_SAMPLES_PER_LABEL = 5  # per failing label and error kind, on validation only

# Drift monitoring (Step 5): unlabeled checks, thresholds from validation only
DRIFT_DIR = MODELS_DIR / "drift"
DRIFT_BATCH_CONTRACTS = 5
DRIFT_NULL_BATCHES = 2_000
DRIFT_EVAL_BATCHES = 1_000
DRIFT_BOOTSTRAP = 10_000          # about 31 resamples per 99.375% tail
DRIFT_BOOTSTRAP_BATCHES = 100
DRIFT_BOOTSTRAP_CHUNK = 250       # resamples per chunk: 25,000 batch rows at a time
DRIFT_ALARM_QUANTILE = 0.99
DRIFT_MODELS = ("baseline", "claude", "gemini")
DRIFT_PRIMARY_SETS = ("shift:Franchise", "shift:Transportation")

# Human-readable split file (tracked in git)
SPLITS_CSV = DATA_DIR / "splits" / "contract_splits.csv"

# LLM classifiers (Step 3). Prices are USD per 1M tokens. Gemini prices are the paid tier,
# Standard, confirmed by the user on ai.google.dev/gemini-api/docs/pricing (page dated
# 2026-09-24). They hold through 2026-12-31 and double on 2027-01-01 (1.50 / 7.50 / 0.15):
# any Gemini run after 2026 needs these updated.
LLM_MODELS = {
    "claude": {"provider": "anthropic", "model_id": "claude-sonnet-5",
               "price_in": 2.00, "price_out": 10.00, "price_cache_read": 0.20,
               "price_cache_write": 2.50, "effort": "low", "max_tokens": 8000},
    "gemini": {"provider": "google", "model_id": "gemini-3.8-flash",
               "price_in": 0.75, "price_out": 3.75, "price_cache_read": 0.075,
               "price_cache_write": 0.0, "thinking_level": "low", "max_tokens": 8000},
}
LLM_WINDOW_SIZE = 10             # fixed context window; batch size is 10 (whole window) or 1
LLM_CONFIDENCE_FLOOR = 0.1       # models list every label with confidence >= this; others score 0
LLM_ITERATION_MIN_SEGMENTS = 1500
LLM_ITERATION_CONTRACTS = PROCESSED_DIR / "llm_iteration_contracts.csv"
LLM_N1_CONTRACTS = PROCESSED_DIR / "llm_n1_contracts.csv"
LLM_ITERATION_DIR = PREDICTIONS_DIR / "iteration"
LLM_THIN_LABEL_SEGMENTS = 5      # iteration-sample labels below this are "too thin to judge"
LLM_MAX_PROMPT_VERSIONS = 5
LLM_PROBE_WINDOWS = 24           # Step 3i diagnostic probe: failing v1 windows sampled (stream "probe")
LLM_HEALTH_MAX_SHARE = 0.05       # validation or held-out run above this below-floor share is redone once (BUILD_LOG 3n, 3af)
LLM_V4_STOP_OUTPUT_TOKENS = 6000  # Rule E v4 gate: a smoke call above this excludes the model
LLM_V4_STOP_LATENCY_S = 90.0      # Rule E v4 gate: a smoke call slower than this excludes the model
LLM_REPEAT_WINDOWS = 30          # repeat check: first 30 windows of the iteration sample
LLM_REPEAT_RUNS = 2              # extra cache-bypassed runs, on top of the original
LLM_BUDGET_USD = 150.0           # hard cap across all LLM runs, enforced from the ledger
LLM_SOFT_CHECKPOINT_USD = 100.0  # a phase that would pass this total needs --past-checkpoint (Rule E)
LLM_LEDGER = LLM_CACHE_DIR / "ledger.jsonl"
LLM_WORKERS = 4
LLM_RPM = 50                     # request starts per minute, per model
LLM_MAX_ATTEMPTS = 8             # transport retries (429, 5xx, timeouts, connection errors)
LLM_TIMEOUT_S = 120.0
# Offline estimate assumptions (replaced by measured tokens after the smoke test)
LLM_EST_CHARS_PER_TOKEN = 4.0
LLM_EST_OUTPUT_TOKENS_PER_TARGET = 25
LLM_EST_THINKING_TOKENS_PER_CALL = 300

# Fine-tuned transformer (Step 6a): one fixed recipe, three encoders, selection on validation
TRANSFORMER_DIR = MODELS_DIR / "transformer"
TRANSFORMER_ENCODERS = {"legal-bert": "nlpaueb/legal-bert-base-uncased",
                        "bert": "google-bert/bert-base-uncased",
                        "deberta-v3": "microsoft/deberta-v3-base"}
TRANSFORMER_DOMAIN_PAIR = ("legal-bert", "bert")
TRANSFORMER_MAX_TOKENS = 512
TRANSFORMER_EPOCHS = 3
TRANSFORMER_BATCH_SIZE = 16          # effective batch
TRANSFORMER_ACCUMULATION = 1         # the pre-registered OOM fallback sets 2 (micro-batch 8)
TRANSFORMER_LR = 2e-5
TRANSFORMER_WEIGHT_DECAY = 0.01      # on every parameter
TRANSFORMER_WARMUP = 0.10
TRANSFORMER_INFER_BATCH = 64
TRANSFORMER_PROBE_SEGMENTS = 1_024   # seeded subset of train segments, timing only
TRANSFORMER_SIZE_TOLERANCE = 0.01    # encoder parameters within 1% count as the same size
