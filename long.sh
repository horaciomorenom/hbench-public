#!/bin/bash
# Long tier: one agentic case with a model through an agent (pi by default), then grade it.
# Usage: long.sh <model> <case>    model: a name from models.json; case: an id from suites/cases.json or
#   suites/cases.local.json (docs/CASES.md): the case's folder is copied, the agent works on the copy, the case's
#   grader scores it.
# Env: LIMIT=seconds of agent wall time (default 10800), FRESH=1 to redo a run,
#      AGENT='cmd' to run a stand-in instead of the agent (no server; for testing the harness).
# Agent: pi, with a config generated from models.json, or the model's "agent_command" (else config.json's), run in
#   the case's working folder with HB_BASE_URL, HB_API_KEY, HB_MODEL_ID, HB_EFFORT, HB_CONTEXT, HB_MAX_OUTPUT,
#   HB_PROMPT_FILE, HB_LOG_DIR and HB_HOME (this folder) set; tools/agent-dsh.sh is one.
# Results: runs/<model>/long/<case>/{work/, logs/} and one line in runs/<model>/long/results.jsonl.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
HB="python3 $H/hb.py"
PY=$($HB python)
model=${1:?model from models.json}; case=${2:?case id from suites/cases.json}
LIMIT=${LIMIT:-10800}
provider=$($HB model "$model" provider) || exit 2
id=$($HB model "$model" id)
src=$H/suites/$($HB case "$case" src 2> /dev/null) || { echo "unknown case $case (cases: $($HB cases))"; exit 2; }
sub=$($HB case "$case" copy); rel=$($HB case "$case" cwd); prompt=$($HB case "$case" prompt)
agent_cmd=$($HB agent "$model")
run=$H/runs/$model/long/$case
[ -e "$run" ] && [ "${FRESH:-}" != 1 ] && { echo "$run exists (FRESH=1 to redo)"; exit 1; }
rm -rf "$run"; mkdir -p "$run/work" "$run/logs"
log(){ echo "$(date +%T) $*" | tee -a "$run/logs/long.log"; }

# Fresh copy of the case; the agent works in $run/work and sees nothing else of the suite.
cp -R "$src/$sub" "$run/work/$sub"
# The copy is its own git repo (the case files as one baseline commit) and git looks no higher than it, so the
# agent's git can't reach a repo hbench sits in, whose history may hold the suites and their answer keys.
git -C "$run/work" init -q
git -C "$run/work" add -A
git -C "$run/work" -c user.name=hbench -c user.email=hbench@localhost -c commit.gpgsign=false -c core.hooksPath=/dev/null \
  commit -q -m "case files"
export GIT_CEILING_DIRECTORIES=$run
cwd=$run/work${rel:+/$rel}
sed "s|<TEST_DIR>|$run/work|g" "$src/$prompt" > "$run/logs/prompt.md"

if [ -z "${AGENT:-}" ]; then
  $H/server.sh up "$model" "$run/logs/long.log"
  $HB pi-config "$H/pi-agent"  # pi's providers, written from models.json
fi

# The answer keys, graders and rubrics are locked while the agent runs.
chmod 000 $H/suites; trap 'chmod 755 $H/suites' EXIT
log "agent start: ${AGENT:-${agent_cmd:+custom agent, }$provider/$id} on $case ($(basename "$src")), limit ${LIMIT}s"
start=$(date +%s)
set +e
if [ -n "${AGENT:-}" ]; then
  (cd "$cwd" && python3 $H/limit.py "$LIMIT" bash -c "$AGENT" > "$run/logs/agent.err" 2>&1); rc=$?
elif [ -n "$agent_cmd" ]; then
  (cd "$cwd" && HB_BASE_URL=$($HB model "$model" url) HB_API_KEY=$($HB model "$model" key) HB_MODEL_ID=$id \
    HB_EFFORT=$($HB model "$model" effort) HB_CONTEXT=$($HB model "$model" context) HB_MAX_OUTPUT=$($HB model "$model" max_output) \
    HB_PROMPT_FILE=$run/logs/prompt.md HB_LOG_DIR=$run/logs HB_HOME=$H \
    python3 $H/limit.py "$LIMIT" bash -c "$agent_cmd" < /dev/null > "$run/logs/agent.log" 2> "$run/logs/agent.err"); rc=$?
