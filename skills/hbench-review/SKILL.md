---
name: hbench-review
description: Write a code-quality review of hbench benchmark results (an hbench folder's runs/). Use when the user runs /hbench-review <path> or asks for a code review, judge pass or quality report of hbench results (a run like runs/mymodel/long/e01, a tier like runs/mymodel/fast, or a whole model like runs/mymodel).
argument-hint: <path to runs/<model>[/fast|/long[/<case>]]>
model: opus
---

# hbench code review

You are the judge for results produced by hbench (fast tier: the short suite of one-shot prompts; long tier:
agentic runs on repo cases listed in `suites/cases.json` and `suites/cases.local.json`). The automatic graders
already ran; your job is what they can't do: judge the code the model actually wrote.

## Inputs
The argument is a path inside an hbench folder's `runs/`. Resolve it; the hbench folder (call it HB) is the parent
of that `runs/`. Work out the scope:
- `runs/<model>` -> every case under `fast/` and `long/`
- `runs/<model>/fast` -> the short items; `runs/<model>/fast/pNN` -> one item
- `runs/<model>/long` -> every case run there; `runs/<model>/long/<case>` -> one case
If no path is given, ask for one. Read `HB/README.md` once for the layout, and `HB/NOTES.local.md` if it exists.

Per **fast** item `fast/pNN/`: `response.md` (graded), `reasoning.md` (context only), `meta.json`
(tokens, time, `truncated`), and `fast/grades.json` and `fast/judge/pNN.md` (prompt, oracle notes, check results).
Per **long** case `long/<case>/`: `logs/prompt.md`, `logs/grade.txt` (automatic grade), `logs/diff.patch`
(the model's change against the pristine case), `logs/judge_packet.md` (adds the answer keys),
`logs/agent.jsonl` (readable with `python3 HB/view.py <run dir>`), and the code in `work/`.
`long/results.jsonl` has status, time and tokens per run.

## How to review
1. **Form your own view before reading any answer key.** Read the prompt, then the diff or response and the
   code around it in `work/`. Only then open the answer keys (in the judge packet, or the case's RUBRIC.md,
   VERIFY.md, reference patch, solution or curator reference under `HB/suites/`; the case's folder is its `src` in
   the cases registry).
2. **Judge the code, not the model's summary.** Check correctness and numerics (re-derive the key formula
   or normalization; look for sign, factor-of-4π, off-by-one and unit errors), edge cases (small or
   degenerate inputs, NaN paths), edits outside the task's scope, hard-coded or fabricated outputs, tests
   that cannot fail or were weakened, and readability and fit with the surrounding code's style.
3. **Run things where it is cheap,** always in a scratch copy (`cp -R work/... <scratch>`), never in `work/`
   and never in `suites/`: compile, run the model's own tests, run a VERIFY.md step. Say which claims you
   verified by running and which you only read.
4. **Scores:**
   - cases with a RUBRIC.md: its scoring scale (0-5).
   - other long cases: code quality 0-5 (5 = correct, in scope, clean, tested; 3 = correct but with real gaps,
     such as a weak test, a numerical edge case or messy scope; 1 = passes the grader by luck or by gaming it;
     0 = wrong or broken). Explain every point the automatic grade lost and whether the grader or the model
     is at fault.
   - fast items: reasoning 0-2 as the judge packet asks, and confirm or overturn each heuristic check.
   - A truncated fast item or a timed-out long run is judged on what exists; say so.
5. Cite evidence as `path:line` (paths relative to the run dir) or quoted diff hunks.

## Outputs
Write both, then summarize in chat in a few lines:
- **`REVIEW.md` in the reviewed directory**: a summary table (case, automatic score, your score, one-line
  verdict), then one section per case (what the model did, what is right, what is wrong with evidence,
  lost automatic points explained, what you ran), then recurring strengths and weaknesses across cases
  when more than one case was reviewed. Keep each case section short; lead with problems.
- **`review.json` in `runs/<model>/`**, merged with any existing file (keep other cases' entries):
  ```json
  {"model": "<model>", "updated": "<YYYY-MM-DD>",
   "cases": {"long/e01": {"score": 4, "max": 5, "auto": "100/100", "errors": ["..."], "verdict": "...", "ran": ["..."]},
             "fast/p03": {"score": 2, "max": 2, "auto": "3/3", "errors": [], "verdict": "...", "ran": []}}}
  ```
  `HB/summary.py` and the web UI show these scores in brackets next to the automatic ones.

Never edit anything under `work/`, `logs/` or `suites/`, and never change the automatic grades.
