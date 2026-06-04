---
stepId: onboarding
nextStepFile: null
---

# Step 00: Source Onboarding

**When to run.** This step is called ONLY when `{CONFIG_DIR}/sources.yaml` is empty (no entries under `sources:`). If the file already has at least one entry, skip straight to the preflight step of the chosen flow. Never run during a normal close.

**Goal.** Guide the user in selecting their data sources (banks, brokers, exchanges) from the public manifest and populate `sources.yaml` with the chosen sources. For sources not yet supported, trigger `tool-builder` to create the parser.

---

## Mandatory Sequence

### Section 1 — Present the manifest

1. Read the public manifest: `3-resources/tools/sb-os/finance/docs/sources-manifest.md`.
2. Display to the user the list of available sources, grouped by category:

   ```
   Available expense sources:
     [ ] bradesco_extrato — Bradesco — Checking Account Statement (csv)
     [ ] santander_extrato — Santander — Checking Account Statement (pdf)
     [ ] santander_fatura — Santander — Visa Card Invoice (pdf)
     [ ] mp_extrato — Mercado Pago — Account Statement (csv)
     [ ] mp_fatura — Mercado Pago — Card Invoice (pdf)
     [ ] wise_extrato — Wise — Multi-Currency Statement (csv)
     [ ] manual_cash — Cash Expenses — Manual Entry
     [ ] nubank_fatura — Nubank — Card Invoice (pdf) [historical only]
     [ ] xp_fatura — XP — Card Invoice (csv) [historical only]

   Available investment sources:
     [ ] safra — Banco Safra / Safra Corretora (pdf, csv)
     [ ] b3 — B3 — Brazilian Exchange via Safra (pdf, csv)
     [ ] avenue — Avenue Securities (csv)
     [ ] mercado_bitcoin — Mercado Bitcoin (csv)
     [ ] bipa — Bipa (csv)
     [ ] funds — Investment Funds via Safra (pdf, csv)

   Which sources do you use? List the ids separated by commas, or "all" to select every active source.
   ```

3. STOP. Wait for the user's response.

### Section 2 — Emit instructions per selected source

For each source selected by the user (in the order they appear in the manifest):

1. Display the source's download/extraction instructions per the manifest:

   ```
   📥 {name}
   Format: {input_format}
   How to download: {download_instructions}
   {extraction_instructions, if present}
   ```

2. Ask whether the source must be enabled for future closes or only for backfill (historical):

   ```
   Use {name} in regular monthly closes?
     [S] Yes — enabled for new closes
     [N] No — only for reprocessing previous months (historical)
   ```

3. STOP. Wait for confirmation on each source before proceeding.

### Section 3 — Unlisted sources (deviation-to-structure)

If the user mentions a source NOT in the manifest:

1. Follow **Rule A** of `gatekeeper-loop.md` — name the deviation:

   ```
   The source "{name_given}" has no parser in this system.

   How do you want to proceed?
     [A] Build the parser now — you send us a sample file and
         we trigger the tool-builder to create and test the parser.
     [B] Ignore this source for now — we log it as a pending item.
     [C] You describe the format now and we log it for a later build.
   ```

2. STOP. Wait for the user's choice.

3. Routing:
   - `[A]` → Trigger **Rule B / Seam 1 (`tool-builder`)** of `gatekeeper-loop.md`:
     - Request a real sample file of the source from the user.
     - Dispatch `tool-builder` via the Agent tool with the dispatch context:
       ```
       need: "Parser for the source '{name}' (format {format})"
       class: write
       use: parser
       destination_artifact: transactions.csv  # (or the correct artifact for the scope)
       real_sample: {path to the file provided by the user}
       ```
     - After `tool-builder` returns the accepted parser, trigger **Seam 2 (`doc-maintainer`)** to update `sources-manifest.md` with the new entry.
   - `[B]` → Log the source as a pending item (one entry in the pending log). Do not block onboarding.
   - `[C]` → Log the format description and dispatch `doc-maintainer` to create a draft manifest entry. Mark `last_validated: pending` on the created entry.

### Section 4 — Populate `sources.yaml` and confirm

1. For each source confirmed by the user, write an entry in `{CONFIG_DIR}/sources.yaml`:

   ```yaml
   - id: {source_id}
     enabled_for_close: {true|false}   # true if Section 2 answer [S]; false if [N]
     note: {optional note, e.g.: "historical only"}
   ```

2. Save `sources.yaml`.

3. Confirm to the user:

   ```
   Onboarding complete. {N} sources registered in sources.yaml.
   {N_enabled} enabled for regular closes.
   {N_pending} pending items logged.

   To start the close, run bookkeeper again.
   ```

4. STOP. The workflow ends here. The user runs `sb-bookkeeper` again to start the close with the configured sources.

---

## Step Menu

- **Gatekeeper checkpoint** → before ending, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A new source added to the manifest (Seam 1 + Seam 2 complete) = structure + docs updated = deviation resolved.
- **[X] Exit** → end without saving (sources.yaml stays empty; onboarding runs again on the next activation).
