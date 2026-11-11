```python
import numpy as np
def run(N=100,T=0.005,cfl=0.4):
    dx=1.0/N; xc=(np.arange(N)+0.5)*dx; u=1+2*np.exp(-((xc-0.5)/0.05)**2); t=0.0
    while t<T:
        k=np.abs(u)**2.5; dt=cfl*dx**2/(2*k.mean()); kf=0.5*(k[1:]+k[:-1]); F=np.zeros(N+1)
        F[1:-1]=-kf*(u[1:]-u[:-1])/dx; F[-1]=F[-2]; u=u-dt*(F[1:]-F[:-1])/dx; t+=dt
    return xc,u
```
