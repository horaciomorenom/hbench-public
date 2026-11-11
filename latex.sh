#!/bin/bash
# LaTeX tier: the latex suite (12 one-shot prompts: tables, math, repairs, TikZ, pgfplots) against one model, then grade.
# Usage: latex.sh <model> [l01 l09 ...]    model: a name from models.json
#        latex.sh selftest                 grade the curator's reference answers (must be full marks) and negative controls
# Starts the model's server if needed (server.sh up) and leaves it up for the next run.
# Results: runs/<model>/latex/  (per item response.md, reasoning.md, meta.json; grades.json; judge/ with rendered pages; latex.log)
# Env: MAX_TOKENS per item (default 32768, thinking included), EFFORT (default: the model's, else medium).
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
S=$H/suites/latex
model=${1:?model from models.json, or selftest}; shift
for t in pdflatex pdftotext pdftoppm; do command -v $t >/dev/null || { echo "latex tier needs $t on PATH" >&2; exit 2; }; done

if [ "$model" = selftest ]; then
  out=$(mktemp -d)
  python3 $S/grade.py --response-dir $S/curator/reference --out "$out/ref" | tail -1
  echo "negative controls (each must lose points):"
  python3 $S/grade.py --response-dir $S/curator/negative --out "$out/neg" | grep -v MISSING
  rm -rf "$out"; exit
fi
python3 "$H/hb.py" model "$model" id > /dev/null || exit 2
run=$H/runs/$model/latex; mkdir -p "$run"
log(){ echo "$(date +%T) $*" | tee -a "$run/latex.log"; }

$H/server.sh up "$model" "$run/latex.log"
effort=${EFFORT:-$(python3 "$H/hb.py" model "$model" effort)}
log "latex suite on $model${*:+ (${*})}, max_tokens ${MAX_TOKENS:-32768}, effort ${effort:-off}"
python3 -u $S/run.py --model "$model" --max-tokens "${MAX_TOKENS:-32768}" --effort "${effort:-off}" ${1:+--ids "$@"} | tee -a "$run/latex.log"
python3 $S/grade.py --model "$model" | tee "$run/grade.txt" | tee -a "$run/latex.log"
log "done; judge packets in runs/$model/latex/judge/. Server left up (server.sh down to stop)."
