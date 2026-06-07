"""Schema-validation + behavior tests for ack_tag_review (write/upsert tool).

`ack_tag_review.py` is the WRITE-class, use=upsert tool that appends
acknowledgement rows to the append-only side-ledger
`.user/finance/bookkeeper/config/corrections/tag-review-acks.csv`
(header: tx_date,tx_description,tx_amount,month,acked_at,source,note). An ack
marks a large untagged despesa as reviewed-and-intentionally-untagged, so
`gate_coverage.py` renders it ACK instead of VIOLATION.

This suite proves the tool-builder Step 5 contract for a `write` tool plus the
tool's load-bearing behaviors:

  1. SCHEMA CONFORMANCE — the tool's output fields conform to the destination
     artifact's current schema, asserted via tool_schema_check.assert_conforms
     (the exact primitive the tool-builder mandates for every write tool).
  2. DRY-RUN (the default, no --apply) writes NOTHING — the destination ack file
     is byte-for-byte unchanged (the retro-rewrite test pattern).
  3. GATE CROSS-CONSISTENCY (round-trip regression guard) — a row acked via this
     tool on a temp copy is reported ACK (not VIOLATION) by gate_coverage.py.
     This is the identity-parity contract: the tool keys acks on the SAME
     (date, description, repr(float(amount))) scheme the gate joins on.
  4. JOINT-MATCH REFUSAL — a request whose description is wrong while date+amount
     match a row fails the joint (date+description+amount) match → exit 1, the
     ack file unchanged (atomic).
  5. DUPLICATE SKIP — re-acking an already-present row → exit 0 (no-op apply is
     success), the ack file unchanged.

Isolation: the tool's --ack-file and --fechamento-dir flags point every read and
write at tmp copies. The real `.user/` files are NEVER touched. conftest.py's
autouse `_isolate_audit` fixture isolates the audit log; BOOKKEEPER_AUDIT_DISABLED
is set per-test for belt-and-suspenders. `ack_tag_review` and `gate_coverage`
live in shared/ (on sys.path via conftest).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import ack_tag_review
from lib import tool_schema_check as tsc


_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent  # scripts/shared/
_GATE_COVERAGE = _SHARED_DIR / "gate_coverage.py"

# The fields ack_tag_review writes, in the destination header order. Mirrors
# ack_tag_review._ACK_HEADER (kept here so the test fails loudly if the tool's
# output schema drifts from the destination contract).
_ACK_HEADER = ["tx_date", "tx_description", "tx_amount", "month", "acked_at", "source", "note"]

# Destination ack file header line (CRLF — the file's real convention; the tool
# preserves it byte-compatibly on append).
_ACK_FILE_HEADER = ",".join(_ACK_HEADER) + "\r\n"

# A transactions.csv whose columns match the real fechamento schema enough for
# the gate (date, description, amount, category, tags) and for the tool's
# identity join (date, description, amount). Hand-authored — never a real ledger.
#
# Exactly ONE large untagged despesa (R13 IBIRAPUERA, -450) so the round-trip is
# clean: unacked → exactly one VIOLATION; acked-via-tool → zero VIOLATIONs. The
# floor is whatever gate_coverage resolves (it falls back to the conservative
# R$100 default here — a full standing-rules.yaml is not provided), so every
# other expense is kept tagged or a receita to stay below scrutiny regardless of
# the active floor. The wrong-description near-miss reuses R13's date+amount.
_TX_HEADER = "date,description,amount,category,tags\n"
_TX_ROWS = [
    # The ONLY large UNTAGGED despesa (no tag) — the ack target / round-trip row.
    "2026-03-22,R13 IBIRAPUERA,-450.00,outros,\n",
    # A tagged despesa — never a violation, never an ack candidate.
    "2026-03-15,POSTO SHELL,-200.00,transporte,carro\n",
    # A tagged despesa above any floor but tagged → not a violation.
    "2026-03-10,SUPERMERCADO EXTRA,-380.00,alimentacao,mercado\n",
    # A receita — excluded category, ignored by the gate entirely.
    "2026-03-01,SALARIO,5000.00,receitas,\n",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def bk(tmp_path, monkeypatch):
    """Isolated tmp tree: a fechamento month + a seeded ack side-ledger + a
    config dir. The tool is pointed here via --ack-file / --fechamento-dir;
    nothing under the real `.user/` is read or written.
    """
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")

    month = "2026-03"
    fechamento_dir = tmp_path / "fechamento"
    (fechamento_dir / month).mkdir(parents=True)
    tx_path = fechamento_dir / month / "transactions.csv"
    tx_path.write_text(_TX_HEADER + "".join(_TX_ROWS), encoding="utf-8")

    # Empty config dir: gate_coverage finds no valid standing-rules.yaml and
    # falls back to its conservative defaults (floor R$100, threshold 0.75) —
    # deterministic, and sufficient for the identity-parity round-trip.
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Seed the ack file with only the header (CRLF), the real file's start state.
    ack_path = tmp_path / "tag-review-acks.csv"
    ack_path.write_bytes(_ACK_FILE_HEADER.encode("utf-8"))

    return {
        "month": month,
        "fechamento_dir": fechamento_dir,
        "tx_path": tx_path,
        "config_dir": config_dir,
        "ack_path": ack_path,
        "tmp": tmp_path,
    }


def _run_tool(bk, *extra, source="review-mode-2026-03"):
    """Invoke ack_tag_review.main() with the isolation flags wired to bk."""
    argv = [
        "--month", bk["month"],
        "--source", source,
        "--ack-file", str(bk["ack_path"]),
        "--fechamento-dir", str(bk["fechamento_dir"]),
        *extra,
    ]
    return ack_tag_review.main(argv)


# ===========================================================================
# 1. Schema conformance — the tool-builder Step 5 mandatory primitive
# ===========================================================================


class TestSchemaConformance:
    def test_output_fields_conform_to_destination_schema(self, bk):
        """The fields the tool writes are all present in the destination ack
        file's current schema — asserted with the exact primitive the
        tool-builder mandates (tool_schema_check.assert_conforms)."""
        destination = tsc.destination_schema(bk["ack_path"])
        # No raise == conforms (output is a subset of the destination header).
        tsc.assert_conforms(_ACK_HEADER, destination, destination=bk["ack_path"])

    def test_no_conformance_gap(self, bk):
        destination = tsc.destination_schema(bk["ack_path"])
        assert tsc.conformance_gap(_ACK_HEADER, destination) == set()

    def test_tool_header_matches_destination_header(self, bk):
        """Belt-and-suspenders: the tool's declared header equals the file's."""
        assert ack_tag_review._ACK_HEADER == _ACK_HEADER
        assert tsc.destination_schema(bk["ack_path"]) == set(_ACK_HEADER)


# ===========================================================================
# 2. Dry-run (default) writes nothing — destination byte-for-byte unchanged
# ===========================================================================


class TestDryRunWritesNothing:
    def test_default_mode_is_dry_run_and_writes_nothing(self, bk):
        before = _sha(bk["ack_path"])
        rc = _run_tool(
            bk,
            "--date", "2026-03-22",
            "--description", "R13 IBIRAPUERA",
            "--amount", "-450.00",
            "--note", "marketplace purchase - no dimensional tag applies",
        )  # no --apply
        assert rc == 0
        assert _sha(bk["ack_path"]) == before  # byte-identical — nothing written

    def test_dry_run_batch_writes_nothing(self, bk):
        batch = bk["tmp"] / "acks.json"
        batch.write_text(
            json.dumps(
                [
                    {"tx_date": "2026-03-22", "tx_description": "R13 IBIRAPUERA", "tx_amount": -450.00},
                    {"tx_date": "2026-03-10", "tx_description": "SUPERMERCADO EXTRA", "tx_amount": -380.00},
                ]
            ),
            encoding="utf-8",
        )
        before = _sha(bk["ack_path"])
        rc = _run_tool(bk, "--input", str(batch))
        assert rc == 0
        assert _sha(bk["ack_path"]) == before


# ===========================================================================
# 3. Gate cross-consistency — round-trip regression guard
# ===========================================================================


def _run_gate(bk):
    """Run gate_coverage.py as a subprocess against the tmp tx + tmp ack copy.

    gate_coverage's main() reads sys.argv directly (no argv param), so a
    subprocess is the faithful invocation. Returns (returncode, stdout, stderr).
    BOOKKEEPER_AUDIT_DISABLED=1 keeps the gate's audit emits silent.
    """
    proc = subprocess.run(
        [
            sys.executable,
            str(_GATE_COVERAGE),
            "--transactions", str(bk["tx_path"]),
            "--ack-file", str(bk["ack_path"]),
            "--config-dir", str(bk["config_dir"]),
        ],
        capture_output=True,
        text=True,
        env={**_subprocess_env()},
    )
    return proc.returncode, proc.stdout, proc.stderr


def _subprocess_env():
    import os

    env = dict(os.environ)
    env["BOOKKEEPER_AUDIT_DISABLED"] = "1"
    return env


class TestGateCrossConsistency:
    def test_unacked_large_untagged_is_a_gate_violation(self, bk):
        """Baseline: before any ack, the large untagged despesa is a VIOLATION
        and the gate fails (exit 1). Establishes the round-trip has teeth."""
        rc, out, err = _run_gate(bk)
        combined = out + err
        assert "VIOLATION" in combined
        assert "R13 IBIRAPUERA" in combined
        assert rc == 1  # gate #3 fails on the unacked large untagged row

    def test_row_acked_via_tool_is_reported_ack_by_gate(self, bk):
        """The round-trip: ack the row WITH THE TOOL (--apply on the temp copy),
        then the gate reports it ACK, not VIOLATION. Proves identity parity —
        the tool writes the same key the gate joins on."""
        # 1. Ack the large untagged despesa via the tool (real append to temp copy).
        rc_ack = _run_tool(
            bk,
            "--date", "2026-03-22",
            "--description", "R13 IBIRAPUERA",
            "--amount", "-450.00",
            "--note", "reviewed - intentionally untagged",
            "--apply",
        )
        assert rc_ack == 0
        # The row was actually written to the temp ack file.
        ack_text = bk["ack_path"].read_text(encoding="utf-8")
        assert "R13 IBIRAPUERA" in ack_text

        # 2. The gate now renders it ACK and no longer counts it as a violation.
        rc, out, err = _run_gate(bk)
        combined = out + err
        assert "ACK" in out  # acked rows print to stdout as visible ACK notes
        assert "R13 IBIRAPUERA" in combined
        # No VIOLATION line for the acked row remains (the only large untagged
        # despesa in the fixture is now acked → gate #3 passes for it).
        assert "VIOLATION" not in err


# ===========================================================================
# 4. Joint-match refusal — wrong description, right date+amount
# ===========================================================================


class TestJointMatchRefusal:
    def test_wrong_description_refuses_and_writes_nothing(self, bk):
        """date + amount match a real row, but the description does not → the
        tool refuses the joint match, exits 1, and writes NOTHING (atomic)."""
        before = _sha(bk["ack_path"])
        rc = _run_tool(
            bk,
            "--date", "2026-03-22",       # matches R13 IBIRAPUERA's date
            "--description", "WRONG VENDOR",  # does NOT match
            "--amount", "-450.00",        # matches R13 IBIRAPUERA's amount
            "--apply",
        )
        assert rc == 1  # named refusal
        assert _sha(bk["ack_path"]) == before  # nothing written

    def test_batch_refusal_is_atomic(self, bk):
        """One bad row in a batch refuses the ENTIRE run — no partial append."""
        batch = bk["tmp"] / "acks.json"
        batch.write_text(
            json.dumps(
                [
                    {"tx_date": "2026-03-22", "tx_description": "R13 IBIRAPUERA", "tx_amount": -450.00},  # valid
                    {"tx_date": "2026-03-22", "tx_description": "WRONG VENDOR", "tx_amount": -450.00},  # invalid
                ]
            ),
            encoding="utf-8",
        )
        before = _sha(bk["ack_path"])
        rc = _run_tool(bk, "--input", str(batch), "--apply")
        assert rc == 1
        assert _sha(bk["ack_path"]) == before  # the valid row was NOT appended


# ===========================================================================
# 5. Duplicate skip — re-acking an existing row is a no-op success
# ===========================================================================


class TestDuplicateSkip:
    def test_reack_of_existing_row_is_noop_success(self, bk):
        """First --apply writes the ack; a second identical --apply skips it as
        a duplicate, exits 0, and leaves the file byte-for-byte unchanged."""
        common = (
            "--date", "2026-03-22",
            "--description", "R13 IBIRAPUERA",
            "--amount", "-450.00",
            "--note", "reviewed",
        )
        rc1 = _run_tool(bk, *common, "--apply")
        assert rc1 == 0
        after_first = _sha(bk["ack_path"])

        # Re-ack the exact same identity triple.
        rc2 = _run_tool(bk, *common, "--apply")
        assert rc2 == 0  # no-op apply is success (requirement 4)
        assert _sha(bk["ack_path"]) == after_first  # duplicate skipped, file unchanged

    def test_all_duplicates_batch_exits_zero(self, bk):
        """A batch where every row already exists → exit 0, file unchanged."""
        batch = bk["tmp"] / "acks.json"
        batch.write_text(
            json.dumps(
                [{"tx_date": "2026-03-22", "tx_description": "R13 IBIRAPUERA", "tx_amount": -450.00}]
            ),
            encoding="utf-8",
        )
        assert _run_tool(bk, "--input", str(batch), "--apply") == 0
        after_first = _sha(bk["ack_path"])
        assert _run_tool(bk, "--input", str(batch), "--apply") == 0  # all dup
        assert _sha(bk["ack_path"]) == after_first
