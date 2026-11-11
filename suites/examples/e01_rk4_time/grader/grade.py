#!/usr/bin/env python3
"""Grade e01 (RK4 time argument): python3 grade.py --workspace <the model's repo folder>

Checks the model's numerics/ode.py on its own (in a child process) and runs the model's tests twice: on its fixed
code (must pass) and with the original buggy ode.py put back (must fail, so the new test catches the bug).
Prints one JSON object: {"score", "maximum": 100, "partial": false, "checks": [...]}."""
import argparse, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRISTINE = os.path.join(os.path.dirname(HERE), "repo")

PROBE = r'''
import inspect, json, sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from numerics import ode
out = {}
def order(f, y0, t1, exact):
    e = [abs(np.asarray(ode.integrate(f, y0, 0.0, t1, n)[1][-1]) - exact).max() for n in (40, 80)]
    return float(np.log2(e[0] / e[1])) if e[1] > 0 else 9.0, float(e[1])
out["cos"] = order(lambda t, y: np.cos(t), 0.0, 10.0, np.sin(10.0))
out["gauss"] = order(lambda t, y: -2.0 * t * y, 1.0, 2.0, np.exp(-4.0))
out["decay"] = order(lambda t, y: -y, 1.0, 2.0, np.exp(-2.0))
t, y = ode.integrate(lambda t, y: np.array([y[1], -y[0]]), np.array([0.0, 1.0]), 0.0, 1.0, 50)
out["system"] = [list(y.shape), float(abs(y[-1, 0] - np.sin(1.0)))]
out["sig"] = [list(inspect.signature(ode.rk4_step).parameters), list(inspect.signature(ode.integrate).parameters)]
print(json.dumps(out))
'''

def unittest_ok(repo):
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=repo, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workspace", required=True)
    ws = os.path.abspath(ap.parse_args().workspace)
    checks = []
    def check(name, ok, pts, detail=""):
        checks.append(dict(name=name, ok=bool(ok), points=pts if ok else 0, max=pts, detail=str(detail)))
    try:
        p = subprocess.run([sys.executable, "-c", PROBE, ws], capture_output=True, text=True, timeout=300)
        r = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else None
        err = None if r else (p.stderr.strip().splitlines() or ["no output"])[-1]
    except Exception as e:
        r, err = None, repr(e)
    if r:
        check("order 4 on y' = cos(t)", r["cos"][0] > 3.7, 20, "order %.2f, error %.1e" % tuple(r["cos"]))
        check("order 4 on y' = -2ty", r["gauss"][0] > 3.7, 20, "order %.2f, error %.1e" % tuple(r["gauss"]))
        check("still order 4 on y' = -y", r["decay"][0] > 3.7, 10, "order %.2f, error %.1e" % tuple(r["decay"]))
        check("systems keep working (shape and accuracy)", r["system"][0] == [51, 2] and r["system"][1] < 1e-8, 10, r["system"])
        check("signatures unchanged", r["sig"] == [["f", "t", "y", "dt"], ["f", "y0", "t0", "t1", "n"]], 10, r["sig"])
    else:
        for name, pts in [("order 4 on y' = cos(t)", 20), ("order 4 on y' = -2ty", 20), ("still order 4 on y' = -y", 10),
                          ("systems keep working (shape and accuracy)", 10), ("signatures unchanged", 10)]:
            check(name, False, pts, f"numerics.ode failed: {err}")
    ok, tail = unittest_ok(ws)
    check("the model's tests pass on its code", ok, 10, tail[0])
    with tempfile.TemporaryDirectory() as d:  # the model's tests against the original, buggy ode.py
        shutil.copytree(ws, f"{d}/repo", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(f"{PRISTINE}/numerics/ode.py", f"{d}/repo/numerics/ode.py")
        bad_ok, bad_tail = unittest_ok(f"{d}/repo")
    check("its tests fail on the original code (they catch the bug)", not bad_ok, 20, bad_tail[0])
    score = sum(c["points"] for c in checks)
    print(json.dumps(dict(score=score, maximum=100, partial=False, checks=checks), indent=1))

if __name__ == "__main__":
    main()
