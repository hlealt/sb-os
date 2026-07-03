#!/usr/bin/env python3
"""sb-tutor-build-library — build the Lumen visual learning library.

Turns per-topic markdown page-sources (``{library_root}/topics/*.md``) into one
self-contained HTML page each (``{library_root}/pages/{slug}.html``) plus a
knowledge-map ``{library_root}/index.html``. CSS/JS are inlined from
``learning-library/assets/`` so every page works offline (no CDN).

Usage:
  python sb-tutor-build-library.py --library-root PATH [--topic SLUG] [--json]

Schema: see learning-library/page-source-schema.md.
"""
from __future__ import annotations
import argparse, html, json, math, re, sys, urllib.parse
from pathlib import Path

try:
    import yaml
    import markdown as md
except ImportError as e:  # deterministic dependency
    sys.stderr.write(f"missing dependency: {e}. Run: pip install pyyaml markdown\n")
    sys.exit(2)

ASSETS = Path(__file__).resolve().parent / "learning-library" / "assets"
SPECIAL = {"graph", "chart", "quiz", "deeper", "trace", "flow", "tabs", "anncode"}
_TRACE_UID = [0]  # page-unique id seed for trace cells' shared-modal sources (reset per process)
_FLOW_UID = [0]   # page-unique id seed for flow stages' shared-modal detail sources
_TABS_UID = [0]   # page-unique id seed for tabs containers (scopes per-container tab switching)
_ACODE_UID = [0]  # page-unique id seed for annotated-code line markers' shared-modal note sources
_CODE_UID = [0]   # page-unique id seed for visible code-block Expand sources
_ZOOM_UID = [0]   # page-unique id seed for graph/chart Zoom sources
FENCE = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.DOTALL | re.MULTILINE)
# matches ONLY md_html-generated visible code blocks (class is exactly "code" + a <code> child);
# never the trace modal's `<pre class="code trace-code">` payload — so trace code is left untouched.
_CODE_BLOCK = re.compile(r'<pre class="code"><code>.*?</code></pre>', re.DOTALL)
# citations (v1): inline [^N] = SOURCE marker, [^gN] = TRAINING marker; footnote-def lines
# `[^N]: {subject, page}` / `[^gN]: desc` are pulled OUT of prose and rendered as a footnotes
# section at page end. Schema: learning-library/page-source-schema.md § Citations & provenance.
_CITE_RE = re.compile(r"\[\^(g?\d+)\]")
_FN_DEF_RE = re.compile(r"^[ \t]*\[\^(g?\d+)\]:[ \t]*(.*)$", re.MULTILINE)
# extracts the CODE TEXT inside each md_html code block so the highlighter can wrap tokens in
# spans without disturbing the wrapper tags (kept in sync with _CODE_BLOCK's shape).
_CODE_INNER = re.compile(r'(<pre class="code"><code>)(.*?)(</code></pre>)', re.DOTALL)
# matches a rendered markdown table so the builder can drop it in a horizontal-scroll wrapper.
_TABLE = re.compile(r'<table\b[^>]*>.*?</table>', re.DOTALL)
# Conservative, language-agnostic code highlighter (json/js/python/bash-ish). Operates on the
# ALREADY-HTML-ESCAPED code text and only WRAPS matched substrings in spans — never alters a
# character, so the visible text (and what Copy yields via textContent) stays byte-identical.
# Left-to-right, non-overlapping (re.finditer via re.sub), alternatives tried in order at each
# position: HTML entities match first and emit unchanged (so digits in `&#39;` are never numbered);
# strings win over comments/numbers/keywords (a `#` or number inside a string stays in the string).
# Anything ambiguous is left plain — a highlighter bug must never corrupt code or break the page.
# Quote delimiters as they appear AFTER HTML-escaping (python-markdown turns " -> &quot; inside
# code, and ' may arrive as &#39;), plus the literal forms for robustness.
_DQ = r'(?:&quot;|&#34;|")'
_SQ = r"(?:&#39;|&#x27;|')"
_HL = re.compile(
    # strings FIRST so a #, //, number, or keyword inside a string stays in the string
    r'(?P<st>' + _DQ + r'(?:\\.|(?!' + _DQ + r').)*' + _DQ
    + r'|' + _SQ + r'(?:\\.|(?!' + _SQ + r').)*' + _SQ + r')'
    # any remaining HTML entity (e.g. &lt; &amp; an unpaired &quot;) emits unchanged
    r'|(?P<ent>&[a-zA-Z]+;|&#x?[0-9A-Fa-f]+;)'
    # line comments: # or // only at line start or after whitespace (so https:// is never a comment)
    r'|(?P<cm>(?:(?<=\s)|^)(?:#|//)[^\n]*)'
    r'|(?P<nu>\b\d+(?:\.\d+)?\b)'
    r'|(?P<bo>\b(?:true|false|null|True|False|None)\b)'
    r'|(?P<kw>\b(?:import|from|def|return|if|else|for|in|function|const|let|var|GET|POST|PUT|DELETE)\b)',
    re.MULTILINE,
)


def _hl_token(m):
    g = m.lastgroup
    s = m.group()
    if g == "ent":  # leave entities untouched — never tokenize inside &lt; / &#39; etc.
        return s
    return f'<span class="{g}">{s}</span>'


def highlight_code(escaped: str) -> str:
    """Wrap recognizable tokens in `<span class="st|cm|nu|bo|kw">` inside ALREADY-ESCAPED code.
    Adds color only — the underlying characters are reproduced verbatim, so `.js-copy`
    (textContent) still yields byte-identical code. Best-effort + fail-safe: on any error the
    original escaped text is returned unchanged."""
    try:
        return _HL.sub(_hl_token, escaped)
    except Exception:
        return escaped


# ---------- small helpers ----------
def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(s).lower()).strip()
    return re.sub(r"[\s_-]+", "-", s) or "topic"


def md_html(text: str) -> str:
    h = md.markdown(text, extensions=["extra", "sane_lists"])
    h = re.sub(r"<pre><code[^>]*>", '<pre class="code"><code>', h)
    # syntax-highlight each visible code block's already-escaped text (wraps tokens in spans only)
    h = _CODE_INNER.sub(lambda m: m.group(1) + highlight_code(m.group(2)) + m.group(3), h)
    # callouts: blockquote starting with [!warn]/[!note]/[!tip]
    def _co(m):
        kind, body = m.group(1).lower(), m.group(2).strip()
        cls = "callout warn" if kind in ("warn", "warning", "danger") else "callout"
        ic = "&#9650;" if "warn" in cls else "&#9670;"
        return f'<div class="{cls}"><span class="ic">{ic}</span><div>{body}</div></div>'
    h = re.sub(r"<blockquote>\s*<p>\s*\[!(\w+)\]\s*(.*?)</p>\s*</blockquote>", _co, h, flags=re.DOTALL)
    # wide-table legibility: horizontal-scroll wrapper (sticky first column + scroll cue via CSS)
    h = _TABLE.sub(lambda m: f'<div class="tablewrap"><div class="tablescroll">{m.group(0)}</div></div>', h)
    return h


