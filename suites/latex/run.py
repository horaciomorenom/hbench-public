#!/usr/bin/env python3
"""Run the latex suite against a model from ../../models.json (its server must be up: server.sh up <model>).

  python3 run.py --model <name> [--ids l01 l05] [--max-tokens 32768] [--effort medium|off]
Results go to runs/<model>/latex/<id>/{response.md, reasoning.md, meta.json}. Re-running skips finished
items, so an interrupted run resumes; a truncated item counts as finished (rm its folder to redo it).
Thinking stays on at the given reasoning effort (off: the field isn't sent); no sampling fields are sent, so
each server's own settings apply. The model's URL and key come from models.json (hb.py). Stdlib only.
"""
import argparse, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import hb
FOOTER = ("\n\nOutput format: reply with exactly one fenced ```latex block holding the complete document, from "
          "\\documentclass to \\end{document}. It is compiled with pdflatex and a full TeX Live, without shell escape and "
          "with no other files besides what the task names. Be concise.\n")

def chat(m, prompt, max_tokens, effort, timeout):
    body = dict(model=m["id"], stream=True, stream_options=dict(include_usage=True), max_tokens=max_tokens,
                messages=[dict(role="user", content=prompt)])
    if effort and effort != "off": body["reasoning_effort"] = effort
    req = urllib.request.Request(f"{m['url']}/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {m['key'] or 'local'}", "User-Agent": "hbench"})
    t0 = time.time(); first = first_content = None; content = []; reasoning = []; finish = None; usage = {}
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            e = json.loads(line[5:])
            usage = e.get("usage") or usage
            for ch in e.get("choices") or []:
                d = ch.get("delta") or {}
                think = d.get("reasoning_content") or d.get("reasoning") or ""
                piece = d.get("content") or ""
                if (think or piece) and first is None: first = time.time() - t0
                if piece and first_content is None: first_content = time.time() - t0
                reasoning.append(think); content.append(piece)
                finish = ch.get("finish_reason") or finish
    return "".join(content), "".join(reasoning), dict(
        seconds=round(time.time() - t0, 1), ttft=first and round(first, 1), answer_start=first_content and round(first_content, 1),
        finish_reason=finish, truncated=finish == "length", prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="a name from models.json")
    ap.add_argument("--ids", nargs="*", help="e.g. l01 l05")
    ap.add_argument("--max-tokens", type=int, default=32768, help="per item, thinking included (some thinking models need >= 32768)")
    ap.add_argument("--effort", default="medium", help="reasoning_effort sent with each request")
    ap.add_argument("--timeout", type=int, default=7200)
    a = ap.parse_args()
    m = hb.model(a.model)
    items = json.load(open(f"{HERE}/items.json"))
    for it in items:
        if a.ids and it["id"] not in a.ids: continue
        d = f"{ROOT}/runs/{a.model}/latex/{it['id']}"
        if os.path.exists(f"{d}/meta.json"):
            print("skip", it["id"]); continue
        os.makedirs(d, exist_ok=True)
        prompt = open(f"{HERE}/{it['prompt']}").read() + FOOTER
        print("run", it["id"], flush=True)
        text, think, meta = chat(m, prompt, a.max_tokens, a.effort, a.timeout)
        meta.update(model=a.model, served_id=m["id"], max_tokens=a.max_tokens, effort=a.effort)
        open(f"{d}/response.md", "w").write(text)
        open(f"{d}/reasoning.md", "w").write(think)
        json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
        print(f"  {meta['seconds']:.0f}s, {meta['completion_tokens']} tokens, finish {meta['finish_reason']}"
              + ("  TRUNCATED" if meta["truncated"] else ""), flush=True)

if __name__ == "__main__":
    main()
