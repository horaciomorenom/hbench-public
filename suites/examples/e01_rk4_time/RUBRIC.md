# e01 rubric (judge, 0-5)

- 5: both midpoint stages evaluate f at t + dt/2; nothing else changed in behaviour; the new test checks a
  time-dependent problem against its exact solution (or the observed order) tightly enough to fail on the old code;
  the summary names the cause correctly.
- 4: correct fix and a test that catches the bug, with minor issues (loose tolerance, test duplicates existing code).
- 3: correct fix but the test would not catch the bug (autonomous problem only, or a tolerance the old code passes).
- 2: partial fix (only one of k2/k3) or a fix that changes the method (e.g. a different scheme) while still converging.
- 1: the symptom is masked (smaller default step, special-casing cos) rather than the stages fixed.
- 0: no fix, broken package, or edits to the tests that hide the problem.
