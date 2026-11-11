"""Automatic oracles for the latex suite.

grade(lid, response_text, save_dir=None) -> {"checks": [...], "auto": passed, "max": n, "error": str|None, "figure": str|None}
The document is taken from the response's last fenced latex block, compiled with pdflatex (no shell escape, files
read and written only under the scratch folder and the TeX tree), and judged on what came out: the log, the text and
word positions in the PDF (pdftotext), and for TikZ the real node positions, which a second compile prints to the
log with a probe added before the last \\end{tikzpicture}. With save_dir, page 1 is kept there as <lid>.png for the judge packet.

Every item has a fixed list of checks whether or not the document compiles (a broken one just fails those that need
the PDF), so the suite's maximum never changes. Checks marked heuristic=True are source-text signals a judge should
confirm; they count in auto/max like the rest. Needs pdflatex and poppler (pdftotext, pdftoppm) on PATH.
"""
import math, os, re, shutil, subprocess, tempfile, unicodedata

TEX_TIMEOUT = 120
TEX_ENV = dict(os.environ, openin_any="p", openout_any="p", shell_escape="f")

def extract_doc(text):
    blocks = re.findall(r"```(?:latex|tex)[ \t]*\n(.*?)```", text, re.S | re.I) or re.findall(r"```[ \t]*\n(.*?)```", text, re.S)
    docs = [b for b in blocks if "\\documentclass" in b]
    if docs: return docs[-1]
    m = re.search(r"\\documentclass.*\\end\{document\}", text, re.S)  # a model that forgot the fence
    return m.group(0) if m else ""

def strip_comments(src):
    return re.sub(r"(?<!\\)%.*", "", src)

def flat(s):
    """Text compared without layout: line breaks, hyphenation and ligatures don't matter."""
    return re.sub(r"[\s\-\u2010-\u2015\u2212]+", "", unicodedata.normalize("NFKC", s))

def run_tex(src, d, passes=3):
    """Compile src in folder d; returns the log of the last pass ('' if pdflatex never ran)."""
    open(f"{d}/doc.tex", "w").write(src); log = ""
    for _ in range(passes):
        try:
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "-no-shell-escape", "doc.tex"], cwd=d, env=TEX_ENV,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=TEX_TIMEOUT)
        except subprocess.TimeoutExpired:
            return log + f"\n! hbench: pdflatex timed out after {TEX_TIMEOUT}s\n"
        log = open(f"{d}/doc.log", errors="replace").read() if os.path.exists(f"{d}/doc.log") else ""
        if not re.search(r"Rerun to get|Label\(s\) may have changed", log): break
    return log

PROBE_DEF = r"""
\makeatletter
\newcommand\hbprobe[1]{\pgfutil@ifundefined{pgf@sh@ns@#1}{\typeout{@@MISS #1}}{%
  \edef\hbshape{\csname pgf@sh@ns@#1\endcsname}%
  \hbanchor{#1}{center}%
  \pgfutil@ifundefined{pgf@anchor@\hbshape @north}{}{\hbanchor{#1}{north}\hbanchor{#1}{south}\hbanchor{#1}{east}\hbanchor{#1}{west}}}}
\newcommand\hbanchor[2]{\pgfpointanchor{#1}{#2}\typeout{@@ANCHOR #1 #2 \the\pgf@x\space\the\pgf@y}}
\makeatother
"""

def probe(src, names):
    """Where TikZ really put the named nodes: {name: {anchor: (x_pt, y_pt)}}, missing names left out."""
    i = src.rfind("\\end{tikzpicture}")
    if i < 0 or "\\begin{document}" not in src: return {}
    calls = "".join(f"\\hbprobe{{{n}}}" for n in names)
    s = (src[:i] + calls + src[i:]).replace("\\begin{document}", PROBE_DEF + "\\begin{document}", 1)
    with tempfile.TemporaryDirectory() as d:
        log = run_tex(s, d, passes=1)
    out = {}
    for n, a, x, y in re.findall(r"@@ANCHOR (\S+) (\S+) (-?[\d.]+)pt\s+(-?[\d.]+)pt", log):
        out.setdefault(n, {})[a] = (float(x), float(y))
    return out

