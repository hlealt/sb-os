---
stepNumber: 2
stepId: normalize
nextStepFile: step-03-validate.md
---

# Step 2: Normalize

**Goal:** Run the normalization script to convert raw bank files into standardized CSVs.

## Mandatory Sequence

1. Verify that Python dependencies are installed:
   ```bash
   pip install -r "{SCRIPTS_DIR}/requirements.txt"
   ```
2. Run the normalization script:
   ```bash
   python "{SCRIPTS_DIR}/normalize.py" "{RAW_DIR}" "{PROCESSED_DIR}" "{CONFIG_DIR}"
   ```
3. Read the script output. If there are errors, report to the user and ask how to proceed.
4. Proceed to Step 03.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool).
- **[C] Continue** → proceed to Step 03 (Validate)
- **[X] Exit** → halt workflow
