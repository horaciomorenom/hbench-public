# hbench

A benchmark harness for language models on scientific-computing code, built for models you run yourself
(llama.cpp, Ollama, vLLM, LM Studio, MLX, ...) but usable with any OpenAI-compatible endpoint. Three tiers:

| Tier | Command | What | Graded by |
|---|---|---|---|
| fast | `./fast.sh <model> [p01 ...]` | 10 one-shot prompts through the API: plotting, quadrature, QR, ODEs, a derivation, a bug hunt | 29 automatic checks, plus judge packets |
| latex | `./latex.sh <model> [l01 ...]` | 12 one-shot LaTeX tasks: tables, math, repairs, subfigures, algorithms, TikZ, pgfplots | 137 automatic checks on the compiled PDF, plus judge packets with the rendered page |
| long | `./long.sh <model> <case>` | an agent (pi) works on a copy of a small repo: find and fix a bug, add a test | the case's grader (0-100), plus judge packets |

Around them: a **web UI** (results, transcripts, live logs and server speed charts, launch and stop runs), a **job
queue** for overnight runs that you can **pause** while you need the machine, **judge packets** (saved as PDF) for a
second model to review, and a Claude Code skill that writes that review.

Runs on macOS and Linux; on Windows through WSL2 ([docs/WINDOWS.md](docs/WINDOWS.md)).

**This repo is a skeleton.** It comes with no models and only small example suites. You plug in your own model
servers ([docs/BACKENDS.md](docs/BACKENDS.md)) and, if you like, your own tests ([docs/TESTS.md](docs/TESTS.md)).
The quickstart below runs end to end with a mock backend, so you can see everything working before you download
any weights.

## Quickstart
Needs Python 3.10+, bash and curl.
```bash
git clone <this repo's URL> hbench && cd hbench
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # numpy, scipy, matplotlib for the graders
cp models.example.json models.json      # the "mock" entry needs no GPU; delete the others for now
python3 doctor.py                       # checks the install
./fast.sh selftest                      # graders score the reference answers: 29/29
./fast.sh mock                          # whole pipeline against the mock backend: 29/29
python3 web/app.py                      # then open http://127.0.0.1:8090
```
Then add your own model: an entry in `models.json`, either with a serve script that starts your server or pointing
at a server you run yourself. [docs/BACKENDS.md](docs/BACKENDS.md) has the details, recipes for common servers, and
step-by-step instructions you can hand to an LLM to build the backend for you. Check it with
`python3 doctor.py <model>`, then `./fast.sh <model>`.

## Let Claude or another LLM install a model for you
Installing a local model means choosing weights that fit your machine, building or installing an inference server,
writing a serve script and checking that the server speaks the API hbench expects. A coding agent can do all of it.
The repo has instructions written for one: [AGENTS.md](AGENTS.md) (which Claude Code loads through `CLAUDE.md`, and
Codex, Cursor, opencode and others load directly) and the step-by-step section at the end of
[docs/BACKENDS.md](docs/BACKENDS.md).

