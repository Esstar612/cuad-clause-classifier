"""Step 9 sourcing rules, pre-registered in BUILD_LOG before the first EDGAR request."""

from __future__ import annotations

import re

from src import config

FRESH_DIR = config.DATA_DIR / "fresh"
TEXT_DIR = FRESH_DIR / "text"              # gitignored: contract text and raw HTML
RAW_DIR = TEXT_DIR / "raw"
LABELS_DIR = FRESH_DIR / "labels"          # label exports: offsets, categories, hashes, no text
GOLD_DIR = LABELS_DIR / "gold"
CANDIDATES = FRESH_DIR / "candidates.parquet"
LIST_REPORT = FRESH_DIR / "list_report.json"
CONTRACTS = FRESH_DIR / "contracts.parquet"
DRAW_LOG = FRESH_DIR / "draw_log.csv"
RULE_F = FRESH_DIR / "rule_f.json"
SEGMENTS = config.PROCESSED_DIR / "fresh_segments.parquet"   # gitignored: holds segment text
BUNDLE = config.ROOT_DIR / "tools" / "labeler" / "bundle.js"   # gitignored: holds contract text

# Training cutoffs, looked up 2026-10-04 on the providers' pages:
#   claude-sonnet-5: "Training data cutoff | Jan 2026",
#     https://platform.claude.com/docs/en/models/sonnet-5/overview
#   gemini-3.8-flash: knowledge cutoff March 2026,
#     https://deepmind.google/models/model-cards/gemini-3-8-flash/ (published September 2026)
#   deepseek-v4p1-flash: none published (Fireworks model page, DeepSeek API change log and release
#     note of 2026-09-10, Hugging Face model card)
FRAME_START = "2026-04-01"   # the day after the latest published cutoff (March 2026)
SLOTS = 30
CONTRACT_ID_START = 1000     # CUAD ids are 0 to 509
EXHIBIT_PREFIX = "EX-10"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{file_name}"
EFTS_PAGE = 100
EFTS_MAX_FROM = 9_900        # EFTS returns at most 10,000 hits per query
PRIOR_START = "2001-01-01"   # start of EFTS full-text coverage
EDGAR_MIN_INTERVAL_S = 0.2   # at most 5 requests per second (SEC allows 10)
EDGAR_MAX_ATTEMPTS = 5
EDGAR_TIMEOUT_S = 60.0

# One quoted-phrase query per CUAD contract type, and the description phrases that assign the type.
TYPES = {
    "Affiliate": ("affiliate agreement", ("affiliate agreement",)),
    "Agency": ("agency agreement", ("agency agreement",)),
    "Co-Branding": ("co-branding agreement", ("co-branding", "cobranding", "co-brand agreement")),
    "Collaboration/Cooperation": ("collaboration agreement", ("collaboration agreement", "cooperation agreement")),
    "Consulting": ("consulting agreement", ("consulting agreement",)),
    "Development": ("development agreement", ("development agreement",)),
    "Distributor": ("distribution agreement", ("distribution agreement", "distributor agreement",
                                               "distributorship agreement")),
    "Endorsement": ("endorsement agreement", ("endorsement agreement",)),
    "Hosting": ("hosting agreement", ("hosting agreement", "hosting services agreement")),
    "IP": ("intellectual property agreement", ("intellectual property agreement", "intellectual property assignment",
                                               "patent assignment", "patent purchase agreement")),
    "Joint Venture": ("joint venture agreement", ("joint venture agreement",)),
    "License": ("license agreement", ("license agreement", "licensing agreement")),
    "Maintenance": ("maintenance agreement", ("maintenance agreement", "maintenance and support agreement",
                                              "maintenance services agreement")),
    "Manufacturing": ("manufacturing agreement", ("manufacturing agreement", "manufacturing services agreement",
                                                  "contract manufacturing")),
    "Marketing": ("marketing agreement", ("marketing agreement", "marketing services agreement")),
    "Outsourcing": ("outsourcing agreement", ("outsourcing agreement",)),
    "Promotion": ("promotion agreement", ("promotion agreement", "promotional agreement")),
    "Reseller": ("reseller agreement", ("reseller agreement", "resale agreement")),
    "Service": ("services agreement", ("services agreement", "service agreement")),
    "Sponsorship": ("sponsorship agreement", ("sponsorship agreement",)),
    "Strategic Alliance": ("strategic alliance agreement", ("strategic alliance", "alliance agreement")),
    "Supply": ("supply agreement", ("supply agreement",)),
}

# Exclusions, all numeric
MIN_CHARS = 5_000
MAX_CHARS = 338_211          # CUAD's longest contract
AMENDMENT = re.compile(r"\bamendment\b|\bwaiver\b|\bjoinder\b|side letter")
AMENDMENT_HEAD_CHARS = 500
RESTATED = "amended and restated"
BLANK_PARTY = re.compile(r"_{5,}|\[●\]|\[Name")
BLANK_HEAD_CHARS = 3_000
BLANK_MAX = 2                # 3 or more markers: a form or template
REDACTION = re.compile(r"\[\*\*\*\]|\[\*\]|\*{3,}|\[REDACTED\]|\[Omitted\]", re.IGNORECASE)
REDACTION_MAX_PER_1000 = 1.0
SHINGLE_WORDS = 8
CUAD_OVERLAP_MAX = 0.20
DUPLICATE_MAX = 0.50
PRIOR_SENTENCES = 3          # the 3 longest sentences of 15 to 40 words; prior appearance if all 3 hit
PRIOR_MIN_WORDS = 15
PRIOR_MAX_WORDS = 40

GUIDE_VERSION = "1"
