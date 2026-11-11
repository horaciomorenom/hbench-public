#!/bin/bash
# Fast tier: the short suite (10 one-shot prompts, 29 automatic checks) against one model, then grade.
# Usage: fast.sh <model> [p01 p05 ...]     model: a name from models.json
#        fast.sh selftest                  grade the curator's reference answers (must be 29/29)
# Starts the model's server if needed (server.sh up) and leaves it up for the next run.
# Results: runs/<model>/fast/  (per item response.md, reasoning.md, meta.json; grades.json; judge/; fast.log)
# Env: MAX_TOKENS per item (default 32768, thinking included), EFFORT (default: the model's, else medium),
#      ATTEMPTS total attempts per item (default 1; finished ones are kept, the item scores their mean).
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
PY=$(python3 "$H/hb.py" python)   # numpy, scipy, matplotlib for the oracles (config.json "python")
S=$H/suites/short
model=${1:?model from models.json, or selftest}; shift

if [ "$model" = selftest ]; then
  out=$(mktemp -d); $PY $S/grade.py --response-dir $S/curator/reference --out "$out" | tail -1; rm -rf "$out"; exit
fi
python3 "$H/hb.py" model "$model" id > /dev/null || exit 2
run=$H/runs/$model/fast; mkdir -p "$run"
log(){ echo "$(date +%T) $*" | tee -a "$run/fast.log"; }

$H/server.sh up "$model" "$run/fast.log"
effort=${EFFORT:-$(python3 "$H/hb.py" model "$model" effort)}
log "short suite on $model${*:+ (${*})}, max_tokens ${MAX_TOKENS:-32768}, effort ${effort:-off}, attempts ${ATTEMPTS:-1}"
python3 -u $S/run.py --model "$model" --max-tokens "${MAX_TOKENS:-32768}" --effort "${effort:-off}" --attempts "${ATTEMPTS:-1}" ${1:+--ids "$@"} | tee -a "$run/fast.log"
$PY $S/grade.py --model "$model" | tee "$run/grade.txt" | tee -a "$run/fast.log"
log "done; judge packets in runs/$model/fast/judge/. Server left up (server.sh down to stop)."
