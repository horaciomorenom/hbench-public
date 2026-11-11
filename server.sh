#!/bin/bash
# Start, stop or show the model servers in models.json, one at a time.
# Usage: server.sh up <model> [log] | down | status
# up, for a model with a serve script: runs config.json's hooks.before_start (if set), starts the serve script
# (under hooks.wrap, if set) with its output in runs/server-<model>.log, and returns once the server answers.
# The previous log moves to runs/server-logs/, named by its start time. It refuses if another server hbench
# started is up. For an external model (no serve script) up only checks that it answers; hbench never starts
# or stops those. runs/.server and runs/.server.pid record the server hbench started.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
HB="python3 $H/hb.py"
STATE=$H/runs/.server; PIDF=$H/runs/.server.pid
mkdir -p "$H/runs"
answers(){ curl -s -m 5 -H "Authorization: Bearer ${2:-local}" "$1/models" | grep -q '"id"'; }
up_ports(){ for p in $($HB managed-ports); do curl -s -m 2 -o /dev/null localhost:$p/v1/models && echo $p; done; true; }
kill_tree(){ local c; for c in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$c"; done; kill "$1" 2>/dev/null || true; }

case ${1:-} in
up)
  model=${2:?model}; log=${3:-/dev/null}
  url=$($HB model "$model" url)
  if [ "$($HB model "$model" managed)" != 1 ]; then
    key=$($HB model "$model" key)
    env=$($HB model "$model" key_env)
    [ -n "$env" ] && [ -z "$key" ] && { echo "$model needs an API key: set $env, or put $env=... in $H/.env" | tee -a "$log"; exit 1; }
    answers "$url" "$key" && { echo "$(date +%T) $model: external server at $url answers" | tee -a "$log"; exit 0; }
    echo "$model is an external server ($url) and it does not answer; start it first (docs/BACKENDS.md)" | tee -a "$log"; exit 1
  fi
  serve=$($HB model "$model" serve)
  running=$(cat "$STATE" 2>/dev/null || true)
  if [ -n "$(up_ports)" ]; then
    [ "$running" = "$model" ] && answers "$url" && exit 0
    echo "a server is already up (${running:-unknown} on :$(up_ports | paste -sd, -)); run server.sh down first"; exit 1
  fi
  hook=$($HB hook before_start "$log")
  [ -n "$hook" ] && eval "$hook"
  slog=$H/runs/server-$model.log
  if [ -e "$slog" ]; then
    mkdir -p "$H/runs/server-logs"
    started=$(python3 -c 'import sys, time; sys.path.insert(0, sys.argv[1]); import hb
print(time.strftime("%Y%m%d-%H%M%S", time.localtime(hb.log_start(sys.argv[2]))))' "$H" "$slog")
    mv "$slog" "$H/runs/server-logs/server-$model.$started.log"
  fi
  echo "$(date +%T) starting $serve" | tee -a "$log"
  echo "# hbench server start $(date +%s) $model" > "$slog"  # the web UI dates the log's lines from this
  wrap=$($HB hook wrap)
  eval "exec nohup env $wrap \"\$serve\"" >> "$slog" 2>&1 &  # exec: no bash left behind that looks like server.sh
  echo $! > "$PIDF"; echo "$model" > "$STATE"
  until answers "$url"; do
    sleep 5
    kill -0 "$(cat "$PIDF")" 2>/dev/null || { echo "server died, see runs/server-$model.log" | tee -a "$log"; rm -f "$STATE" "$PIDF"; exit 1; }
  done
  echo "$(date +%T) server ready: $model at $url" | tee -a "$log" ;;
down)
  [ -s "$PIDF" ] && kill_tree "$(cat "$PIDF")"
  for i in $(seq 1 30); do [ -z "$(up_ports)" ] && break; sleep 1; done
  if [ -n "$(up_ports)" ] && command -v lsof > /dev/null; then  # started without a PID file: stop what listens on the port
    for p in $(up_ports); do kill $(lsof -ti tcp:$p -sTCP:LISTEN) 2>/dev/null || true; done
    for i in $(seq 1 30); do [ -z "$(up_ports)" ] && break; sleep 1; done
  fi
  rm -f "$STATE" "$PIDF"; [ -z "$(up_ports)" ] && echo "no server up" || { echo "still up: $(up_ports)"; exit 1; } ;;
status)
  p=$(up_ports); [ -n "$p" ] && echo "up: $(cat "$STATE" 2>/dev/null || echo unknown) on :$p" || echo "no server up" ;;
*) echo "usage: server.sh up <model> [log] | down | status"; exit 2 ;;
esac
