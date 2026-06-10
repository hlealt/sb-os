# Lint Step 9 handler — PROPOSED ANSWERS (questions answer-sweep)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the `questions-answer-proposals` set is non-empty (which requires the questions layer ON). Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for PROPOSED ANSWERS (questions answer-sweep, step 7.7a):

| Response | Behavior |
|----------|----------|
| `accept N` (e.g. `accept 1,2`) — **`questions.md` row** | Accrete the 1-sentence claim onto that `questions.md` entry's `answer:` field per the answer-write procedure in `../../shared/question-entry-shapes.md` (`answer:` field rule + State rule), citing `[[<answering-page>.md]]`. No log entry. |
| `accept N` (e.g. `accept 1,2`) — **topic-home row** | STRIKE the matched `Open questions` line in place (`~~…~~`, never delete) and FOLD the answer into the topic body under the topic-shape-appropriate section with an inline `[^N]` marker + a matching `[^N]: [[<answering-page>.md]]` def in `Sources`; bump `last-touched: <today>`. Append-only protection per `../../shared/stub-policy.md` "Append-Only Protection" applies — NEVER overwrite existing prose. NEVER auto-authors a page. No log entry — the topic page records its own content. |
| `reject` (default) | No change to any `questions.md` entry or topic page. No log entry. The match is not preserved — re-detected on the next sweep (or at ingest) if overlap recurs. |
