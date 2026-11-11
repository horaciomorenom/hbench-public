#!/usr/bin/env python3
"""hbench's settings and platform helpers, shared by the scripts, the queue and the web UI.

  config.json   your machine (start from config.example.json): python, hooks, keep_awake, pdf_browser, agent
  models.json   your models (start from models.example.json); fields in docs/BACKENDS.md
  .env          optional KEY=value lines: API keys for models' api_key_env when the variable isn't set
  suites/cases.json + suites/cases.local.json   the long-tier cases (docs/CASES.md)

CLI for the shell scripts (prints one value, empty if unset):
  hb.py python                    the Python the graders use (needs numpy, scipy, matplotlib)
  hb.py model <name> <field>      url, id, serve, managed (1/0), port, key, context, max_output, effort, ...
  hb.py agent <name>              the long-tier agent command for a model (its agent_command, else config.json's)
  hb.py hook before_start <log>   your command to run before a server starts, with {log} filled in
  hb.py hook wrap                 the command your serve scripts run under (e.g. a memory guard)
  hb.py case <id> <field> [k=v]   src, copy, cwd, prompt, grade (with {python} {suites} {src} {cwd} {run} filled in)
  hb.py managed-ports             ports of the local servers hbench starts
  hb.py pi-config <dir>           write <dir>/models.json for the pi agent from models.json
Stdlib only; runs on macOS and Linux (including WSL2 on Windows).
"""
import json, os, platform, re, shlex, shutil, subprocess, sys

H = os.path.dirname(os.path.abspath(__file__))
RUNS, SUITES = f"{H}/runs", f"{H}/suites"
SYSTEM = platform.system()  # Darwin or Linux
WSL = SYSTEM == "Linux" and "microsoft" in platform.release().lower()

def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def config():
    c = _load(f"{H}/config.json", {})
    c.setdefault("hooks", {})
    return c

def python():
    c = config().get("python")
    if c: return os.path.expanduser(c)
    if os.path.exists(f"{H}/.venv/bin/python"): return f"{H}/.venv/bin/python"
    return shutil.which("python3") or sys.executable

# ---------------------------------------------------------------- models

def env(name):
    """An environment variable, else its value in .env (so queued runs see API keys without a shell profile)."""
    if os.environ.get(name): return os.environ[name]
    try:
        for l in open(f"{H}/.env"):
            k, _, v = l.strip().partition("=")
            if k.strip().removeprefix("export ").strip() == name: return v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return ""

def models():
    """name -> normalized entry: url (…/v1), id, serve (abs path or None), managed, port, key, and the pi fields."""
    out = {}
    for name, m in _load(f"{H}/models.json", {}).items():
        if name.startswith("_"): continue  # "_comment" keys
        url = (m.get("base_url") or f"http://127.0.0.1:{m['port']}/v1").rstrip("/")
        port = re.match(r"https?://(?:127\.0\.0\.1|localhost)(?::(\d+))?", url)
        key_env = m.get("api_key_env")
        serve = os.path.join(H, os.path.expanduser(m["serve"])) if m.get("serve") else None  # relative: inside hbench
        out[name] = dict(name=name, url=url, id=m["id"], serve=serve,
                         managed=bool(m.get("serve")), port=int(port.group(1)) if port and port.group(1) else None,
                         key_env=key_env, key=env(key_env) if key_env else "local", agent_command=m.get("agent_command"),
                         provider=m.get("provider") or name, label=m.get("label") or m["id"],
                         context=int(m.get("context", 32768)), max_output=int(m.get("max_output", 32768)),
                         reasoning=m.get("reasoning", True), effort=m.get("effort", "medium") or "off")
    return out

def model(name):
    ms = models()
    if name not in ms: raise KeyError(f"unknown model {name} (not in models.json)")
    return ms[name]

def pi_config():
    """pi's models.json: one provider per server URL, every model of models.json under it."""
    provs = {}
    for m in models().values():
        p = provs.setdefault(m["provider"], dict(baseUrl=m["url"], api="openai-completions", apiKey=m["key"] or "local", models=[]))
        p["models"].append(dict(id=m["id"], name=m["label"], reasoning=bool(m["reasoning"]), input=["text"],
                                contextWindow=m["context"], maxTokens=m["max_output"],
                                cost=dict(input=0, output=0, cacheRead=0, cacheWrite=0), compat=dict(supportsDeveloperRole=False)))
    return dict(providers=provs)

# ---------------------------------------------------------------- long-tier cases

def cases():
    """id -> case; suites/cases.json (shared) then suites/cases.local.json (yours) on top. long.sh locks suites/
    while an agent runs, so the last list read is kept in runs/.cases.json and used then."""
    out = {}
    try:
        for f in ("cases.json", "cases.local.json"):
            for k, v in _load(f"{SUITES}/{f}", {}).items():
                if not k.startswith("_"): out[k] = v
    except PermissionError:
        return _load(f"{RUNS}/.cases.json", {})
    if os.path.isdir(RUNS) and out != _load(f"{RUNS}/.cases.json", None):
        with open(f"{RUNS}/.cases.json", "w") as f: json.dump(out, f)
    return out

