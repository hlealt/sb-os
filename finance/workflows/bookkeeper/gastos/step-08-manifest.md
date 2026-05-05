---
stepNumber: 8
stepId: manifest
---

# Step 8: Update Dashboard Manifest

**Goal:** Register the closed month in the dashboard manifest so it appears in the financial dashboard.

## Mandatory Sequence

1. Read `{DASHBOARD_DATA}/months.json`.
2. Add `{MONTH}` to the array if not already present.
3. Sort the array chronologically.
4. Save the file.

The manifest feeds the financial dashboard (`dashboard.html`). Without this entry, the month will not appear in the dashboard.

## Routing

After saving the manifest:

- If `{PATH}` = `ambos` → proceed to `{INV_WORKFLOW_DIR}/step-01-preflight.md` (continue with the investimentos flow for the same `{MONTH}`).
- Otherwise → workflow complete.

## Step Menu

- **[D] Done** → if `{PATH}` ≠ `ambos`, workflow complete; if `{PATH}` = `ambos`, continue to investimentos preflight