def apply_glossary(htext: str, glossary: dict, done=None) -> str:
    """Wrap the FIRST text occurrence of each glossary term in a highlighted span whose
    plain-language definition shows as a hover/focus tooltip (rendered by .gloss::after).
    Apply ONLY to prose HTML — NEVER to SVG/special-block HTML (an inline span inside an
    SVG <text> renders blank, e.g. a glossary term that matches a graph node label).
    The inserted <span> (definition and all) is parked at a TAG index so later terms never
    match inside it — a glossary definition often contains another glossary term, and
    wrapping that would corrupt the data-def attribute."""
    if not glossary:
        return htext
    if done is None:
        done = set()
    parts = re.split(r"(<[^>]+>)", htext)  # even indices = text outside tags; odd = tags (skipped)
    for term, definition in glossary.items():
        if term.lower() in done:
            continue
        pat = re.compile(r"\b(" + re.escape(term) + r")\b", re.IGNORECASE)
        for i in range(0, len(parts), 2):
            m = pat.search(parts[i])
            if m:
                span = f'<span class="gloss" tabindex="0" data-def="{esc(definition)}">{m.group(1)}</span>'
                parts[i:i + 1] = [parts[i][:m.start()], span, parts[i][m.end():]]  # span -> tag (odd) index
                done.add(term.lower())
                break
    return "".join(parts)


def wrap_code_blocks(htext: str) -> str:
    """Give every VISIBLE prose code block (md_html output) a Copy + Expand toolbar.
    Each match is wrapped in a `.codewrap` carrying a `.codebar` (Copy via app.js copyText;
    Expand opens the shared modal via `js-modal-open`/`data-modal-src`) plus a hidden
    `.lib-modal-src` duplicate the modal reads. Apply ONLY to the prose/md stream + deeper
    bodies — NEVER to a hidden modal source (the trace payload's `<pre class="code trace-code">`
    is not matched by _CODE_BLOCK, so trace code is never double-wrapped)."""
    def _w(m):
        _CODE_UID[0] += 1
        uid = f"cw{_CODE_UID[0]}"
        pre = m.group(0)
        return ('<div class="codewrap"><div class="codebar">'
                '<button class="codebtn js-copy" type="button" aria-label="Copy code">&#10697; Copy</button>'
                f'<button class="codebtn js-modal-open" type="button" data-modal-src="{uid}" '
                'aria-label="Expand code in a wide modal">&#10530; Expand</button></div>'
                f'{pre}<div class="lib-modal-src" id="{uid}" hidden>{pre}</div></div>')
    return _CODE_BLOCK.sub(_w, htext)


# ---------- citations & footnotes ----------
def _record_fn(m, footnotes: dict) -> str:
    """Record one footnote def (first def per label wins) and return '' so the def line is
    stripped from the prose flow. SOURCE defs ([^N]) carry {subject, page} (a flow map, or a
    bare subject string); TRAINING defs ([^gN]) carry a plain one-line description."""
    label, val = m.group(1), m.group(2).strip()
    if label.startswith("g"):
        footnotes.setdefault(label, {"kind": "gen", "desc": val})
    else:
        subject, page = val, None
        if val.startswith("{"):  # flow map {subject: ..., page: ...}
            try:
                d = yaml.safe_load(val)
            except yaml.YAMLError:
                d = None
            if isinstance(d, dict):
                subject = d.get("subject") or d.get("title") or d.get("name") or ""
                page = d.get("page") or d.get("path") or d.get("note")
        footnotes.setdefault(label, {"kind": "src", "subject": subject, "page": page})
    return ""


def _strip_fn_defs(text: str, footnotes: dict) -> str:
    """Pull footnote-def lines out of ONE prose chunk (recording them in `footnotes`), while
    protecting any fenced code so a def-shaped line inside a code block is never taken."""
    stash: list = []
    def _mask(mm):
        stash.append(mm.group(0))
        return f"\x00FN{len(stash) - 1}\x00"
    masked = FENCE.sub(_mask, text)
    masked = _FN_DEF_RE.sub(lambda mm: _record_fn(mm, footnotes), masked)
    return re.sub(r"\x00FN(\d+)\x00", lambda mm: stash[int(mm.group(1))], masked)


def collect_footnotes(sections):
    """Walk md segments across all sections, pull footnote-def lines OUT of prose, and return
    (footnotes, sections') — `footnotes` is a page-wide ordered dict keyed by as-authored label
    ('N' / 'gN'). Special/SVG segments (graph/chart/quiz/deeper/trace) are left untouched."""
    footnotes: dict = {}
    out = []
    for title, sid, segs in sections:
        nsegs = [("md", _strip_fn_defs(s[1], footnotes)) if s[0] == "md" else s for s in segs]
        out.append((title, sid, nsegs))
    return footnotes, out


def _cite_marker(label: str, footnotes: dict) -> str:
    """Render one inline citation marker: a hover-provenance superscript anchored to its
    footnote. SOURCE shows the as-authored number (violet); TRAINING shows a 'g' (amber)."""
    fn = footnotes.get(label) or {}
    if label.startswith("g"):
        desc = fn.get("desc", "")
        prov = "general knowledge (training data): " + desc if desc else "general knowledge (training data)"
        return (f'<sup class="cite cite-gen" data-prov="{esc(prov)}">'
                f'<a href="#fn-{esc(label)}">g</a></sup>')
    subject = fn.get("subject", "")
    prov = "from your wiki: " + subject if subject else "from your wiki"
    return (f'<sup class="cite cite-src" data-prov="{esc(prov)}">'
            f'<a href="#fn-{esc(label)}">{esc(label)}</a></sup>')


def process_citations(htext: str, footnotes: dict) -> str:
    """Convert inline [^N]/[^gN] in PROSE html into hover-provenance superscript markers.
    Markers inside code (`<pre>`/`<code>`, masked here) or inside HTML tags (only text nodes
    are scanned) are NEVER processed — citations are a prose-only feature. No-op when the html
    carries no marker, so a citation-free page renders byte-identically."""
    if not _CITE_RE.search(htext):
        return htext
    stash: list = []
    def _mask(m):
        stash.append(m.group(0))
        return f"\x00CT{len(stash) - 1}\x00"
    masked = re.sub(r"<pre\b[\s\S]*?</pre>", _mask, htext)
    masked = re.sub(r"<code\b[\s\S]*?</code>", _mask, masked)
    parts = re.split(r"(<[^>]+>)", masked)  # even = text outside tags; odd = tags (skipped)
    for i in range(0, len(parts), 2):
        parts[i] = _CITE_RE.sub(lambda m: _cite_marker(m.group(1), footnotes), parts[i])
    out = "".join(parts)
    return re.sub(r"\x00CT(\d+)\x00", lambda m: stash[int(m.group(1))], out)


