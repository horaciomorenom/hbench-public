#!/usr/bin/env python3
"""Run a command with a wall-clock limit, in its own process group, and kill the whole group at the limit
(the agent and every tool process it started). Usage: limit.py SECONDS cmd [args...]
Exit status: the command's, or 124 on timeout (and a line on stderr)."""
import os, signal, subprocess, sys

limit, cmd = int(sys.argv[1]), sys.argv[2:]
p = subprocess.Popen(cmd, start_new_session=True)
def kill(sig):
    try: os.killpg(p.pid, sig)
    except ProcessLookupError: pass
signal.signal(signal.SIGTERM, lambda *_: (kill(signal.SIGTERM), sys.exit(143)))
signal.signal(signal.SIGINT, lambda *_: (kill(signal.SIGTERM), sys.exit(130)))
try:
    sys.exit(p.wait(timeout=limit))
except subprocess.TimeoutExpired:
    print(f"limit.py: {limit}s limit reached, killing process group {p.pid}", file=sys.stderr)
    kill(signal.SIGTERM)
    try: p.wait(timeout=10)
    except subprocess.TimeoutExpired: pass
    kill(signal.SIGKILL)
    sys.exit(124)
