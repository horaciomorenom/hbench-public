#!/usr/bin/env python3
"""A stand-in model server for testing hbench without a GPU: OpenAI-compatible, answers the short suite with
the reference answers (suites/short and suites/latex, curator/reference), and anything else with a short greeting.

  tools/mock_backend.py [--port 8099]

GET /v1/models lists "mock"; POST /v1/chat/completions streams (with usage when asked) or returns one JSON
reply, with a line of reasoning in "reasoning_content" the way llama.cpp sends thinking. With it, models.json's
"mock" entry should score full marks on the fast and latex tiers (fast.sh mock, latex.sh mock): that checks the whole pipeline. It can't run
the long tier's agent (no tool calls). Stdlib only.
"""
import argparse, glob, json, os, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = [f"{H}/suites/short", f"{H}/suites/latex"]

def answers():
    """Prompt title line -> reference answer, for each item of the one-shot suites."""
    out = {}
    for s in SUITES:
        for p in sorted(glob.glob(f"{s}/prompts/*.md")):
            pid = os.path.basename(p)[:-3]
            ref = f"{s}/curator/reference/{pid}.md"
            if os.path.exists(ref):
                out[open(p).readline().strip()] = open(ref).read()
    return out

ANSWERS = answers()

def reply(messages):
    text = "\n".join(m.get("content") or "" for m in messages if isinstance(m.get("content"), str))
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if first in ANSWERS:
        return "The mock backend returns the reference answer for this item.", ANSWERS[first]
    return "This is the mock backend.", "Hello from the hbench mock backend."

def tokens(s):
    return max(1, len(re.findall(r"\S+", s)))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            return self.send_json(200, {"object": "list", "data": [{"id": "mock", "object": "model", "owned_by": "hbench"}]})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self.send_json(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        think, text = reply(req.get("messages") or [])
        usage = dict(prompt_tokens=sum(tokens(m.get("content") or "") for m in req.get("messages") or [] if isinstance(m.get("content"), str)),
                     completion_tokens=tokens(think) + tokens(text))
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        base = dict(id=f"mock-{time.time_ns()}", object="chat.completion", created=int(time.time()), model=req.get("model", "mock"))
        if not req.get("stream"):
            return self.send_json(200, base | dict(choices=[dict(index=0, finish_reason="stop",
                                                                  message=dict(role="assistant", content=text, reasoning_content=think))], usage=usage))
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        def event(delta, finish=None, **extra):
            ch = base | dict(object="chat.completion.chunk", choices=[dict(index=0, delta=delta, finish_reason=finish)], **extra)
            self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode()); self.wfile.flush()
        event(dict(role="assistant", reasoning_content=think))
        for i in range(0, len(text), 400):
            event(dict(content=text[i:i + 400]))
        event({}, "stop")
        if (req.get("stream_options") or {}).get("include_usage"):
            self.wfile.write(f"data: {json.dumps(base | dict(object='chat.completion.chunk', choices=[], usage=usage))}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    port = ap.parse_args().port
    print(f"mock backend on http://127.0.0.1:{port}/v1 ({len(ANSWERS)} reference answers)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
