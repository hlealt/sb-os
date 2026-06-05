---
stepNumber: 6
stepId: review
nextStepFile: step-07-snapshot.md
---

# Step 6: Review — Present Changes and Anomalies

**Goal:** Present the user a summary of the month's changes (deltas) and detected anomalies, for confirmation before creating the snapshot.

## Mandatory Sequence

1. Compare the freshly-generated `portfolio.json` with the previous snapshot in `{INV_LEDGER_DIR}/snapshots.json` (last entry). Compute:
   - Δ total value (BRL and %)
   - Δ per class (variable_income, fixed_income, crypto, funds)
   - Δ per broker
   - Top movers (largest absolute and percentage changes per position)

2. Present:

```
Review {MONTH}:

  Total: R$ X.XXX.XXX → R$ X.XXX.XXX (+R$ XX.XXX, +X.X%)
  
  By class:
    Variável: +R$ XX (+X.X%)
    RF:       +R$ XX (+X.X%)
    Crypto:   −R$ XX (−X.X%)
    Fundos:   +R$ XX (+X.X%)

  Top movers:
    +R$ X.XXX  PETR4 (price ↑ + purchases)
    −R$ X.XXX  BTC (price ↓)
    +R$ X.XXX  SAFRA ABS (aplicação)

  Detected anomalies:
    - <empty> | OR list (change >20%, position unexpectedly zeroed, new ticker, etc.)
```

3. For each anomaly, ask the user to classify: accept (real movement) or investigate (probable bug).

4. If there are anomalies to investigate, do NOT proceed — go back to Step 02-03-04 as appropriate.

5. **Completion gates — pre-snapshot (auto-halt).** Before creating the snapshot (Step 07), run the three portfolio gates. All read the freshly-generated `portfolio.json`; none auto-loops (the user decides the next action). Each failure is Rule C **blocking** — do NOT advance to Step 07 until it is resolved or the user explicitly accepts.

   a. **Portfolio delta anomaly (`gate_portfolio_delta.py`, gate #8):**

      ```bash
      python "{SCRIPTS_DIR}/gate_portfolio_delta.py" --portfolio "{INV_LEDGER_DIR}/portfolio.json" --flagged-ids "{IDS_ACEITOS}"
      ```

      Mechanizes the "Detected anomalies" list of step 2: per-position change >20%, position unexpectedly zeroed, new ticker vs previous snapshot. Pass in `{IDS_ACEITOS}` (comma-separated) the `id`s the user classified as "accept (real movement)" in step 3 — so the gate only fails on UNrecognized anomalies. Exit 0 = no unflagged anomaly; exit 1 = unflagged anomalies remain; exit 2 = files missing. No previous snapshot → vacuous pass.

   b. **IRR sanity + rf_balcao band (`gate_irr_sanity.py`, gate #9):**

      ```bash
      python "{SCRIPTS_DIR}/gate_irr_sanity.py"
      ```

      Fails (exit 1) if `|irr| > 200%` on any position/class, if `irr_quality` is missing on a balcão position with value, or if an `rf_balcao` position has an annualized return outside the band `[7%, 15%]` (read from `investment_rules.sanity_bands.rf_balcao` in `standing-rules.yaml`) and is NOT band-exempt. Band-exempt positions (listed in `investment_rules.sanity_bands.rf_balcao.band_exempt_ids`) skip the band check and print a visible `EXEMPT` note instead; strict checks (`|irr|>200%`, `irr_quality`) still apply. Exit 0 = no violations; exit 2 = `portfolio.json` missing.

   c. **IRR bucket divergence (`gate_bucket_divergence.py`, gate #10):**

      ```bash
      python "{SCRIPTS_DIR}/gate_bucket_divergence.py"
      ```

      Fails (exit 1) if, in any **non-informational** bucket (rv_br/rv_eua/rf_balcao/fundos), `|per-asset-simple-mean − stored-bucket-IRR| > 5%`. The `crypto` bucket is informational — its section and divergence always print (marked "informational — not counted") but NEVER cause exit 1; its structural divergence is expected by construction (lifetime XIRR vs open-positions average). Exit 0 = all non-informational buckets within tolerance; exit 2 = `portfolio.json` missing.

   For EACH gate with exit 1: Rule C **blocking** (`../gatekeeper-loop.md`). Surface the violations inline, propose the fix (investigate a data/parser bug → correct and re-run Step 02-05; or explicitly accept the anomaly — for #8, re-run with the `id` added to `--flagged-ids`), and offer `[S]`/`[N]`. Exit 2 on any gate → `portfolio.json` was not generated; go back to Step 05.

6. STOP. Wait for the user's confirmation ("OK, the snapshot can be created").

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. This step is the canonical Rule C surface for investimentos: an anomaly classified "investigate" (change >20%, position zeroed, new ticker) is BLOCKING — surface inline with a proposed fix and do not advance until resolved; a low-materiality quality flag (`seed_only`, `short_window`) is DEFERRABLE — record it and route to review-mode. Three completion gates auto-halt here before the snapshot: `gate_portfolio_delta.py` (#8), `gate_irr_sanity.py` (#9), `gate_bucket_divergence.py` (#10).
- **[C] Continue** → proceed to Step 07 (Snapshot)
- **[B] Back** → go back to investigate
- **[X] Exit** → halt workflow
