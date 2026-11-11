#!/usr/bin/env python3
"""hbench job queue: fast, latex and long jobs one after another (overnight), with pause and resume.

  jobq.py add fast <model> [p01 ...] [--max-tokens N] [--effort E] [--attempts N] [--front]
  jobq.py add latex <model> [l01 ...] [--max-tokens N] [--effort E] [--front]
  jobq.py add long <model> <case> [--limit SECONDS] [--fresh] [--front]
  jobq.py list
  jobq.py start [HH:MM]        run the queue now, or from HH:MM (the next one)
  jobq.py pause [HH:MM]        pause now, or at HH:MM
  jobq.py remove <id> | clear  (clear drops finished and failed entries)

The queue starts out paused: add jobs, then start it. One job at a time, in order. When the next job
needs another local model, the runner stops the server that is up (server.sh down) and the job's own
server.sh up starts the right one (with config.json's hooks, as always).

Pause kills whatever benchmark job is running (from the queue, the web UI or a shell), puts it back at
the front of the queue and stops the model server, so the memory is free. That run is lost: a fast or latex run
redoes the item it was on (finished items are kept), a long case reruns from scratch (FRESH=1).
When the queue runs out, the runner stops the server (unless keep_server is set) and pauses the queue,
so jobs added later wait for the next start.

The runner (jobq.py runner) is started by start/add/pause-at and exits when there is nothing left to
do. While a job runs or a start time is pending it keeps the machine awake: `caffeinate -is` on macOS (no idle
sleep, no system sleep on AC power; closing the lid on battery still sleeps the Mac), systemd-inhibit on Linux;
off on WSL (set Windows to not sleep while plugged in) or with "keep_awake": false in config.json.
State: runs/.queue.json. Logs: web/jobs/queue.log (the runner), web/jobs/<job id>.log (each job, listed
in the web UI with the jobs it starts). Stdlib only.
"""
import argparse, contextlib, fcntl, glob, json, os, re, signal, subprocess, sys, time

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import hb
from hb import ps, descendants
RUNS, SUITES, JOBS = f"{H}/runs", f"{H}/suites", f"{H}/web/jobs"
STATE, LOCK, QLOG = f"{RUNS}/.queue.json", f"{RUNS}/.queue.lock", f"{JOBS}/queue.log"
JOB_RE = re.compile(r"(?:^|\s)(?:/bin/)?bash\s+\S*?(fast|latex|long|server)\.sh\s+(.*)$")
ONESHOT = dict(fast=r"p\d\d", latex=r"l\d\d")  # the tiers of one-shot prompts: their item ids; script <tier>.sh, results runs/<model>/<tier>/
WRAP = 'echo $? > "$HB_RC"'  # in the command line of the bash wrapper spawn() puts around each job
os.makedirs(JOBS, exist_ok=True); os.makedirs(RUNS, exist_ok=True)

def log(msg):
    with open(QLOG, "a") as f:
        f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")

def hhmm(t):
    return time.strftime("%H:%M", time.localtime(t))

def next_time(s):
    """HH:MM -> epoch of its next occurrence."""
    h, m = map(int, s.split(":"))
    lt = time.localtime()
    t = time.mktime(lt[:3] + (h, m, 0, 0, 0, -1))
    return t + 86400 if t <= time.time() else t

# ---------------------------------------------------------------- processes

def outer_jobs(rows=None):
    """Benchmark scripts running now, from anywhere: the outermost fast.sh / latex.sh / long.sh / server.sh up."""
    rows = rows or ps()
    matched = {}
    for r in rows.values():
        m = JOB_RE.search(r["cmd"])
        if m and not r["cmd"].startswith(("zsh", "/bin/zsh", "sh -c")):
            matched[r["pid"]] = (m.group(1), m.group(2).split())
    out = []
    for pid, (kind, args) in matched.items():
        anc, nested = rows[pid]["ppid"], False
        while anc in rows and anc > 1:
            if anc in matched: nested = True; break
            anc = rows[anc]["ppid"]
        if nested or (kind == "server" and (not args or args[0] != "up")): continue
        out.append(dict(pid=pid, ppid=rows[pid]["ppid"], kind=kind, args=args, etime=rows[pid]["etime"]))
    return out

