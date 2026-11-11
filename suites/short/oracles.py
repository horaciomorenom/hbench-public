"""Automatic oracles for the short suite.

grade(pid, response_text) -> {"checks": [...], "auto": passed, "max": n, "error": str|None}
Model code is extracted from fenced python blocks and executed in a child process
(timeout) with matplotlib on Agg. With save_dir, a figure the oracle drew with the model's code (p01)
is kept there as <pid>.png for the judge packet. Nothing here reads prose: text checks only parse lines the
prompt asks for, and derivations and explanations are scored by the judge.

Every item has a fixed list of checks (CHECKS below), so max is always 29 for the suite:
text checks run on the response alone, code checks run in the child, and a crash, a timeout
or a missing function fails the code checks it prevented instead of replacing them.
"""
import ast, contextlib, json, os, re, shutil, subprocess, sys, tempfile

def extract_code(text):
    blocks = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", text, re.S)
    good = []
    for b in blocks:
        try:
            ast.parse(b)
            good.append(b)
        except SyntaxError:
            pass
    return "\n\n".join(good)

def grade(pid, text, timeout=180, save_dir=None):
    code = extract_code(text)
    checks = TEXT[pid](text, code) if pid in TEXT else []
    error = None
    with tempfile.TemporaryDirectory() as d:
        open(f"{d}/code.py", "w").write(code)
        open(f"{d}/text.txt", "w").write(text)
        try:
            p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", pid, d],
                               capture_output=True, text=True, timeout=timeout, cwd=d)
            lines = [l for l in p.stdout.splitlines() if l.startswith("@@RESULT@@")]
            if lines:
                got, error = json.loads(lines[-1][10:])
            else:
                got, error = [], "child produced no result; stderr: " + p.stderr[-300:]
        except subprocess.TimeoutExpired:
            got, error = [], f"timed out after {timeout}s"
        figure = None
        if save_dir:
            if os.path.exists(f"{save_dir}/{pid}.png"): os.remove(f"{save_dir}/{pid}.png")
            if os.path.exists(f"{d}/figure.png"):
                shutil.copy(f"{d}/figure.png", f"{save_dir}/{pid}.png"); figure = f"{pid}.png"
    have = {c["name"]: c for c in got}
    for name in CODE_NAMES[pid]:
        checks.append(have.get(name) or _ck(name, False, error or "not reached"))
    return dict(checks=checks, auto=sum(c["ok"] for c in checks), max=len(checks), code_chars=len(code), error=error, figure=figure)

def _ck(name, ok, detail=""):
    return dict(name=name, ok=bool(ok), detail=str(detail))

def _need(ns, *names):
    for n in names:
        if n not in ns:
            raise KeyError(f"function `{n}` not defined")

# ------------------------------------------------- text checks (response only, no execution)
# Only machine-readable lines the prompt asks for (ANSWER:, THEORY_ORDER:, STIFF:). Prose is left to the judge:
# keyword matching on explanations passed wrong answers and failed right ones.
def _tagged(text, tag):
    """Value of the last `TAG: value` line, ignoring markdown emphasis and code ticks; None when absent."""
    m = re.findall(rf"(?m)^[\s>*_`#-]*{tag}\s*:[\s*_`]*([^\s*_`]+)", text)
    return m[-1].rstrip(".") if m else None

