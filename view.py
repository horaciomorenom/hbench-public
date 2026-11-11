#!/usr/bin/env python3
"""Print a pi --mode json log (or dsh --json, tools/agent-dsh.sh) as readable text. Usage: view.py <agent.jsonl | run dir> [-f to follow]"""
import json, sys, time
from pathlib import Path

DIM, BOLD, CYAN, RED, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[31m", "\033[0m"
if not sys.stdout.isatty():
    DIM = BOLD = CYAN = RED = RESET = ""
MAX_LINES = 25  # of each tool result

path = Path(sys.argv[1]).expanduser()
if path.is_dir():
    path = path / "logs" / "agent.jsonl" if (path / "logs").is_dir() else path / "agent.jsonl"
follow = "-f" in sys.argv[2:]


def lines():
    with path.open() as f:
        buf = ""
        while True:
            chunk = f.readline()
            if chunk:
                buf += chunk
                if buf.endswith("\n"):
                    yield buf
                    buf = ""
            elif follow:
                time.sleep(0.5)
            else:
                return


def text_of(result):
    if isinstance(result, dict):
        parts = result.get("content") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict)) or json.dumps(result)[:2000]
    return str(result)


def out(s):
    sys.stdout.write(s)
    sys.stdout.flush()


for line in lines():
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    t = ev.get("type")
    if t == "message_update":
        a = ev.get("assistantMessageEvent") or {}
        k = a.get("type")
        if k == "thinking_start":
            out(f"\n{DIM}[thinking] ")
        elif k == "thinking_delta":
            out(a.get("delta", ""))
        elif k == "thinking_end":
            out(RESET + "\n")
        elif k == "text_start":
            out("\n")
        elif k == "text_delta":
            out(a.get("delta", ""))
        elif k == "toolcall_end":
            tc = a.get("toolCall") or {}
            args = tc.get("arguments") or {}
            shown = args.get("command") or args.get("path") or json.dumps(args)
            extra = ""
            if tc.get("name") in ("edit", "write"):
                extra = "\n" + json.dumps({k: v for k, v in args.items() if k != "path"}, indent=1)[:3000]
            out(f"\n{CYAN}▶ {tc.get('name')}: {shown}{RESET}{DIM}{extra}{RESET}\n")
    elif t == "tool_execution_end":
        body = text_of(ev.get("result")).rstrip().splitlines()
        more = f"\n  … {len(body) - MAX_LINES} more lines" if len(body) > MAX_LINES else ""
        color = RED if ev.get("isError") else DIM
        out(color + "\n".join("  " + l for l in body[:MAX_LINES]) + more + RESET + "\n")
    elif t == "message_end":
        m = ev.get("message") or {}
        if m.get("role") == "user":
            txt = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict))
            out(f"{BOLD}[prompt]{RESET} {txt[:400]}{'…' if len(txt) > 400 else ''}\n")
        elif m.get("role") == "assistant":
            u = m.get("usage") or {}
            err = f" {RED}{m.get('errorMessage')}{RESET}" if m.get("errorMessage") else ""
            out(f"{DIM}[turn: {u.get('input', 0)} in / {u.get('cacheRead', 0)} cached / {u.get('output', 0)} out, "
                f"stop={m.get('stopReason')}]{RESET}{err}\n")
    elif t in ("compaction_start", "compaction_end", "auto_retry_start", "auto_retry_end"):
        out(f"{BOLD}[{t}]{RESET} {json.dumps({k: v for k, v in ev.items() if k not in ('type', 'result')})[:300]}\n")
    elif t == "agent_end":
        out(f"\n{BOLD}[agent finished]{RESET}\n")
        if follow:
            break
    # dsh: whole blocks, one event each
    elif t == "thinking":
        out(f"\n{DIM}[thinking] {ev.get('text', '')}{RESET}\n")
    elif t == "text":
        out("\n" + ev.get("text", "") + "\n")
    elif t == "tool_call":
        args = ev.get("input") if isinstance(ev.get("input"), dict) else {}
        shown = args.get("command") or args.get("file_path") or json.dumps(args)
        extra = ""
        if ev.get("tool") in ("edit", "write"):
            extra = "\n" + json.dumps({k: v for k, v in args.items() if k != "file_path"}, indent=1)[:3000]
        out(f"\n{CYAN}▶ {ev.get('tool')}: {shown}{RESET}{DIM}{extra}{RESET}\n")
    elif t == "tool_result":
        body = str(ev.get("result", "")).rstrip().splitlines()
        more = f"\n  … {len(body) - MAX_LINES} more lines" if len(body) > MAX_LINES else ""
        color = RED if ev.get("status") == "error" else DIM
        out(color + "\n".join("  " + l for l in body[:MAX_LINES]) + more + RESET + "\n")
    elif t == "status" and ev.get("phase") == "step_end":
        u = ev.get("usage") or {}
        out(f"{DIM}[step: {u.get('inputTokens', 0)} in / {u.get('cacheReadTokens', 0)} cached / {u.get('outputTokens', 0)} out]{RESET}\n")
    elif t == "error":
        out(f"{RED}[error] {ev.get('message')}{RESET}\n")
    elif t == "final":
        out(f"\n{BOLD}[agent finished]{RESET}\n")
        if follow:
            break