def kill_job(pid):
    """Kill a benchmark script and everything under it: pi's process group first (via limit.py), then the
    tree deepest first, then SIGKILL whatever is left after 10 s. Also its spawn() wrapper, if it has one."""
    rows = ps()
    if pid not in rows: return
    desc = descendants(rows, pid)
    leaders = {rows[d]["pgid"] for d in desc if rows[d]["pgid"] == d}
    targets = list(reversed(desc)) + [pid]
    if WRAP in rows.get(rows[pid]["ppid"], {}).get("cmd", ""): targets.append(rows[pid]["ppid"])
    for a in [d for d in desc if "limit.py" in rows[d]["cmd"]]:
        with contextlib.suppress(ProcessLookupError): os.kill(a, signal.SIGTERM)
    def kill_all(sig):
        for g in leaders:
            with contextlib.suppress(ProcessLookupError, PermissionError): os.killpg(g, sig)
        for t in targets:
            with contextlib.suppress(ProcessLookupError): os.kill(t, sig)
    kill_all(signal.SIGTERM)
    for _ in range(20):
        if not any(alive(t) for t in targets): return
        time.sleep(0.5)
    kill_all(signal.SIGKILL)

def alive(pid):
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    with contextlib.suppress(ChildProcessError):  # reap it if it is our finished child
        if os.waitpid(pid, os.WNOHANG)[0] == pid: return False
    return True

def unlock_suites():
    """long.sh unlocks suites/ when it exits; restore it if a kill skipped that."""
    if not any(j["kind"] == "long" for j in outer_jobs()) and (os.stat(SUITES).st_mode & 0o777) == 0:
        os.chmod(SUITES, 0o755)

def server_down(why):
    r = subprocess.run([f"{H}/server.sh", "down"], capture_output=True, text=True)
    log(f"server.sh down ({why}): {(r.stdout + r.stderr).strip()}")

