#!/usr/bin/env python3
"""hbench web UI: browse every run, launch and stop runs, follow live logs.

  python3 web/app.py [--port 8090]      then open http://127.0.0.1:8090

Stdlib only. Listens on 127.0.0.1. Reads runs/ directly, so it also sees runs started from the shell
(fast.sh / latex.sh / long.sh / server.sh), and can stop those too. Jobs it launches log to web/jobs/<id>.log.
Only one benchmark job at a time, like the harness itself (memory). The job queue (pause, resume,
scheduled start and pause) is ../jobq.py; this UI drives it, and it keeps running without the UI.
"""
import argparse, glob, json, os, re, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS, SUITES, WEB = f"{H}/runs", f"{H}/suites", f"{H}/web"
JOBS = f"{WEB}/jobs"
SKIP_DIRS = {".git", "__pycache__", "grids", "outputs", "gbuild", ".DS_Store"}
os.makedirs(JOBS, exist_ok=True)
sys.path.insert(0, H)
import hb, jobq
from hb import ps, descendants
procs = {}  # Popen objects of jobs started here, so they get reaped

# ---------------------------------------------------------------- helpers

def read(path, limit=2_000_000):
    try:
        with open(path, "rb") as f:
            b = f.read(limit + 1)
    except OSError:
        return None
    text = b[:limit].decode("utf-8", "replace")
    return text + ("\n… (truncated)" if len(b) > limit else "")

def jload(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default

def models():
    """The models for the browser: no API keys."""
    return {n: dict(id=m["id"], label=m["label"], url=m["url"], managed=m["managed"]) for n, m in hb.models().items()}

def cases():
    return list(hb.cases())

SUITE_OF = dict(fast="short", latex="latex")
_items = {}
def items(tier="fast"):
    """A one-shot tier's items; cached because long.sh locks suites/ (chmod 000) while an agent runs."""
    suite = SUITE_OF[tier]
    fresh = jload(f"{SUITES}/{suite}/items.json")
    if fresh:
        for it in fresh:
            it["prompt_text"] = read(f"{SUITES}/{suite}/{it['prompt']}")
        _items[tier] = fresh
    return _items.get(tier, [])

def safe(rel):
    """Resolve a path under runs/ or web/jobs/; anything else is refused."""
    p = os.path.realpath(os.path.join(H, rel))
    if not (p.startswith(RUNS + os.sep) or p.startswith(JOBS + os.sep)):
        raise ValueError("path outside runs/")
    return p

mem = hb.mem

def port_up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=0.7) as r:
            return b'"id"' in r.read()
    except Exception:
        return False

def server_state():
    ports = sorted({m["port"] for m in hb.models().values() if m["managed"] and m["port"]})
    up = [p for p in ports if port_up(p)]
    name = (read(f"{RUNS}/.server") or "").strip() or None
    return dict(up_ports=up, model=name if up else None, recorded=name)

# ---------------------------------------------------------------- processes and jobs

def ui_jobs():
    js = []
    for f in sorted(glob.glob(f"{JOBS}/*.json"), reverse=True):
        j = jload(f)
        if not j: continue
        rc = read(f"{JOBS}/{j['id']}.rc")
        j["rc"] = int(rc) if rc and rc.strip().lstrip("-").isdigit() else None
        js.append(j)
    return js

def running_jobs():
    """Benchmark scripts running now, from the UI, the queue or a shell: the outermost fast/latex/long/server.sh processes."""
    rows = ps()
    for p in list(procs.values()):
        p.poll()  # reap finished children
    uis = {j["wrapper_pid"]: j for j in ui_jobs() if j.get("rc") is None}
    out = []
    for oj in jobq.outer_jobs(rows):
        pid, kind, args = oj["pid"], oj["kind"], oj["args"]
        desc = descendants(rows, pid)
        agent = next((d for d in desc if "limit.py" in rows[d]["cmd"]), None)
        ui = uis.get(rows[pid]["ppid"]) or uis.get(pid)
        j = dict(pid=pid, kind=kind, args=args, etime=rows[pid]["etime"], agent_pid=agent,
                 ui_job=ui["id"] if ui else None, queue_item=ui.get("queue_item") if ui else None,
                 model=args[1] if kind == "server" else (args[0] if args else None))
        if kind == "long" and len(args) > 1:
            j["case"] = args[1]; j["phase"] = "agent" if agent else "setup/grading"
        if kind in jobq.ONESHOT:
            j["ids"] = args[1:]
        out.append(j)
    return out

