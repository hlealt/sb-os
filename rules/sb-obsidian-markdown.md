# Obsidian Markdown

**Scope:** Vault files. Does NOT apply to directories that are their own git repositories (they follow their own conventions).

Vault files use Obsidian-flavored markdown. Key non-standard patterns:

## Callouts

```markdown
> [!type] Optional Title
> Content here.
```

Collapse modifiers: `> [!tip]- Title` (collapsed), `> [!warning]+ Title` (expanded, collapsible). Callouts nest with additional `>` prefixes.

## Embeds

| Pattern | Example |
|---------|---------|
| Heading | `![[Note#Heading]]` |
| Block | `![[Note#^block-id]]` |
| Image with width | `![[image.png\|300]]` |
| PDF at page | `![[doc.pdf#page=3]]` |

## Frontmatter

YAML between `---`. Use `tags:` list, `aliases:` for link suggestions. Wikilinks in frontmatter: `related: "[[Other Note]]"`.

Detailed syntax reference: `{sb_os_path}/docs/obsidian-markdown/`.
