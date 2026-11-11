#!/usr/bin/env python3
"""Tables of results across models.  Usage: summary.py [fast|latex|long]  (all by default)
fast, latex: runs/<model>/<tier>/grades.json.  long: runs/<model>/long/results.jsonl (latest line per case).
Judge scores come from any review.json the hbench-review skill wrote under runs/<model>/ (keys like
"long/x02" or "fast/p03"), shown as score/max after the automatic one."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hb

RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
want = sys.argv[1:] or ["fast", "latex", "long"]

def reviews(model):
    out = {}
    for f in glob.glob(f"{RUNS}/{model}/**/review.json", recursive=True):
        rel = os.path.relpath(os.path.dirname(f), f"{RUNS}/{model}")
        for k, v in json.load(open(f)).get("cases", {}).items():
            key = os.path.normpath(os.path.join(rel, k)) if rel != "." else k
            out[key] = v
    return out

def judge(rv, key):
    v = rv.get(key)
    return f" [{v.get('score')}/{v.get('max')}]" if v else ""

models = sorted(d for d in os.listdir(RUNS) if os.path.isdir(f"{RUNS}/{d}"))
for tier, heading in (("fast", "FAST (short suite, 29 checks)"), ("latex", "LATEX (latex suite)")):
    if tier not in want: continue
    rows = []
    for m in models:
        f = f"{RUNS}/{m}/{tier}/grades.json"
        if not os.path.exists(f): continue
        g = json.load(open(f)); t = g.pop("_total"); rv = reviews(m)
        rows.append([m, f"{t['score']}/{t['max']}", str(len(t["truncated"])), f"{t['completion_tokens']}", f"{t['seconds'] / 60:.0f}"]
                    + [f"{v['auto']}/{v['max']}{judge(rv, tier + '/' + k)}" for k, v in sorted(g.items())])
    if rows:
        ids = sorted(k for k in json.load(open(f"{RUNS}/{rows[0][0]}/{tier}/grades.json")) if k != "_total")
        head = ["model", "total", "trunc", "tokens", "min"] + ids
        w = [max(len(str(r[i])) for r in rows + [head]) for i in range(len(head))]
        print(heading)
        for r in [head] + rows: print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
        print()
if "long" in want:
    cases = list(hb.cases())
    rows = []
    for m in models:
        f = f"{RUNS}/{m}/long/results.jsonl"
        if not os.path.exists(f): continue
        last = {}
        for l in open(f):
            r = json.loads(l); last[r["case"]] = r
        rv = reviews(m)
        def cell(c):
            r = last.get(c)
            if not r: return "-"
            s = f"{r['score']}/{r['max']}" if r["score"] is not None else "err"
            return (s + ("*" if r["status"] != "completed" else "") + ("†" if r.get("task_version") else "")
                    + f" {r['seconds'] // 60}m" + judge(rv, "long/" + c))
        rows.append([m] + [cell(c) for c in cases])
    if rows:
        head = ["model"] + cases
        w = [max(len(str(r[i])) for r in rows + [head]) for i in range(len(head))]
        print("LONG (score/max, * = timeout or agent error, minutes; judge scores in [ ])")
        for r in [head] + rows: print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
        print("† graded on an earlier version of the task (see results.jsonl task_version); not comparable")