def stop(pid, mode):
    rows = ps()
    if pid not in rows or not any(pid == j["pid"] for j in running_jobs()):
        raise ValueError("not a running benchmark job")
    desc = descendants(rows, pid)
    agents = [d for d in desc if "limit.py" in rows[d]["cmd"]]
    if mode == "agent":
        if not agents: raise ValueError("no agent running in this job")
        for a in agents: os.kill(a, signal.SIGTERM)  # limit.py kills pi's group; long.sh then grades
        return "agent stopped; long.sh will grade what it has"
    # abort: agent group first, then the job tree (deepest first), then SIGKILL anything left
    for a in agents:
        try: os.kill(a, signal.SIGTERM)
        except ProcessLookupError: pass
    leaders = {rows[d]["pgid"] for d in desc if rows[d]["pgid"] == d}
    targets = list(reversed(desc)) + [pid]
    wrapper = rows[pid]["ppid"]
    if any(j.get("wrapper_pid") == wrapper for j in ui_jobs()): targets.append(wrapper)
    def kill_all(sig):
        for g in leaders:
            try: os.killpg(g, sig)
            except (ProcessLookupError, PermissionError): pass
        for t in targets:
            try: os.kill(t, sig)
            except ProcessLookupError: pass
    kill_all(signal.SIGTERM)
    def later():
        time.sleep(5); kill_all(signal.SIGKILL); time.sleep(1); unlock_suites()
    threading.Thread(target=later, daemon=True).start()
    return "aborted"

def unlock_suites():
    """long.sh unlocks suites/ in its EXIT trap; restore it if an abort skipped that."""
    if not any(j["kind"] == "long" for j in running_jobs()) and (os.stat(SUITES).st_mode & 0o777) == 0:
        os.chmod(SUITES, 0o755)

def launch(a):
    kind, ms = a.get("kind"), models()
    busy = [j for j in running_jobs()]
    if busy and kind != "server_down":
        raise ValueError(f"a job is already running ({busy[0]['kind']} {' '.join(busy[0]['args'])}); stop it first")
    env = {}
    model = a.get("model")
    if kind in (*jobq.ONESHOT, "long", "server_up") and model not in ms:
        raise ValueError(f"unknown model {model}")
    if kind in jobq.ONESHOT:
        ids = [i for i in (a.get("ids") or []) if re.fullmatch(jobq.ONESHOT[kind], i)]
        argv = [f"{H}/{kind}.sh", model] + ids
        if a.get("max_tokens"): env["MAX_TOKENS"] = str(int(a["max_tokens"]))
        if a.get("effort"): env["EFFORT"] = re.sub(r"[^a-z]", "", a["effort"])
        if kind == "fast" and a.get("attempts") and int(a["attempts"]) > 1: env["ATTEMPTS"] = str(int(a["attempts"]))
    elif kind == "selftest":
        argv = [f"{H}/fast.sh", "selftest"]
    elif kind == "latex_selftest":
        argv = [f"{H}/latex.sh", "selftest"]
    elif kind == "long":
        if a.get("case") not in hb.cases(): raise ValueError("unknown case")
        argv = [f"{H}/long.sh", model, a["case"]]
        if a.get("limit"): env["LIMIT"] = str(int(a["limit"]))
        if a.get("fresh"): env["FRESH"] = "1"
    elif kind == "server_up":
        argv = [f"{H}/server.sh", "up", model]
    elif kind == "server_down":
        argv = [f"{H}/server.sh", "down"]
    else:
        raise ValueError("unknown kind")
    rec, p = jobq.spawn(argv, env, kind=kind)
    procs[rec["id"]] = p
    if kind in (*jobq.ONESHOT, "long") and jobq.snapshot()["pause_at"]:  # so a scheduled pause also stops this job
        keep(jobq.ensure_runner())
    return rec

def keep(p):
    if p: procs[f"runner-{p.pid}"] = p  # reaped by running_jobs()

def queue_op(a):
    op = a.get("op")
    at = float(a["at"]) if a.get("at") else None
    if op == "add":
        it = jobq.make_item(a.get("kind"), a.get("model"), ids=a.get("ids"), case=a.get("case"), max_tokens=a.get("max_tokens"),
                            effort=a.get("effort"), limit=a.get("limit"), fresh=a.get("fresh"),
                            attempts=a.get("attempts") if a.get("kind") == "fast" else None)
        it, p = jobq.add(it, bool(a.get("front"))); keep(p)
        return {"message": f"queued {' '.join(it['argv'])}"}
    if op == "start":
        keep(jobq.start(at)); return {"message": f"queue starts at {jobq.hhmm(at)}" if at else "queue started"}
    if op == "pause":
        if at:
            keep(jobq.pause_at(at)); return {"message": f"queue pauses at {jobq.hhmm(at)}"}
        threading.Thread(target=jobq.pause, args=("paused from the web UI",), daemon=True).start()
        return {"message": "pausing: stopping the job and the server"}
    if op == "cancel_pause_at": jobq.pause_at(None); return {"message": "scheduled pause cleared"}
    if op == "cancel_start_at": jobq.cancel_start(); return {"message": "scheduled start cleared; the queue stays paused"}
    if op == "remove": jobq.remove(a["id"]); return {"message": "removed"}
    if op == "move": jobq.move(a["id"], -1 if a.get("dir") == "up" else 1); return {"message": "moved"}
    if op == "clear": jobq.clear(); return {"message": "cleared finished entries"}
    if op == "keep_server": jobq.set_keep_server(a.get("value")); return {"message": "saved"}
    raise ValueError("unknown queue op")

