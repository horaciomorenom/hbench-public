#!/usr/bin/env python3
"""Run the short suite against a model from ../../models.json (its server must be up: server.sh up <model>).

  python3 run.py --model <name> [--ids p01 p05] [--max-tokens 32768] [--effort medium|off] [--attempts N]
Results go to runs/<model>/fast/<id>/{response.md, reasoning.md, meta.json} (attempt 1) and
runs/<model>/fast/<id>/r<n>/ for attempts 2..N. --attempts N is the total wanted per item: finished attempts
are kept and only the missing ones run (round by round: every item's attempt 2, then every item's attempt 3),
so an interrupted run resumes; a truncated attempt counts as finished (rm its folder to redo it).
grade.py averages each item's score over its attempts.
Thinking stays on at the given reasoning effort (off: the field isn't sent); no sampling fields are sent, so
each server's own settings apply. The model's URL and key come from models.json (hb.py). Stdlib only.
"""
import argparse, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import hb
FOOTER = ("\n\nOutput format: put all code in fenced ```python blocks and define every "
          "requested function at top level. Do not call plt.show(). Be concise.\n")

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
    ap.add_argument("--ids", nargs="*", help="e.g. p01 p05")
    ap.add_argument("--max-tokens", type=int, default=32768, help="per item, thinking included (some thinking models need >= 32768)")
    ap.add_argument("--effort", default="medium", help="reasoning_effort sent with each request")
    ap.add_argument("--attempts", type=int, default=1, help="total attempts wanted per item (finished ones are kept)")
    ap.add_argument("--timeout", type=int, default=7200)
    a = ap.parse_args()
    m = hb.model(a.model)
    items = json.load(open(f"{HERE}/items.json"))
    todo = [it for it in items if not a.ids or it["id"] in a.ids]
    for n in range(1, a.attempts + 1):
        for it in todo:
            base = f"{ROOT}/runs/{a.model}/fast/{it['id']}"
            d, tag = (base, it["id"]) if n == 1 else (f"{base}/r{n}", f"{it['id']} attempt {n}")
            if os.path.exists(f"{d}/meta.json"):
                print("skip", tag)
                continue
            os.makedirs(d, exist_ok=True)
            prompt = open(f"{HERE}/{it['prompt']}").read() + FOOTER
            print("run", tag, flush=True)
            text, think, meta = chat(m, prompt, a.max_tokens, a.effort, a.timeout)
            meta.update(model=a.model, served_id=m["id"], max_tokens=a.max_tokens, effort=a.effort, attempt=n)
            open(f"{d}/response.md", "w").write(text)
            open(f"{d}/reasoning.md", "w").write(think)
            json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
            print(f"  {meta['seconds']:.0f}s, {meta['completion_tokens']} tokens, finish {meta['finish_reason']}"
                  + ("  TRUNCATED" if meta["truncated"] else ""), flush=True)

if __name__ == "__main__":
    main()
