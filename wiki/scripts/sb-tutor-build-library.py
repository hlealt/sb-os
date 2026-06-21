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
import argparse, html, json, math, re, sys
from pathlib import Path

try:
    import yaml
    import markdown as md
except ImportError as e:  # deterministic dependency
    sys.stderr.write(f"missing dependency: {e}. Run: pip install pyyaml markdown\n")
    sys.exit(2)

ASSETS = Path(__file__).resolve().parent / "learning-library" / "assets"
SPECIAL = {"graph", "chart", "quiz", "deeper"}
FENCE = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.DOTALL | re.MULTILINE)


# ---------- small helpers ----------
def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(s).lower()).strip()
    return re.sub(r"[\s_-]+", "-", s) or "topic"


def md_html(text: str) -> str:
    h = md.markdown(text, extensions=["extra", "sane_lists"])
    h = re.sub(r"<pre><code[^>]*>", '<pre class="code"><code>', h)
    # callouts: blockquote starting with [!warn]/[!note]/[!tip]
    def _co(m):
        kind, body = m.group(1).lower(), m.group(2).strip()
        cls = "callout warn" if kind in ("warn", "warning", "danger") else "callout"
        ic = "&#9650;" if "warn" in cls else "&#9670;"
        return f'<div class="{cls}"><span class="ic">{ic}</span><div>{body}</div></div>'
    h = re.sub(r"<blockquote>\s*<p>\s*\[!(\w+)\]\s*(.*?)</p>\s*</blockquote>", _co, h, flags=re.DOTALL)
    return h


def apply_glossary(htext: str, glossary: dict) -> str:
    """Wrap the FIRST text-node occurrence of each glossary term in a clickable span."""
    if not glossary:
        return htext
    parts = re.split(r"(<[^>]+>)", htext)  # odd indices are tags
    done = set()
    for term, definition in glossary.items():
        pat = re.compile(r"\b(" + re.escape(term) + r")\b", re.IGNORECASE)
        for i in range(0, len(parts), 2):
            if term.lower() in done:
                break
            if pat.search(parts[i]):
                parts[i] = pat.sub(
                    lambda m: f'<button class="gloss" data-def="{esc(definition)}">{m.group(1)}</button>',
                    parts[i], count=1)
                done.add(term.lower())
                break
    return "".join(parts)


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


def split_sections(body: str):
    """Return [(title, id, [segments])]. Segments: ('md',text) | ('special',kind,html)."""
    out = []
    for block in re.split(r"^##\s+", body, flags=re.MULTILINE)[1:]:
        line, _, rest = block.partition("\n")
        title = line.strip()
        out.append((title, slugify(title), parse_segments(rest)))
    return out


def parse_segments(text: str):
    segs, pos = [], 0
    for m in FENCE.finditer(text):
        if m.group(1).lower() not in SPECIAL:
            continue  # leave code fences in the md stream
        if text[pos:m.start()].strip():
            segs.append(("md", text[pos:m.start()]))
        segs.append(("special", m.group(1).lower(), render_special(m.group(1).lower(), m.group(2))))
        pos = m.end()
    if text[pos:].strip():
        segs.append(("md", text[pos:]))
    return segs


def render_special(kind: str, content: str) -> str:
    if kind == "deeper":
        first, _, rest = content.partition("\n")
        return (f'<details class="deeper"><summary>{esc(first.strip())}</summary>'
                f'<div class="dbody">{md_html(rest.strip())}</div></details>')
    try:  # one malformed block must NOT fail the whole page
        spec = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        msg = str(e).splitlines()[0]
        return (f'<div class="callout warn"><span class="ic">&#9650;</span><div>This <b>{esc(kind)}</b> block '
                f'could not be rendered (YAML error: {esc(msg)}). Quote any value containing <code>:</code> or <code>#</code>.</div></div>')
    if kind == "graph":
        return render_graph(spec)
    if kind == "chart":
        return render_chart(spec)
    if kind == "quiz":
        return render_quiz(spec)
    return ""