# ---------------------------------------------------------------- results

def reviews(model):
    out = {}
    for f in glob.glob(f"{RUNS}/{model}/**/review.json", recursive=True):
        rel = os.path.relpath(os.path.dirname(f), f"{RUNS}/{model}")
        for k, v in (jload(f, {}).get("cases") or {}).items():
            out[os.path.normpath(os.path.join(rel, k)) if rel != "." else k] = v
    return out

def results():
    live = running_jobs()
    run_models = sorted(d for d in os.listdir(RUNS) if os.path.isdir(f"{RUNS}/{d}") and not d.startswith("."))
    oneshot, long = {t: {} for t in jobq.ONESHOT}, {}
    for m in run_models:
        rv = reviews(m)
        for tier in jobq.ONESHOT:
            fd = f"{RUNS}/{m}/{tier}"
            if not os.path.isdir(fd): continue
            g = jload(f"{fd}/grades.json", {})
            gm = os.path.getmtime(f"{fd}/grades.json") if g else 0
            fl = [j for j in live if j["kind"] == tier and j["model"] == m]
            row = dict(total=g.get("_total"), live=bool(fl), items={})
            for it in [i["id"] for i in items(tier)] or sorted(os.listdir(fd)):
                d = f"{fd}/{it}"
                meta = jload(f"{d}/meta.json")
                gi = g.get(it)
                att = attempt_dirs(d)
                done = [x for x in att if os.path.exists(f"{x}/meta.json")]
                if meta:
                    st = "graded" if gi and gm >= max(os.path.getmtime(f"{x}/meta.json") for x in done) else "ungraded"
                elif os.path.isdir(d):
                    st = "running" if fl else "incomplete"
                else:
                    st = "missing"
                row["items"][it] = dict(status=st, auto=gi and gi.get("auto"), max=gi and gi.get("max"),
                                        truncated=bool(meta and meta.get("truncated")) or any(x.get("truncated") for x in (gi or {}).get("attempts") or []),
                                        seconds=meta and meta.get("seconds"), tokens=meta and meta.get("completion_tokens"), judge=rv.get(f"{tier}/{it}"),
                                        attempts=len(done), attempt_scores=[x["auto"] for x in (gi or {}).get("attempts") or []],
                                        pending=bool(fl) and len(done) < len(att))
            oneshot[tier][m] = row
        ld = f"{RUNS}/{m}/long"
        if os.path.isdir(ld):
            hist = {}
            for l in (read(f"{ld}/results.jsonl") or "").splitlines():
                try: r = json.loads(l)
                except ValueError: continue
                hist.setdefault(r["case"], []).append(r)
            row = {}
            for c in cases():
                ll = [j for j in live if j["kind"] == "long" and j["model"] == m and j.get("case") == c]
                if c not in hist and not os.path.isdir(f"{ld}/{c}") and not ll: continue
                row[c] = dict(latest=(hist.get(c) or [None])[-1], runs=len(hist.get(c, [])), live=bool(ll),
                              judge=rv.get(f"long/{c}"), has_dir=os.path.isdir(f"{ld}/{c}"))
            long[m] = row
    return dict(**oneshot, long=long, cases=cases(), case_titles={k: v.get("title", k) for k, v in hb.cases().items()}, items=[dict(id=i["id"], title=i["title"]) for i in items()],
                latex_items=[dict(id=i["id"], title=i["title"]) for i in items("latex")],
                models=list(models()), run_models=run_models)

def attempt_dirs(d):
    """A one-shot item's attempt folders: the item folder (attempt 1), then r2, r3, ... (fast.sh ATTEMPTS)."""
    rs = sorted(int(x[1:]) for x in (os.listdir(d) if os.path.isdir(d) else []) if re.fullmatch(r"r\d+", x))
    return ([d] if os.path.isdir(d) else []) + [f"{d}/r{n}" for n in rs if n > 1]

def fast_item(model, it, tier="fast", attempt=1):
    if tier not in jobq.ONESHOT: raise ValueError("unknown tier")
    attempt = int(attempt)
    base = f"{RUNS}/{model}/{tier}/{it}"
    d = base if attempt == 1 else f"{base}/r{attempt}"
    safe(os.path.relpath(d, H))
    g = jload(f"{RUNS}/{model}/{tier}/grades.json", {})
    gi = g.get(it); jdir = "judge" if attempt == 1 else f"judge/r{attempt}"
    if gi and gi.get("attempts"):  # that attempt's own score and checks (the item's auto is the mean)
        a = next((x for x in gi["attempts"] if x["n"] == attempt), None)
        gi = dict(gi, checks=a["checks"], auto=a["auto"], figure=a["figure"], error=a["error"]) if a else None
    info = next((i for i in items(tier) if i["id"] == it), {})
    window = item_window(d)
    return dict(window=window, meta=jload(f"{d}/meta.json"), response=read(f"{d}/response.md"), reasoning=read(f"{d}/reasoning.md"),
                grade=gi, attempt=attempt, n_attempts=len(attempt_dirs(base)), mean=(g.get(it) or {}).get("auto"),
                judge_dir=jdir, judge_packet=read(f"{RUNS}/{model}/{tier}/{jdir}/{it}.md"),
                review=reviews(model).get(f"{tier}/{it}"), title=info.get("title"), prompt=info.get("prompt_text"),
                oracle_notes=info.get("oracle_notes"))