# ---------- source parsing ----------
def parse_source(path: Path):
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.DOTALL)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
    meta.setdefault("slug", slugify(meta.get("title", path.stem)))
    meta.setdefault("title", path.stem)
    return meta, body


def split_sections(body: str, glossary: dict):
    """Return [(title, id, [segments])]. Segments: ('md',text) | ('special',kind,html).
    glossary is threaded to the special renderers so a graph node/edge explanation
    (shown in the click-to-explain panel) gets the same highlighted hover tooltips as prose."""
    out = []
    for block in re.split(r"^##\s+", body, flags=re.MULTILINE)[1:]:
        line, _, rest = block.partition("\n")
        title = line.strip()
        out.append((title, slugify(title), parse_segments(rest, glossary)))
    return out


def parse_segments(text: str, glossary: dict):
    segs, pos = [], 0
    for m in FENCE.finditer(text):
        if m.group(1).lower() not in SPECIAL:
            continue  # leave code fences in the md stream
        if text[pos:m.start()].strip():
            segs.append(("md", text[pos:m.start()]))
        segs.append(("special", m.group(1).lower(), render_special(m.group(1).lower(), m.group(2), glossary)))
        pos = m.end()
    if text[pos:].strip():
        segs.append(("md", text[pos:]))
    return segs


def render_special(kind: str, content: str, glossary: dict) -> str:
    if kind == "deeper":
        first, _, rest = content.partition("\n")
        return (f'<details class="deeper"><summary>{esc(first.strip())}</summary>'
                f'<div class="dbody">{wrap_code_blocks(apply_glossary(md_html(rest.strip()), glossary))}</div></details>')
    try:  # one malformed block must NOT fail the whole page
        spec = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        msg = str(e).splitlines()[0]
        return (f'<div class="callout warn"><span class="ic">&#9650;</span><div>This <b>{esc(kind)}</b> block '
                f'could not be rendered (YAML error: {esc(msg)}). Quote any value containing <code>:</code> or <code>#</code>.</div></div>')
    if kind == "graph":
        return render_graph(spec, glossary)
    if kind == "chart":
        return render_chart(spec)
    if kind == "quiz":
        return render_quiz(spec)
    if kind == "trace":
        return render_trace(spec, glossary)
    if kind == "flow":
        return render_flow(spec, glossary)
    if kind == "tabs":
        return render_tabs(spec, glossary)
    if kind == "anncode":
        return render_anncode(spec, glossary)
    return ""


# ---------- visuals ----------
def _zoom_affordance(svg_str: str) -> str:
    """A Zoom button (opens the diagram's SVG in the shared wide modal via
    `js-modal-open`/`data-modal-src`) plus the hidden `.lib-modal-src` the modal reads."""
    _ZOOM_UID[0] += 1
    uid = f"zm{_ZOOM_UID[0]}"
    return (f'<button class="viz-zoom js-modal-open" type="button" data-modal-src="{uid}" '
            f'aria-label="Zoom this diagram to full width">&#10530; Zoom</button>'
            f'<div class="lib-modal-src" id="{uid}" hidden><div class="viz-modal">{svg_str}</div></div>')