def spawn(argv, env, **extra):
    """Start a benchmark script detached, output to web/jobs/<id>.log and its exit status to <id>.rc;
    writes and returns its record <id>.json (what the web UI lists), and the Popen."""
    jid = time.strftime("%Y%m%d-%H%M%S")
    while os.path.exists(f"{JOBS}/{jid}.json"): jid += "b"
    log_, rc = f"{JOBS}/{jid}.log", f"{JOBS}/{jid}.rc"
    p = subprocess.Popen(["bash", "-c", '"$@"; ' + WRAP, "job"] + argv, cwd=H,
                         env=os.environ | env | {"HB_RC": rc}, stdin=subprocess.DEVNULL,
                         stdout=open(log_, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    rec = dict(id=jid, argv=[os.path.basename(argv[0])] + argv[1:], env=env, started=time.time(),
               wrapper_pid=p.pid, log=f"web/jobs/{jid}.log", **extra)
    json.dump(rec, open(f"{JOBS}/{jid}.json", "w"))
    return rec, p

# ---------------------------------------------------------------- state

@contextlib.contextmanager
def state():
    """The queue state, locked for a read-modify-write and saved afterwards (not saved on an exception)."""
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try: st = json.load(open(STATE))
        except (OSError, ValueError): st = {}
        st.setdefault("items", [])
        st.setdefault("paused", True)
        st.setdefault("keep_server", False)
        for k in ("start_at", "pause_at", "runner_pid", "note"): st.setdefault(k, None)
        yield st
        json.dump(st, open(STATE + ".tmp", "w"), indent=1)
        os.replace(STATE + ".tmp", STATE)

def snapshot():
    with state() as st:
        st["runner_alive"] = runner_alive(st)
        return st

def runner_alive(st, rows=None):
    pid = st.get("runner_pid")
    r = pid and (rows or ps()).get(pid)
    return bool(r and "jobq.py runner" in r["cmd"])

def ensure_runner():
    """Start the runner unless one is up; returns its Popen (the caller may reap it) or None."""
    with state() as st:
        if runner_alive(st): return None
        p = subprocess.Popen([sys.executable, f"{H}/jobq.py", "runner"], cwd=H, stdin=subprocess.DEVNULL,
                             stdout=open(QLOG, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        st["runner_pid"] = p.pid
        return p

def label(it):
    return " ".join(it["argv"]) + "".join(f" {k}={v}" for k, v in it["env"].items())

def make_item(kind, model, ids=(), case=None, max_tokens=None, effort=None, limit=None, fresh=False, note=None, attempts=None):
    if model not in hb.models(): raise ValueError(f"unknown model {model}")
    env = {}
    if kind in ONESHOT:
        argv = [f"{kind}.sh", model] + [i for i in ids or [] if re.fullmatch(ONESHOT[kind], i)]
        if max_tokens: env["MAX_TOKENS"] = str(int(max_tokens))
        if effort: env["EFFORT"] = re.sub(r"[^a-z]", "", effort)
        if attempts and int(attempts) > 1:
            if kind != "fast": raise ValueError("attempts: only the fast tier repeats items")
            env["ATTEMPTS"] = str(int(attempts))
    elif kind == "long":
        if case not in hb.cases(): raise ValueError(f"unknown case {case}")
        argv = ["long.sh", model, case]
        if limit: env["LIMIT"] = str(int(limit))
        if fresh: env["FRESH"] = "1"
    else:
        raise ValueError("the queue takes fast, latex and long jobs")
    return dict(id=f"{time.strftime('%m%d-%H%M%S')}-{os.urandom(2).hex()}", kind=kind, model=model, argv=argv, env=env,
                status="queued", added=time.time(), tries=0, note=note, job=None, wrapper_pid=None, rc=None)

# ---------------------------------------------------------------- operations

def add(item, front=False):
    with state() as st:
        st["items"].insert(next((n for n, i in enumerate(st["items"]) if i["status"] == "queued"), len(st["items"]))
                           if front else len(st["items"]), item)
        start = not st["paused"]
    log(f"added {item['id']}: {label(item)}")
    return item, ensure_runner() if start else None

def remove(iid):
    with state() as st:
        it = next((i for i in st["items"] if i["id"] == iid), None)
        if not it: raise ValueError(f"no queue entry {iid}")
        if it["status"] == "running": raise ValueError("that job is running; pause or abort it first")
        st["items"].remove(it)

def move(iid, step):
    with state() as st:
        its = st["items"]; n = next((n for n, i in enumerate(its) if i["id"] == iid), None)
        if n is None: raise ValueError(f"no queue entry {iid}")
        m = n + step
        while 0 <= m < len(its) and its[m]["status"] != "queued": m += step
        if its[n]["status"] == "queued" and 0 <= m < len(its): its[n], its[m] = its[m], its[n]

def clear():
    with state() as st:
        st["items"] = [i for i in st["items"] if i["status"] in ("queued", "running")]

def start(at=None):
    """Run the queue now, or from `at` (epoch)."""
    with state() as st:
        st["paused"], st["start_at"], st["note"] = (True, at, f"starts at {hhmm(at)}") if at else (False, None, None)
    log(f"start {'at ' + hhmm(at) if at else 'now'}")
    return ensure_runner()

def cancel_start():
    with state() as st:
        if st["paused"]: st["start_at"], st["note"] = None, None
    log("scheduled start cleared")

def pause_at(at):
    with state() as st:
        st["pause_at"] = at
    log(f"pause {'at ' + hhmm(at) if at else 'time cleared'}")
    return ensure_runner() if at else None

def set_keep_server(v):
    with state() as st:
        st["keep_server"] = bool(v)

def requeue_spec(j):
    """A queue entry that reruns a job started outside the queue (web UI 'Run now' or a shell)."""
    rec = next((r for r in map(lambda f: json.load(open(f)), glob.glob(f"{JOBS}/*.json")) if r.get("wrapper_pid") == j["ppid"]), None)
    args, env = (rec["argv"][1:], dict(rec["env"])) if rec else (j["args"], {})
    model = args[0] if args else None
    if model not in hb.models(): return None  # selftest: nothing to keep
    if not rec:  # a shell run: its settings from the log line the script wrote when it started
        if j["kind"] in ONESHOT and os.path.exists(f := f"{RUNS}/{model}/{j['kind']}/{j['kind']}.log") and \
                (m := re.findall(r"max_tokens (\d+), effort (\w+)(?:, attempts (\d+))?", open(f).read())):
            env = dict(MAX_TOKENS=m[-1][0], EFFORT=m[-1][1], ATTEMPTS=m[-1][2] or None)
        if j["kind"] == "long" and len(args) > 1 and os.path.exists(f := f"{RUNS}/{model}/long/{args[1]}/logs/long.log"):
            if m := re.findall(r"limit (\d+)s", open(f).read()): env = dict(LIMIT=m[-1])
    if j["kind"] in ONESHOT:
        return make_item(j["kind"], model, ids=args[1:], max_tokens=env.get("MAX_TOKENS"), effort=env.get("EFFORT"),
                         attempts=env.get("ATTEMPTS"), note=f"paused {hhmm(time.time())} (started from {'the web UI' if rec else 'a shell'})")
    return make_item("long", model, case=args[1], limit=env.get("LIMIT"), fresh=True,
                     note=f"paused {hhmm(time.time())} (started from {'the web UI' if rec else 'a shell'})")

def pause(reason="paused"):
    """Hold the queue, kill the running benchmark job (back at the front of the queue) and stop the server."""
    with state() as st:
        st["paused"], st["start_at"], st["note"] = True, None, f"{reason} at {hhmm(time.time())}"
        cur = next((i for i in st["items"] if i["status"] == "running"), None)
        victims, front = [], []
        for j in outer_jobs():
            victims.append(j)
            if cur and j["ppid"] == cur["wrapper_pid"]:
                cur.update(status="queued", tries=cur["tries"] + 1, job=None, wrapper_pid=None,
                           note=f"{reason} at {hhmm(time.time())}, run discarded")
                if cur["kind"] == "long": cur["env"]["FRESH"] = "1"
            elif j["kind"] != "server" and (it := requeue_spec(j)):
                front.append(it)
        if cur and cur["status"] == "running":  # just spawned (not in ps as a job yet) or already gone
            if alive(cur["wrapper_pid"]): victims.append(dict(pid=cur["wrapper_pid"], kind=cur["kind"], args=cur["argv"][1:]))
            cur.update(status="queued", tries=cur["tries"] + 1, job=None, wrapper_pid=None)
            if cur["kind"] == "long": cur["env"]["FRESH"] = "1"
        st["items"][:0] = front
    log(f"{reason}: stopping {', '.join(' '.join([j['kind']] + j['args']) for j in victims) or 'nothing (no job running)'}")
    for j in victims: kill_job(j["pid"])
    unlock_suites()
    server_down(reason)

# ---------------------------------------------------------------- runner

def registry_up():
    """(model recorded in runs/.server or None, whether a local server hbench manages answers)."""
    import urllib.request
    up = False
    for port in sorted({m["port"] for m in hb.models().values() if m["managed"] and m["port"]}):
        with contextlib.suppress(Exception):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as r:
                up = up or b'"id"' in r.read()
    rec = open(f"{RUNS}/.server").read().strip() if os.path.exists(f"{RUNS}/.server") else None
    return rec, up

def runner():
    me, procs, awake, ran, said = os.getpid(), {}, None, False, None
    with state() as st:
        if runner_alive(st) and st["runner_pid"] != me: return
        st["runner_pid"] = me
    log("runner up")
    def keep_awake(on):
        nonlocal awake
        if on and not (awake and awake.poll() is None) and (cmd := hb.keep_awake_cmd(me)):
            awake = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif not on and awake:
            awake.terminate(); awake.wait(); awake = None
    while True:
        now, nxt, due_pause = time.time(), None, False
        with state() as st:
            if st["runner_pid"] != me and runner_alive(st):
                log("another runner took over; exiting"); return
            st["runner_pid"] = me
            cur = next((i for i in st["items"] if i["status"] == "running"), None)
            if cur and not (procs[cur["job"]].poll() is None if cur["job"] in procs else alive(cur["wrapper_pid"])):
                rc = open(f"{JOBS}/{cur['job']}.rc").read().strip() if os.path.exists(f"{JOBS}/{cur['job']}.rc") else ""
                cur.update(status="done" if rc == "0" else "failed", rc=int(rc) if rc.lstrip("-").isdigit() else None, ended=now)
                log(f"{cur['id']} {cur['status']} (exit {cur['rc']}): {label(cur)}")
                cur = None
            due_pause = bool(st["pause_at"] and now >= st["pause_at"])
            if due_pause:
                st["pause_at"] = None
            elif st["paused"] and st["start_at"] and now >= st["start_at"]:
                st["paused"], st["start_at"], st["note"] = False, None, None
                log("scheduled start")
            queued = [i for i in st["items"] if i["status"] == "queued"]
            if not cur and not st["paused"] and queued:
                nxt = queued[0]
            finished = not cur and not st["paused"] and not queued
            if finished:
                st["paused"], st["note"] = True, f"queue finished at {hhmm(now)}"
            idle = not cur and st["paused"] and not st["start_at"] and not (st["pause_at"] and outer_jobs())
            if (finished or idle) and not due_pause:
                st["runner_pid"] = None
            keep = st["keep_server"]
            keep_awake(bool(cur or nxt or (st["paused"] and st["start_at"])))
        if due_pause:
            pause("scheduled pause"); continue
        if finished or idle:
            if finished:
                log("queue finished")
                if ran and not keep: server_down("queue finished")
            log("runner exits"); keep_awake(False); return
        if nxt:
            others = outer_jobs()
            if others:  # something started from the web UI or a shell: wait for it
                msg = f"waiting for {' '.join([others[0]['kind']] + others[0]['args'])} to finish"
                if msg != said: log(msg); said = msg
                time.sleep(5); continue
            rec_model, up = registry_up()
            if up and rec_model != nxt["model"] and hb.models().get(nxt["model"], {}).get("managed"):
                server_down(f"next job needs {nxt['model']}")
            with state() as st:  # a pause may have come in while the server was switching
                it = next((i for i in st["items"] if i["id"] == nxt["id"]), None)
                if st["paused"] or not it or it["status"] != "queued": continue
                rec, p = spawn([f"{H}/{it['argv'][0]}"] + it["argv"][1:], it["env"], kind=it["kind"], queue_item=it["id"])
                procs[rec["id"]] = p
                it.update(status="running", job=rec["id"], wrapper_pid=p.pid, started=time.time(), rc=None)
                log(f"{it['id']} started as job {rec['id']}: {label(it)}")
                ran, said = True, None
            continue
        time.sleep(3)

# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="hbench job queue (see the module docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("kind", choices=[*ONESHOT, "long"]); a.add_argument("model"); a.add_argument("rest", nargs="*")
    a.add_argument("--max-tokens", type=int); a.add_argument("--effort"); a.add_argument("--limit", type=int)
    a.add_argument("--attempts", type=int, help="fast: total attempts per item (finished ones are kept)")
    a.add_argument("--fresh", action="store_true"); a.add_argument("--front", action="store_true")
    sub.add_parser("list"); sub.add_parser("clear"); sub.add_parser("runner")
    for c in ("start", "pause"): sub.add_parser(c).add_argument("at", nargs="?", help="HH:MM")
    sub.add_parser("remove").add_argument("id")
    o = ap.parse_args()
    if o.cmd == "add":
        it = make_item(o.kind, o.model, ids=o.rest, case=o.rest[0] if o.kind == "long" and o.rest else None,
                       max_tokens=o.max_tokens, effort=o.effort, limit=o.limit, fresh=o.fresh, attempts=o.attempts)
        add(it, o.front); print("queued", it["id"], label(it))
    elif o.cmd == "start": start(next_time(o.at) if o.at else None)
    elif o.cmd == "pause": pause_at(next_time(o.at)) if o.at else pause("paused from the shell")
    elif o.cmd == "remove": remove(o.id)
    elif o.cmd == "clear": clear()
    elif o.cmd == "runner": runner(); return
    st = snapshot()
    state_ = "paused" if st["paused"] else "running"
    print(f"queue {state_}{' (' + st['note'] + ')' if st['note'] else ''}; runner {'up' if st['runner_alive'] else 'not running'}"
          + (f"; starts {hhmm(st['start_at'])}" if st["start_at"] else "") + (f"; pauses {hhmm(st['pause_at'])}" if st["pause_at"] else ""))
    for i in st["items"]:
        print(f"  {i['id']}  {i['status']:<7} {label(i)}" + (f"  [{i['note']}]" if i.get("note") else "")
              + (f"  job {i['job']}" if i.get("job") else ""))

if __name__ == "__main__":
    main()