def item_window(d):
    """When a one-shot item ran: from its meta.json (written at the end, with the seconds it took), or since the folder
    was made while it is running."""
    if not os.path.isdir(d): return None
    meta = jload(f"{d}/meta.json")
    if meta and meta.get("seconds") is not None:
        end = os.path.getmtime(f"{d}/meta.json")
        return dict(start=end - meta["seconds"], end=end)
    return dict(start=birth(d), end=None)

def fast_model(model, tier="fast"):
    if tier not in jobq.ONESHOT: raise ValueError("unknown tier")
    fd = f"{RUNS}/{model}/{tier}"
    dirs = [f"{fd}/{x}" for x in os.listdir(fd) if re.fullmatch(jobq.ONESHOT[tier], x)] if os.path.isdir(fd) else []
    live = any(j["kind"] == tier and j["model"] == model for j in running_jobs())
    metas = [os.path.getmtime(f"{d}/meta.json") for d in dirs if os.path.exists(f"{d}/meta.json")]
    window = dict(start=min(item_window(d)["start"] for d in dirs), end=None if live or not metas else max(metas)) if dirs else None
    return dict(window=window, log_path=os.path.relpath(f"{fd}/{tier}.log", H), grade_txt=read(f"{fd}/grade.txt"),
                total=(jload(f"{fd}/grades.json", {}) or {}).get("_total"))

def long_run(model, case):
    d = f"{RUNS}/{model}/long/{case}"
    safe(os.path.relpath(d, H))
    hist = [r for r in (json.loads(l) for l in (read(f"{RUNS}/{model}/long/results.jsonl") or "").splitlines() if l.strip())
            if r.get("case") == case]
    logs = sorted(os.listdir(f"{d}/logs")) if os.path.isdir(f"{d}/logs") else []
    window = None
    if "prompt.md" in logs:
        start = os.path.getmtime(f"{d}/logs/prompt.md")  # written once, as the run starts
        live = any(j["kind"] == "long" and j["model"] == model and j.get("case") == case for j in running_jobs())
        window = dict(start=start, end=None if live or not hist else start + hist[-1]["seconds"])
    return dict(window=window, history=hist, review=reviews(model).get(f"long/{case}"), review_md=read(f"{d}/REVIEW.md"),
                logs=logs, base=os.path.relpath(d, H), has_work=os.path.isdir(f"{d}/work"))

def tree(rel):
    root = safe(rel)
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(x for x in dns if x not in SKIP_DIRS and not x.startswith("build"))
        for f in sorted(fns):
            if f in SKIP_DIRS: continue
            p = os.path.join(dp, f)
            try: out.append(dict(path=os.path.relpath(p, H), size=os.path.getsize(p)))
            except OSError: pass
            if len(out) >= 3000: return out
    return out

def file_text(rel):
    p = safe(rel)
    with open(p, "rb") as f:
        head = f.read(8192)
    if b"\0" in head:
        return dict(binary=True, size=os.path.getsize(p))
    return dict(text=read(p, 1_500_000), size=os.path.getsize(p))

def tail(rel, offset):
    p = safe(rel)
    size = os.path.getsize(p) if os.path.exists(p) else 0
    if offset < 0 or offset > size:
        offset = max(0, size - 65536)
    with open(p, "rb") if size else open(os.devnull, "rb") as f:
        f.seek(offset)
        data = f.read(1_000_000)
    return dict(data=data.decode("utf-8", "replace"), offset=offset + len(data), size=size, exists=os.path.exists(p))

# ---------------------------------------------------------------- judge packet as PDF