def render_graph(spec: dict, glossary: dict) -> str:
    # Full-width graph (detail panel BELOW it) so labels have room; nodes are text-sized
    # PILLS (no overflow); viewBox sized near display width so text scales ~1:1.
    # Node/edge descs may carry glossary <span> markup; data-desc DOUBLE-encodes it
    # (esc of already-rendered HTML) so app.js getAttribute()+innerHTML restores live HTML
    # — a jargon term inside a click-to-explain panel is itself hover-defined. SVG node
    # LABELS stay glossary-free (a <span> inside <text> renders blank).
    nodes = spec.get("nodes", []) or []
    edges = spec.get("edges", []) or []
    if not nodes:
        return ""
    order = [nd["id"] for nd in nodes]
    idset = set(order)
    half = {nd["id"]: (max(64, len(nd.get("label", "")) * 7.7 + 28) / 2.0, 17.0) for nd in nodes}
    deg = {i: 0 for i in order}
    for e in edges:
        if e.get("from") in deg: deg[e["from"]] += 1
        if e.get("to") in deg: deg[e["to"]] += 1
    back_set = set()
    pos = {}
    author_pos = all(("x" in nd and "y" in nd) for nd in nodes)
    if author_pos:
        for nd in nodes:
            pos[nd["id"]] = (float(nd["x"]), float(nd["y"]))
        W = 760
        H = int(max((y for _, y in pos.values()), default=370) + 60)
    else:
        outs = {i: [] for i in order}
        inc = {i: [] for i in order}
        for e in edges:
            f, t = e.get("from"), e.get("to")
            if f in idset and t in idset and f != t:
                outs[f].append(t); inc[t].append(f)
        # mark cycle back-edges (DFS) so layering runs over a DAG
        color = {i: 0 for i in order}
        def visit(u):
            color[u] = 1
            for v in outs[u]:
                if color[v] == 1: back_set.add((u, v))
                elif color[v] == 0: visit(v)
            color[u] = 2
        roots = [i for i in order if not inc[i]] or [next((nd["id"] for nd in nodes if nd.get("hi")), order[0])]
        for r in roots:
            if color[r] == 0: visit(r)
        for i in order:
            if color[i] == 0: visit(i)
        fedges = [(e.get("from"), e.get("to")) for e in edges
                  if e.get("from") in idset and e.get("to") in idset
                  and e.get("from") != e.get("to") and (e.get("from"), e.get("to")) not in back_set]
        # longest-path layering over the DAG (forward edges only)
        layer = {i: 0 for i in order}
        for _ in range(len(order) + 1):
            ch = False
            for f, t in fedges:
                if layer[t] < layer[f] + 1: layer[t] = layer[f] + 1; ch = True
            if not ch: break
        maxL = max(layer.values()) if layer else 0
        rows = {}
        for i in order:
            rows.setdefault(layer[i], []).append(i)
        widest = max((len(r) for r in rows.values()), default=1)
        W = max(840, widest * 132)
        mxp, top, gap = 64, 50, 124
        H = int(top + maxL * gap + 60)
        for L in range(maxL + 1):
            row = rows.get(L, [])
            if L > 0:  # order each layer by parent barycenter to cut edge crossings
                def _bary(i):
                    ps = [pos[p][0] for p in inc[i] if p in pos]
                    return sum(ps) / len(ps) if ps else W / 2.0
                row = sorted(row, key=_bary); rows[L] = row
            k = len(row)
            for j, i in enumerate(row):
                pos[i] = ((W / 2.0) if k == 1 else (mxp + (W - 2 * mxp) * ((j + 0.5) / k)), top + L * gap)

    def border(c, toward, hw, hh, gp):
        # point on c's rect border toward `toward`, pushed out by gp px (room for the arrowhead)
        ux, uy = toward[0] - c[0], toward[1] - c[1]
        if ux == 0 and uy == 0: return c
        t = min(hw / abs(ux) if ux else 9e9, hh / abs(uy) if uy else 9e9)
        d = math.hypot(ux, uy) or 1
        return c[0] + ux * t + ux / d * gp, c[1] + uy * t + uy / d * gp

    svg = [f'<svg viewBox="0 0 {W} {H}" role="group" aria-label="Interactive concept diagram">']
    for e in edges:
        f, t = e.get("from"), e.get("to")
        if f not in pos or t not in pos:
            continue
        a, b = pos[f], pos[t]
        hwf, hhf = half.get(f, (32, 17)); hwt, hht = half.get(t, (32, 17))
        sx, sy = border(a, b, hwf, hhf, 0)   # leave the SOURCE border
        ex, ey = border(b, a, hwt, hht, 7)   # stop 7px before the TARGET border (arrowhead sits in the gap)
        label = e.get("label", ""); wl = len(label) * 6.4 + 12
        if (f, t) in back_set:               # curved cycle-return edge
            cxp = max(sx, ex) + 72 + abs(sy - ey) * 0.16
            mp = (sy + ey) / 2
            geo = (f'<path class="hit" d="M{sx:.0f},{sy:.0f} Q{cxp:.0f},{mp:.0f} {ex:.0f},{ey:.0f}" fill="none"/>'
                   f'<path class="vis" d="M{sx:.0f},{sy:.0f} Q{cxp:.0f},{mp:.0f} {ex:.0f},{ey:.0f}" fill="none"/>')
            lx, ly = cxp - 4, mp
        else:
            geo = (f'<line class="hit" x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}"/>'
                   f'<line class="vis" x1="{sx:.0f}" y1="{sy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}"/>')
            # bias the label toward the lower-degree (spoke) end so labels spread out instead of piling at a hub
            frac = 0.6 if deg.get(f, 0) >= deg.get(t, 0) else 0.4
            lx, ly = sx + (ex - sx) * frac, sy + (ey - sy) * frac
        svg.append(
            f'<g class="iedge" tabindex="0" role="button" data-kind="Edge" '
            f'data-title="{esc(label)}" data-desc="{esc(apply_glossary(esc(e.get("desc","")), glossary))}">'
            f'{geo}'
            f'<rect class="elbg" x="{lx-wl/2:.0f}" y="{ly-9:.0f}" width="{wl:.0f}" height="17" rx="5"/>'
            f'<text x="{lx:.0f}" y="{ly+3:.0f}" text-anchor="middle">{esc(label)}</text></g>')
    for nd in nodes:
        x, y = pos[nd["id"]]
        label = nd.get("label", "")
        w = max(64, len(label) * 7.7 + 28)
        cls = "inode k" if nd.get("hi") else "inode"
        svg.append(
            f'<g class="{cls}" tabindex="0" role="button" data-kind="{esc(nd.get("kind","Node"))}" '
            f'data-title="{esc(label)}" data-desc="{esc(apply_glossary(esc(nd.get("desc","")), glossary))}">'
            f'<rect x="{x-w/2:.0f}" y="{y-17:.0f}" width="{w:.0f}" height="34" rx="17"/>'
            f'<text x="{x:.0f}" y="{y+5:.0f}" text-anchor="middle">{esc(label)}</text></g>')
    svg.append("</svg>")
    svg_str = "".join(svg)
    cap = f'<div class="vcap">{esc(spec.get("caption","click any node or edge to inspect"))}</div>'
    zoom = _zoom_affordance(svg_str)
    return (f'<div class="igraph-wrap"><div class="viz igraph">{zoom}<div class="hint">Click any node or edge</div>'
            f'{svg_str}{cap}</div>'
            f'<div class="detail empty" aria-live="polite"><div>Click any <b>node</b> or <b>edge</b> '
            f'in the diagram to see what it is.</div></div></div>')


def render_chart(spec: dict) -> str:
    xs = spec.get("x", []) or []
    series = spec.get("series", []) or []
    xlabel = spec.get("xlabel", "x"); ylabel = spec.get("ylabel", "value")
    W, H, x0, x1, y0, y1 = 820, 430, 78, 792, 70, 360  # full-width viewBox → fills the column, text scales ~1:1
    allv = [v for s in series for v in (s.get("values") or [])]
    maxv = max(allv) if allv else 1
    px = lambda i: x0 + (x1 - x0) * (i / max(len(xs) - 1, 1))
    py = lambda v: y1 - (y1 - y0) * (v / maxv if maxv else 0)
    svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(spec.get("caption","chart"))}">',
           f'<line class="ax" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>',
           f'<line class="ax" x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>']
    for i, xv in enumerate(xs):
        svg.append(f'<text class="axl" x="{px(i):.0f}" y="{y1+24:.0f}" text-anchor="middle">{esc(xv)}</text>')
    if spec.get("xlabel"):
        svg.append(f'<text class="axt" x="{(x0+x1)//2}" y="{H-10}" text-anchor="middle">{esc(xlabel)} &#8594;</text>')
    if spec.get("ylabel"):
        svg.append(f'<text class="axt" x="22" y="{(y0+y1)//2}" transform="rotate(-90 22 {(y0+y1)//2})" text-anchor="middle">{esc(ylabel)}</text>')
    lx = x0  # top legend
    for s in series:
        nm = s.get("name", "")
        svg.append(f'<rect x="{lx}" y="34" width="13" height="13" rx="3" fill="{esc(s.get("color","#5B4FE0"))}"/>'
                   f'<text class="leg" x="{lx+19}" y="45">{esc(nm)}</text>')
        lx += int(42 + len(nm) * 7.2)
    for s in series:
        vals = s.get("values") or []
        color = esc(s.get("color", "#5B4FE0"))
        nm = s.get("name", "")
        pts = " ".join(f"{px(i):.0f},{py(v):.0f}" for i, v in enumerate(vals))
        svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{pts}"/>')
        for i, v in enumerate(vals):
            xval = xs[i] if i < len(xs) else i
            tip = f"{nm}: {ylabel} = {v} at {xlabel} = {xval}"  # self-explanatory (axis-labelled)
            svg.append(f'<circle class="pt" cx="{px(i):.0f}" cy="{py(v):.0f}" r="6" fill="{color}">'
                       f'<title>{esc(tip)}</title></circle>')
    svg.append("</svg>")
    svg_str = "".join(svg)
    zoom = _zoom_affordance(svg_str)
    return (f'<div class="viz chartviz">{zoom}<div class="hint">Hover the dots for exact values</div>'
            f'{svg_str}<div class="vcap">{esc(spec.get("caption",""))}</div></div>')


