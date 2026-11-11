#!/usr/bin/env python3
"""Grade a short-suite run:  python3 grade.py --model <name>
Reads runs/<model>/fast/, writes grades.json there (per item: checks, score, run meta; plus totals) and
judge/<id>.md packets for a second model. An item with several attempts (run.py --attempts: <id>/ and <id>/r2, r3, ...)
scores the mean over its attempts; grades.json keeps each attempt's score and each check's pass rate, and
attempt n's judge packet is judge/r<n>/<id>.md. Needs numpy, scipy and matplotlib (fast.sh uses the Python from hb.py: config.json or .venv).
Self-test:  python3 grade.py --response-dir curator/reference --out /tmp/selftest   (all 29 checks pass)"""
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(HERE))
import oracles

def attempt_dirs(item_dir):
    """An item's attempt folders, in order: the item folder itself (attempt 1), then r2, r3, ... (run.py --attempts)."""
    rs = sorted((int(x[1:]), f"{item_dir}/{x}") for x in (os.listdir(item_dir) if os.path.isdir(item_dir) else [])
                if re.fullmatch(r"r\d+", x) and os.path.exists(f"{item_dir}/{x}/meta.json"))
    return [(1, item_dir)] + [r for r in rs if r[0] > 1]

def num(x):
    x = round(x, 2)
    return int(x) if x == int(x) else x

def read(p):
    return open(p).read() if os.path.exists(p) else ""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model")
    ap.add_argument("--response-dir", help="grade a directory of pNN.md files instead (self-test)")
    ap.add_argument("--out", help="with --response-dir: where grades.json and judge/ go")
    a = ap.parse_args()
    if not (a.model or (a.response_dir and a.out)): ap.error("--model, or --response-dir with --out")
    items = json.load(open(f"{HERE}/items.json")); out = {}; tot = mx = 0; truncated = []; counts = []
    base = a.out or f"{ROOT}/runs/{a.model}/fast"; os.makedirs(f"{base}/judge", exist_ok=True)
    for it in items:
        if a.response_dir:
            runs = [(1, f"{a.response_dir}/{it['id']}.md", {}, "")]
        else:
            runs = [(n, f"{d}/response.md", json.load(open(f"{d}/meta.json")) if os.path.exists(f"{d}/meta.json") else {},
                     read(f"{d}/reasoning.md")) for n, d in attempt_dirs(f"{base}/{it['id']}")]
        grades = []
        for n, p, meta, think in runs:
            text = read(p)
            jd = f"{base}/judge" if n == 1 else f"{base}/judge/r{n}"; os.makedirs(jd, exist_ok=True)
            g = oracles.grade(it["id"], text, save_dir=jd)
            g["meta"] = meta; g["missing"] = not os.path.exists(p); grades.append(g)
            if meta.get("truncated"): truncated.append(it["id"] + (f"#{n}" if n > 1 else ""))
            packet = [f"# Judge packet {it['id']} - {it['title']}" + (f" (attempt {n} of {len(runs)})" if len(runs) > 1 else ""), "",
                      "## Task given to the model",
                      open(f"{HERE}/{it['prompt']}").read(), "## Reference oracle notes", it["oracle_notes"], "",
                      *(["## Rendered figure", f"![{it['figure_note']}]({g['figure']})" if g["figure"]
                         else f"(no figure: {g['error'] or 'the code did not return one'})", ""] if it.get("figure_note") else []),
                      "## Run", "```json", json.dumps(meta, indent=1), "```", "",
                      "## Automatic check results", "```json", json.dumps(g["checks"], indent=1), "```", "",
                      "## Model response (verbatim)", text, "",
                      "## Model reasoning (verbatim, for context; grade the response)", think[-20000:] or "(none)", "",
                      "## Your job",
                      "The automatic checks cover code and the tagged answer lines only; score the derivation and explanation they cannot see. Do not trust the model's own claims; "
                      "re-derive the key step. Output JSON: {id, reasoning_score 0-2, errors:[...], verdict}."]
            open(f"{jd}/{it['id']}.md", "w").write("\n".join(packet))
        # the item's score is the mean over its attempts; checks, figure and meta shown are attempt 1's
        g = dict(grades[0]); k = len(grades)
        g["auto"] = num(sum(x["auto"] for x in grades) / k); g["n_attempts"] = k
        g["attempts"] = [dict(n=n, auto=x["auto"], max=x["max"], missing=x["missing"], truncated=bool(x["meta"].get("truncated")),
                              seconds=x["meta"].get("seconds"), completion_tokens=x["meta"].get("completion_tokens"),
                              failed=[c["name"] for c in x["checks"] if not c["ok"]], checks=x["checks"], error=x["error"],
                              figure=x["figure"] and (x["figure"] if n == 1 else f"r{n}/{x['figure']}"))
                         for (n, *_), x in zip(runs, grades)]
        g["pass_rate"] = {c["name"]: sum(any(d["name"] == c["name"] and d["ok"] for d in x["checks"]) for x in grades) / k
                          for c in grades[0]["checks"]}
        out[it["id"]] = g; tot += sum(x["auto"] for x in grades) / k; mx += g["max"]; counts.append(k)
        flag = "MISSING " if g["missing"] else "TRUNCATED " if g["meta"].get("truncated") else ""
        if k == 1:
            print(f"{it['id']}  {g['auto']}/{g['max']}  {flag}" + "; ".join(c["name"] for c in g["checks"] if not c["ok"]))
        else:
            print(f"{it['id']}  {g['auto']}/{g['max']} mean of {k} ({' '.join(str(x['auto']) for x in grades)})  " +
                  "; ".join(f"{name} {round(r * k)}/{k}" for name, r in g["pass_rate"].items() if r < 1))
    allm = [x for g in out.values() for x in g["attempts"]]
    out["_total"] = dict(score=num(tot), max=mx, truncated=truncated, attempts=min(counts), attempts_max=max(counts),
                         seconds=round(sum(x["seconds"] or 0 for x in allm), 1),
                         completion_tokens=sum(x["completion_tokens"] or 0 for x in allm))
    json.dump(out, open(f"{base}/grades.json", "w"), indent=1)
    rng = f"{min(counts)}" if min(counts) == max(counts) else f"{min(counts)}-{max(counts)}"
    print(f"TOTAL {num(tot)}/{mx}" + (f"  (mean of {rng} attempts per item)" if max(counts) > 1 else "")
          + (f"  ({len(truncated)} truncated: {' '.join(truncated)})" if truncated else ""))

if __name__ == "__main__":
    main()
