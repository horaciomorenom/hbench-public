# Building your own tests

hbench ships three small suites as working examples. Keep them, change them, or replace them with your own subject.
There are three ways to add tests, from least to most work:

| You want | Do | Work |
|---|---|---|
| an agent to fix or build something in a repo | add a **long-tier case** | a folder and one registry line; no hbench code changes |
| one more one-shot prompt | add an **item** to `suites/short` or `suites/latex` | a prompt, an oracle function, a reference answer |
| a new subject with its own grader | add a **one-shot tier** | copy a suite and wire its name in five places |

Whatever you add, write three things together: the **prompt**, a **reference answer** that should get full marks,
and a **negative control** (a plausible wrong answer) that should lose points. A check that the negative control
passes is not checking anything. The selftests run both.

## 1. A long-tier case (agentic)
The easiest way to add a test, and the one that needs no changes to hbench. A case is a folder with a prompt, a
working folder the agent gets a copy of, and a grader that prints one JSON object with a score. Register it in
`suites/cases.local.json` (private to you) or `suites/cases.json` (shared). It then shows up in the web UI's Launch
page and in `./long.sh <model> <case>`.

[CASES.md](CASES.md) has the folder layout, the registry fields and the grader's output format.
`suites/examples/e01_rk4_time/` is a complete case in about 150 lines; copy it and edit.

Check it before running a model on it:
```bash
python3 suites/mine/my_case/grader/grade.py --workspace suites/mine/my_case/repo   # the untouched repo: low score
# apply your reference solution to a temporary copy and grade that: full score
```

## 2. An item in an existing one-shot suite
One-shot items are a prompt sent once through the API; the grader works on the reply.

**`suites/latex`** (grader is stdlib only): add `prompts/lNN.md`, an entry in `items.json`, a function in
`oracles.py` listed in `ITEMS`, a reference in `curator/reference/lNN.md` and a negative control in
`curator/negative/lNN.md`.

**`suites/short`** (grader runs the model's Python): add `prompts/pNN.md`, an entry in `items.json`, a reference in
`curator/reference/pNN.md`, and in `oracles.py`:
- a function `cNN(ns, text, code, out)` that returns a list of `_ck(name, ok, detail)`. `ns` is the namespace left
  after running the model's code, `out` is what it printed. Extend the range in `CHECKS` to include it.
- the names of those checks in `CODE_NAMES["pNN"]`, in order. This list is what keeps the total fixed: if the
  model's code crashes, every check it never reached is counted as failed.
- optionally `tNN(text, code)` in `TEXT` for checks on the reply's text, such as a tagged `ANSWER:` line.

For both suites:
- The prompt's **first line must be unique** across all suites. The mock backend finds the reference answer by it.
- Item ids are `p` or `l` plus two digits. The queue and UI match ids by that pattern (`ONESHOT` in `jobq.py`).
- Run `./fast.sh selftest` or `./latex.sh selftest`, then `./fast.sh mock` for the whole pipeline. The totals (29
  and 137) appear in the READMEs, script comments and two UI headings; `grep -rn "29 \|29/29\|137"` finds them.
- Prefer checks on behaviour (call the function, compile the document, parse a tagged line) over keywords in prose.
  Leave what a check can't see to the judge packet.

## 3. A new one-shot tier
For a subject that needs its own grader (SQL, shell, a language other than Python, your own domain). The `latex`
tier was added this way and is the template: it is standalone and its grader has no dependencies.

1. Copy `suites/latex/` to `suites/<suite>/` and `latex.sh` to `<tier>.sh`. Replace the prompts, `items.json`,
   `oracles.py` and `curator/`. Keep the layout of what `run.py` and `grade.py` write, because the UI reads it:
   `runs/<model>/<tier>/<item>/{response.md,reasoning.md,meta.json}`, `grades.json`, `judge/<item>.md` and
   `<tier>.log`.
2. Pick an id pattern for the items (a letter and two digits) that no other tier uses.
3. Wire the name in. `grep -n latex jobq.py web/app.py web/index.html summary.py tools/mock_backend.py` lists
   every place; they are:
   - `jobq.py`: `ONESHOT` (tier name and id pattern). The queue, pause and resume follow from it.
   - `web/app.py`: `SUITE_OF` (tier to suite folder), the `<tier>_items` list sent to the UI, the selftest job
     kind, and the run-start lines read from `<tier>.log`.
   - `web/index.html`: the results heading, the Launch panel, and the route lists that name `"fast", "latex"`.
   - `summary.py`: the list of tiers.
   - `tools/mock_backend.py`: `SUITES`, so `./<tier>.sh mock` returns your reference answers.
4. `./<tier>.sh selftest` gives full marks on the references and every negative control loses points; then
   `./<tier>.sh mock` gives full marks through the server, queue and UI.

This is a mechanical job that an LLM does well: give it this section and your prompts.

## Keeping tests honest
- The model must never see `curator/`, a case's `grader/`, `solution/` or `RUBRIC.md`. The one-shot tiers send only
  the prompt; `long.sh` copies only the working folder and locks `suites/` while the agent runs.
- If you publish your suites, models will eventually be trained on them. Tests you want to stay meaningful go in
  `suites/cases.local.json` and folders you don't share (add them to `.gitignore`).
- Read a few judge packets after the first runs. A passing score on bad work, or a failing score on good work,
  means the prompt left out something the grader requires. Fix the prompt and mark the older results.