else
  # pi-agent/ holds the local providers and httpIdleTimeoutMs 0 (a long tool call at a few t/s outlasts pi's
  # default idle timeout). --no-skills keeps the machine's own pi skills (~/.agents/skills) out of the prompt.
  # The filter drops the full partial message pi repeats in every streamed event.
  (cd "$cwd" && PI_CODING_AGENT_DIR=$H/pi-agent python3 $H/limit.py "$LIMIT" \
    pi -p --mode json --provider $provider --model $id --session-dir "$run/logs/session" \
    --no-skills \
    "$(cat "$run/logs/prompt.md")" < /dev/null 2> "$run/logs/agent.err" |
    python3 -u -c 'import json,sys
for l in sys.stdin:
    e = json.loads(l)
    if e.get("type") == "message_update":
        e.pop("message", None); e["assistantMessageEvent"].pop("partial", None)
    print(json.dumps(e), flush=True)' > "$run/logs/agent.jsonl"; exit ${PIPESTATUS[0]})
  rc=$?
fi
set -e
chmod 755 $H/suites
secs=$(( $(date +%s) - start ))
status=completed; [ $rc = 124 ] && status=timeout; [ $rc != 0 ] && [ $rc != 124 ] && status=agent_exit_$rc
log "agent end: $status, ${secs}s"

# Tool calls that look like reaching for the answers or the original repo's history (plus the case's own "peek" words),
# from pi's session or dsh's event stream (agent.jsonl; pi's copy of its session there is skipped).
python3 - "$run" "$($HB case "$case" peek)" > "$run/logs/peek.txt" <<'EOF'
import glob, json, re, sys
pat = re.compile(r'solution/|reference(_extra)?\.patch|curator/|grader/|RUBRIC|/suites/|git (log|show)' + (f"|{sys.argv[2]}" if sys.argv[2] else ""))
for f in glob.glob(f"{sys.argv[1]}/logs/session/*.jsonl") + glob.glob(f"{sys.argv[1]}/logs/agent.jsonl"):
    for line in open(f):
        try: e = json.loads(line)
        except ValueError: continue
        if f.endswith("/agent.jsonl"): calls = [(e.get("tool"), e.get("input"))] if e.get("type") == "tool_call" else []
        else: calls = [(b["name"], b.get("arguments")) for b in (e.get("message") or {}).get("content") or []
                       if isinstance(b, dict) and b.get("type") == "toolCall"]
        for name, args in calls:
            if pat.search(json.dumps(args)): print(name, json.dumps(args)[:300])
EOF
[ -s "$run/logs/peek.txt" ] && log "check logs/peek.txt: $(wc -l < "$run/logs/peek.txt" | tr -d ' ') suspicious tool calls"

grader=$($HB case "$case" grade cwd="$cwd" run="$run")
eval "$grader" > "$run/logs/grade.txt" 2>&1 || true
python3 $H/packet.py "$run" "$src" "$sub" > /dev/null

# One line per run: status, time, score, tokens from the pi session or dsh's event stream.
python3 - "$run" "$model" "$case" "$status" "$secs" >> "$H/runs/$model/long/results.jsonl" <<'EOF'
import glob, json, os, sys
run, model, case, status, secs = sys.argv[1:6]
g = open(f"{run}/logs/grade.txt").read()
try: j = json.loads(g[g.index("{"):g.rindex("}") + 1]); score, mx, partial = j.get("score"), j.get("maximum"), bool(j.get("partial"))
except ValueError: score = mx = None; partial = False
out = turns = 0
for f in glob.glob(f"{run}/logs/session/*.jsonl"):
    for l in open(f):
        m = json.loads(l).get("message") or {}
        if m.get("role") == "assistant": turns += 1; out += (m.get("usage") or {}).get("output", 0)
for l in open(f"{run}/logs/agent.jsonl") if os.path.exists(f"{run}/logs/agent.jsonl") else []:  # dsh steps
    try: e = json.loads(l)
    except ValueError: continue
    if e.get("type") == "status" and e.get("phase") == "step_end": turns += 1; out += (e.get("usage") or {}).get("outputTokens", 0)
print(json.dumps(dict(model=model, case=case, status=status, seconds=int(secs), score=score, max=mx,
                      judge_needed=partial, output_tokens=out, turns=turns)))
EOF
log "grade: $(tail -1 "$H/runs/$model/long/results.jsonl")"