def render_quiz(spec: dict) -> str:
    out = [f'<div class="quiz"><p><b>{esc(spec.get("q",""))}</b></p>']
    for o in spec.get("options", []) or []:
        ok = "1" if o.get("correct") else "0"
        out.append(f'<button class="opt" type="button" data-ok="{ok}" data-fb="{esc(o.get("fb",""))}">{esc(o.get("text",""))}</button>')
    out.append('<div class="fb"></div></div>')
    return "".join(out)


def render_trace(spec: dict, glossary: dict) -> str:
    """N-column per-step comparison. Each step is a row carrying a visible `goal` (and
    optional `note`); each of its `cells` fills one column with a visible `summary` plus an
    optional `note`/`code` that opens in the page's shared wide modal (code shown verbatim,
    horizontal scroll — never glossary-wrapped, like the graph/SVG exception). Columns stay
    narrow; the bulky payload/script gets the modal's full width. YAML-authored; author code
    via a `code: |` block scalar (literal — no quoting, no nested ``` fences)."""
    cols = spec.get("columns") or []
    ncol = max(1, len(cols))
    out = ['<div class="trace">']
    cap = spec.get("caption", "")
    if cap:
        out.append(f'<div class="trace-cap">{esc(str(cap))}</div>')
    for step in spec.get("steps") or []:
        if not isinstance(step, dict):
            continue
        goal = str(step.get("goal", ""))
        out.append('<div class="trace-step">')
        if goal:
            out.append(f'<div class="trace-goal">{apply_glossary(md_html(goal), glossary)}</div>')
        if step.get("note"):
            out.append(f'<div class="trace-note">{apply_glossary(md_html(str(step["note"])), glossary)}</div>')
        cells = step.get("cells") or []
        out.append(f'<div class="trace-cols" style="--tc:{ncol}">')
        for ci in range(ncol):
            head = str(cols[ci]) if ci < len(cols) else ""
            cell = cells[ci] if ci < len(cells) else {}
            if not isinstance(cell, dict):
                cell = {"summary": str(cell)}
            out.append('<div class="trace-col">')
            out.append(f'<div class="trace-colhead">{esc(head)}</div>')
            if cell.get("summary"):
                out.append(f'<div class="trace-sum">{apply_glossary(md_html(str(cell["summary"])), glossary)}</div>')
            code, cnote = str(cell.get("code", "")), str(cell.get("note", ""))
            if code or cnote:
                _TRACE_UID[0] += 1
                uid = f"tr{_TRACE_UID[0]}"
                body = [f'<div class="trace-modal-title"><span class="trace-modal-col">{esc(head)}</span>{esc(goal)}</div>']
                if cnote:
                    body.append(f'<div class="trace-modal-note">{md_html(cnote)}</div>')
                if code:
                    body.append(f'<pre class="code trace-code">{esc(code)}</pre>')
                out.append(f'<button class="trace-view js-modal-open" type="button" data-modal-src="{uid}">View I/O &#9656;</button>')
                out.append(f'<div class="trace-src lib-modal-src" id="{uid}" hidden>{"".join(body)}</div>')
            out.append('</div>')
        out.append('</div></div>')
    out.append('</div>')
    return "".join(out)


def render_flow(spec: dict, glossary: dict) -> str:
    """Process / pipeline. `stages` render in document order as a connected vertical column of
    boxes joined by arrow connectors; each box shows `label` (bold) + `kind` (a small tag) +
    a one-line `desc`. A stage carrying `detail` gets a 'details' affordance that opens the
    page's shared wide modal, populated from a hidden `.lib-modal-src` div holding the rendered
    `detail` markdown (run through md_html). Known kinds (input/step/output/decision) get subtle
    color variants; any other kind gets a neutral style. Robust: non-dict or field-missing
    stages degrade gracefully and the renderer never raises. Glossary applies to desc/caption
    prose only — never to the modal `detail` payload's code."""
    stages = [s for s in (spec.get("stages") or []) if isinstance(s, dict)]
    out = ['<div class="flow">']
    cap = spec.get("caption", "")
    if cap:
        out.append(f'<div class="flow-cap">{apply_glossary(esc(str(cap)), glossary)}</div>')
    known = {"input", "step", "output", "decision"}
    n = len(stages)
    for idx, stage in enumerate(stages):
        label = str(stage.get("label", "") or stage.get("id", ""))
        kind = str(stage.get("kind", "") or "")
        kcls = ("k-" + kind.lower()) if kind.lower() in known else "k-other"
        desc = str(stage.get("desc", "") or "")
        out.append(f'<div class="flow-stage {kcls}">')
        head = f'<span class="flow-label">{esc(label)}</span>'
        if kind:
            head += f'<span class="flow-kind">{esc(kind)}</span>'
        out.append(f'<div class="flow-stagehead">{head}</div>')
        if desc:
            out.append(f'<div class="flow-desc">{apply_glossary(md_html(desc), glossary)}</div>')
        detail = str(stage.get("detail", "") or "")
        if detail.strip():
            _FLOW_UID[0] += 1
            uid = f"fl{_FLOW_UID[0]}"
            out.append(f'<button class="flow-details js-modal-open" type="button" data-modal-src="{uid}">details &#9656;</button>')
            out.append(f'<div class="flow-src lib-modal-src" id="{uid}" hidden>'
                       f'<div class="flow-modal-title">{esc(label)}</div>{md_html(detail)}</div>')
        out.append('</div>')
        if idx < n - 1:
            out.append('<div class="flow-arrow" aria-hidden="true">&#8595;</div>')
    out.append('</div>')
    return "".join(out)


