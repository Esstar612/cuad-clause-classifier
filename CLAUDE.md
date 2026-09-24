# CLAUDE.md

Contract clause classifier on the CUAD dataset (commercial contracts labeled by lawyers). Portfolio project for a data scientist application at an AI-native law firm. Rigor and honest evaluation matter more than flashy results.

## Working rules

### Process
- Plan mode first. Show the plan, then wait for approval before editing.
- Claude handles mechanical work directly: scaffolding, config, boilerplate, file moves, docs.
- For core logic (data splitting, feature pipeline, model training, prompts, metrics, bootstrap, drift checks, rate limiting), Claude shows the code with a short explanation. The user decides whether to place it themselves or have Claude place it.

### Execution
- Never run tests, training, or evaluation scripts. Give the exact command; the user runs it and pastes the output back.

### Honesty in numbers
- Never invent numbers. Every figure in any doc must come from output the user pasted.

### Evaluation discipline
- The test set is touched once per model, at the end.
- All tuning, prompt iteration, and threshold choices happen on validation only.

### Reproducibility
- Every source of randomness (splits, sampling, bootstrap, model training) uses a fixed seed from `src/config.py`. No hardcoded seeds elsewhere.
- Dependencies are declared only in `pyproject.toml`. `requirements.txt` is a generated lock file with pinned versions and is never edited by hand. Whenever a dependency is added, it goes in `pyproject.toml` and the lock file gets regenerated.

### Writing and git
- No em dashes in any writing.
- Commit messages carry no AI attribution.

## Logging
- After every completed step, append a dated entry to `BUILD_LOG.md` using the template at the top of that file.
- Ambiguous labeling cases go in `docs/labeling_schema.md`.
- Final result tables go in `docs/results.md`, using only pasted figures.

## Layout
- `data/` raw and processed data (`data/raw/` is gitignored)
- `src/` library code; `src/config.py` holds the seed and paths
- `notebooks/` exploration
- `service/` FastAPI app
- `tests/` pytest suite
- `docs/` labeling schema, results, and `plan.md` (roadmap and shared prediction format)