def case_field(cid, field, **fill):
    c = cases()[cid]
    v = {"cwd": c.get("cwd", c["copy"]), "prompt": c.get("prompt", "PROMPT.md")}.get(field, c.get(field, ""))
    if field == "grade":
        v = v.format(python=shlex.quote(python()), suites=shlex.quote(SUITES), src=shlex.quote(f"{SUITES}/{c['src']}"),
                     **{k: shlex.quote(x) for k, x in fill.items()})
    return v

# ---------------------------------------------------------------- processes

def ps():
    out = subprocess.run(["ps", "-Ao", "pid=,ppid=,pgid=,etime=,command="], capture_output=True, text=True).stdout
    rows = {}
    for l in out.splitlines():
        parts = l.split(None, 4)
        if len(parts) == 5:
            pid, ppid, pgid, et, cmd = parts
            rows[int(pid)] = dict(pid=int(pid), ppid=int(ppid), pgid=int(pgid), etime=et, cmd=cmd)
    return rows

def descendants(rows, pid):
    kids = {}
    for r in rows.values():
        kids.setdefault(r["ppid"], []).append(r["pid"])
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        for k in kids.get(p, []):
            out.append(k); todo.append(k)
    return out

# ---------------------------------------------------------------- platform

def mem():
    """Free memory for the header meter: level (% free) and swap in use."""
    if SYSTEM == "Darwin":
        lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_level"], capture_output=True, text=True).stdout.strip()
        swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
        m = re.search(r"used = ([\d.]+M)", swap)
        return dict(level=int(lvl or 0), swap_used=m.group(1) if m else "?", what="free memory (macOS memory level)")
    try:
        mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if len(l.split()) >= 2}
        return dict(level=round(100 * mi["MemAvailable"] / mi["MemTotal"]), swap_used=f"{(mi['SwapTotal'] - mi['SwapFree']) // 1024}M",
                    what="available system RAM" + (" of the WSL VM (GPU memory is not shown)" if WSL else ""))
    except (OSError, KeyError, ValueError):
        return dict(level=0, swap_used="?", what="unknown")

def keep_awake_cmd(pid):
    """A command that keeps the machine awake until process pid exits, or None (off)."""
    if config().get("keep_awake") is False or WSL: return None
    if SYSTEM == "Darwin": return ["caffeinate", "-is", "-w", str(pid)]
    if shutil.which("systemd-inhibit"):
        return ["systemd-inhibit", "--what=idle:sleep", "--who=hbench", "--why=benchmark queue running",
                "sh", "-c", f"while kill -0 {pid} 2>/dev/null; do sleep 5; done"]
    return None

def pdf_browser():
    c = config().get("pdf_browser")
    if c: return os.path.expanduser(c)
    for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "/Applications/Chromium.app/Contents/MacOS/Chromium"]:
        if os.path.exists(p): return p
    return next((shutil.which(b) for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")
                 if shutil.which(b)), None)

def log_start(path):
    """When the server that writes this log started: the epoch server.sh puts on its first line, else the file's
    creation time (macOS; logs from before that line existed), else its change time."""
    try:
        with open(path) as f:
            m = re.match(r"# hbench server start (\d+)", f.readline())
        if m: return float(m.group(1))
    except OSError:
        pass
    st = os.stat(path)
    return getattr(st, "st_birthtime", st.st_ctime)

# ---------------------------------------------------------------- CLI

def main(a):
    if not a: print(__doc__); return
    cmd = a[0]
    if cmd == "python": print(python())
    elif cmd == "model":
        v = model(a[1])[a[2]]
        print("1" if v is True else "0" if v is False else "" if v is None else v)
    elif cmd == "agent": print(model(a[1])["agent_command"] or config().get("agent_command") or "")
    elif cmd == "hook":
        v = config()["hooks"].get(a[1]) or ""
        print(v.replace("{log}", shlex.quote(a[2])) if len(a) > 2 else v)
    elif cmd == "case": print(case_field(a[1], a[2], **dict(x.split("=", 1) for x in a[3:])))
    elif cmd == "cases": print(" ".join(cases()))
    elif cmd == "managed-ports": print(" ".join(sorted({str(m["port"]) for m in models().values() if m["managed"] and m["port"]})))
    elif cmd == "pi-config":
        os.makedirs(a[1], exist_ok=True)
        with open(f"{a[1]}/models.json", "w") as f: json.dump(pi_config(), f, indent=2)
    else: sys.exit(f"hb.py: unknown command {cmd}")

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyError as e:
        sys.exit(f"hb.py: {e.args[0]}")
