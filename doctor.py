#!/usr/bin/env python3
"""Check an hbench install, and that a model's server plugs in.

  python3 doctor.py            the install: Python packages, config, models, cases, optional tools
  python3 doctor.py <model>    also the model's server: /v1/models, a short streamed chat, usage, reasoning

Each line is OK, WARN (something optional is missing) or FAIL (fix this first). Exit status 1 if anything failed.
For a model with a serve script, start it first (./server.sh up <model>); doctor never starts or stops servers.
"""

import json, os, shutil, subprocess, sys, time, urllib.request

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import hb

failed = False


def say(level, msg):
    global failed
    failed |= level == "FAIL"
    print(f"{level:4}  {msg}")


def install():
    say(
        "OK",
        f"hbench at {H} ({hb.SYSTEM}{' on WSL' if hb.WSL else ''}, Python {sys.version.split()[0]})",
    )
    if " " in H:
        say(
            "WARN",
            "the hbench path contains a space; the job queue can't recognise its scripts there, move it",
        )
    for f, ex in (
        ("config.json", "config.example.json"),
        ("models.json", "models.example.json"),
    ):
        if not os.path.exists(f"{H}/{f}"):
            say(
                "FAIL" if f == "models.json" else "WARN",
                f"no {f}: copy {ex} to {f} and edit it",
            )
        else:
            try:
                json.load(open(f"{H}/{f}"))
                say("OK", f"{f} parses")
            except ValueError as e:
                say("FAIL", f"{f}: {e}")
    py = hb.python()
    r = subprocess.run(
        [
            py,
            "-c",
            "import numpy, scipy, matplotlib; print(numpy.__version__, scipy.__version__, matplotlib.__version__)",
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        say("OK", f"grader Python {py}: numpy, scipy, matplotlib {r.stdout.strip()}")
    else:
        say(
            "FAIL",
            f"grader Python {py} lacks numpy/scipy/matplotlib: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",
        )
    for tool, why in (
        ("curl", "server.sh checks servers with it"),
        ("bash", "the tier scripts"),
    ):
        say("OK" if shutil.which(tool) else "FAIL", f"{tool} ({why})")
    try:
        ms = hb.models()
        say(
            "OK" if ms else "FAIL",
            f"{len(ms)} model(s): "
            + ", ".join(
                f"{n} ({'hbench starts it' if m['managed'] else 'external'})"
                for n, m in ms.items()
            ),
        )
        for n, m in ms.items():
            if m["managed"] and not os.access(m["serve"], os.X_OK):
                say("FAIL", f"{n}: serve script {m['serve']} missing or not executable")
            if m["key_env"] and not m["key"]:
                say(
                    "WARN",
                    f"{n}: API key {m['key_env']} is not set (export it, or put it in .env)",
                )
    except (KeyError, ValueError) as e:
        say("FAIL", f"models.json: {e!r} (every model needs id and base_url or port)")
    cs = hb.cases()
    say("OK", f"{len(cs)} long-tier case(s): {', '.join(cs)}")
    missing = [c for c, v in cs.items() if not os.path.isdir(f"{hb.SUITES}/{v['src']}")]
    if missing:
        say("FAIL", f"case folders missing for {', '.join(missing)}")
    say(
        "OK" if shutil.which("pi") else "WARN",
        "pi agent (long tier): "
        + (
            shutil.which("pi")
            or "not found; npm install -g @earendil-works/pi-coding-agent, or set agent_command"
        ),
    )
    tex = [
        t
        for t in ("pdflatex", "pdftotext", "pdftoppm", "kpsewhich")
        if not shutil.which(t)
    ]
    if not tex:
        tex = [
            f
            for f in (
                "tikz.sty",
                "pgfplots.sty",
                "booktabs.sty",
                "multirow.sty",
                "subcaption.sty",
                "algpseudocode.sty",
                "cleveref.sty",
                "example-image-a.pdf",
            )
            if not subprocess.run(
                ["kpsewhich", f], capture_output=True, text=True
            ).stdout.strip()
        ]
    say(
        "WARN" if tex else "OK",
        "latex tier: "
        + (
            f"missing {', '.join(tex)} (needs TeX Live and poppler)"
            if tex
            else "pdflatex, poppler and the packages it uses"
        ),
    )
    say(
        "OK" if shutil.which("pandoc") and hb.pdf_browser() else "WARN",
        "judge packet PDFs: "
        + (
            f"pandoc and {hb.pdf_browser()}"
            if shutil.which("pandoc") and hb.pdf_browser()
            else "need pandoc and Chrome/Chromium/Edge (optional)"
        ),
    )
    hooks = hb.config()["hooks"]
    for k in ("before_start", "wrap"):
        if hooks.get(k):
            say("OK", f"hook {k}: {hooks[k]}")
    aw = hb.keep_awake_cmd(os.getpid())
    say(
        "OK" if aw else "WARN",
        "keep awake during queued runs: "
        + (aw[0] if aw else "off (on WSL: set Windows to never sleep when plugged in)"),
    )
    m = hb.mem()
    say("OK", f"memory meter: {m['level']}% {m['what']}")


def check_model(name):
    try:
        m = hb.model(name)
    except KeyError as e:
        say("FAIL", e.args[0])
        return
    hdr = {
        "Authorization": f"Bearer {m['key'] or 'local'}",
        "Content-Type": "application/json",
        "User-Agent": "hbench",
    }  # Cloudflare-fronted APIs (Cerebras) 403 urllib's default
    print(f"\n{name}: {m['url']}  id {m['id']}")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{m['url']}/models", headers=hdr), timeout=10
        ) as r:
            ids = [d.get("id") for d in json.load(r).get("data", [])]
        say(
            "OK" if m["id"] in ids else "WARN",
            f"/models lists {ids}"
            + (
                ""
                if m["id"] in ids
                else f"; {m['id']} is not among them (some servers accept any id)"
            ),
        )
    except Exception as e:
        say(
            "FAIL",
            f"/models: {e}"
            + (
                f" (start it: ./server.sh up {name})"
                if m["managed"]
                else " (start your server)"
            ),
        )
        return
    body = dict(
        model=m["id"],
        stream=True,
        stream_options=dict(include_usage=True),
        max_tokens=512,
        messages=[dict(role="user", content="Reply with the single word: ready")],
    )
    if m["effort"] != "off":
        body["reasoning_effort"] = "low"
    t0, first, text, think, fields, usage, finish = (
        time.time(),
        None,
        "",
        "",
        set(),
        None,
        None,
    )
    try:
        req = urllib.request.Request(
            f"{m['url']}/chat/completions", json.dumps(body).encode(), hdr
        )
        with urllib.request.urlopen(req, timeout=600) as r:
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data:") or line.endswith("[DONE]"):
                    continue
                e = json.loads(line[5:])
                usage = e.get("usage") or usage
                for ch in e.get("choices") or []:
                    d = ch.get("delta") or {}
                    for k in ("reasoning_content", "reasoning"):
                        if d.get(k):
                            think += d[k]
                            fields.add(k)
                    if d.get("content"):
                        text += d["content"]
                    if (d.get("content") or think) and first is None:
                        first = time.time() - t0
                    finish = ch.get("finish_reason") or finish
    except urllib.error.HTTPError as e:
        say(
            "FAIL",
            f"chat: HTTP {e.code} {e.read()[:300]!r}"
            + (
                '; if it rejects reasoning_effort, set "effort": false'
                if e.code == 400
                else ""
            ),
        )
        return
    except Exception as e:
        say("FAIL", f"chat: {e}")
        return
    say(
        "OK" if text.strip() else "FAIL",
        f"streamed reply in {time.time() - t0:.1f}s (first token {first or 0:.1f}s): {text.strip()[:80]!r}, finish {finish}",
    )
    if "<think>" in text:
        say(
            "WARN",
            "thinking arrives inside the reply text (<think>…); the graders read only code and answers, "
            "but enable the server's reasoning parser (llama.cpp --reasoning-format, vLLM --reasoning-parser) if it has one",
        )
    say(
        "OK" if fields else "WARN",
        f"reasoning text in {', '.join(sorted(fields))}"
        if fields
        else "no separate reasoning text (fine for non-thinking models)",
    )
    say(
        "OK" if usage and usage.get("completion_tokens") else "WARN",
        f"usage: {usage}"
        if usage
        else "no usage in the stream (token counts will be blank; llama.cpp, vLLM and Ollama send it)",
    )


if __name__ == "__main__":
    install()
    for name in sys.argv[1:]:
        check_model(name)
    sys.exit(1 if failed else 0)
