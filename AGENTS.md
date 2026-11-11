# Instructions for an LLM agent working in this repo

This is hbench: a benchmark harness and web UI for language models served over the OpenAI chat-completions API.
It ships as a skeleton. The user brings their own model servers and, if they want, their own tests. You are most
likely here to help with one of the jobs below. Read the linked doc before acting; each has checks that tell you
whether a step worked.

| The user wants to... | Read | Done when |
|---|---|---|
| install hbench | README.md, "Quickstart" | `python3 doctor.py` has no FAIL, `./fast.sh selftest` prints 29/29, `./fast.sh mock` prints 29/29 |
| install a model and plug it in | docs/BACKENDS.md, "For an LLM setting up a backend" | `python3 doctor.py <model>` is clean and `./fast.sh <model> p01` produced `runs/<model>/fast/p01/response.md` |
| use a server they already run (Ollama, LM Studio, an API) | docs/BACKENDS.md, "Recipes" | same as above; no serve script, just a `models.json` entry |
| write their own tests | docs/TESTS.md | the suite's selftest gives full marks on the reference answers and the negative control loses points |
| run on Windows | docs/WINDOWS.md | the quickstart passes inside WSL2 |

## Ground rules
- **Ask before anything big or irreversible**: downloading more than a few GB of weights, installing system
  packages, building an inference server, or spending money on a paid API. Say the size or cost when you ask.
- **Check the machine before choosing a model**: OS, GPU and its memory, free RAM and disk. Weights that don't fit
  in GPU memory (unified memory on Apple Silicon) with room for the context will run very slowly or not at all.
- **Weights live outside this repo.** Serve scripts go in `backends/`; they point at the weights by path.
- **Machine-specific files are never committed**: `models.json`, `config.json`, `.env`, `runs/`,
  `suites/cases.local.json`. They are in `.gitignore`. Start from `models.example.json` and `config.example.json`.
- **API keys** go in `.env` (`NAME=value`) or the user's environment, referenced by `api_key_env`. Never write a
  key into `models.json`, a script, or a commit, and never print one back.
- **Verify, don't assume.** After every change to a backend run `python3 doctor.py <model>`. Server flags change
  between versions: if one is rejected, read the server's `--help` instead of guessing.
- **Don't run the full suites unless asked.** One item (`./fast.sh <model> p01`) is the smoke test; a full run can
  take hours on a slow model. Stop the server when you finish: `./server.sh down`.
- **Keep the answers away from the model under test**: `suites/*/curator/`, each case's `grader/`, `solution/` and
  `RUBRIC.md`. If you are the model being benchmarked (an agent started by `long.sh`), these are not yours to read.

## Map
| Path | What |
|---|---|
| `models.json` | the user's models; one entry per backend |
| `backends/` | serve scripts that start a local server in the foreground |
| `server.sh`, `fast.sh`, `latex.sh`, `long.sh` | server lifecycle and the three tiers |
| `doctor.py` | checks the install and a model's server |
| `tools/mock_backend.py` | a complete minimal backend, stdlib only: the reference for what a server must do |
| `suites/` | the tests: `short/` and `latex/` (one-shot), `examples/` (agentic case), `cases.json` (registry) |
| `web/`, `jobq.py` | the web UI (`python3 web/app.py`, port 8090) and the job queue |
| `hb.py` | settings and helpers shared by everything; `python3 hb.py` prints its CLI |

## When you finish
Tell the user what you installed and where, the serve command, the `doctor.py` output, how to start a run and open
the UI, and anything you could not verify.
