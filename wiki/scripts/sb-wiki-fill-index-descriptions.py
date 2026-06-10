#!/usr/bin/env python3
"""Fill missing wiki leaf-index `Description` cells from each page's lead definition sentence.

Companion to `sb-wiki-lint-deterministic.py`. That helper creates index ROWS whose cells are
deterministic (raw Title/Date) and leaves concept/entity `Description` cells in `judgment_needed`
for the agent. In practice each concept/entity page is authored with its definition as the lead
body line, so the `Description` is derivable: this script extracts that lead sentence, cleans it
(flatten wikilinks, strip footnote markers/emphasis, escape table pipes, truncate to one sentence),
and appends `| [[slug.md]] | <desc> |` rows to the correct leaf index or router `## Flat pages`
table — preserving existing rows and alphabetical order when the table is already sorted.

A page with NO clean lead sentence (empty / too short) is NOT written — it is reported as `weak`
for agent judgment. `Description` stays judgment-bearing per the wiki schema; this only covers the
deterministic majority and surfaces the rest.

Usage (from vault root):
    python {sb_os_path}/wiki/scripts/sb-wiki-fill-index-descriptions.py            # dry-run
    python {sb_os_path}/wiki/scripts/sb-wiki-fill-index-descriptions.py --apply    # write rows
"""
import os, re, glob, json, argparse

NON_PAGE = {'claude.md', 'agents.md', 'qwen.md', 'readme.md'}
MAX_DESC = 230


def resolve_wiki_root(vault_root):
    """Read wiki_root from sb-os.json; never hardcode (sb-os convention)."""
    cfg = os.path.join(vault_root, 'sb-os.json')
    if os.path.exists(cfg):
        wr = json.load(open(cfg, encoding='utf-8')).get('wiki_root')
        if wr:
            return os.path.join(vault_root, wr.replace('/', os.sep))
    return os.path.join(vault_root, '3-resources', 'knowledge-base')


def is_page(path, index_stem):
    base = os.path.basename(path)
    return base.lower() not in NON_PAGE and os.path.splitext(base)[0] != index_stem


def frontmatter_stripped(txt):
    if txt.startswith('---'):
        parts = txt.split('---', 2)
        if len(parts) >= 3:
            return parts[2]
    return txt


def lead_sentence(path):
    txt = frontmatter_stripped(open(path, encoding='utf-8').read())
    for raw in txt.splitlines():
        l = raw.strip()
        if not l or l.startswith(('#', '>', '|', '![', '---')):
            continue
        if re.match(r'^[-*]\s', l):   # list item — not a definition lead
            continue
        return l
    return None


def clean(s):
    if not s:
        return None
    s = re.sub(r'\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]',
               lambda m: (m.group(2) or m.group(1).rsplit('/', 1)[-1].replace('.md', '')), s)
    s = re.sub(r'\[\^[^\]]+\]', '', s)        # footnote markers
    s = re.sub(r'\*\*|\*|`|__', '', s)         # emphasis / code
    s = s.replace('|', r'\|')                   # table-safe
    s = re.sub(r'\s+', ' ', s).strip()
    m = re.match(r'(.+?[.!?])(?:\s|$)', s)      # first sentence
    if m and len(m.group(1)) >= 15:
        s = m.group(1)
    if len(s) > MAX_DESC:
        cut = s[:MAX_DESC]
        if ' ' in cut:
            cut = cut.rsplit(' ', 1)[0]
        s = cut.rstrip(' ,;:') + '…'
    return s.strip()


def index_slugs(table_text):
    return set(re.findall(r'\|\s*\[\[([^\]|#]+?)\.md', table_text))


def find_table_bounds(lines, after_heading=None):
    """(header_idx, last_row_idx) for the | File | Description | table, optionally after a heading."""
    start = 0
    if after_heading is not None:
        for i, l in enumerate(lines):
            if l.strip().lower() == after_heading.lower():
                start = i + 1
                break
        else:
            return None
    header_idx = None
    for i in range(start, len(lines)):
        if re.match(r'^\|\s*File\s*\|\s*Description\s*\|', lines[i].strip(), re.I):
            header_idx = i
            break
    if header_idx is None:
        return None
    last = header_idx + 1
    j = header_idx + 2
    while j < len(lines) and lines[j].strip().startswith('|'):
        last = j
        j += 1
    return header_idx, last


def build_jobs(wiki):
    """List of (index_path, after_heading_or_None, [page_paths])."""
    jobs = []
    for t in ('concepts', 'entities'):
        base = os.path.join(wiki, t)
        if not os.path.isdir(base):
            continue
        flat = [p for p in glob.glob(base + '/*.md') if is_page(p, t)]
        jobs.append((os.path.join(base, t + '.md'), '## Flat pages', flat))
        for d in sorted(glob.glob(base + '/*/')):
            sub = os.path.basename(d.rstrip('/\\'))
            pages = [p for p in glob.glob(d + '*.md') if is_page(p, sub)]
            jobs.append((os.path.join(d, sub + '.md'), None, pages))
    return jobs


def row_slug(r):
    m = re.search(r'\[\[([^\]|#]+?)\.md', r)
    return m.group(1).lower() if m else '￿'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='write rows (default: dry-run)')
    ap.add_argument('--vault-root', default='.', help='vault root (default: cwd)')
    args = ap.parse_args()
    wiki = os.path.join(resolve_wiki_root(args.vault_root), 'wiki')

    total_added, weak, samples = 0, [], []
    for idx_path, heading, pages in build_jobs(wiki):
        if not os.path.exists(idx_path):
            continue
        txt = open(idx_path, encoding='utf-8').read()
        existing = index_slugs(txt)
        new_rows = []
        for p in sorted(pages):
            slug = os.path.splitext(os.path.basename(p))[0]
            if slug in existing:
                continue
            desc = clean(lead_sentence(p))
            if not desc or len(desc) < 15:
                weak.append(os.path.relpath(p, wiki))
                continue
            new_rows.append(f'| [[{slug}.md]] | {desc} |')
            if len(samples) < 14:
                samples.append((os.path.relpath(idx_path, wiki), slug, desc))
        if not new_rows:
            continue
        lines = txt.splitlines()
        bounds = find_table_bounds(lines, heading)
        if bounds is None:
            weak.append(f'!!NO-TABLE!! {os.path.relpath(idx_path, wiki)} ({len(new_rows)} rows)')
            continue
        header_idx, last_row = bounds
        first_data = header_idx + 2
        existing_rows = lines[first_data:last_row + 1]
        slugs = [row_slug(r) for r in existing_rows]
        if slugs == sorted(slugs):
            merged = sorted(existing_rows + new_rows, key=row_slug)
        else:
            merged = existing_rows + new_rows  # custom order — append, never reorder
        lines[first_data:last_row + 1] = merged
        total_added += len(new_rows)
        if args.apply:
            open(idx_path, 'w', encoding='utf-8', newline='').write(
                '\n'.join(lines) + ('\n' if txt.endswith('\n') else ''))

    print(f'MODE: {"APPLY" if args.apply else "DRY-RUN"}')
    print(f'Rows {"added" if args.apply else "to add"}: {total_added}')
    print(f'Weak/flagged (no clean lead sentence): {len(weak)}')
    for w in weak[:40]:
        print('   WEAK:', w)
    print('--- sample generated rows ---')
    for idx, slug, desc in samples:
        print(f'[{idx}] {slug} :: {desc}')


if __name__ == '__main__':
    main()