def render_tabs(spec: dict, glossary: dict) -> str:
    """Inline tabbed content: a tab bar whose buttons switch which panel is visible — variants of
    one thing held in a single space (e.g. the same example in Python / shell). `tabs` is a list of
    `{label, body}`; each `body` is a block scalar of markdown rendered through md_html (so lists,
    bold, tables, and code all work — and code blocks inherit the existing Copy/Expand toolbar via
    wrap_code_blocks). First tab active by default. Each block gets a page-unique container id
    (prefix `tb`, via _TABS_UID) so the JS scopes switching WITHIN one `.tabs` container and
    multiple tabs blocks on one page never cross-wire. Glossary tooltips apply to body prose +
    caption only. Robust: non-dict/empty tabs degrade and the renderer never raises."""
    tabs = [t for t in (spec.get("tabs") or []) if isinstance(t, dict)]
    if not tabs:
        return ""
    _TABS_UID[0] += 1
    cid = f"tb{_TABS_UID[0]}"
    out = [f'<div class="tabs" id="{cid}">']
    cap = spec.get("caption", "")
    if cap:
        out.append(f'<div class="tabs-cap">{apply_glossary(esc(str(cap)), glossary)}</div>')
    bar = ['<div class="tab-bar" role="tablist">']
    panels = []
    for i, t in enumerate(tabs):
        label = str(t.get("label", "") or f"Tab {i + 1}")
        body = str(t.get("body", "") or "")
        sel = "true" if i == 0 else "false"
        bar.append(f'<button class="tab-btn{" active" if i == 0 else ""}" type="button" role="tab" '
                   f'data-tab="{i}" aria-selected="{sel}">{esc(label)}</button>')
        panel_html = wrap_code_blocks(apply_glossary(md_html(body), glossary))
        panels.append(f'<div class="tab-panel{" on" if i == 0 else ""}" role="tabpanel" '
                      f'data-tab="{i}">{panel_html}</div>')
    bar.append('</div>')
    out.append("".join(bar))
    out.extend(panels)
    out.append('</div>')
    return "".join(out)


def render_anncode(spec: dict, glossary: dict) -> str:
    """Annotated code: a code block with a LEFT line-number gutter where specific lines carry a
    clickable marker that opens that line's explanation in the page's shared wide modal — for
    teaching code line-by-line. `code` is a literal `code: |` block scalar (no quoting/escaping);
    `annotations` is a list of `{line, note, label?}` where `line` is the 1-based line number into
    `code`. Each annotated line gets a marker (`class="acode-mark js-modal-open"` +
    `data-modal-src="acN"`) pointing at a hidden `.lib-modal-src` div holding the md_html-rendered
    `note` (+ an `L{line}`/`label` heading); annotated lines also get a subtle highlight. Lines with
    no annotation render plain. Out-of-range / duplicate `line` values skip gracefully (never raise).
    Code is rendered VERBATIM (escaped + syntax-highlighted) — glossary applies to the note/caption
    PROSE only, NEVER to the code lines (the graph/SVG glossary exception). Robust: missing fields
    skip; a non-dict spec or empty `code` returns ''."""
    if not isinstance(spec, dict):
        return ""
    code = str(spec.get("code", "") or "")
    if not code.strip():
        return ""
    lines = code.split("\n")
    if lines and lines[-1] == "":  # drop the block scalar's single trailing newline
        lines.pop()
    anns: dict = {}
    for a in spec.get("annotations") or []:
        if not isinstance(a, dict):
            continue
        try:
            ln = int(a.get("line"))
        except (TypeError, ValueError):
            continue
        if ln < 1 or ln > len(lines) or ln in anns:
            continue  # out-of-range / duplicate -> skip gracefully
        anns[ln] = a
    out = ['<div class="acode">']
    cap = spec.get("caption", "")
    lang = str(spec.get("lang", "") or "")
    if cap or lang:
        head = []
        if lang:
            head.append(f'<span class="acode-lang">{esc(lang)}</span>')
        if cap:
            head.append(f'<span class="acode-cap">{apply_glossary(esc(str(cap)), glossary)}</span>')
        out.append(f'<div class="acode-head">{"".join(head)}</div>')
    srcs = []
    # body is a real <pre class="code"> so it inherits the dark style AND the `pre.code .kw/.st/...`
    # highlight colors; NO whitespace between row divs (pre preserves it) — keep the join separator ''.
    out.append('<pre class="code acode-body">')
    for i, line in enumerate(lines, 1):
        rowcls = "acode-line annotated" if i in anns else "acode-line"
        body_html = highlight_code(esc(line)) or "&#8203;"  # zero-width keeps an empty line's height
        out.append(f'<div class="{rowcls}"><span class="acode-ln">{i}</span>'
                   f'<span class="acode-src">{body_html}</span>')
        if i in anns:
            _ACODE_UID[0] += 1
            uid = f"ac{_ACODE_UID[0]}"
            a = anns[i]
            label = str(a.get("label", "") or "")
            mark = esc(label) if label else "&#9679;"  # the label, else a small dot
            out.append(f'<button class="acode-mark js-modal-open" type="button" data-modal-src="{uid}" '
                       f'aria-label="Explain line {i}">{mark}</button>')
            heading = label or f"Line {i}"
            note = str(a.get("note", "") or "")
            mbody = (f'<div class="acode-modal-title"><span class="acode-modal-ln">L{i}</span>{esc(heading)}</div>'
                     f'<div class="acode-modal-note">{apply_glossary(md_html(note), glossary)}</div>')
            srcs.append(f'<div class="lib-modal-src" id="{uid}" hidden>{mbody}</div>')
        out.append('</div>')
    out.append('</pre>')
    out.extend(srcs)
    out.append('</div>')
    return "".join(out)


# ---------- section + rail + page ----------
def build_section(title, sid, segments, glossary, footnotes):
    # Render blocks in document order, full-width (visuals own the horizontal space).
    # Glossary links prose ONLY (shared `done` = once per section) — never the SVG/special HTML.
    # Citation markers ([^N]/[^gN]) render LAST, on prose html only (code already wrapped, so
    # process_citations masks it); special/SVG blocks are passed through verbatim.
    done = set()
    parts = []
    for seg in segments:
        if seg[0] == "md" and seg[1].strip():
            parts.append(process_citations(wrap_code_blocks(apply_glossary(md_html(seg[1]), glossary, done)), footnotes))
        elif seg[0] == "special":
            parts.append(seg[2])
    inner = "".join(parts)
    return (f'<section class="item" id="s-{sid}" data-toc="{esc(title)}" data-item="{esc(title)}">'
            f'<button class="sechead" aria-expanded="true"><span class="chev">&#9662;</span>'
            f'<h2>{esc(title)}</h2></button><div class="secbody">{inner}</div></section>')


