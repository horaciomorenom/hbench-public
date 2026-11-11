#!/usr/bin/env python3
"""Judge packet for one long-tier run: the task, the case's rubric/verify notes, the answer key, the automatic
grade and the model's change as a diff against the pristine case. Usage: packet.py <run dir> <case source dir> [copied folder]
Writes <run>/logs/judge_packet.md and <run>/logs/diff.patch. The packet holds the answer key: never give it
to the model under test."""
import json, os, subprocess, sys

run, src = sys.argv[1], sys.argv[2]
logs = f"{run}/logs"
sub = sys.argv[3] if len(sys.argv) > 3 else "repo" if os.path.isdir(f"{src}/repo") else "workspace"
mine = f"{run}/work/{sub}"
diff = subprocess.run(["diff", "-ruN", "-x", "build*", "-x", "gbuild", "-x", ".git", "-x", "__pycache__", "-x", "grids",
                       "-x", "outputs", "-x", ".DS_Store", f"{src}/{sub}", mine], capture_output=True, text=True).stdout
diff = diff.replace(f"{src}/{sub}", "a").replace(mine, "b")
open(f"{logs}/diff.patch", "w").write(diff)
keys = [f for f in ("RUBRIC.md", "VERIFY.md", "reference.patch", "solution/reference.patch", "curator/campaign_reference.py")
        if os.path.exists(f"{src}/{f}")]
grade = open(f"{logs}/grade.txt").read() if os.path.exists(f"{logs}/grade.txt") else "(no automatic grade)"
pk = [f"# Judge packet: {os.path.basename(run)}", "", "## Task given to the model", open(f"{logs}/prompt.md").read(), ""]
for k in keys:
    body = open(f"{src}/{k}", errors="replace").read()
    fence = "diff" if k.endswith(".patch") else "python" if k.endswith(".py") else ""
    pk += [f"## {k} (answer key: for the judge, not the model)", f"```{fence}" if fence else "", body[:30000], "```" if fence else "", ""]
pk += ["## Automatic grade", "```", grade[-6000:], "```", "",
       "## Model's change (diff of the pristine case against its workspace)", "```diff", diff[:80000], "```", "",
       "## Your job", "Judge the model's change, not its claims. Score against the rubric where there is one (otherwise: "
       "explain any lost points in the automatic grade and say whether the grader or the model is at fault). Flag: wrong "
       "math or normalization, edits outside scope, hard-coded outputs, tests that cannot fail. "
       "Reply JSON: {id, rubric_score, max, errors:[...], verdict}."]
open(f"{logs}/judge_packet.md", "w").write("\n".join(pk))
print(f"{logs}/judge_packet.md ({len(diff)} chars of diff)")