def _number(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def t02(text, code):
    v = _tagged(text, "ANSWER")
    return [_ck("final answer 9.8 h", _number(v) is not None and abs(_number(v) - 9.8) < 0.05, v)]

def t03(text, code):
    v = _tagged(text, "THEORY_ORDER")
    return [_ck("THEORY_ORDER: 4", _number(v) == 4, v)]

def t04(text, code):
    v = _tagged(text, "STIFF")
    return [_ck("STIFF: no (the RHS is exactly -y)", (v or "").lower() == "no", v)]

TEXT = {"p02": t02, "p03": t03, "p04": t04}

# ------------------------------------------------- forbidden library routines
FORBIDDEN = {"p05": [("numpy.linalg", "qr"), ("numpy.linalg", "lstsq"), ("scipy.linalg", "qr"), ("scipy.linalg", "lstsq")],
             "p06": [("numpy.polynomial.legendre", "leggauss"), ("scipy.special", "roots_legendre"), ("scipy.special", "p_roots")]}

@contextlib.contextmanager
def _forbid(ns, pid):
    """While the oracle calls the model's functions, the library routines the prompt forbids record their calls
    (and still work, so the numeric checks stay independent). Covers module attributes and the model's own aliases
    (`from numpy.linalg import qr as q`). Code under `if __name__ == "__main__":` never runs, so a self-test may use them."""
    import importlib
    hits, undo = [], []
    for modname, name in FORBIDDEN[pid]:
        try: mod = importlib.import_module(modname)
        except ImportError: continue
        orig = getattr(mod, name, None)
        if orig is None: continue
        def stub(*a, _orig=orig, _name=f"{modname}.{name}", **k):
            hits.append(_name); return _orig(*a, **k)
        setattr(mod, name, stub); undo.append((mod, name, orig))
        for k, v in list(ns.items()):
            if v is orig: ns[k] = stub; undo.append((ns, k, orig))
    try:
        yield hits
    finally:
        for target, name, orig in reversed(undo):
            if isinstance(target, dict): target[name] = orig
            else: setattr(target, name, orig)

# ------------------------------------------------- code checks (run in the child)
# Check names per item, in the order the checks report them; a check missing from the child's
# result is failed with the reason it was not reached.
CODE_NAMES = {
    "p01": ["order within 0.05 of 2", "log-log axes", "annotation text present", "legend present"],
    "p02": [],
    "p03": ["S10 = 0.693150", "observed order 3.8-4.2"],
    "p04": ["printed y(10) ~ exp(-10) (rel 1e-3 on printed digits)"],
    "p05": ["Q is 50x50, R is 50x16", "||QR-A||/||A|| < 1e-13", "||QtQ-I|| < 1e-13",
            "lstsq_qr residual matches lstsq (1e-10)", "no library qr/lstsq called"],
    "p06": ["nodes match leggauss (1e-13)", "weights match leggauss (1e-13)", "integrates exp to 1e-14",
            "no library Gauss-Legendre rule called"],
    "p07": ["sum(u) conserved to 1e-12", "min(u) >= 1 (max principle)", "N=200 vs 400 RMS < 5e-3"],
    "p08": ["omega(kx, ky, v_star) = -v_star ky/(1+kx^2+ky^2)", "rel L2 vs exact < 1e-6"],
    "p09": ["Br, Bt match closed form", "Br(1,th)=cos th and Bt(R_ss,th)=0", "div B ~ 0 and curl B ~ 0 (1e-8)"],
    "p10": ["bug (b) fixed: sum(u) conserved 1e-12", "bug (a) fixed: finite and min(u) >= 1"],
}

def c01(ns, text, code, out):
    import numpy as np
    _need(ns, "plot_convergence")
    h = np.array([0.2, 0.1, 0.05, 0.025]); err = 0.3 * h**2 * (1 + 0.01 * np.array([1, -1, 1, -1]))
    p, fig = ns["plot_convergence"](h, err)
    try:  # for the judge packet (grade() keeps it), not a check
        fig.savefig("figure.png", dpi=150, bbox_inches="tight")
    except Exception:
        pass
    ax = fig.axes[0]
    return [_ck("order within 0.05 of 2", abs(p - 2) < 0.05, f"{p:.3f}"),
            _ck("log-log axes", ax.get_xscale() == "log" and ax.get_yscale() == "log"),
            _ck("annotation text present", len(ax.texts) > 0 or len(fig.texts) > 0),
            _ck("legend present", ax.get_legend() is not None)]

def c02(ns, text, code, out):
    return []

def c03(ns, text, code, out):
    import numpy as np, math
    _need(ns, "simpson")
    f = lambda x: 1 / x
    s10 = float(ns["simpson"](f, 1, 2, 10))
    e = [abs(float(ns["simpson"](f, 1, 2, n)) - math.log(2)) for n in (10, 20, 40)]
    order = math.log2(e[0] / e[1])
    return [_ck("S10 = 0.693150", abs(s10 - 0.693150) < 5e-7, f"{s10:.7f}"),
            _ck("observed order 3.8-4.2", 3.8 < order < 4.2, f"{order:.2f}")]

def c04(ns, text, code, out):
    import math
    ref = math.exp(-10)
    if not out.strip():   # output behind `if __name__ == "__main__":` -> run it as a script
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "model_code.py", "exec"), {"__name__": "__main__"})
        out = buf.getvalue()
    nums = [float(x) for x in re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", out)]
    ok = any(abs(x - ref) / ref < 1e-3 for x in nums)
    return [_ck("printed y(10) ~ exp(-10) (rel 1e-3 on printed digits)", ok, nums[-3:])]

def c05(ns, text, code, out):
    import numpy as np
    _need(ns, "householder_qr", "lstsq_qr")
    x = np.linspace(0, 1, 50); A = np.vander(x, 16, increasing=True); b = np.cos(4 * x)
    r_ref = np.linalg.norm(A @ np.linalg.lstsq(A, b, rcond=None)[0] - b)
    with _forbid(ns, "p05") as hits:
        Q, R = ns["householder_qr"](A)
    Q = np.asarray(Q); R = np.asarray(R)
    res = [_ck("Q is 50x50, R is 50x16", Q.shape == (50, 50) and R.shape == (50, 16), (Q.shape, R.shape))]
    if Q.shape == (50, 50) and R.shape == (50, 16):
        res += [_ck("||QR-A||/||A|| < 1e-13", np.linalg.norm(Q @ R - A) / np.linalg.norm(A) < 1e-13),
                _ck("||QtQ-I|| < 1e-13", np.linalg.norm(Q.T @ Q - np.eye(50)) < 1e-13)]
    with _forbid(ns, "p05") as more:
        sol = ns["lstsq_qr"](A, b)
    hits += more
    sol = np.asarray(sol[0] if isinstance(sol, tuple) else sol).ravel()
    r = np.linalg.norm(A @ sol - b)
    return res + [_ck("lstsq_qr residual matches lstsq (1e-10)", abs(r - r_ref) < 1e-10, f"{r:.2e} vs {r_ref:.2e}"),
                  _ck("no library qr/lstsq called", not hits, ", ".join(sorted(set(hits))))]

def c06(ns, text, code, out):
    import numpy as np, math
    _need(ns, "gauss_legendre")
    xr, wr = np.polynomial.legendre.leggauss(64)
    with _forbid(ns, "p06") as hits:
        x, w = ns["gauss_legendre"](64)
    x = np.asarray(x); w = np.asarray(w)
    return [_ck("nodes match leggauss (1e-13)", np.max(abs(x - xr)) < 1e-13, f"{np.max(abs(x-xr)):.1e}"),
            _ck("weights match leggauss (1e-13)", np.max(abs(w - wr)) < 1e-13, f"{np.max(abs(w-wr)):.1e}"),
            _ck("integrates exp to 1e-14", abs(w @ np.exp(x) - (math.e - 1 / math.e)) < 1e-14),
            _ck("no library Gauss-Legendre rule called", not hits, ", ".join(sorted(set(hits))))]

def c07(ns, text, code, out):
    import numpy as np
    _need(ns, "conduction")
    x1, u1 = ns["conduction"](200); x2, u2 = ns["conduction"](400)
    x1 = np.asarray(x1); u1 = np.asarray(u1); u2 = np.asarray(u2)
    u0 = 1 + 2 * np.exp(-((x1 - 0.5) / 0.05) ** 2)
    cons = abs(u1.sum() - u0.sum()) / u0.sum()
    conv = np.sqrt(np.mean((u1 - 0.5 * (u2[::2] + u2[1::2])) ** 2))
    return [_ck("sum(u) conserved to 1e-12", cons < 1e-12, f"{cons:.1e}"),
            _ck("min(u) >= 1 (max principle)", u1.min() >= 1 - 1e-12, f"{u1.min():.4f}"),
            _ck("N=200 vs 400 RMS < 5e-3", conv < 5e-3, f"{conv:.1e}")]

def c08(ns, text, code, out):
    import numpy as np
    pts = [(0.3, 0.2, 1.0), (0.0, 0.5, 1.0), (1.2, -0.7, 1.0), (0.3, 0.2, 2.5)]   # the last one catches a dropped v_star
    want = [-v * ky / (1 + kx**2 + ky**2) for kx, ky, v in pts]
    try:   # omega and solve_hm are checked independently: a missing or broken omega doesn't hide the solver
        got = [float(ns["omega"](kx, ky, v_star=v)) for kx, ky, v in pts]
        res = [_ck("omega(kx, ky, v_star) = -v_star ky/(1+kx^2+ky^2)", np.allclose(got, want, rtol=1e-10, atol=1e-14),
                   " ".join(f"{g:.4g}" for g in got))]
    except Exception as ex:
        res = [_ck("omega(kx, ky, v_star) = -v_star ky/(1+kx^2+ky^2)", False, "function `omega` not defined" if "omega" not in ns else repr(ex)[:200])]
    if "solve_hm" not in ns:
        return res + [_ck("rel L2 vs exact < 1e-6", False, "function `solve_hm` not defined")]
    L = 20 * np.pi; N = 32
    g = np.arange(N) * L / N; X, Y = np.meshgrid(g, g, indexing="ij")
    kx, ky = 2 * np.pi * 3 / L, 2 * np.pi * 2 / L
    ana = np.cos(kx * X + ky * Y + ky * 100.0 / (1 + kx**2 + ky**2))
    num = np.asarray(ns["solve_hm"](32, 0.1, 100.0))
    rel = np.linalg.norm(num - ana) / np.linalg.norm(ana)
    return res + [_ck("rel L2 vs exact < 1e-6", rel < 1e-6, f"{rel:.1e}")]

def c09(ns, text, code, out):
    import numpy as np
    _need(ns, "Br", "Bt")
    Rss = 2.5; den = 1 + 2 * Rss**3
    refBr = lambda r, th: (1 + 2 * Rss**3 / r**3) / den * np.cos(th)
    refBt = lambda r, th: -(1 - Rss**3 / r**3) / den * np.sin(th)
    r = np.array([1.0, 1.3, 1.7, 2.2, 2.5]); th = np.array([0.2, 0.9, 1.4, 2.0, 3.0])
    ok_ref = np.allclose(ns["Br"](r, th), refBr(r, th), atol=1e-9) and np.allclose(ns["Bt"](r, th), refBt(r, th), atol=1e-9)
    Br, Bt = ns["Br"], ns["Bt"]; r0, th0, e = 1.7, 0.9, 1e-5
    div = (((r0 + e)**2 * Br(r0 + e, th0) - (r0 - e)**2 * Br(r0 - e, th0)) / (2 * e)) / r0**2 + \
          (np.sin(th0 + e) * Bt(r0, th0 + e) - np.sin(th0 - e) * Bt(r0, th0 - e)) / (2 * e) / (r0 * np.sin(th0))
    curl = ((r0 + e) * Bt(r0 + e, th0) - (r0 - e) * Bt(r0 - e, th0)) / (2 * e) / r0 - (Br(r0, th0 + e) - Br(r0, th0 - e)) / (2 * e) / r0
    return [_ck("Br, Bt match closed form", ok_ref),
            _ck("Br(1,th)=cos th and Bt(R_ss,th)=0", abs(Br(1.0, 0.7) - np.cos(0.7)) < 1e-12 and abs(Bt(2.5, 0.7)) < 1e-12),
            _ck("div B ~ 0 and curl B ~ 0 (1e-8)", abs(div) < 1e-8 and abs(curl) < 1e-8, f"{div:.1e} {curl:.1e}")]

def c10(ns, text, code, out):
    import numpy as np
    _need(ns, "run")
    with np.errstate(all="ignore"):
        xc, u = ns["run"]()
    xc = np.asarray(xc); u = np.asarray(u)
    u0 = 1 + 2 * np.exp(-((xc - 0.5) / 0.05) ** 2)
    cons = abs(u.sum() - u0.sum()) / u0.sum()
    finite = np.all(np.isfinite(u))
    return [_ck("bug (b) fixed: sum(u) conserved 1e-12", finite and cons < 1e-12, f"{cons:.1e}"),
            _ck("bug (a) fixed: finite and min(u) >= 1", finite and u.min() >= 1 - 1e-12, f"min={u.min():.3g}")]

CHECKS = {f"p{i:02d}": globals()[f"c{i:02d}"] for i in range(1, 11)}

def child(pid, d):
    import io, contextlib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.show = lambda *a, **k: None
    code = open(f"{d}/code.py").read(); text = open(f"{d}/text.txt").read()
    ns = {"__name__": "model"}; buf = io.StringIO(); res = []; errors = []
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "model_code.py", "exec"), ns)
    except BaseException as ex:
        errors.append("model code raised " + repr(ex)[:200])
    out = buf.getvalue()
    try:
        res = CHECKS[pid](ns, text, code, out)
    except BaseException as ex:
        errors.append("oracle stopped: " + repr(ex)[:200])
    sys.stdout.write("\n@@RESULT@@" + json.dumps([res, "; ".join(errors) or None]) + "\n")

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--child":
    child(sys.argv[2], sys.argv[3])