def packet_pdf(rel):
    """A judge packet (runs/<model>/<fast|latex>/judge/<item>.md or runs/<model>/long/<case>/logs/judge_packet.md) as a PDF:
    pandoc to HTML styled by web/pdf.css, then headless Chrome prints it. Returns (filename, bytes)."""
    p = safe(rel)
    parts = os.path.relpath(p, RUNS).split(os.sep)
    if len(parts) == 5 and parts[2] == "judge" and re.fullmatch(r"r\d+", parts[3]):  # attempt n's packet: judge/r<n>/<item>.md
        parts = parts[:3] + [parts[4][:-3] + f"-{parts[3]}.md"]
    if not (parts[-1] == "judge_packet.md" or (len(parts) == 4 and parts[1] in jobq.ONESHOT and parts[2] == "judge" and parts[3].endswith(".md"))):
        raise ValueError("not a judge packet")
    browser = hb.pdf_browser()
    if not browser or not shutil.which("pandoc"):
        raise ValueError("making a PDF needs pandoc and Chrome, Chromium or Edge (or set pdf_browser in config.json); see README")
    what = f"{parts[0]} · {parts[1]} {parts[3][:-3]}" if parts[1] in jobq.ONESHOT else f"{parts[0]} · long {parts[2]}"
    name = f"hbench-{parts[0]}-{parts[1]}-{parts[3][:-3] if parts[1] in jobq.ONESHOT else parts[2]}-judge.pdf"
    with tempfile.TemporaryDirectory() as d:
        open(f"{d}/head.html", "w").write(f"<style>{open(f'{WEB}/pdf.css').read()}</style>")
        open(f"{d}/before.html", "w").write(f'<div class="hb-head">hbench judge packet · {what} · {rel} · '
                                            f'{time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))}</div>')
        subprocess.run(["pandoc", p, "-f", "markdown-smart", "-t", "html5", "-s", "--math-method=mathml", "--metadata", f"pagetitle={name}",
                        "--embed-resources", f"--resource-path={os.path.dirname(p)}",
                        "-H", f"{d}/head.html", "-B", f"{d}/before.html", "-o", f"{d}/p.html"], check=True, capture_output=True, timeout=60)
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={d}/chrome",
                        f"--print-to-pdf={d}/p.pdf", f"file://{d}/p.html"], capture_output=True, timeout=120)
        if not os.path.exists(f"{d}/p.pdf"): raise ValueError("Chrome did not write the PDF")
        return name, open(f"{d}/p.pdf", "rb").read()

# ---------------------------------------------------------------- server log timings
# llama-server: "M.SS.mmm.uuu I slot print_timing: id 0 | task 7 | prompt eval time = 593.31 ms / 139 tokens (... 234.28 tokens per second)"
# (time since server start), the same for "eval time", and with newer builds "n_gen = 136, tg = 44.71 t/s, tg_3s = 45.04 t/s"
# every 3 s while generating. splash: "HH:MM:SS Done · input 3,037 · cached 0 · ... · output 98 · ... · TTFT 12.0s · 8.0 tok/s".
# bmoe-server logs no per-request timings. server.sh starts each log with "# hbench server start <epoch>" (hb.log_start),
# which the times since start are counted from; earlier logs go to runs/server-logs/.
LTS = r"^(\d+)\.(\d\d)\.(\d{3})\.\d{3} I slot print_timing: id +(\d+) \| task (\d+) \| "
RE_EVAL = re.compile(LTS + r"(prompt eval| *eval) time = +([\d.]+) ms / +(\d+) tokens .*?([\d.]+) tokens per second")
RE_PROG = re.compile(LTS + r"n_gen = +(\d+), tg = +([\d.]+) t/s, tg_3s = +([\d.]+) t/s")
RE_SPLASH = re.compile(r"^(\d\d):(\d\d):(\d\d) Done · input ([\d,]+) · cached ([\d,]+).*? · output ([\d,]+).*?TTFT ([\d.]+)s · ([\d.]+) tok/s")
RE_GUARD = re.compile(r"exit=(-?\d+) min_level=(\d+)%")

def parse_server_log(p):
    st = os.stat(p)
    base = hb.log_start(p)
    reqs, prog, guard, kind = {}, [], None, None
    day, last = time.mktime(time.localtime(base)[:3] + (0, 0, 0, 0, 0, -1)), -1
    for l in (read(p, 50_000_000) or "").splitlines():
        if m := RE_EVAL.match(l):
            t = base + int(m[1]) * 60 + int(m[2]) + int(m[3]) / 1000
            r = reqs.setdefault((int(m[4]), int(m[5])), dict(slot=int(m[4]), task=int(m[5])))
            k = "prompt" if m[6].startswith("prompt") else "gen"
            r.update({f"{k}_ms": float(m[7]), f"{k}_n": int(m[8]), f"{k}_tps": float(m[9]), "t": t})
            kind = "llama"
        elif m := RE_PROG.match(l):
            prog.append(dict(t=base + int(m[1]) * 60 + int(m[2]) + int(m[3]) / 1000, slot=int(m[4]), n=int(m[6]), tps=float(m[8])))
        elif m := RE_SPLASH.match(l):
            sec = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
            if sec < last: day += 86400
            last = sec
            n = lambda s: int(s.replace(",", ""))
            reqs[len(reqs)] = dict(t=day + sec, prompt_n=n(m[4]) - n(m[5]), cached=n(m[5]), gen_n=n(m[6]),
                                   ttft=float(m[7]), gen_tps=float(m[8]))
            kind = "splash"
        elif m := RE_GUARD.search(l):
            guard = dict(exit=int(m[1]), min_level=int(m[2]))
    rows = sorted((r for r in reqs.values() if "t" in r), key=lambda r: r["t"])
    for r in rows:  # start of the request, for placing it in a run's time window
        r["t0"] = r["t"] - (r.get("prompt_ms", 0) + r.get("gen_ms", 0)) / 1000 if kind == "llama" else r["t"] - r["ttft"] - r["gen_n"] / max(r["gen_tps"], 1e-9)
    return dict(base=base, end=st.st_mtime, size=st.st_size, kind=kind, rows=rows, prog=prog, guard=guard)

