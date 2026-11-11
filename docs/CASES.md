# Long-tier cases: adding your own

A case is a folder under `suites/` and one entry in a registry: `suites/cases.json` (shipped) or
`suites/cases.local.json` (yours; not exported). `long.sh <model> <case>` copies the case's working folder into
`runs/<model>/long/<case>/work/`, gives the agent the prompt, locks `suites/` while the agent runs, then runs the grader.
`suites/examples/e01_rk4_time` is a complete small example.

## Folder
```
suites/mine/my_case/
  PROMPT.md            the task; <TEST_DIR> is replaced with the run's work folder
  repo/                what the agent gets a copy of (any name; "copy" in the registry)
  grader/grade.py      scores the agent's copy (any command; "grade" in the registry)
  RUBRIC.md            optional: scoring guide for the judge (goes into the judge packet)
  solution/reference.patch   optional: the answer, for the judge packet
```
Only the copied folder reaches the agent. Keep answers, graders and rubrics outside it.

## Registry entry
```json
"m01": {"title": "my case", "src": "mine/my_case", "copy": "repo", "cwd": "repo",
        "grade": "{python} {src}/grader/grade.py --workspace {cwd}", "peek": "my-private-repo-name"}
```
| Field | Meaning |
|---|---|
| `src` | the case folder, relative to `suites/` |
| `copy` | the subfolder copied to `work/<copy>` |
| `cwd` | where the agent starts, relative to `work/` (`""` = `work/` itself); default `copy` |
| `prompt` | the prompt file in `src`; default `PROMPT.md` |
| `grade` | shell command; `{python}` (the grader Python), `{suites}`, `{src}` (absolute), `{cwd}` (the agent's folder) and `{run}` (the run folder) are filled in |
| `peek` | optional regex: tool calls matching it are listed in `logs/peek.txt` (e.g. the name of the repo the case came from) |

## Grader output
The grader's output goes to `logs/grade.txt`, and `long.sh` reads one JSON object from it: everything from the first
`{` to the last `}`. So print a single JSON object, and nothing else that contains braces:
```json
{"score": 80, "maximum": 100, "partial": false, "checks": [{"name": "...", "ok": true, "points": 20, "max": 20}]}
```
`partial: true` means "the automatic score is a sanity check; a judge should score the rest" (shown as
`judge_needed` in `results.jsonl`). Grade the agent's copy without modifying it; run things in a temporary copy.
