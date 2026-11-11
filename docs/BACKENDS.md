# Backends: plugging a model into hbench

hbench talks to every model through the OpenAI chat-completions API. A **backend** is a server that speaks it,
plus one entry in `models.json` that tells hbench where it is and, optionally, how to start it.

You don't have to do this by hand: the last section, "For an LLM setting up a backend", is written for a coding agent
(Claude Code, Codex, Cursor, ...) to follow, and the README has prompts to start it with.

## What the server must do
- `GET {base_url}/models` returns `{"data": [{"id": "<model id>"}, ...]}`. hbench uses it to see that the server is up.
- `POST {base_url}/chat/completions` with what hbench sends:
  ```json
  {"model": "<id>", "messages": [{"role": "user", "content": "..."}], "stream": true,
   "stream_options": {"include_usage": true}, "max_tokens": 32768, "reasoning_effort": "medium"}
  ```
  and answers with a server-sent-event stream of `chat.completion.chunk` objects: text in
  `choices[0].delta.content`, a `finish_reason` (`stop`, or `length` when cut off), and ideally a last chunk with
  `usage` (`prompt_tokens`, `completion_tokens`).
  - Thinking models: the thinking should arrive separately, in `delta.reasoning_content` (llama.cpp, vLLM) or
    `delta.reasoning` (other servers); `doctor.py <model>` tells you which one yours uses. hbench stores it next to
    the answer; the graders read only the answer.
  - No `temperature` or other sampling fields are sent; configure sampling in the server.
  - If the server rejects `reasoning_effort`, set `"effort": false` for that model.
- Long tier only: the agent (pi) uses the same endpoint with **tool calls** (OpenAI `tools` / `tool_calls`), and its
  conversations grow to tens of thousands of tokens: give the server at least a 32K context, 64K is better.

## models.json
```json
{
 "mymodel": {"serve": "backends/mymodel.sh", "port": 8081, "id": "my-model", "label": "My model Q4_K_M",
             "context": 65536, "max_output": 32768}
}
```
| Field | Meaning |
|---|---|
| name (the key) | what you type: `./fast.sh mymodel`; results go to `runs/mymodel/` |
| `id` | the model id the server expects in requests (and lists at `/models`) |
| `port` or `base_url` | `port` means `http://127.0.0.1:<port>/v1`; `base_url` is any URL ending in `/v1` |
| `serve` | optional. A script hbench runs to start the server (path relative to the hbench folder, or absolute). Without it the server is **external**: you start it, hbench only uses it |
| `api_key_env` | optional. Name of an environment variable holding the API key (sent as `Authorization: Bearer`); if it isn't set, hbench reads it from `.env` in the hbench folder (`NAME=value` lines, never exported) |
| `agent_command` | optional. The long tier's agent for this model, instead of pi or config.json's `agent_command` (same contract, config.example.json); e.g. `"\"$HB_HOME/tools/agent-dsh.sh\""` for DeepSeek Harness |
| `label`, `context`, `max_output` | for the agent's config: a display name, the context window, and the most output tokens per reply (defaults 32768 and 32768) |
| `reasoning` | `false` for models that don't think (agent config); default `true` |
| `effort` | `reasoning_effort` sent by the fast tier (`low`, `medium`, `high`); `false` to send none. Default `medium` |
| `provider` | optional. Models with the same provider share one entry in the agent's config (same URL) |

**A serve script** must run the server in the foreground (end with `exec <server> ...`), listen on the port in
models.json, and print its log to stdout/stderr. hbench starts it in the background with its output in
`runs/server-<model>.log`, waits until `/models` answers (and gives up if the script exits), and stops it by
killing its process tree (`./server.sh down`). Only one hbench-started server runs at a time; models sharing a
port (the same weights at two context sizes, say) are fine. `config.json` hooks: `before_start` runs before each
start (e.g. wait for other GPU jobs to finish), `wrap` is put in front of the script (e.g. a memory watchdog).
See `backends/llamacpp-qwen.sh` for an example.

## Recipes
Versions and flags change; check your server's docs if one is rejected.