def render_footnotes(footnotes: dict, vault_name) -> str:
    """Footnotes section at the END of the page body: a **Sources** subgroup (each subject
    hyperlinked to its corpus note via wiki_source_html — same Obsidian link as the source
    rail) and a **General knowledge** subgroup (plain text). Each <li> carries id fn-N / fn-gN
    so inline markers anchor-link to it. Returns '' when the page authored no footnotes (so a
    citation-free page is unchanged)."""
    src = [(label, f) for label, f in footnotes.items() if f.get("kind") == "src"]
    gen = [(label, f) for label, f in footnotes.items() if f.get("kind") == "gen"]
    if not src and not gen:
        return ""
    out = ['<section class="item footnotes" id="s-footnotes" data-toc="Footnotes" data-item="Footnotes">'
           '<button class="sechead" aria-expanded="true"><span class="chev">&#9662;</span>'
           '<h2>Footnotes</h2></button><div class="secbody">']
    if src:
        out.append('<div class="fngroup"><h3 class="fnhead">Sources</h3><ul class="fnlist">')
        for label, f in src:
            link = wiki_source_html({"subject": f.get("subject", ""), "page": f.get("page")}, vault_name)
            out.append(f'<li id="fn-{esc(label)}" class="fn fn-src">'
                       f'<span class="fnnum">{esc(label)}</span> {link}</li>')
        out.append("</ul></div>")
    if gen:
        out.append('<div class="fngroup gen"><h3 class="fnhead">General knowledge</h3><ul class="fnlist">')
        for label, f in gen:
            out.append(f'<li id="fn-{esc(label)}" class="fn fn-gen">'
                       f'<span class="fnnum">{esc(label)}</span> {esc(f.get("desc", ""))}</li>')
        out.append("</ul></div>")
    out.append("</div></section>")
    return "".join(out)


def _status_cls(s):
    s = (s or "").lower()
    return "k" if s.startswith("k") else "h" if s.startswith("h") else "n"


def find_vault_name(start: Path):
    """Walk up from the library path to the vault root (the dir holding sb-os.json) and
    return its folder name = the Obsidian vault name. None if no vault root is found."""
    for d in [start, *start.parents]:
        if (d / "sb-os.json").is_file():
            return d.name
    return None


def wiki_source_html(entry, vault_name):
    """Render one wiki source. With a recorded page reference + a known vault, the subject
    hyperlinks to that wiki note in Obsidian, resolved BY NOTE NAME (survives the wiki
    moving folders): obsidian://open?vault=<vault>&file=<note>. Plain subject text otherwise.
    Accepts a plain string (subject, no link) or a dict {subject, page}."""
    if isinstance(entry, dict):
        subject = entry.get("subject") or entry.get("title") or entry.get("name") or ""
        page = entry.get("page") or entry.get("path") or entry.get("note")
    else:
        subject, page = str(entry), None
    if page and vault_name:
        note = Path(str(page)).stem  # link by NAME, not folder path
        href = ("obsidian://open?vault=" + urllib.parse.quote(vault_name)
                + "&file=" + urllib.parse.quote(note))
        return f'<a href="{esc(href)}">{esc(subject)}</a>'
    return esc(subject)


def build_rail(meta, vault_name):
    boxes = []
    boxes.append('<div class="box"><h3>Where you are <span class="tag">in this topic</span></h3>'
                 '<div class="tprog"><i id="tprog"></i></div><nav class="toc" id="toc"></nav></div>')
    related = meta.get("related") or []
    if related:
        rows = []
        for r in related:
            href = f'{slugify(r["slug"])}.html' if r.get("slug") else "#"  # sibling — pages already live in pages/
            rows.append(f'<a href="{esc(href)}"><div class="rn">{esc(r.get("title",""))}</div>'
                        f'<div class="rr">{esc(r.get("why",""))}</div></a>')
        boxes.append(f'<div class="box rel"><h3>Related topics <span class="tag">learn next</span></h3>{"".join(rows)}</div>')
    terms = meta.get("terms") or []
    if terms:
        chips, known = [], 0
        for t in terms:
            if isinstance(t, dict):
                tt, st = t.get("t") or t.get("term"), t.get("s") or t.get("status")
            else:
                tt, _, st = str(t).partition(":")
            cl = _status_cls(st)
            if cl == "k":
                known += 1
            chips.append(f'<span class="term"><i class="mk {cl}"></i>{esc((tt or "").strip())}</span>')
        lvl = meta.get("started_level", "")
        boxes.append(f'<div class="box"><h3>Where you started <span class="tag">{known}/{len(terms)} known</span></h3>'
                     f'<div class="terms">{"".join(chips)}</div>'
                     f'<div class="startln">Started {esc(lvl)}.</div></div>')
    src = meta.get("sources") or {}
    if src:
        rows = []
        if src.get("wiki"):
            wiki_html = " &#183; ".join(wiki_source_html(w, vault_name) for w in src["wiki"])
            rows.append(f'<div class="src"><span class="k">Wiki</span> {wiki_html}</div>')
        for it in src.get("internet", []) or []:
            rows.append(f'<div class="src"><span class="k">Internet</span> <a href="{esc(it.get("url","#"))}">{esc(it.get("title",""))}</a></div>')
        if src.get("training"):
            rows.append(f'<div class="src"><span class="k">Training data</span> {esc(src["training"])}</div>')
        boxes.append(f'<div class="box"><h3>Light sources <span class="tag">grounded from</span></h3>{"".join(rows)}</div>')
    return "".join(boxes)


PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} — Learning Library</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body data-topic="{topic_attr}" data-source="{source_attr}">
<div id="bar"></div>
<svg width="0" height="0"><defs>
<marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="#8A7DF5"/></marker>
<marker id="ar2" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="#8A7DF5"/></marker></defs></svg>
<div class="topbar"><div class="wrap"><div class="brand"><span class="nm">Lumen<b>.</b></span><span class="sub">Learning Library</span></div>
<a class="backlink" href="../index.html">&#8592; Knowledge map</a></div></div>
<main class="wrap"><div class="thead"><span class="eyebrow">{eyebrow}</span><h1>{title}</h1><div class="sub">{sub}</div></div>
<div class="tgrid"><div class="main">{sections}</div><aside><div class="rail">{rail}</div></aside></div>
<div class="foot">Collapse a section &#183; hover a block to copy a <code>/sb-tutor</code> prompt &#183; open &ldquo;go deeper&rdquo; for the dense parts.</div></main>
<div class="lib-modal" id="libModal" hidden><div class="lib-modal-scrim"></div><div class="lib-modal-card" role="dialog" aria-modal="true"><button class="lib-modal-x" type="button" aria-label="Close">&#215;</button><div class="lib-modal-body"></div></div></div>
<div class="toast" id="toast">copied</div><script>{js}</script></body></html>"""


def build_page(meta, css, js, source_rel, vault_name):
    glossary = meta.get("glossary") or {}
    sections = split_sections(meta["_body"], glossary)
    footnotes, sections = collect_footnotes(sections)  # pull footnote-defs out of prose (page-wide)
    sec_html = "".join(build_section(t, sid, segs, glossary, footnotes) for t, sid, segs in sections)
    sec_html += render_footnotes(footnotes, vault_name)  # footnotes section at page end ('' if none)
    sub = []
    if meta.get("date"):
        sub.append(f'LEARNED {esc(meta["date"])}')
    if meta.get("goal"):
        sub.append(f'GOAL: {esc(meta["goal"])}')
    eyebrow = f'Topic &#183; {len(sections)} section' + ("s" if len(sections) != 1 else "")
    return PAGE.format(title=esc(meta["title"]), topic_attr=esc(meta["title"]), css=css, js=js,
                       source_attr=esc(source_rel), eyebrow=eyebrow, sub=" &#183; ".join(sub),
                       sections=sec_html, rail=build_rail(meta, vault_name))


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Learning Library</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div id="bar"></div>
<div class="topbar"><div class="wrap"><div class="brand"><span class="nm">Lumen<b>.</b></span><span class="sub">Learning Library</span></div></div></div>
<main class="wrap"><div class="hero"><span class="eyebrow">Your knowledge map &#183; {count} topic{plural}</span>
<h1>Everything you've learned, <em>connected.</em></h1>
<p>Each topic is a point on your map; lines link ideas that build on each other. The bigger and brighter the point, the more you'd mastered by the end.</p></div>
{body}</main><div class="toast" id="toast">copied</div><script>{js}</script></body></html>"""


