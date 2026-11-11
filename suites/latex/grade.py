#!/usr/bin/env python3
"""Grade a latex-suite run:  python3 grade.py --model <name>
Reads runs/<model>/latex/, writes grades.json there (per item: checks, score, run meta; plus totals) and
judge/<id>.md packets for a second model, with the rendered first page. Needs pdflatex and poppler; stdlib only.
Self-test:  python3 grade.py --response-dir curator/reference --out <scratch>   (all checks pass)"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(HERE))
import oracles

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model")
    ap.add_argument("--response-dir", help="grade a directory of lNN.md files instead (self-test)")
    ap.add_argument("--out", help="with --response-dir: where grades.json and judge/ go")
    a = ap.parse_args()
    if not (a.model or (a.response_dir and a.out)): ap.error("--model, or --response-dir with --out")
    items = json.load(open(f"{HERE}/items.json")); out = {}; tot = mx = 0; truncated = []
    base = a.out or f"{ROOT}/runs/{a.model}/latex"; os.makedirs(f"{base}/judge", exist_ok=True)
    for it in items:
        if a.response_dir:
            p, meta, think = f"{a.response_dir}/{it['id']}.md", {}, ""
        else:
            p = f"{base}/{it['id']}/response.md"
            meta = json.load(open(f"{base}/{it['id']}/meta.json")) if os.path.exists(f"{base}/{it['id']}/meta.json") else {}
            think = open(f"{base}/{it['id']}/reasoning.md").read() if os.path.exists(f"{base}/{it['id']}/reasoning.md") else ""
        text = open(p).read() if os.path.exists(p) else ""
        g = oracles.grade(it["id"], text, save_dir=f"{base}/judge")
        g["meta"] = meta; g["missing"] = not os.path.exists(p)
        out[it["id"]] = g; tot += g["auto"]; mx += g["max"]
        if meta.get("truncated"): truncated.append(it["id"])
        auto_only = [c for c in g["checks"] if not c.get("heuristic")]
        flag = "MISSING " if g["missing"] else "TRUNCATED " if meta.get("truncated") else ""
        print(f"{it['id']}  {g['auto']}/{g['max']}  (hard {sum(c['ok'] for c in auto_only)}/{len(auto_only)})  {flag}" +
              "; ".join(c["name"] for c in g["checks"] if not c["ok"]))
        packet = [f"# Judge packet {it['id']} - {it['title']}", "", "## Task given to the model",
                  open(f"{HERE}/{it['prompt']}").read(), "## Reference oracle notes", it["oracle_notes"], "",
                  "## Rendered first page", f"![First page of the compiled document]({g['figure']})" if g["figure"]
                  else f"(no PDF: {g['error'] or 'no document found'})", "",
                  "## Run", "```json", json.dumps(meta, indent=1), "```", "",
                  "## Automatic check results", "```json", json.dumps(g["checks"], indent=1), "```", "",
                  "## Model response (verbatim)", text, "",
                  "## Model reasoning (verbatim, for context; grade the response)", think[-20000:] or "(none)", "",
                  "## Your job",
                  "Confirm each heuristic check by reading the source. Look at the rendered page: is it what a careful author "
                  "would submit (legible, nothing colliding, sensible layout)? Output JSON: {id, visual_score 0-2, errors:[...], verdict}."]
        open(f"{base}/judge/{it['id']}.md", "w").write("\n".join(packet))
    out["_total"] = dict(score=tot, max=mx, truncated=truncated,
                         seconds=round(sum((g.get("meta") or {}).get("seconds") or 0 for g in out.values()), 1),
                         completion_tokens=sum((g.get("meta") or {}).get("completion_tokens") or 0 for g in out.values()))
    json.dump(out, open(f"{base}/grades.json", "w"), indent=1)
    print(f"TOTAL {tot}/{mx}" + (f"  ({len(truncated)} truncated: {' '.join(truncated)})" if truncated else ""))

if __name__ == "__main__":
    main()