class Doc:
    def __init__(self, text, save_as=None):
        self.src = extract_doc(text); self.code = strip_comments(self.src)
        self.log = ""; self.layout = ""; self.words = []; self.page_width = 0; self.figure = None
        if not self.src: return
        with tempfile.TemporaryDirectory() as d:
            self.log = run_tex(self.src, d)
            pdf = f"{d}/doc.pdf"
            if not os.path.exists(pdf): return
            self.layout = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
            box = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True).stdout
            m = re.search(r'<page width="([\d.]+)"', box); self.page_width = float(m.group(1)) if m else 0
            self.words = [(w, float(a), float(b), float(c), float(e)) for a, b, c, e, w in
                          re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', box)]
            if save_as:
                subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", "1", "-l", "1", "-singlefile", pdf, f"{d}/page"], capture_output=True)
                if os.path.exists(f"{d}/page.png"):
                    shutil.copy(f"{d}/page.png", save_as); self.figure = os.path.basename(save_as)
    @property
    def errors(self):
        return re.findall(r"^! .*", self.log, re.M)
    @property
    def compiled(self):
        return bool(self.page_width) and not self.errors
    def said(self, s):
        return flat(s) in flat(self.layout)
    def row(self, *cells):
        """The cells on one line of the rendered page, in order, as whole words."""
        return re.search(r"(?<!\S)" + r"\s+".join(map(re.escape, cells)) + r"(?!\S)", self.layout)
    def has(self, pat, flags=0):
        return re.search(pat, self.code, flags)
    def count(self, pat):
        return len(re.findall(pat, self.code))
    def package_at(self, name):
        """Where the document loads a package, -1 if it doesn't."""
        for m in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", self.code):
            if name in [p.strip() for p in m.group(1).split(",")]: return m.start()
        return -1
    def package(self, name):
        return self.package_at(name) >= 0
    def shows_words(self, text):
        """Every word of text on the page: for pictures, where a node's lines can land among its neighbours' text."""
        have = {flat(w[0]) for w in self.words}
        return all(flat(w) in have for w in text.split())
    def overfull(self, limit=10):
        return [float(x) for x in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide", self.log) if float(x) > limit]
    def kept(self, *sentences):
        """Sentences of the original still in the source (an edit that rewrites or drops text fails)."""
        norm = re.sub(r"\s+", " ", self.code)
        return [s for s in sentences if s not in norm]

def _ck(name, ok, detail="", heuristic=False):
    return dict(name=name, ok=bool(ok), detail=str(detail), heuristic=heuristic)

def common(doc):
    undefined = re.findall(r"(?:Reference|Citation) `[^']*' .*undefined", doc.log)
    return [_ck("compiles with pdflatex, no errors", doc.compiled, "; ".join(doc.errors[:3]) or ("no document found" if not doc.src else "")),
            _ck("no undefined references", doc.page_width and not undefined, "; ".join(undefined[:3])),
            _ck("no overfull line over 10pt", doc.compiled and not doc.overfull(), doc.overfull())]

# ------------------------------------------------- TikZ source: which node is joined to which
def tikz_body(doc):
    m = re.search(r"\\begin\{tikzpicture\}(.*)\\end\{tikzpicture\}", doc.code, re.S)
    return m.group(1) if m else ""

def statements(body):
    out, cur, depth = [], [], 0
    for ch in body:
        depth += (ch == "{") - (ch == "}")
        if ch == ";" and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    return out

def edges(doc, names):
    """[(source, target, text between them, whole statement)] from \\draw (a) -- node {x} (b); and the like."""
    out = []
    for st in statements(tikz_body(doc)):
        ms = [m for m in re.finditer(r"\(\s*(\w+)(?:\.[^()]*)?\s*\)", st) if m.group(1) in names]
        for m, n in zip(ms, ms[1:]):
            between = st[m.end():n.start()]
            if not re.search(r"--|-\||\|-|\.\.|\bedge\b|\bto\b", between): continue
            a, b = m.group(1), n.group(1)
            if a == b: continue  # (a) -- ($(a)+(0,1)$) -- (b): a waypoint, not a loop
            if re.search(r"\[[^\]]*<-(?!>)[^\]]*\]", st): a, b = b, a
            out.append((a, b, between, st))
    return out

def bbox(anchors):
    xs = [anchors[k][0] for k in ("east", "west") if k in anchors]; ys = [anchors[k][1] for k in ("north", "south") if k in anchors]
    return (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None

def overlaps(where, tol=1.0):
    boxes = {n: bbox(a) for n, a in where.items() if bbox(a)}; names = sorted(boxes); bad = []
    for i, n in enumerate(names):
        for m in names[i + 1:]:
            p, q = boxes[n], boxes[m]
            if min(p[2], q[2]) - max(p[0], q[0]) > tol and min(p[3], q[3]) - max(p[1], q[1]) > tol: bad.append((n, m))
    return bad

def column_spec(tab):
    """The tabular's column spec, nested braces and all ('' if there is no tabular)."""
    m = re.search(r"\\begin\{tabular\}\s*(?:\[\w\])?\s*\{", tab)
    if not m: return ""
    depth, i = 1, m.end()
    while depth and i < len(tab):
        depth += (tab[i] == "{") - (tab[i] == "}"); i += 1
    return tab[m.end():i - 1]

# ------------------------------------------------- items
def l01(doc):
    tab = doc.code.split("\\begin{table}")[-1] if "\\begin{table}" in doc.code else ""
    pos = lambda s: tab.find(s) if s in tab else -1
    spec = column_spec(tab)
    align = re.sub(r"[@!<>]\{[^}]*\}|\[[^\]]*\]|\s", "", spec)
    align = re.sub(r"\*\{(\d)\}\{(\w)\}", lambda m: m.group(2) * int(m.group(1)), align)
    unchanged = ("We compare four iterative solvers on a model Poisson problem", "Multigrid is the method of choice for this problem class.", "and is the fastest by a wide margin.")
    return common(doc) + [
        _ck("booktabs rules, no \\hline", doc.package("booktabs") and all(r in tab for r in ("\\toprule", "\\midrule", "\\bottomrule")) and "\\hline" not in tab),
        _ck("no vertical rules", spec and "|" not in spec, spec),
        _ck("numeric columns right-aligned", re.fullmatch(r"[lc]r{3}|[lc]S{3}", align), align),
        _ck("caption above the tabular, label after the caption", 0 <= pos("\\caption") < pos("\\label{tab:solvers}") and pos("\\caption") < pos("\\begin{tabular}")),
        _ck("caption text in the output", doc.said("Table 1: Solver comparison on the 1283 grid")),
        _ck("cross-reference prints Table 1", doc.said("As Table 1 shows") and "TODO-REF" not in doc.code and "\\ref{tab:solvers}" in doc.code),
        _ck("table placed after the paragraph", 0 < doc.layout.find("summarised below") < doc.layout.find("Iterations") < doc.layout.find("As Table 1 shows")),
        _ck("all four rows correct", doc.row("Jacobi", "1842", "3.41", "0.0098") and doc.row("Gauss-Seidel", "967", "2.05", "0.0091")
            and doc.row("SOR", "214", "0.62", "0.0087") and doc.row("Multigrid", "11", "0.18", "0.0042")),
        _ck("rest of the text unchanged", doc.src and not doc.kept(*unchanged), doc.kept(*unchanged))]

def l02(doc):
    bold = re.findall(r"(?:\\textbf\{\s*|\\bfseries\s*|\\mathbf\{\s*)([\d.]+)", doc.code)
    return common(doc) + [
        _ck("booktabs, no \\hline, no vertical rules", doc.package("booktabs") and "\\hline" not in doc.code and not doc.has(r"\\begin\{tabular\}\s*\{[^}]*\|")),
        _ck("two \\multicolumn group headers", doc.has(r"\\multicolumn\{2\}\{[^}]*\}\{(\\\w+\{)?\s*CG\b") and doc.has(r"\\multicolumn\{2\}\{[^}]*\}\{(\\\w+\{)?\s*GMRES\b")),
        _ck("\\cmidrule under each group", doc.count(r"\\cmidrule") >= 2),
        _ck("multirow for 2D and 3D", doc.package("multirow") and doc.has(r"\\multirow(\[\w\])?\{2\}\{[^}]*\}\{(\\\w+\{)?\s*2D\b") and doc.has(r"\\multirow(\[\w\])?\{2\}\{[^}]*\}\{(\\\w+\{)?\s*3D\b")),
        _ck("second header row", doc.row("Dimension", "N", "Iter.", "Time", "(s)", "Iter.", "Time", "(s)")),
        _ck("all four rows correct", doc.row("64", "112", "0.42", "98", "0.57") and doc.row("128", "225", "1.93", "201", "1.71")
            and doc.row("64", "141", "8.15", "133", "9.02") and doc.row("128", "287", "71.6", "262", "64.3")),
        _ck("bold marks exactly the faster times", sorted(bold) == sorted(["0.42", "1.71", "8.15", "64.3"]), bold),
        _ck("caption and label", doc.said("Krylov solver cost") and "\\label{tab:krylov}" in doc.code)]

L03_CELLS = ["Spatial discretisation", "Second-order finite volumes on a staggered grid", "Conserves mass exactly and avoids spurious pressure modes on uniform meshes",
             "Time integration", "Third-order strong-stability-preserving Runge-Kutta", "Keeps the total variation bounded for the advective terms at moderate cost",
             "Linear solver", "Conjugate gradients with an algebraic multigrid preconditioner", "Iteration counts stay nearly independent of the mesh size in all our tests"]

def l03(doc):
    cheat = re.findall(r"\\(?:resizebox|scalebox|adjustbox|makebox|rotatebox|tiny|scriptsize|footnotesize)\b|\{(?:adjustbox|landscape|sidewaystable)\}|\\newgeometry", doc.code)
    out = [w for w in doc.words if w[1] < 70 or w[3] > doc.page_width - 70]
    lost = [c for c in L03_CELLS if flat(c) not in flat(doc.code)]  # the source: wrapped cells interleave on the page
    return common(doc) + [
        _ck("no overfull \\hbox at all", doc.compiled and not doc.overfull(1), doc.overfull(1)),
        _ck("every word inside the margins", doc.compiled and not out, [w[0] for w in out][:5]),
        _ck("no scaling, hiding, rotating or tiny fonts", doc.src and not cheat, cheat),
        _ck("margins unchanged", "\\usepackage[margin=1in]{geometry}" in doc.code),
        _ck("all cell text kept", doc.compiled and not lost, lost),
        _ck("caption, label and rules kept", doc.said("Table 1: Options considered for each part of the solver") and doc.said("Table 1 lists the options")
            and all(r in doc.code for r in ("\\toprule", "\\midrule", "\\bottomrule")))]

def l04(doc):
    weak = next((b for _, b in re.findall(r"\\begin\{(align|equation)\}(.*?)\\end\{\1\}", doc.code, re.S) if "\\label{eq:weak}" in b), "")
    return common(doc) + [
        _ck("amsmath loaded; no $$ or eqnarray", doc.package("amsmath") and doc.src and "$$" not in doc.code and "eqnarray" not in doc.code),
        _ck("exactly four numbers, (1) to (4)", all(f"({i})" in doc.layout for i in range(1, 5)) and "(5)" not in doc.layout),
        _ck("eq:pde and eq:bc numbered in one align", doc.has(r"\\begin\{(align|alignat|flalign)\}(?:(?!\\end\{).)*\\label\{eq:pde\}(?:(?!\\end\{).)*\\label\{eq:bc\}", re.S)),
        _ck("PDE and boundary condition", doc.has(r"-\s*\\Delta\s*u\s*&?\s*=") and doc.has(r"\\partial\s*\\Omega")),
        _ck("cases with the two branches", doc.has(r"\\begin\{cases\}(?:(?!\\end\{cases\}).)*otherwise", re.S) and doc.has(r"\\frac\{1\}\{2\}|1/2")),
        _ck("weak form aligned on =, numbered once", "\\nabla" in weak and len(re.findall(r"&\s*=", weak)) >= 2 and re.search(r"\\nonumber|\\notag|\\begin\{(split|aligned)\}", weak)),
        _ck("integrals over Omega", doc.count(r"\\int_\{?\\Omega") >= 3),
        _ck("stiffness matrix", doc.has(r"\\frac\{1\}\{h\}") and doc.has(r"\\begin\{pmatrix\}\s*1\s*&\s*-\s*1\s*\\\\\s*-\s*1\s*&\s*1")),
        _ck("matrix display unnumbered", doc.has(r"\\begin\{(equation\*|align\*)\}(?:(?!\\end\{(?:equation|align)).)*\\begin\{pmatrix\}", re.S) or doc.has(r"\\\[(?:(?!\\\]).)*\\begin\{pmatrix\}", re.S)),
        _ck("references print the numbers", doc.has(r"(\\eqref|\\ref)\{eq:pde\}") and doc.has(r"(\\eqref|\\ref)\{eq:weak\}") and doc.said("Multiplying (1)") and doc.said("Equation (4) holds"))]

def l05(doc):
    # The faults sit in one paragraph: an unescaped grid_size starts math mode and drags the next sentences off the
    # page, so the % and & fixes also count when the source has them (the grid_size check and the compile checks
    # already charge for the underscore).
    text = re.sub(r"\s+", " ", doc.code)
    return common(doc) + [
        _ck("grid_size in the text", re.search(r"grid.?size set to 128", doc.layout.replace("\n", " "))),
        _ck("50% and the rest of its sentence kept", doc.said("About 50% of the runs converged within the first hundred iterations")
            or "About 50\\% of the runs converged within the first hundred iterations" in text),
        _ck("literal ampersand", doc.said("Jacobi & Gauss-Seidel") or re.search(r"Jacobi\s*(\\&|\\textrm\{\\&\})\s*Gauss-Seidel", text)),
        _ck("itemize kept, with its items", doc.count(r"\\begin\{itemize\}") == 1 and doc.count(r"\\end\{itemize\}") == 1 and doc.said("At most 500 iterations per solve")),
        _ck("reference to Setup prints Section 1", doc.said("settings from Section 1") and "\\ref{sec:setup}" in doc.code),
        _ck("fraction closed correctly", doc.has(r"\\frac\{1\}\{1\s*\+\s*k\^2\}\s*(\\,)?\s*e_0|\\frac\{1\}\{1\s*\+\s*k\^2\s*(\\,)?\s*e_0\}")),
        _ck("graphicx loaded, figure kept", doc.package("graphicx") and "example-image-a" in doc.code),
        _ck("figure reference prints Figure 1 (label after caption)", doc.said("visible in Figure 1") and doc.has(r"\\caption\{[^}]*\}\s*\\label\{fig:decay\}|\\caption\{.*\\label\{fig:decay\}")),
        _ck("literal dollar", doc.said("cost was $1200 per run")),
        _ck("equation reference kept", doc.said("By (1) the error decays quadratically"))]

def l06(doc):
    # Read on the proof's own sentences: the headings print "Lemma 1.2" whatever the references do. Each reference is
    # checked ignoring case, and the capital once: plain \cref prints "lemma 1.2", which the prompt rules out
    # ("like 'Lemma 1.2'"), and that one choice shouldn't cost three checks. said() ignores line breaks and
    # hyphenation ("Defini- tion").
    page = flat(doc.layout)
    sentences = ("By Lemma 1.2", "required by Definition 1.1", "analysis of Theorem 1.3")
    printed = lambda s: flat(s).lower() in page.lower()
    return common(doc) + [
        _ck("amsthm; hyperref before cleveref", doc.package("amsthm") and 0 <= doc.package_at("hyperref") < doc.package_at("cleveref")),
        _ck("numbering: Definition 1.1, Lemma 1.2, Theorem 1.3", doc.said("Definition 1.1") and doc.said("Lemma 1.2") and doc.said("Theorem 1.3")),
        _ck("definition in the definition style", doc.has(r"\\theoremstyle\{definition\}")),
        _ck("proof environment", doc.count(r"\\begin\{proof\}") == 1),
        _ck("proof cites lemma and definition via cleveref", doc.has(r"\\[cC]ref\{lem:bound\}") and doc.has(r"\\[cC]ref\{def:stable\}")
            and printed(sentences[0]) and printed(sentences[1])),
        _ck("closing sentence cites the theorem", doc.has(r"\\[cC]ref\{thm:main\}") and printed(sentences[2])),
        _ck("references print capitalised names (Lemma 1.2, not lemma 1.2)", all(doc.said(s) for s in sentences),
            [s for s in sentences if not doc.said(s)])]

def l07(doc):
    a = [w for w in doc.words if w[0] == "(a)"]; b = [w for w in doc.words if w[0] == "(b)"]
    side = a and b and abs(a[0][2] - b[0][2]) < 3 and b[0][1] - a[0][1] > 100
    return common(doc) + [
        _ck("subcaption package, not subfigure/subfig", doc.package("subcaption") and not doc.package("subfigure") and not doc.package("subfig")),
        _ck("two subfigure environments with both images", doc.count(r"\\begin\{subfigure\}") == 2 and "example-image-a" in doc.code and "example-image-b" in doc.code),
        _ck("subcaptions side by side in the output", side, [(w[0], w[1], w[2]) for w in a + b]),
        _ck("subcaption texts", doc.said("(a) Error") and doc.said("(b) Runtime")),
        _ck("overall caption", doc.said("Figure 1: Mesh refinement study") and "\\label{fig:study}" in doc.code),
        _ck("references print Figure 1a and Figure 1b", doc.said("as Figure 1a shows") and doc.said("as Figure 1b shows") and "TODO" not in doc.code),
        _ck("rest of the text unchanged", doc.src and not doc.kept("We refined the mesh four times and recorded the error and the time for each level.")),
        _ck("figure after the first paragraph", doc.code.find("each level.") < doc.code.find("\\begin{figure}") < doc.code.find("The error falls"))]

def l08(doc):
    m = re.sub(r"\{k\s*\+\s*1\}", "k1", doc.code); m = re.sub(r"\^\{(\\?\w+)\}", r"^\1", m)  # r_{k+1}^{T} -> r_k1^T
    to = r"\s*(\\gets|\\leftarrow|:?=)\s*"; ratio = r"\\d?frac\{[^{}]*r[^{}]*z[^{}]*\}\{[^{}]*%s[^{}]*\}"
    math_has = lambda p: re.search(p, m)
    return common(doc) + [
        _ck("algorithm + algpseudocode", doc.package("algorithm") and doc.package("algpseudocode")),
        _ck("numbered algorithmic", doc.has(r"\\begin\{algorithmic\}\[1\]") and re.search(r"(?m)^\s*1:", doc.layout)),
        _ck("caption and reference print Algorithm 1", doc.said("Algorithm 1 Preconditioned conjugate gradients") and doc.has(r"\\ref\{alg:pcg\}") and doc.said("Algorithm 1 needs one preconditioner solve")),
        _ck("Require, Ensure, While, Return, Comment", all(doc.has(r"\\" + k + r"\b") for k in ("Require", "Ensure", "While", "EndWhile", "Return", "Comment"))),
        _ck("initial setup r0, z0, p0", math_has(r"r_0" + to + r"b\s*-\s*A\s*x_0") and math_has(r"z_0" + to + r"M\^\{-1\}\s*r_0") and math_has(r"p_0" + to + r"z_0"), heuristic=True),
        _ck("alpha uses r^T z / p^T A p", math_has(r"\\alpha_k" + to + ratio % r"p[^{}]*A[^{}]*p"), heuristic=True),
        _ck("beta is new r^T z over old r^T z", math_has(r"\\beta_k" + to + r"\\d?frac\{[^{}]*r_k1[^{}]*z_k1[^{}]*\}\{(?![^{}]*k1)[^{}]*r[^{}]*z[^{}]*\}"), heuristic=True),
        _ck("updates x += alpha p, r -= alpha A p, p = z + beta p", math_has(r"x(_k1)?" + to + r"x(_k)?\s*\+\s*\\alpha") and math_has(r"r(_k1)?" + to + r"r(_k)?\s*-\s*\\alpha")
            and math_has(r"p(_k1)?" + to + r"z(_k1)?\s*\+\s*\\beta"), heuristic=True)]

L09 = ["mesh", "assemble", "solve", "check", "refine", "output"]
L09_EDGES = {("mesh", "assemble"), ("assemble", "solve"), ("solve", "check"), ("check", "output"), ("check", "refine"), ("refine", "assemble")}
L09_TEXT = ["Generate mesh", "Assemble system", "Solve system", "Error small?", "Refine mesh", "Write output"]

def l09(doc):
    where = probe(doc.src, L09); es = edges(doc, L09); got = {e[:2] for e in es}
    label = lambda a, b, w: any(e[:2] == (a, b) and re.search(r"\bnode\b.*\b%s\b" % w, e[3], re.I | re.S) for e in es)
    return common(doc) + [
        _ck("all six named nodes exist", set(where) == set(L09), sorted(set(L09) - set(where))),
        _ck("node texts in the output", all(doc.shows_words(t) for t in L09_TEXT) and bool(doc.words), [t for t in L09_TEXT if not doc.shows_words(t)]),
        _ck("exactly the requested arrows", got == L09_EDGES, sorted(got ^ L09_EDGES)),
        _ck("arrow tips", doc.has(r"->|-\{?(Stealth|Latex|stealth|latex)"), heuristic=True),
        _ck("yes and no labels on the right arrows", label("check", "output", "yes") and label("check", "refine", "no")),
        _ck("no overlapping nodes", len(where) == 6 and not overlaps(where), overlaps(where)),
        _ck("diamond decision, rounded output", doc.has(r"\bdiamond\b") and doc.has(r"\brounded\b")),
        _ck("back edge does not pass through solve", _clear_back_edge(where, es), heuristic=True)]

def _clear_back_edge(where, es):
    """A straight refine -> assemble line that runs across another node's box is a drawing bug."""
    if not where.get("refine") or not where.get("assemble"): return False
    e = next((e for e in es if e[:2] == ("refine", "assemble")), None)
    if not e: return False
    if re.search(r"-\||\|-|bend|out=|in=|\+\+|\.\.", e[3]): return True
    (x0, y0), (x1, y1) = where["refine"]["center"], where["assemble"]["center"]
    for n, a in where.items():
        if n in ("refine", "assemble") or not bbox(a): continue
        l, b, r, t = bbox(a)
        for k in range(101):
            x = x0 + (x1 - x0) * k / 100; y = y0 + (y1 - y0) * k / 100
            if l < x < r and b < y < t: return False
    return True

L10 = list("abcdef")
L10_EDGES = {("a", "b"): 4, ("a", "c"): 2, ("b", "c"): 5, ("b", "d"): 10, ("c", "d"): 8, ("c", "e"): 3, ("d", "e"): 7, ("d", "f"): 6, ("e", "f"): 9}
L10_MST = {("a", "c"), ("c", "e"), ("a", "b"), ("d", "f"), ("d", "e")}

def l10(doc):
    where = probe(doc.src, L10)
    es = [(tuple(sorted(e[:2])), e[2], e[3]) for e in edges(doc, L10)]
    got = [e[0] for e in es]; want = set(L10_EDGES)
    wrong = [k for k, _, st in es if k in L10_EDGES and not re.search(r"\{[^{}]*(?<![\d.])%d(?![\d.])[^{}]*\}" % L10_EDGES[k], st)]
    mst = {k for k, between, st in es if re.search(r"\bmst\b", st)}
    return common(doc) + [
        _ck("six named circular nodes", set(where) == set(L10) and doc.has(r"\bcircle\b"), sorted(set(L10) - set(where))),
        _ck("exactly the nine edges, each once", set(got) == want and len(got) == len(want), sorted(set(got) ^ want)),
        _ck("every weight on its edge", set(got) >= want and not wrong, wrong),
        _ck("mst style defined", doc.has(r"\bmst\s*/\.style")),
        _ck("mst style on exactly the tree edges", mst == L10_MST, sorted(mst ^ L10_MST)),
        _ck("caption states total weight 22", re.search(r"total\s+weight\s+\$?22\$?", re.sub(r"\s+", " ", doc.layout))),
        _ck("no overlapping nodes", len(where) == 6 and not overlaps(where), overlaps(where))]

R = 2 * 72.27 / 2.54  # 2 cm in TeX points
L11 = dict(O=(0, 0), A=(R, 0), P=(R * math.cos(math.pi / 6), R / 2), Q=(R * math.cos(math.pi / 6), 0), T=(R, R * math.tan(math.pi / 6)))

def l11(doc):
    where = probe(doc.src, list(L11)); tol = 0.1 / 25.4 * 72.27  # 0.1 mm
    o = where.get("O", {}).get("center")
    def near(n):
        c = where.get(n, {}).get("center")
        return bool(c and o) and math.hypot(c[0] - o[0] - L11[n][0], c[1] - o[1] - L11[n][1]) < tol
    seg = lambda a, b: re.search(r"\(%s[^)]*\)[^;]*?(--|\bto\b)[^;]*?\(%s[^)]*\)" % (a, b), doc.code) or re.search(r"\(%s[^)]*\)[^;]*?(--|\bto\b)[^;]*?\(%s[^)]*\)" % (b, a), doc.code)
    return common(doc) + [
        _ck("all five coordinates exist", set(where) == set(L11), sorted(set(L11) - set(where))),
        *[_ck(f"{n} at the exact position", near(n), where.get(n, {}).get("center")) for n in "APQT"],
        _ck("circle of radius 2", doc.has(r"circle\s*(\[\s*radius\s*=\s*2(cm)?\s*\]|\(\s*2(cm)?\s*\))"), heuristic=True),
        _ck("segments OP, PQ and AT drawn", (seg("O", "P") or seg("O", "T")) and seg("P", "Q") and seg("A", "T"), heuristic=True),
        _ck("axes with arrow tips", doc.has(r"->|-\{?(Stealth|Latex|stealth|latex)"), heuristic=True),
        _ck("angle arc", doc.has(r"\barc\b|angle\s*=|pic\s*\[?[^;]*angle"), heuristic=True),
        _ck("labels sin, cos, tan and theta", all(doc.has(r"\\%s\s*\\theta" % k) for k in ("sin", "cos", "tan")) and doc.said("sin θ") and doc.said("cos θ") and doc.said("tan θ"))]

L12_DATA = [0.2, 0.1, 0.05, 0.025, 3.1e-2, 7.9e-3, 2.0e-3, 5.0e-4, 4.2e-3, 5.4e-4, 6.8e-5, 8.5e-6]

def l12(doc):
    m = re.search(r"\\begin\{(loglogaxis|axis)\}(.*?)\\end\{\1\}", doc.code, re.S)
    body = m.group(2) if m else ""
    nums = [float(x) for x in re.findall(r"(?<![\w.^-])\d*\.?\d+(?:[eE][-+]?\d+)?", body)]
    missing = [v for v in L12_DATA if not any(abs(n - v) < 1e-9 + 1e-6 * v for n in nums)]
    ref = any(abs(n - 1.55) < 0.01 or abs(n - 9.6875e-4) < 4e-6 for n in nums) or re.search(r"(0?\.062|6\.2e-0?2)\s*\*?\s*\(\s*x\s*/\s*0?\.2\s*\)\s*\^\s*\{?2|(0?\.062|6\.2e-0?2)\s*/\s*0?\.04", body)
    return common(doc) + [
        _ck("pgfplots with a numeric compat", doc.package("pgfplots") and doc.has(r"compat\s*=\s*1\.\d+")),
        _ck("no pgfplots compatibility warning", doc.compiled and "running in backwards compatibility mode" not in doc.log),
        _ck("both axes logarithmic", m and (m.group(1) == "loglogaxis" or (re.search(r"xmode\s*=\s*log", body) and re.search(r"ymode\s*=\s*log", body)))),
        _ck("axis labels", doc.said("Mesh size") and re.search(r"ylabel\s*=", body) and re.search(r"xlabel\s*=", body)),
        _ck("major grid", re.search(r"grid\s*=\s*(major|both)|\bgrid\b", body)),
        _ck("every data value plotted", m and not missing, missing),
        _ck("three \\addplot series", len(re.findall(r"\\addplot", body)) == 3),
        _ck("legend P1, P2, slope 2", doc.row("P1") and doc.row("P2") and doc.said("slope 2")),
        _ck("slope-2 line through (0.2, 6.2e-2)", ref and re.search(r"dashed", body), heuristic=True),
        _ck("figure with caption", doc.count(r"\\begin\{figure\}") == 1 and doc.said("Figure 1: Convergence under mesh refinement"))]

ITEMS = dict(l01=l01, l02=l02, l03=l03, l04=l04, l05=l05, l06=l06, l07=l07, l08=l08, l09=l09, l10=l10, l11=l11, l12=l12)

def grade(lid, text, save_dir=None):
    save_as = f"{save_dir}/{lid}.png" if save_dir else None
    if save_as and os.path.exists(save_as): os.remove(save_as)
    doc = Doc(text, save_as)
    checks = ITEMS[lid](doc)
    return dict(checks=checks, auto=sum(c["ok"] for c in checks), max=len(checks), error="; ".join(doc.errors[:5]) or None, figure=doc.figure)