# ---------- visuals ----------
def render_graph(spec: dict) -> str:
    # Full-width graph (detail panel BELOW it) so labels have room; nodes are text-sized
    # PILLS (no overflow); viewBox sized near display width so text scales ~1:1.
    nodes = spec.get("nodes", []) or []
    edges = spec.get("edges", []) or []
    W, H, cx, cy = 760, 430, 380, 210
    rad = 230 if len(nodes) > 4 else 170
    pos = {}
    n = len(nodes)
    for i, nd in enumerate(nodes):
        if "x" in nd and "y" in nd:
            pos[nd["id"]] = (float(nd["x"]), float(nd["y"]))
        else:
            a = math.radians(-90 + 360.0 * i / max(n, 1))
            pos[nd["id"]] = (cx + rad * math.cos(a), cy + rad * 0.62 * math.sin(a))
    svg = [f'<svg viewBox="0 0 {W} {H}" role="group" aria-label="Interactive concept diagram">']
    for e in edges:
        a, b = pos.get(e.get("from")), pos.get(e.get("to"))
        if not a or not b:
            continue
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        label = e.get("label", "")
        wl = len(label) * 6.4 + 12
        svg.append(
            f'<g class="iedge" tabindex="0" role="button" data-kind="Edge" '
            f'data-title="{esc(label)}" data-desc="{esc(e.get("desc",""))}">'
            f'<line class="hit" x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}"/>'
            f'<line class="vis" x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}"/>'
            f'<rect class="elbg" x="{mx-wl/2:.0f}" y="{my-9:.0f}" width="{wl:.0f}" height="17" rx="5"/>'
            f'<text x="{mx:.0f}" y="{my+3:.0f}" text-anchor="middle">{esc(label)}</text></g>')
    for nd in nodes:
        x, y = pos[nd["id"]]
        label = nd.get("label", "")
        w = max(64, len(label) * 7.7 + 28)
        cls = "inode k" if nd.get("hi") else "inode"
        svg.append(
            f'<g class="{cls}" tabindex="0" role="button" data-kind="{esc(nd.get("kind","Node"))}" '
            f'data-title="{esc(label)}" data-desc="{esc(nd.get("desc",""))}">'
            f'<rect x="{x-w/2:.0f}" y="{y-17:.0f}" width="{w:.0f}" height="34" rx="17"/>'
            f'<text x="{x:.0f}" y="{y+5:.0f}" text-anchor="middle">{esc(label)}</text></g>')
    svg.append("</svg>")
    cap = f'<div class="vcap">{esc(spec.get("caption","click any node or edge to inspect"))}</div>'
    return (f'<div class="igraph-wrap"><div class="viz igraph"><div class="hint">Click any node or edge</div>'
            f'{"".join(svg)}{cap}</div>'
            f'<div class="detail empty" aria-live="polite"><div>Click any <b>node</b> or <b>edge</b> '
            f'in the diagram to see what it is.</div></div></div>')


def render_chart(spec: dict) -> str:
    xs = spec.get("x", []) or []
    series = spec.get("series", []) or []
    W, H, x0, x1, y0, y1 = 470, 320, 66, 448, 64, 250  # viewBox ~ display width (capped 480) → text scales ~1:1
    allv = [v for s in series for v in (s.get("values") or [])]
    maxv = max(allv) if allv else 1
    px = lambda i: x0 + (x1 - x0) * (i / max(len(xs) - 1, 1))
    py = lambda v: y1 - (y1 - y0) * (v / maxv if maxv else 0)
    svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(spec.get("caption","chart"))}">',
           f'<line class="ax" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>',
           f'<line class="ax" x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>']
    for i, xv in enumerate(xs):
        svg.append(f'<text class="axl" x="{px(i):.0f}" y="{y1+18:.0f}" text-anchor="middle">{esc(xv)}</text>')
    if spec.get("xlabel"):
        svg.append(f'<text class="axt" x="{(x0+x1)//2}" y="{H-8}" text-anchor="middle">{esc(spec["xlabel"])} &#8594;</text>')
    if spec.get("ylabel"):
        svg.append(f'<text class="axt" x="16" y="{(y0+y1)//2}" transform="rotate(-90 16 {(y0+y1)//2})" text-anchor="middle">{esc(spec["ylabel"])}</text>')
    lx = x0  # top legend (replaces overlapping inline end-labels)
    for s in series:
        nm = s.get("name", "")
        svg.append(f'<rect x="{lx}" y="30" width="12" height="12" rx="3" fill="{esc(s.get("color","#5B4FE0"))}"/>'
                   f'<text class="leg" x="{lx+17}" y="40">{esc(nm)}</text>')
        lx += int(36 + len(nm) * 6.6)
    for s in series:
        vals = s.get("values") or []
        color = esc(s.get("color", "#5B4FE0"))
        pts = " ".join(f"{px(i):.0f},{py(v):.0f}" for i, v in enumerate(vals))
        svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{pts}"/>')
        for i, v in enumerate(vals):
            label = xs[i] if i < len(xs) else i
            svg.append(f'<circle class="pt" cx="{px(i):.0f}" cy="{py(v):.0f}" r="5" fill="{color}">'
                       f'<title>{esc(s.get("name",""))} &#183; {esc(label)}: {esc(v)}</title></circle>')
    svg.append("</svg>")
    return (f'<div class="viz chartviz"><div class="hint">Hover the dots for exact values</div>'
            f'{"".join(svg)}<div class="vcap">{esc(spec.get("caption",""))}</div></div>')


