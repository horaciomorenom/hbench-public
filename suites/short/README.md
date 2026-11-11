# short suite

10 problems, ordered cheap to expensive, about 6,300 output tokens in total (about 10 min at 10 t/s without thinking).
Standalone: nothing here depends on the long-tier cases.

    ./fast.sh <model>       # from the hbench folder: server up, run.py --model <model>, grade.py --model <model>
    ./fast.sh selftest      # grade.py on curator/reference: 29/29

`curator/` holds reference responses and a negative control. Do not show it to the model.
No check reads prose. Interface additions to some prompts (solve_hm, omega, Br/Bt constants, run, and the
ANSWER, THEORY_ORDER and STIFF lines) exist only so the oracles can call the model's code or parse its answer;
derivations and explanations are left to the judge packets. Keyword checks on prose were dropped in November 2026:
probed with wrong and right answers, they misgraded 13 of 18 (e.g. "non-stiff solver" passed "not stiff",
"least squares" passed "squares the condition number", `-v* * ky` failed the dispersion check).

## Grading notes
- Every item has a fixed check list, so the total is always 29: a crash or a missing function fails the checks it
  blocked instead of replacing them. Tagged-line checks run even when the code crashes.
- The "no library qr/lstsq" (p05) and "no library Gauss-Legendre rule" (p06) checks record calls to the forbidden
  routines, including the model's aliases of them, while the oracle runs the model's functions. A self-test under
  `if __name__ == "__main__":` never runs, so it may compare against them.
- Tagged lines take the last match and ignore markdown emphasis (`**ANSWER:** 9.8.` reads as 9.8); p04 asks for 6 significant figures and runs code behind
  `if __name__ == "__main__":` when nothing was printed; p08's `omega` is called with v_star = 2.5 once, so a dropped v* fails; p10 doesn't mark the
  bug lines or say how many bugs there are.
- p01's judge packet includes the figure the model's `plot_convergence` drew on the oracle's test data.
- `run.py` keeps the reasoning, `finish_reason` and token counts, and flags truncated items.