**llama.cpp** (CUDA on Linux/WSL, Metal on macOS); good default for GGUF models:
```bash
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_CUDA=ON        # macOS: cmake -B build   (Metal is on by default)
cmake --build build --config Release -j
```
Serve script (as in `backends/llamacpp-qwen.sh`):
`exec llama-server -m model.gguf --host 127.0.0.1 --port 8081 --alias my-model -c 65536 -ngl 99 --jinja --reasoning-format deepseek -fa on`.
`--jinja` enables tool calls (long tier), `--reasoning-format deepseek` sends thinking as `reasoning_content`,
`-ngl 99` puts all layers on the GPU (lower it if the model doesn't fit), `-c` is the context.

**Ollama** (external): `ollama pull qwen3:8b`, then
`{"base_url": "http://127.0.0.1:11434/v1", "id": "qwen3:8b"}`. Ollama's default context is small: raise it
(`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or a Modelfile with `PARAMETER num_ctx 32768`), or long answers and the
agent's conversations get cut.

**vLLM** (Linux/WSL with an NVIDIA GPU): serve script
`exec vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --served-model-name qwen3-8b --max-model-len 32768 --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser hermes`.

**LM Studio** (external): load a model, start the server (Developer tab, or `lms server start`), then
`{"base_url": "http://127.0.0.1:1234/v1", "id": "<the model's identifier>", "effort": false}`.

**MLX** (Apple Silicon): serve script `exec mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080` and
`"id"` set to the same model name.

**Remote APIs** (OpenRouter, OpenAI, a server on another machine): external, with
`{"base_url": "https://openrouter.ai/api/v1", "id": "qwen/qwen3-235b-a22b", "api_key_env": "OPENROUTER_API_KEY"}`.
Mind the cost: a fast-tier run is up to about 300K output tokens with thinking, a long case can be more.

**DeepSeek API with DeepSeek Harness** (external; long tier through `dsh` instead of pi): `npm install -g @deepseek-ai/dsh`,
put `DEEPSEEK_API_KEY=sk-...` in `.env` (or export it), then
`{"base_url": "https://api.deepseek.com/v1", "id": "deepseek-v4-pro", "api_key_env": "DEEPSEEK_API_KEY", "effort": "high", "context": 1000000, "agent_command": "\"$HB_HOME/tools/agent-dsh.sh\""}`
(or `"id": "deepseek-flash"`). The fast tier uses DeepSeek's OpenAI-compatible endpoint at `base_url`; dsh uses its own
DeepSeek route (the Anthropic-compatible endpoint, same key). DeepSeek's efforts are `off`, `low`, `high`, `max`.
`tools/agent-dsh.sh` also runs dsh against any other OpenAI-compatible `base_url`, local servers included.

**Your own server**: anything that meets "What the server must do" above. `tools/mock_backend.py` is a complete
minimal example (about 100 lines, stdlib only).

## For an LLM setting up a backend
You are adding a model to hbench on this machine. Work in the hbench folder. Do the steps in order and don't skip
the checks; each one says what success looks like.

1. **Inspect the machine.** OS (`uname -a`; on Windows you are in WSL2, see docs/WINDOWS.md), GPU and its memory
   (`nvidia-smi`, or on macOS `system_profiler SPDisplaysDataType` and unified memory from `sysctl hw.memsize`),
   free disk (`df -h .`). Pick a model and quantization whose weights fit in GPU memory with room for the context
   (rule of thumb: weights + 1-2 GB for 32K of context on a small model).
2. **Choose the server**: an inference server already installed and working beats building one. Prefer llama.cpp
   for GGUF files, vLLM for full-precision or AWQ/GPTQ weights on NVIDIA, MLX on Apple Silicon, Ollama or LM Studio
   if the user already uses them. Build or install it; confirm it runs (`llama-server --version`, ...).
3. **Get the weights** into a folder outside hbench. Check the download size and the network first; ask the user
   before downloading more than a few GB.
4. **Write the serve script** `backends/<name>.sh` (foreground, `exec`, `127.0.0.1`, a free port, the model id as
   alias, tool calls and a reasoning parser enabled if the server supports them), `chmod +x` it. For an external
   server, start it the way the user wants instead and skip the script.
5. **Add the models.json entry** (`id`, `port` or `base_url`, `serve` if any, `label`, `context`, `max_output`).
6. **Start and check**: `./server.sh up <name>` (managed) then `python3 doctor.py <name>`. Success: every line OK
   or WARN with a reason you understand; `streamed reply` shows text; `usage` has tokens. If reasoning arrives inside
   the text as `<think>`, enable the server's reasoning parser. If the request is rejected for `reasoning_effort`, set
   `"effort": false`.
7. **Smoke test the tiers**: `./fast.sh <name> p01` (one item, a minute or two; the result is in
   `runs/<name>/fast/p01/`), and if the long tier is wanted, `LIMIT=900 ./long.sh <name> e01` (check
   `runs/<name>/long/e01/logs/agent.err` and that `grade.txt` has a score). Then `./server.sh down`.
8. **Report** what you installed, where the weights are, the serve command, the doctor output, and anything you
   couldn't verify. Don't run the full suites unless asked: they take hours on slow models.