def render_quiz(spec: dict) -> str:
    out = [f'<div class="quiz"><p><b>{esc(spec.get("q",""))}</b></p>']
    for o in spec.get("options", []) or []:
        ok = "1" if o.get("correct") else "0"
        out.append(f'<button class="opt" type="button" data-ok="{ok}" data-fb="{esc(o.get("fb",""))}">{esc(o.get("text",""))}</button>')
    out.append('<div class="fb"></div></div>')
    return "".join(out)


# ---------- section + rail + page ----------
def build_section(title, sid, segments, glossary):
    specials = [s for s in segments if s[0] == "special"]
    kinds = [s[1] for s in specials]
    md_segs = [s for s in segments if s[0] == "md" and s[1].strip()]
    has_table = any(re.search(r"^\s*\|?[ :|-]*-{3,}[ :|-]*\|", t, re.M) for _, t in md_segs)
    if kinds == ["chart"] and md_segs and not has_table:  # tables need full width — don't cram into a split column
        left = "".join(md_html(t) for _, t in md_segs)
        inner = f'<div class="split"><div>{left}</div>{specials[0][2]}</div>'
    else:
        parts = []
        for seg in segments:
            if seg[0] == "md" and seg[1].strip():
                parts.append(md_html(seg[1]))
            elif seg[0] == "special":
                parts.append(seg[2])
        inner = "".join(parts)
    inner = apply_glossary(inner, glossary)
    return (f'<section class="item" id="s-{sid}" data-toc="{esc(title)}" data-item="{esc(title)}">'
            f'<button class="sechead" aria-expanded="true"><span class="chev">&#9662;</span>'
            f'<h2>{esc(title)}</h2></button><div class="secbody">{inner}</div></section>')


def _status_cls(s):
    s = (s or "").lower()
    return "k" if s.startswith("k") else "h" if s.startswith("h") else "n"


def build_rail(meta):
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
            rows.append(f'<div class="src"><span class="k">Wiki</span> {" &#183; ".join(esc(w) for w in src["wiki"])}</div>')
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
<style>{css}</style></head><body data-topic="{topic_attr}">
<div id="bar"></div><div id="pop"></div>
<svg width="0" height="0"><defs>
<marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="#8A7DF5"/></marker>
<marker id="ar2" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="#8A7DF5"/></marker></defs></svg>
<div class="topbar"><div class="wrap"><div class="brand"><span class="nm">Lumen<b>.</b></span><span class="sub">Learning Library</span></div>
<a class="backlink" href="../index.html">&#8592; Knowledge map</a></div></div>
<main class="wrap"><div class="thead"><span class="eyebrow">{eyebrow}</span><h1>{title}</h1><div class="sub">{sub}</div></div>
<div class="tgrid"><div class="main">{sections}</div><aside><div class="rail">{rail}</div></aside></div>
<div class="foot">Collapse a section &#183; hover a block to copy a <code>/sb-tutor</code> prompt &#183; open &ldquo;go deeper&rdquo; for the dense parts.</div></main>
<div class="toast" id="toast">copied</div><script>{js}</script></body></html>"""


def build_page(meta, css, js):
    sections = split_sections(meta["_body"])
    glossary = meta.get("glossary") or {}
    sec_html = "".join(build_section(t, sid, segs, glossary) for t, sid, segs in sections)
    sub = []
    if meta.get("date"):
        sub.append(f'LEARNED {esc(meta["date"])}')
    if meta.get("goal"):
        sub.append(f'GOAL: {esc(meta["goal"])}')
    eyebrow = f'Topic &#183; {len(sections)} section' + ("s" if len(sections) != 1 else "")
    return PAGE.format(title=esc(meta["title"]), topic_attr=esc(meta["title"]), css=css, js=js,
                       eyebrow=eyebrow, sub=" &#183; ".join(sub), sections=sec_html, rail=build_rail(meta))


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
            f'<text class="lbl" x="{x:.0f}" y="{y-rad-12:.0f}" text-anchor="middle">{esc(m["title"])}</text>'
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
            (pages_dir / f'{meta["slug"]}.html').write_text(build_page(meta, css, js), encoding="utf-8")
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