# splash logs a request only when it ends; while one runs, its /status lists it with generated_tokens and age_ms.
# Each poll of a live Server page samples that, so splash gets progress points like llama-server's every-3-s lines.
# The samples live in this process only (a restart of app.py starts the chart afresh).
SPLASH_PROG = {}

def splash_progress(model):
    m = hb.models().get(model) or {}
    hist = SPLASH_PROG.setdefault(model, [])
    if not m.get("port"):
        return hist
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{m['port']}/status", timeout=0.7) as r:
            active = json.load(r).get("active_requests") or []
    except Exception:
        return hist
    now = time.time()
    for a in active:
        if a.get("phase") != "decode": continue
        n = int(a.get("generated_tokens") or 0)
        prev = next((x for x in reversed(hist) if x["slot"] == a.get("id")), None)
        if prev and now > prev["t"] and n >= prev["n"] and now - prev["t"] < 60:
            tps = (n - prev["n"]) / (now - prev["t"])
        else:  # first sample of a request: its average so far
            tps = n / max((a.get("age_ms") or 0) / 1000, 1e-9)
        hist.append(dict(t=now, slot=a.get("id"), n=n, tps=tps))
    del hist[:-2000]
    return hist

def server_logs(model):
    """The model's server logs, oldest first: those server.sh kept in runs/server-logs/, then the current one."""
    cur = f"{RUNS}/server-{model}.log"
    return sorted(glob.glob(f"{RUNS}/server-logs/server-{model}.*.log"), key=hb.log_start) + ([cur] if os.path.exists(cur) else [])

def server_stats(model, since=None, until=None):
    safe(f"runs/server-{model}.log")
    logs = server_logs(model)
    if since is None:  # the Server page: the server as it is now
        logs = logs[-1:]
    else:  # a run's window: every server that was up during it (a run can span a restart)
        logs = [p for p in logs if hb.log_start(p) <= (until or time.time()) + 5 and os.path.getmtime(p) >= since - 5]
    if not logs:
        return dict(exists=False)
    parsed = [parse_server_log(p) for p in logs]
    rows = sorted((r for x in parsed for r in x["rows"]), key=lambda r: r["t"])
    prog = sorted((x for y in parsed for x in y["prog"]), key=lambda x: x["t"])
    kind = next((x["kind"] for x in reversed(parsed) if x["kind"]), None)
    guard = min((x["guard"] for x in parsed if x["guard"]), key=lambda g: g["min_level"], default=None)
    base = parsed[0]["base"]
    inside = lambda t: (since is None or t >= since - 5) and (until is None or t <= until + 5)
    # A request belongs to the window by when it started: back-to-back items start within milliseconds of the
    # previous request's end, so matching on the end time (with the slack the log's clock needs) let the
    # previous item's request in. Progress samples during a request left out are left out too.
    mine = lambda r: (since is None or r["t0"] >= since - 2) and (until is None or (r["t0"] <= until + 1 and r["t"] <= until + 5))
    if (kind == "splash" or hb.models().get(model, {}).get("provider") == "splash") and (until is None or until >= time.time() - 10):
        prog = sorted(prog + splash_progress(model), key=lambda x: x["t"])
    others = [r for r in rows if not mine(r)]
    rows = [r for r in rows if mine(r)]
    prog = [x for x in prog if inside(x["t"]) and not any(r["t0"] - 1 <= x["t"] <= r["t"] + 1 for r in others)]
    starts = [x for x in run_starts(model) if x["t"] >= base - 5 and inside(x["t"])]
    return dict(exists=True, kind=kind or "none", started=parsed[-1]["base"], size=sum(x["size"] for x in parsed), requests=rows,
                progress=prog, guard=guard, starts=starts, logs=[os.path.relpath(p, H) for p in logs])

def clock_lines(path, pattern):
    """Lines of a log that start with HH:MM:SS, as (epoch, match). The last line is on the day the file was last
    written; going back, the day changes wherever the clock goes backwards."""
    if not os.path.exists(path):
        return []
    rows, last, wraps = [], -1, 0
    for l in (read(path) or "").splitlines():
        m = re.match(r"^(\d\d):(\d\d):(\d\d) ", l)
        if not m: continue
        sec = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if sec < last: wraps += 1
        last = sec
        if mm := re.search(pattern, l):
            rows.append((wraps, sec, mm))
    end_day = time.mktime(time.localtime(os.path.getmtime(path))[:3] + (0, 0, 0, 0, 0, -1))
    return [(end_day - (wraps - w) * 86400 + sec, mm) for w, sec, mm in rows]