def map_label(m):
    """Knowledge-map node label. MUST stay short: long labels render as single centered SVG
    lines that overlap neighboring nodes. Honor an explicit `map_label` frontmatter override;
    otherwise take the topic's short name (text before a dash separator) and hard-cap length."""
    lbl = str(m.get("map_label") or "").strip()
    if lbl:
        return lbl
    title = str(m.get("title", ""))
    for sep in (" — ", " – ", " -- ", " - "):
        i = title.find(sep)
        if i != -1:
            title = title[:i]
            break
    title = title.strip()
    if len(title) > 30:
        title = title[:29].rstrip() + "…"
    return title


def build_index(all_meta, css, js):
    if not all_meta:
        body = '<div class="emptylib">No topics yet. Learn something with <b>/sb-tutor</b> and your first page appears here.</div>'
        return INDEX.format(css=css, js=js, count=0, plural="s", body=body)
    n = len(all_meta)
    W, H, cx, cy = 1180, 470, 590, 235
    r = 90 if n <= 2 else 150 if n <= 5 else 190
    pos = {}
    for i, m in enumerate(all_meta):
        a = math.radians(-90 + 360.0 * i / n)
        pos[m["slug"]] = (cx + r * math.cos(a), cy + (r * 0.82) * math.sin(a))
    svg = [f'<svg class="map" viewBox="0 0 {W} {H}" role="list" aria-label="Knowledge map of learned topics">',
           f'<circle class="ring" cx="{cx}" cy="{cy}" r="{int(r*1.25)}"/><circle class="ring" cx="{cx}" cy="{cy}" r="{r}"/>']
    slugs = {m["slug"] for m in all_meta}
    seen = set()
    for m in all_meta:
        a = pos[m["slug"]]
        for rel in m.get("related") or []:
            t = slugify(rel.get("slug") or rel.get("title", ""))
            key = tuple(sorted((m["slug"], t)))
            if t in slugs and t != m["slug"] and key not in seen:
                seen.add(key)
                b = pos[t]
                svg.append(f'<line class="medge" x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}"/>')
    for m in all_meta:
        x, y = pos[m["slug"]]
        mastery = int(m.get("mastery", 60))
        rad = 6 + 8 * (mastery / 100.0)
        hi = "mnode hi" if mastery >= 75 else "mnode"
        terms = m.get("terms") or []
        known = sum(1 for t in terms if _status_cls(t.get("s") or t.get("status") if isinstance(t, dict) else str(t).partition(":")[2]) == "k")
        mag = f'{known}/{len(terms)} KNOWN' if terms else ""
        meta_line = f'{mag} &#183; {esc(m.get("date",""))}' if mag else esc(m.get("date", ""))
        svg.append(
            f'<a href="pages/{esc(m["slug"])}.html"><g class="{hi}" tabindex="0" role="listitem">'
            f'<circle class="halo" cx="{x:.0f}" cy="{y:.0f}" r="{rad+22:.0f}"/>'
            f'<circle class="core" cx="{x:.0f}" cy="{y:.0f}" r="{rad:.0f}"/>'
            f'<text class="lbl" x="{x:.0f}" y="{y-rad-12:.0f}" text-anchor="middle">{esc(map_label(m))}</text>'
            f'<text class="mag" x="{x:.0f}" y="{y+rad+18:.0f}" text-anchor="middle">{meta_line}</text></g></a>')
    svg.append("</svg>")
    legend = ('<div class="legend"><span><i class="v"></i>learned topic</span>'
              '<span><i class="a"></i>high mastery</span><span>line = topics that connect</span>'
              '<span>click a point to open it</span></div>')
    body = f'<div class="mapwrap">{"".join(svg)}</div>{legend}'
    return INDEX.format(css=css, js=js, count=n, plural="" if n == 1 else "s", body=body)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Build the Lumen learning library.")
    ap.add_argument("--library-root", required=True)
    ap.add_argument("--topic", help="build only this slug's page (index always rebuilt)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.library_root).resolve()
    vault_name = find_vault_name(root)
    topics_dir, pages_dir = root / "topics", root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    css = (ASSETS / "styles.css").read_text(encoding="utf-8")
    js = (ASSETS / "app.js").read_text(encoding="utf-8")

    built, errors, all_meta = [], [], []
    for src in sorted(topics_dir.glob("*.md")):
        try:
            meta, body = parse_source(src)
            meta["_body"] = body
            all_meta.append(meta)
            if args.topic and meta["slug"] != args.topic:
                continue
            (pages_dir / f'{meta["slug"]}.html').write_text(build_page(meta, css, js, f"topics/{src.name}", vault_name), encoding="utf-8")
            built.append(meta["slug"])
        except Exception as e:  # one bad source never kills the build
            errors.append({"file": src.name, "error": f"{type(e).__name__}: {e}"})

    all_meta.sort(key=lambda m: str(m.get("date", "")), reverse=True)
    (root / "index.html").write_text(build_index([m for m in all_meta if "_body" in m], css, js), encoding="utf-8")

    summary = {"built_pages": built, "topics_total": len(all_meta), "index": str(root / "index.html"), "errors": errors}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f'Built {len(built)} page(s); {len(all_meta)} topic(s) in index -> {root / "index.html"}')
        for e in errors:
            print(f'  ERROR {e["file"]}: {e["error"]}')
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
