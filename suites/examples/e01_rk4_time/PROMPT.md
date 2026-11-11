# Fix the RK4 integrator

`<TEST_DIR>/repo` is a small Python package, `numerics`, with a fixed-step RK4 integrator (`numerics/ode.py`).

A user reports: integrating `y' = cos(t)`, `y(0) = 0` to `t = 10` with `integrate(f, 0.0, 0.0, 10.0, 100)` gives an
error of about 6e-2, and doubling the number of steps only halves it. Classical RK4 at that step size should be
many orders of magnitude more accurate. The existing test for `y' = -y` passes.

1. Find the cause and fix it in `numerics/ode.py`. Keep the public functions and their signatures
   (`rk4_step(f, t, y, dt)`, `integrate(f, y0, t0, t1, n)`) unchanged.
2. Add a test under `tests/` that fails on the current code and passes on the fixed code.
3. Run the tests from the repo folder with `python -m unittest discover -s tests`.

Finish with a short summary of the cause and the fix.
