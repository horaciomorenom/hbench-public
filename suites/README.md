# Suites

| Folder | Tier | What | Grading |
|---|---|---|---|
| `short/` | fast | 10 one-shot prompts: plotting code, numerics, a derive-and-implement, a bug hunt | 29 automatic checks (`short/oracles.py`) + judge packets |
| `latex/` | latex | 12 one-shot LaTeX tasks: tables, math, repairs, TikZ, pgfplots | 137 automatic checks on the compiled PDF (`latex/oracles.py`) + judge packets |
| `examples/e01_rk4_time/` | long | a small Python repo with one planted RK4 bug: find it, fix it, add a test that catches it | automatic, 100 points (`grader/grade.py`) + rubric |

`cases.json` lists the long-tier cases; add your own in `cases.local.json` (not shared), see `docs/CASES.md`.
These suites are examples: `docs/TESTS.md` explains how to add items, cases and whole tiers of your own.

Keep the answers away from the model: `short/curator/` and `latex/curator/` (reference answers), each case's `grader/`, `solution/` and
`RUBRIC.md`. The scripts only hand the model the prompt or a copy of the case's working folder, and `long.sh` locks
`suites/` while an agent runs.
