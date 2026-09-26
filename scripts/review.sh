#!/usr/bin/env bash
# Read-only Cursor review of a diff against the project rules.
# Usage: scripts/review.sh [BASE] [PATH...]   (BASE defaults to HEAD: uncommitted changes)
set -euo pipefail

# Pinned to a non-Claude model so code review adds a perspective the Claude builder and plan reviewer lack.
REVIEW_MODEL="gpt-5.6-sol-high"
cd "$(git rev-parse --show-toplevel)"
base="${1:-HEAD}"
[ $# -gt 0 ] && shift
paths=("$@")
[ ${#paths[@]} -eq 0 ] && paths=(src tests scripts docs CLAUDE.md)

diff_file="$(mktemp -t cursor-review).diff"
git diff "$base" -- "${paths[@]}" > "$diff_file"
while IFS= read -r f; do
  git diff --no-index /dev/null "$f" >> "$diff_file" || true
done < <(git ls-files --others --exclude-standard -- "${paths[@]}")
if [ ! -s "$diff_file" ]; then
  echo "Nothing to review against $base."
  exit 0
fi
echo "Reviewing $(grep -c '^diff --git' "$diff_file") changed files against $base with $REVIEW_MODEL ..."

cursor-agent -p --mode ask --trust --model "$REVIEW_MODEL" --output-format text "You are reviewing a change to a contract clause classifier built on the CUAD dataset. This is a review only: do not edit any file and do not run commands that change anything.

Read the diff at $diff_file, then read CLAUDE.md and whichever files the diff touches.

Report findings most severe first, as a numbered list. For each: file:line, the problem in one sentence, and a concrete failure scenario (inputs or state leading to a wrong result or crash).

Look for:
1. Correctness bugs.
2. Violations of the project rules in CLAUDE.md, especially: every source of randomness uses the seed in src/config.py; the test set is touched once per model; tuning, prompt choices and thresholds use validation data only; no leakage between train, validation, test and the shift set; no invented numbers in docs; no em dashes; comments only where the reason is not obvious.
3. New behaviour without a test.

Do not report style preferences or restate what the code does. If there are no correctness findings, write exactly: No findings.

After all correctness findings, add a final section titled \"Simplification (optional)\":
- At most 3 items: redundant code, duplicated logic, or functions that can be made shorter or clearer without changing behavior.
- Never suggest changes to anything that affects results or cache keys (prompt text and prompt construction, request payloads, schemas, splits, seeds, bootstrap, metrics, thresholds) unless the change comes with a test proving identical output.
- Skip pure speed optimizations unless the code is in a hot path that matters for run time.
- If nothing is worth changing, write: none.
These items never block an approval."
