"""Fixed-step explicit integration of y' = f(t, y)."""
import numpy as np


def rk4_step(f, t, y, dt):
    """One classical fourth-order Runge-Kutta step of size dt from (t, y)."""
    k1 = f(t, y)
    k2 = f(t, y + 0.5 * dt * k1)
    k3 = f(t, y + 0.5 * dt * k2)
    k4 = f(t + dt, y + dt * k3)
    return y + dt / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def integrate(f, y0, t0, t1, n):
    """Integrate from t0 to t1 in n equal RK4 steps. Returns (t, y): t has n+1 points, y[i] is the solution at t[i]."""
    t = np.linspace(t0, t1, n + 1)
    y = np.empty((n + 1,) + np.shape(y0))
    y[0] = y0
    dt = (t1 - t0) / n
    for i in range(n):
        y[i + 1] = rk4_step(f, t[i], y[i], dt)
    return t, y
