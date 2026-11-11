# latex suite

12 LaTeX tasks a model gets asked in real use, ordered roughly cheap to expensive: about 5,600 output tokens in total without thinking.
Standalone: nothing here depends on the other suites. Needs pdflatex (a full TeX Live) and poppler; the grader is stdlib only.

    ./latex.sh <model> [l01 l09]    # from the hbench folder: server up, run.py, grade.py
    ./latex.sh selftest             # curator/reference: 137/137; curator/negative: every item loses points

| id | task | | id | task |
|---|---|---|---|---|
| l01 | add a booktabs table to a document | | l07 | side-by-side subfigures |
| l02 | table with grouped headers, multirow, bold minima | | l08 | PCG pseudocode (algpseudocode) |
| l03 | fix a table that overflows, no scaling tricks | | l09 | TikZ flowchart |
| l04 | typeset equations from plain text | | l10 | TikZ weighted graph, with its spanning tree worked out |
| l05 | repair a broken document, without dropping text | | l11 | TikZ geometry at exact coordinates |
| l06 | amsthm with cleveref | | l12 | pgfplots log-log convergence plot |

`curator/` holds the reference answers and negative controls. Do not show it to the model.

## How grading works
The response's last fenced latex block is compiled (no shell escape, three passes at most) and judged by what came out:
- **The log**: errors, undefined references, overfull boxes.
- **The PDF text** (`pdftotext`): cross-references print the right number, table rows hold the right values on one line, no text was lost.
- **Word positions**: every word inside the margins (l03), subcaptions on one line (l07).
- **Node positions**: for TikZ, a second compile adds a probe before the last `\end{tikzpicture}` that prints the named nodes' real anchors to the log. This measures overlaps (l09, l10) and exact coordinates (l11), however the model built them.
- **The source**: which packages and environments it used, and in l09 and l10 which nodes each `\draw` joins. That's why those prompts fix the node names and ask for one `\draw` per edge.

Every item has a fixed check list, so the total is always 137: a document that won't compile fails what needs the PDF, and source checks still run.
Checks marked `heuristic` are source-text signals that a judge should confirm. Automatic checks can't tell whether a picture looks good: each judge packet has the rendered first page, and the judge scores that.

## Adding an item
Add `prompts/lNN.md` (its first line must be unique: the mock backend finds answers by it), an entry in `items.json`, a function in `oracles.py` listed in `ITEMS`, a reference in `curator/reference/` and a negative control in `curator/negative/`. Then run the selftest, and update the 137 here and in the READMEs.