def run_starts(model):
    """Where each benchmark run on this model began: fast.sh and latex.sh suites and long.sh agent starts."""
    out = [dict(t=t, kind="fast", label="fast", detail=f"short suite{m[1]}", link=f"#/fast/{model}")
           for t, m in clock_lines(f"{RUNS}/{model}/fast/fast.log", r"short suite on \S+(.*)")]
    out += [dict(t=t, kind="latex", label="latex", detail=f"latex suite{m[1]}", link=f"#/latex/{model}")
            for t, m in clock_lines(f"{RUNS}/{model}/latex/latex.log", r"latex suite on \S+(.*)")]
    for f in glob.glob(f"{RUNS}/{model}/long/*/logs/long.log"):
        case = f.split("/")[-3]
        out += [dict(t=t, kind="long", label=case, detail=f"long {case}: {m[1]}", link=f"#/long/{model}/{case}")
                for t, m in clock_lines(f, r"agent start: (.*)")]
    return sorted(out, key=lambda x: x["t"])

def birth(p):
    st = os.stat(p)
    return getattr(st, "st_birthtime", st.st_ctime)

# ---------------------------------------------------------------- pi transcript (same reading as view.py)

def text_of(result):
    if isinstance(result, dict):
        parts = result.get("content") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict)) or json.dumps(result)[:4000]
    return str(result)

def tool_event(cid, name, args):
    """A tool call for the transcript; pi's argument names, or dsh's (file_path, old_string/new_string)."""
    path = args.get("path") or args.get("file_path")
    ev_ = dict(t="tool", id=cid, name=name, path=path, command=args.get("command"),
               shown=args.get("command") or path or json.dumps(args)[:500])
    if name == "edit":  # pi: {path, edits: [{oldText, newText}]}; older: {path, oldText, newText}; dsh: {file_path, old_string, new_string}
        eds = args.get("edits") or ([dict(oldText=args.get("oldText"), newText=args.get("newText"))] if "oldText" in args else
                                    [dict(oldText=args.get("old_string"), newText=args.get("new_string"))] if "old_string" in args else [])
        ev_["edits"] = [dict(old=(x.get("oldText") or "")[:20000], new=(x.get("newText") or "")[:20000]) for x in eds]
    elif name == "write":
        ev_["content"] = (args.get("content") or "")[:40000]
    elif name not in ("bash", "read"):
        ev_["extra"] = json.dumps(args, indent=1)[:20000]
    return ev_

def transcript(rel, offset):
    """pi's --mode json stream, or dsh's --json events (tools/agent-dsh.sh; strings there are capped at 8 KiB)."""
    p = safe(rel)
    if not os.path.exists(p):
        return dict(events=[], offset=0, exists=False)
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read(16_000_000)
    end = data.rfind(b"\n") + 1
    ev = []
    def add(e):  # merge consecutive deltas of the same block (pi interleaves blocks by contentIndex)
        if e["t"] == "add" and ev and ev[-1]["t"] == "add" and ev[-1].get("i") == e.get("i"): ev[-1]["s"] += e["s"]
        else: ev.append(e)
    for line in data[:end].splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        t = e.get("type")
        if t == "message_update":
            a = e.get("assistantMessageEvent") or {}
            k = a.get("type")
            i = a.get("contentIndex")
            if k in ("thinking_start", "text_start"): add(dict(t="open", k=k.split("_")[0], i=i))
            elif k in ("thinking_delta", "text_delta"): add(dict(t="add", s=a.get("delta", ""), i=i))
            elif k in ("thinking_end", "text_end"): add(dict(t="close", i=i))
            elif k == "toolcall_end":
                tc = a.get("toolCall") or {}
                add(tool_event(tc.get("id"), tc.get("name"), tc.get("arguments") or {}))
        elif t == "tool_execution_end":
            add(dict(t="result", id=e.get("toolCallId"), name=e.get("toolName"), s=text_of(e.get("result"))[:40000], err=bool(e.get("isError"))))
        elif t == "message_end":
            m = e.get("message") or {}
            if m.get("role") == "user":
                add(dict(t="prompt", s="".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict))))
            elif m.get("role") == "assistant":
                u = m.get("usage") or {}
                add(dict(t="turn", inp=u.get("input", 0), cached=u.get("cacheRead", 0), out=u.get("output", 0),
                         stop=m.get("stopReason"), err=m.get("errorMessage")))
        elif t in ("compaction_start", "compaction_end", "auto_retry_start", "auto_retry_end"):
            add(dict(t="sys", s=f"{t} " + json.dumps({k: v for k, v in e.items() if k not in ("type", "result")})[:300]))
        elif t == "agent_end":
            add(dict(t="sys", s="agent finished"))
        # dsh: whole blocks (no deltas), so a live view updates once per step
        elif t == "session" and "sessionId" in e:  # pi's session line has "id"
            prompt = os.path.join(os.path.dirname(p), "prompt.md")
            if os.path.exists(prompt): add(dict(t="prompt", s=open(prompt).read()))
        elif t in ("thinking", "text"):
            add(dict(t="open", k=t, i=None)); add(dict(t="add", s=e.get("text", ""), i=None)); add(dict(t="close", i=None))
        elif t == "tool_call":
            add(tool_event(e.get("callId"), e.get("tool"), e.get("input") if isinstance(e.get("input"), dict) else {}))
        elif t == "tool_result":
            add(dict(t="result", id=e.get("callId"), name=None, s=str(e.get("result", ""))[:40000], err=e.get("status") == "error"))
        elif t == "status" and e.get("phase") == "step_end":
            u = e.get("usage") or {}
            add(dict(t="turn", inp=u.get("inputTokens", 0), cached=u.get("cacheReadTokens", 0), out=u.get("outputTokens", 0), stop="step", err=None))
        elif t == "status" and e.get("phase") == "turn_end":
            add(dict(t="sys", s=f"turn end: {(e.get('reason') or {}).get('kind')}"))
        elif t == "error":
            add(dict(t="sys", s=f"error: {e.get('message')}"))
        elif t == "final":
            add(dict(t="sys", s="agent finished"))
    return dict(events=ev, offset=offset + end, exists=True)

# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def host_ok(self):
        # Refuse other Host headers (DNS rebinding) so only pages served from here can use the API.
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self.host_ok(): return self.send(403, {"error": "bad host"})
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self.send(200, open(f"{WEB}/index.html", "rb").read(), "text/html")
            if u.path == "/api/pdf":
                # Only for this UI's own pages (a link elsewhere can't make it start Chrome).
                if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"): return self.send(403, {"error": "forbidden"})
                name, pdf = packet_pdf(q["path"])
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(pdf)))
                self.end_headers()
                return self.wfile.write(pdf)
            if u.path == "/api/image":  # figures under runs/ (p01's plot in its judge packet)
                f = safe(q["path"]); ext = f.rsplit(".", 1)[-1].lower()
                types = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}
                if ext not in types or not os.path.isfile(f): return self.send(404, {"error": "not found"})
                b = open(f, "rb").read()
                self.send_response(200); self.send_header("Content-Type", types[ext]); self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store"); self.end_headers()
                return self.wfile.write(b)
            if u.path.startswith("/vendor/"):  # highlight.js, kept locally so the UI works offline
                f = os.path.realpath(f"{WEB}{u.path}")
                if not f.startswith(f"{WEB}/vendor/") or not os.path.isfile(f): return self.send(404, {"error": "not found"})
                return self.send(200, open(f, "rb").read(), "text/css" if f.endswith(".css") else "text/javascript")
            r = {
                "/api/status": lambda: dict(server=server_state(), mem=mem(), jobs=running_jobs(), recent=ui_jobs()[:15], queue=jobq.snapshot(),
                                            suites_locked=(os.stat(SUITES).st_mode & 0o777) == 0, models=models()),
                "/api/results": results,
                "/api/fast_item": lambda: fast_item(q["model"], q["item"], q.get("tier", "fast"), q.get("attempt", 1)),
                "/api/fast_model": lambda: fast_model(q["model"], q.get("tier", "fast")),
                "/api/long_run": lambda: long_run(q["model"], q["case"]),
                "/api/tree": lambda: tree(q["path"]),
                "/api/server_stats": lambda: server_stats(q["model"], float(q["since"]) if q.get("since") else None,
                                                          float(q["until"]) if q.get("until") else None),
                "/api/file": lambda: file_text(q["path"]),
                "/api/tail": lambda: tail(q["path"], int(q.get("offset", -1))),
                "/api/transcript": lambda: transcript(q["path"], int(q.get("offset", 0))),
            }.get(u.path)
            if not r: return self.send(404, {"error": "not found"})
            self.send(200, r())
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
            self.send(400, {"error": str(e)})

    def do_POST(self):
        # The custom header can't be sent cross-site without CORS, which this server never allows.
        if not self.host_ok() or self.headers.get("X-HBench") != "1":
            return self.send(403, {"error": "forbidden"})
        try:
            a = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/launch": return self.send(200, launch(a))
            if self.path == "/api/queue": return self.send(200, queue_op(a))
            if self.path == "/api/stop": return self.send(200, {"message": stop(int(a["pid"]), a.get("mode", "abort"))})
            self.send(404, {"error": "not found"})
        except (ValueError, KeyError, OSError) as e:
            self.send(400, {"error": str(e)})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    port = ap.parse_args().port
    items()
    print(f"hbench UI on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