**With a coding agent** ([Claude Code](https://claude.com/claude-code), Codex, Cursor, opencode, ...): start it in
the hbench folder and paste a prompt like one of these, edited for what you want.

> Set up hbench on this machine: follow the Quickstart in README.md until `./fast.sh mock` scores 29/29. Then
> install a local model for me following "For an LLM setting up a backend" in docs/BACKENDS.md. Look at my hardware
> first and propose a model and quantization that fits; ask me before downloading anything.

> I already run Ollama (or LM Studio, or have an API key for ...). Add the model `<name>` to hbench as an external
> backend following docs/BACKENDS.md, check it with `python3 doctor.py`, and run one fast-tier item as a smoke test.

> Add `<Hugging Face repo or GGUF file>` to hbench with llama.cpp, following docs/BACKENDS.md. Use the largest
> context that fits in memory, and report the doctor output.

The agent runs commands on your machine, so read what it proposes. The instructions tell it to ask before large
downloads, system installs and paid API calls, to keep weights outside the repo and to keep API keys in `.env`.

**With a chat assistant that can't run commands** (a chat window, or a small local model): paste in
[docs/BACKENDS.md](docs/BACKENDS.md), the output of `python3 doctor.py`, and your hardware (`nvidia-smi`, or on a Mac
`sysctl hw.memsize` and the chip). Ask for the serve script and the `models.json` entry, run
`python3 doctor.py <model>`, and paste its output back until every line is OK.

When it works, the model shows up in the web UI's Launch page and `./fast.sh <model>` runs the short suite on it.

## Your own tests
The shipped suites (numerical Python, LaTeX, one agentic bug fix) are examples of the three kinds of test. To add
an agentic case, a one-shot item or a whole new tier for your own subject, see [docs/TESTS.md](docs/TESTS.md).
Agentic cases need no changes to hbench: a folder with a prompt, a repo and a grader, plus one line in a registry.

## Optional setup
`config.json` (copy `config.example.json`) for hooks that run before a server starts or wrap it (a GPU
lock, a memory watchdog), the Python the graders use, keep-awake, and the agent command. The long tier needs Node and
the pi agent (`npm install -g @earendil-works/pi-coding-agent`), DeepSeek Harness (`tools/agent-dsh.sh`) or your own
`agent_command`; judge packet PDFs need
pandoc and Chrome, Chromium or Edge.

## Commands
```bash
./fast.sh <model> [p03 p07]     # short suite; starts the model's server if hbench manages it, then grades
./fast.sh selftest              # grade the reference answers (29/29)
./latex.sh <model> [l03 l09]    # latex suite; needs pdflatex and poppler. ./latex.sh selftest: 137/137, plus negative controls
./long.sh <model> e01           # one agentic case (LIMIT=seconds, default 3 h; FRESH=1 to redo it)
./server.sh up <model> | down | status   # one hbench-started server at a time; it stays up between runs
python3 summary.py [fast|latex|long]  # model x item tables
python3 view.py runs/<model>/long/e01 -f # follow an agent run in the terminal
python3 doctor.py [model]       # check the install, and that a model's server plugs in
```
Results go to `runs/<model>/` (fast: one folder per item with `response.md`, `reasoning.md`, `meta.json`, then
`grades.json` and judge packets; long: the agent's copy of the case in `work/` and its logs, grade and judge packet
in `logs/`, one line per run in `long/results.jsonl`).

- Fast tier: thinking on at the model's `effort` (default medium; `EFFORT=` to change), 32768 output tokens per
  item including thinking (`MAX_TOKENS=`), no sampling fields sent, so the server's own settings apply. A cut-off
  item is marked truncated. Finished items are skipped, so an interrupted run resumes. `ATTEMPTS=N` (queue:
  `--attempts N`) gives each item N attempts in total, keeping the ones already there (attempt n in `<item>/r<n>/`);
  the item then scores the mean, and grades.json keeps each attempt's score and checks.
- Long tier: the case's folder is copied to `runs/<model>/long/<case>/work`; `suites/` is locked (chmod 000) while
  the agent runs so it can't read the answers; at the time limit the agent and everything it started are killed;
  `logs/peek.txt` lists tool calls that look like reaching for answers.

## Web UI
`python3 web/app.py [--port 8090]`, then http://127.0.0.1:8090 (listens on localhost only; stdlib only).
- **Results**: model x item tables for both tiers; each run's response, reasoning, checks, prompt, judge packet
  (with Save as PDF), review, workspace files, and the server's request log with speed charts.
- **Launch**: run now, or add to the queue. **Jobs**: the queue, running jobs, and logs. **Server**: start/stop.
- The header shows the running job, the queue, free memory, and a **Pause** button.

## Queue: overnight runs, pause while you need the machine
```bash
python3 jobq.py add long mymodel e01     # or: add fast mymodel [p03 ...] [--max-tokens N]; add latex mymodel [l09 ...]
python3 jobq.py start 23:00              # or start (now); list shows the queue
python3 jobq.py pause 08:00              # scheduled pause; pause (no time) = now
```
- **Pause** kills whatever benchmark job is running (queued, Run now, or from a shell), puts it back at the front of
  the queue and stops the model server, so the memory is yours. That run is lost: a fast run redoes the item it was
  on (finished items are kept), a long case reruns from scratch. Resume = start.
- Jobs run one at a time. When the next job needs another model, the queue swaps servers; when the queue runs out
  it stops the server and pauses itself, so jobs you add during the day wait for the next start.
- While it works it keeps the machine awake (macOS `caffeinate`, Linux `systemd-inhibit`; off on WSL).
- It keeps running when the UI is closed. State in `runs/.queue.json`, log in `web/jobs/queue.log`.

## Judging
Automatic checks can't tell good code from code that passes. Every item and case gets a **judge packet** (task,
answer key, automatic results, the model's response or diff, its reasoning) for a second model to review; save it as
a PDF from the UI to read it yourself.

With [Claude Code](https://claude.com/claude-code), copy `skills/hbench-review` to `~/.claude/skills/` and run
`/hbench-review runs/<model>` (or a single run): it reviews the code itself, runs it in a scratch copy where cheap,
and writes `REVIEW.md` plus `runs/<model>/review.json`, whose scores `summary.py` and the UI show in brackets.

## Files
| Path | What |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | instructions for a coding agent helping you set things up |
| `docs/` | [BACKENDS.md](docs/BACKENDS.md) (models), [TESTS.md](docs/TESTS.md) and [CASES.md](docs/CASES.md) (tests), [WINDOWS.md](docs/WINDOWS.md) |
| `models.json` / `models.example.json` | your models ([docs/BACKENDS.md](docs/BACKENDS.md)) |
| `config.json` / `config.example.json` | your machine: grader Python, hooks, keep-awake, PDF browser, agent |
| `suites/short/` | fast tier: prompts, oracles (`oracles.py`), reference answers (`curator/`) |
| `suites/latex/` | latex tier: prompts, oracles, reference answers and negative controls (`curator/`) |
| `suites/cases.json`, `suites/examples/` | long-tier cases; yours go in `suites/cases.local.json` ([docs/CASES.md](docs/CASES.md)) |
| `fast.sh`, `long.sh`, `server.sh` | the tiers and the server lifecycle |
| `jobq.py`, `web/` | queue and web UI |
| `hb.py` | settings and platform helpers shared by everything |
| `doctor.py`, `tools/mock_backend.py` | install and backend checks; a no-GPU stand-in server |
| `pi-agent/` | the pi agent's settings; its `models.json` is generated from yours before each long run |
| `tools/agent-dsh.sh`, `dsh-agent/` | the DeepSeek Harness agent (a model's `agent_command`) and its state |
| `.env` | optional API keys (`NAME=value`) for models' `api_key_env`, read when the variable isn't set |
| `tools/export.sh` | make a shareable copy without your config, models, private cases and results |
