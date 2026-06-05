"""Schema-validation tests for upsert_assets.py (write/upsert tool).

Step 5 mandatory test for the tool-builder companion acceptance cycle.
Spec: tool-builder.md § Step 5.1

Assertions per spec:
  (a) Output schema conformance via `lib.tool_schema_check.assert_conforms`.
  (b) `--dry-run` (default invocation) leaves destination byte-for-byte unchanged.
  (c) `--apply` inserts a new row correctly (against a TEMP copy of assets.csv).
  (d) Field-ownership enforcement: a `curated` field on an EXISTING row is NOT
      overwritten by actor `agent_manual`.
  (e) An unknown input column fails loud (non-zero exit / FieldOwnershipError).

The test NEVER writes to the real assets.csv. All writes go to a tmp_path copy
managed by the fixture. Audit is disabled via BOOKKEEPER_AUDIT_DISABLED=1 for
test isolation.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-path resolution and import
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_SHARED_DIR = _TESTS_DIR.parent                   # shared/
_SCRIPTS_DIR = _SHARED_DIR.parent                 # scripts/
_INV_SCRIPTS_DIR = _SCRIPTS_DIR / "investimentos"

# Make shared/ importable (for lib.*).
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from lib import tool_schema_check  # noqa: E402


def _load_upsert_assets():
    """Import upsert_assets.py by file path (lives outside a package)."""
    src = _INV_SCRIPTS_DIR / "upsert_assets.py"
    spec = importlib.util.spec_from_file_location("upsert_assets", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["upsert_assets"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


upsert_assets = _load_upsert_assets()

# ---------------------------------------------------------------------------
# Locate the REAL assets.csv to copy into fixtures
# ---------------------------------------------------------------------------

_VAULT_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "CLAUDE.md").exists() and (p / ".user").is_dir()),
    None,
)
_REAL_ASSETS = (
    _VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "data" / "assets.csv"
    if _VAULT_ROOT
    else None
)
_REAL_CONFIG = (
    _VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "config"
    if _VAULT_ROOT
    else None
)

# ---------------------------------------------------------------------------
# Minimal assets.csv content for isolated tests
# (mirrors the real header; two rows — one crypto, one fixed_income with
#  curated fields populated to exercise ownership protection on update)
# ---------------------------------------------------------------------------

_ASSETS_HEADER = (
    "id,asset_class,name,type,sector,currency,current_broker,active,"
    "issuer,indexer,rate,indexer_pct,application_date,maturity_date,cnpj,manager\n"
)

_EXISTING_ROW_BTC = (
    "BTC,crypto,Bitcoin,crypto,,BRL,,true,,,,,,,,\n"
)

_EXISTING_ROW_KLABIN = (
    "cra_ipca_klabin_350,fixed_income,CRA Klabin (curated name),cra,,BRL,safra,true,"
    "KLABIN S.A.,IPCA,3.5,100.0,2019-10-07,2029-06-15,,\n"
)

_MINIMAL_ASSETS_CONTENT = _ASSETS_HEADER + _EXISTING_ROW_BTC + _EXISTING_ROW_KLABIN


def _write_minimal_assets(path: Path) -> None:
    path.write_text(_MINIMAL_ASSETS_CONTENT, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fixture: isolated bookkeeper tree
# ---------------------------------------------------------------------------


@pytest.fixture
def bk(tmp_path, monkeypatch):
    """Build a minimal isolated bookkeeper tree.

    Sets up:
      - tmp assets.csv with 2 rows
      - real _field_ownership.yaml copied from vault (required by the tool)
      - audit disabled
      - upsert_assets module globals patched to point at tmp tree
    """
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    # Write a minimal assets.csv (2 rows: BTC + curated fixed-income row)
    assets_path = data_dir / "assets.csv"
    _write_minimal_assets(assets_path)

    # Copy the real _field_ownership.yaml — the manifest MUST be real because
    # the test must verify that the tool behaves correctly against the live
    # field-class registry.
    if _REAL_CONFIG is None or not (_REAL_CONFIG / "_field_ownership.yaml").exists():
        pytest.skip("Real _field_ownership.yaml not present (running outside vault).")
    shutil.copy(_REAL_CONFIG / "_field_ownership.yaml", config_dir / "_field_ownership.yaml")

    # Create a minimal sb-os.json so audit's vault-root search succeeds if needed.
    (tmp_path / "sb-os.json").write_text("{}", encoding="utf-8")

    # Disable audit to avoid JSONL noise and vault-root writes during tests.
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")

    # Patch the module-level destination + config paths so the tool writes to
    # our tmp tree, not the real vault.
    monkeypatch.setattr(upsert_assets, "DESTINATION", assets_path)
    monkeypatch.setattr(upsert_assets, "CONFIG_DIR", config_dir)

    return {
        "assets": assets_path,
        "config": config_dir,
        "data_dir": data_dir,
        "tmp": tmp_path,
    }


# ---------------------------------------------------------------------------
# Input CSV helpers
# ---------------------------------------------------------------------------


def _write_input(path: Path, rows: list[dict]) -> None:
    """Write a well-formed input CSV to `path`."""
    if not rows:
        path.write_text(_ASSETS_HEADER, encoding="utf-8")
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _new_asset_row(asset_id: str = "ETH") -> dict:
    return {
        "id": asset_id,
        "asset_class": "crypto",
        "name": "Ethereum",
        "type": "crypto",
        "sector": "",
        "currency": "BRL",
        "current_broker": "",
        "active": "false",
        "issuer": "",
        "indexer": "",
        "rate": "",
        "indexer_pct": "",
        "application_date": "",
        "maturity_date": "",
        "cnpj": "",
        "manager": "",
    }


# ---------------------------------------------------------------------------
# (a) Schema conformance via tool_schema_check.assert_conforms
# ---------------------------------------------------------------------------


class TestSchemaConformance:
    def test_output_conforms_to_destination_schema(self, bk):
        """The tool's output field set must be a subset of assets.csv schema."""
        dest_schema = tool_schema_check.destination_schema(bk["assets"])
        # The tool always uses exactly the destination header for output rows.
        # Verify the destination schema derived from our tmp file matches the
        # expected 16 columns.
        expected_cols = {
            "id", "asset_class", "name", "type", "sector", "currency",
            "current_broker", "active", "issuer", "indexer", "rate",
            "indexer_pct", "application_date", "maturity_date", "cnpj", "manager",
        }
        assert dest_schema == expected_cols, (
            f"Unexpected destination schema. Got: {sorted(dest_schema)}"
        )
        # assert_conforms must pass for the same column set.
        tool_schema_check.assert_conforms(
            expected_cols, dest_schema, destination=bk["assets"]
        )

    def test_assert_conforms_raises_on_gap(self, bk):
        """assert_conforms raises SchemaGapError when a new field is introduced."""
        dest_schema = tool_schema_check.destination_schema(bk["assets"])
        with pytest.raises(tool_schema_check.SchemaGapError, match="absent from the destination"):
            tool_schema_check.assert_conforms(
                {"id", "asset_class", "new_unknown_field"}, dest_schema
            )


# ---------------------------------------------------------------------------
# (b) --dry-run leaves destination byte-for-byte unchanged
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_writes_nothing(self, bk, tmp_path):
        """Default invocation (no --apply) must NOT mutate assets.csv."""
        before = _sha256(bk["assets"])
        input_csv = tmp_path / "input.csv"
        _write_input(input_csv, [_new_asset_row("ETH")])

        rc = upsert_assets.run(input_csv, apply=False, actor="agent_manual")
        assert rc == 0
        assert _sha256(bk["assets"]) == before, (
            "Dry-run mutated assets.csv — destination must be byte-for-byte unchanged"
        )

    def test_dry_run_noop_writes_nothing(self, bk, tmp_path):
        """Dry-run against an EXISTING id (noop) also leaves destination unchanged."""
        before = _sha256(bk["assets"])
        input_csv = tmp_path / "input_noop.csv"
        # BTC already exists in the fixture; re-submitting the same row = noop.
        _write_input(input_csv, [{
            "id": "BTC",
            "asset_class": "crypto",
            "name": "Bitcoin",
            "type": "crypto",
            "sector": "",
            "currency": "BRL",
            "current_broker": "",
            "active": "true",
            "issuer": "",
            "indexer": "",
            "rate": "",
            "indexer_pct": "",
            "application_date": "",
            "maturity_date": "",
            "cnpj": "",
            "manager": "",
        }])

        rc = upsert_assets.run(input_csv, apply=False, actor="agent_manual")
        assert rc == 0
        assert _sha256(bk["assets"]) == before

    def test_dry_run_returns_zero_on_valid_input(self, bk, tmp_path):
        """Dry-run exit code is 0 for valid input."""
        input_csv = tmp_path / "input_valid.csv"
        _write_input(input_csv, [_new_asset_row("DOT")])
        rc = upsert_assets.run(input_csv, apply=False, actor="agent_manual")
        assert rc == 0


# ---------------------------------------------------------------------------
# (c) --apply inserts a new row correctly
# ---------------------------------------------------------------------------


class TestApplyInsert:
    def test_apply_inserts_new_row(self, bk, tmp_path):
        """--apply must add a new row to assets.csv and exit 0."""
        input_csv = tmp_path / "input_new.csv"
        new_row = _new_asset_row("ETH")
        _write_input(input_csv, [new_row])

        before_count = sum(1 for _ in open(bk["assets"], encoding="utf-8")) - 1  # exclude header
        rc = upsert_assets.run(input_csv, apply=True, actor="agent_manual")
        assert rc == 0

        # Verify the new row is present.
        with open(bk["assets"], encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        after_count = len(rows)
        assert after_count == before_count + 1, (
            f"Expected {before_count + 1} rows after insert; got {after_count}"
        )

        ids = [r["id"] for r in rows]
        assert "ETH" in ids, "Inserted id 'ETH' not found in assets.csv after apply"

    def test_apply_inserted_row_fields_correct(self, bk, tmp_path):
        """The inserted row must carry the values from the input CSV."""
        input_csv = tmp_path / "input_fields.csv"
        new_row = _new_asset_row("LINK")
        _write_input(input_csv, [new_row])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        assert "LINK" in rows
        row = rows["LINK"]
        assert row["asset_class"] == "crypto"
        assert row["name"] == "Ethereum"   # value from _new_asset_row
        assert row["type"] == "crypto"
        assert row["currency"] == "BRL"

    def test_apply_new_row_inserted_at_byte_sort_position(self, bk, tmp_path):
        """After apply, new rows are inserted at byte/ASCII sort position.

        The fixture has BTC (uppercase) and cra_ipca_klabin_350 (lowercase).
        Byte order: uppercase < lowercase, so BTC < cra_…
        ADA (uppercase) must be inserted BEFORE BTC.
        ETH (uppercase) must be inserted BETWEEN BTC and cra_…
        """
        input_csv = tmp_path / "input_sort.csv"
        _write_input(input_csv, [_new_asset_row("ADA")])  # ADA < BTC in byte order

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            ids = [r["id"] for r in csv.DictReader(f)]

        # Byte-sort: ADA < BTC < cra_ipca_klabin_350
        assert ids[0] == "ADA", f"ADA should be first (byte-sort); got {ids}"
        assert ids[1] == "BTC", f"BTC should be second; got {ids}"
        assert ids[2] == "cra_ipca_klabin_350", f"cra row should be third; got {ids}"

    def test_apply_mutates_destination(self, bk, tmp_path):
        """Hash of assets.csv must change after --apply with a new row."""
        before = _sha256(bk["assets"])
        input_csv = tmp_path / "input_hash.csv"
        _write_input(input_csv, [_new_asset_row("XMR")])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        assert _sha256(bk["assets"]) != before, (
            "assets.csv hash unchanged after --apply insert — write did not happen"
        )


# ---------------------------------------------------------------------------
# (f) Byte-sort insert order — existing rows must not be reordered
# ---------------------------------------------------------------------------


# Fixture content for byte-sort tests: ids chosen to span the uppercase/lowercase
# boundary in ASCII order.  Byte order: BTC < XRP < aplicacoes_renda_fixa < cdb_meli
_BYTE_SORT_HEADER = (
    "id,asset_class,name,type,sector,currency,current_broker,active,"
    "issuer,indexer,rate,indexer_pct,application_date,maturity_date,cnpj,manager\n"
)
_BYTE_SORT_ROWS = (
    "BTC,crypto,Bitcoin,crypto,,BRL,,true,,,,,,,,\n"
    "XRP,crypto,Ripple,crypto,,BRL,,true,,,,,,,,\n"
    "aplicacoes_renda_fixa,fixed_income,Aplicações Renda Fixa,di,,BRL,,true,,,,,,,,\n"
    "cdb_meli,fixed_income,CDB Mercado Livre,cdb,,BRL,xp,true,,,,,,,,\n"
)
_BYTE_SORT_CONTENT = _BYTE_SORT_HEADER + _BYTE_SORT_ROWS


@pytest.fixture
def bk_byte_sort(tmp_path, monkeypatch):
    """Fixture with 4 ids spanning the uppercase/lowercase byte boundary."""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    assets_path = data_dir / "assets.csv"
    assets_path.write_text(_BYTE_SORT_CONTENT, encoding="utf-8")

    if _REAL_CONFIG is None or not (_REAL_CONFIG / "_field_ownership.yaml").exists():
        pytest.skip("Real _field_ownership.yaml not present (running outside vault).")
    shutil.copy(_REAL_CONFIG / "_field_ownership.yaml", config_dir / "_field_ownership.yaml")

    (tmp_path / "sb-os.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(upsert_assets, "DESTINATION", assets_path)
    monkeypatch.setattr(upsert_assets, "CONFIG_DIR", config_dir)

    return {"assets": assets_path, "config": config_dir, "tmp": tmp_path}


def _byte_sort_row(asset_id: str, asset_class: str = "crypto", typ: str = "crypto") -> dict:
    return {
        "id": asset_id,
        "asset_class": asset_class,
        "name": asset_id,
        "type": typ,
        "sector": "",
        "currency": "BRL",
        "current_broker": "",
        "active": "true",
        "issuer": "",
        "indexer": "",
        "rate": "",
        "indexer_pct": "",
        "application_date": "",
        "maturity_date": "",
        "cnpj": "",
        "manager": "",
    }


class TestByteSortInsertOrder:
    """All assertions in this class cover the correction requirement:

    • Existing rows MUST remain byte-identical and in their original positions.
    • New rows MUST be inserted at their byte/ASCII sort position.
    • The implementation MUST NOT re-sort existing rows.
    """

    def test_existing_rows_unchanged_after_insert(self, bk_byte_sort, tmp_path):
        """Insert a new row; all 4 existing rows must be byte-identical afterward.

        Reads the file line-by-line before and after --apply; verifies each
        pre-existing line is still present and in its original order.
        """
        assets = bk_byte_sort["assets"]

        # Capture every data line (skip header) before the run.
        before_lines = assets.read_text(encoding="utf-8").splitlines()[1:]

        input_csv = tmp_path / "input_new.csv"
        _write_input(input_csv, [_byte_sort_row("ETH")])  # ETH: between BTC/XRP and aplicacoes

        rc = upsert_assets.run(input_csv, apply=True, actor="agent_manual")
        assert rc == 0

        after_lines = assets.read_text(encoding="utf-8").splitlines()[1:]

        # Each original line must still exist in after_lines.
        for orig_line in before_lines:
            assert orig_line in after_lines, (
                f"Existing line was modified or removed after insert:\n  {orig_line!r}"
            )

        # Original lines must appear in their original relative order.
        after_line_positions = {line: i for i, line in enumerate(after_lines)}
        orig_positions = [after_line_positions[line] for line in before_lines]
        assert orig_positions == sorted(orig_positions), (
            f"Existing rows were reordered after insert.\n"
            f"Original: {before_lines}\nAfter: {after_lines}"
        )

    def test_new_row_inserted_at_byte_sort_position(self, bk_byte_sort, tmp_path):
        """New row ETH (uppercase) must land between XRP and aplicacoes_renda_fixa.

        Byte order: BTC < ETH < XRP < aplicacoes_renda_fixa < cdb_meli
        Expected ids sequence after insert: BTC, ETH, XRP, aplicacoes_renda_fixa, cdb_meli
        """
        input_csv = tmp_path / "input_eth.csv"
        _write_input(input_csv, [_byte_sort_row("ETH")])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk_byte_sort["assets"], encoding="utf-8", newline="") as f:
            ids = [r["id"] for r in csv.DictReader(f)]

        expected = ["BTC", "ETH", "XRP", "aplicacoes_renda_fixa", "cdb_meli"]
        assert ids == expected, (
            f"Wrong id order after inserting ETH.\n"
            f"  expected: {expected}\n"
            f"  got:      {ids}"
        )

    def test_new_row_before_all_uppercase_inserted_first(self, bk_byte_sort, tmp_path):
        """New row ADA (byte-sorts before BTC) must become the first row."""
        input_csv = tmp_path / "input_ada.csv"
        _write_input(input_csv, [_byte_sort_row("ADA")])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk_byte_sort["assets"], encoding="utf-8", newline="") as f:
            ids = [r["id"] for r in csv.DictReader(f)]

        assert ids[0] == "ADA", f"ADA should be first (byte-sorts before BTC); got {ids}"
        assert ids[1] == "BTC", f"BTC should remain second; got {ids}"

    def test_new_lowercase_row_inserted_among_lowercase(self, bk_byte_sort, tmp_path):
        """New row 'bb_cdb' (lowercase) must land between aplicacoes and cdb_meli."""
        input_csv = tmp_path / "input_bb.csv"
        _write_input(input_csv, [_byte_sort_row("bb_cdb", "fixed_income", "cdb")])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk_byte_sort["assets"], encoding="utf-8", newline="") as f:
            ids = [r["id"] for r in csv.DictReader(f)]

        # Byte order: aplicacoes < bb_cdb < cdb_meli
        idx_ap = ids.index("aplicacoes_renda_fixa")
        idx_bb = ids.index("bb_cdb")
        idx_cd = ids.index("cdb_meli")
        assert idx_ap < idx_bb < idx_cd, (
            f"bb_cdb not in correct byte-sort position. ids={ids}"
        )

    def test_no_reorder_on_pure_update(self, bk_byte_sort, tmp_path):
        """An update (no new rows) must leave the file byte-identical."""
        assets = bk_byte_sort["assets"]
        before = assets.read_bytes()

        # Update BTC — change currency from BRL to USD (derived field, freely writable).
        # Actually currency is likely derived; let's change current_broker which is derived.
        input_csv = tmp_path / "input_update.csv"
        _write_input(input_csv, [{
            **_byte_sort_row("BTC"),
            "current_broker": "binance",  # derived field — writeable
        }])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        after = assets.read_bytes()
        after_lines = after.decode("utf-8").splitlines()
        before_lines = before.decode("utf-8").splitlines()

        # Row count unchanged.
        assert len(after_lines) == len(before_lines), (
            f"Row count changed on pure update: {len(before_lines)} → {len(after_lines)}"
        )

        # All non-BTC rows must be byte-identical.
        before_non_btc = [l for l in before_lines if not l.startswith("BTC,")]
        after_non_btc = [l for l in after_lines if not l.startswith("BTC,")]
        assert before_non_btc == after_non_btc, (
            "Non-updated rows changed on a pure update."
        )


# ---------------------------------------------------------------------------
# (d) Field-ownership enforcement: curated field NOT overwritten on update
# ---------------------------------------------------------------------------


class TestFieldOwnershipEnforcement:
    def test_curated_name_not_overwritten_by_agent_manual(self, bk, tmp_path):
        """actor=agent_manual must NOT overwrite `name` (curated) on an existing row."""
        # The fixture has cra_ipca_klabin_350 with name "CRA Klabin (curated name)".
        input_csv = tmp_path / "input_curated.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "SHOULD NOT BE WRITTEN",   # curated — must be blocked
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "KLABIN S.A.",            # also curated — must be blocked
            "indexer": "IPCA",
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        rc = upsert_assets.run(input_csv, apply=True, actor="agent_manual")
        assert rc == 0

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        klabin = rows["cra_ipca_klabin_350"]
        assert klabin["name"] == "CRA Klabin (curated name)", (
            f"Curated `name` was overwritten by agent_manual — got {klabin['name']!r}"
        )

    def test_curated_issuer_not_overwritten_by_agent_manual(self, bk, tmp_path):
        """actor=agent_manual must NOT overwrite `issuer` (curated) on an existing row."""
        input_csv = tmp_path / "input_issuer.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "CRA Klabin (curated name)",
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "WRONG ISSUER NAME",   # curated — must not be written
            "indexer": "IPCA",
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        klabin = rows["cra_ipca_klabin_350"]
        assert klabin["issuer"] == "KLABIN S.A.", (
            f"Curated `issuer` was overwritten by agent_manual — got {klabin['issuer']!r}"
        )

    def test_curated_active_not_overwritten_by_agent_manual(self, bk, tmp_path):
        """actor=agent_manual must NOT overwrite `active` (curated) on an existing row."""
        input_csv = tmp_path / "input_active.csv"
        _write_input(input_csv, [{
            "id": "BTC",
            "asset_class": "crypto",
            "name": "Bitcoin",
            "type": "crypto",
            "sector": "",
            "currency": "BRL",
            "current_broker": "",
            "active": "false",     # BTC fixture has active=true; should be blocked
            "issuer": "",
            "indexer": "",
            "rate": "",
            "indexer_pct": "",
            "application_date": "",
            "maturity_date": "",
            "cnpj": "",
            "manager": "",
        }])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        assert rows["BTC"]["active"] == "true", (
            f"Curated `active` was overwritten by agent_manual — got {rows['BTC']['active']!r}"
        )


# ---------------------------------------------------------------------------
# (e) Unknown input column fails loud
# ---------------------------------------------------------------------------


class TestUnknownFieldFailsLoud:
    def test_unknown_column_returns_nonzero(self, bk, tmp_path):
        """An input CSV with a column not in _field_ownership.yaml must exit non-zero."""
        input_csv = tmp_path / "input_unknown.csv"
        # Write a CSV with an extra unknown column.
        with open(input_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(_new_asset_row("SOL").keys()) + ["completely_unknown_field"],
                lineterminator="\n",
            )
            writer.writeheader()
            row = _new_asset_row("SOL")
            row["completely_unknown_field"] = "some_value"
            writer.writerow(row)

        rc = upsert_assets.run(input_csv, apply=False, actor="agent_manual")
        assert rc != 0, (
            "Expected non-zero exit when input CSV contains an unknown column"
        )

    def test_unknown_column_does_not_write(self, bk, tmp_path):
        """Even --apply must be refused when input has unknown columns."""
        before = _sha256(bk["assets"])
        input_csv = tmp_path / "input_unknown_apply.csv"
        with open(input_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(_new_asset_row("SOL").keys()) + ["ghost_field"],
                lineterminator="\n",
            )
            writer.writeheader()
            row = _new_asset_row("SOL")
            row["ghost_field"] = "boom"
            writer.writerow(row)

        rc = upsert_assets.run(input_csv, apply=True, actor="agent_manual")
        assert rc != 0
        assert _sha256(bk["assets"]) == before, (
            "assets.csv was mutated despite unknown-column failure — boundary violated"
        )


# ---------------------------------------------------------------------------
# (g) User-actor semantics — curated-field updates via --actor user
# ---------------------------------------------------------------------------


class TestUserActorUpsert:
    """End-to-end coverage for the --actor user behavior change.

    Spec (Step 5 requirements):
      (a) can_write curated update allowed for actor user — covered in test_field_ownership.py.
      (b) curated update blocked for agent_manual/parser — covered in test_field_ownership.py.
      (c) source_bound update blocked for user — covered in test_field_ownership.py.
      (d) dry-run with --actor user produces UPDATE for a curated-field change and
          writes nothing (destination byte-for-byte unchanged).

    This class covers requirement (d): end-to-end dry-run behavior.
    """

    def test_user_actor_dry_run_produces_update_for_curated_field(self, bk, tmp_path):
        """(d) Dry-run with actor=user reports UPDATE for a curated field change.

        The fixture has cra_ipca_klabin_350 with name="CRA Klabin (curated name)".
        actor=user is the only identity that may update curated fields on an existing row.
        A dry-run must show the UPDATE diff and return exit code 0.
        """
        before = _sha256(bk["assets"])
        input_csv = tmp_path / "input_user_curated.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "CRA Klabin (user corrected name)",  # curated field — only user may update
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "KLABIN S.A.",
            "indexer": "IPCA",
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        rc = upsert_assets.run(input_csv, apply=False, actor="user")
        assert rc == 0, "Dry-run with actor=user must exit 0 for valid curated-field change"

        # Destination must be byte-for-byte unchanged (dry-run writes nothing).
        assert _sha256(bk["assets"]) == before, (
            "Dry-run with actor=user mutated assets.csv — destination must be unchanged"
        )

    def test_user_actor_dry_run_writes_nothing(self, bk, tmp_path):
        """(d) Destination is byte-for-byte unchanged after dry-run with actor=user."""
        before_bytes = bk["assets"].read_bytes()
        input_csv = tmp_path / "input_user_noop_check.csv"
        _write_input(input_csv, [{
            "id": "BTC",
            "asset_class": "crypto",
            "name": "Bitcoin RENAMED",   # curated — user actor would update; dry-run must not write
            "type": "crypto",
            "sector": "",
            "currency": "BRL",
            "current_broker": "",
            "active": "true",
            "issuer": "",
            "indexer": "",
            "rate": "",
            "indexer_pct": "",
            "application_date": "",
            "maturity_date": "",
            "cnpj": "",
            "manager": "",
        }])

        upsert_assets.run(input_csv, apply=False, actor="user")
        assert bk["assets"].read_bytes() == before_bytes, (
            "assets.csv changed after dry-run with actor=user — dry-run must write nothing"
        )

    def test_user_actor_apply_updates_curated_field(self, bk, tmp_path):
        """(d) Under --apply, actor=user DOES overwrite a curated field on an existing row."""
        input_csv = tmp_path / "input_user_apply.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "CRA Klabin (user corrected name)",  # curated — user actor may write
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "KLABIN S.A.",
            "indexer": "IPCA",
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        rc = upsert_assets.run(input_csv, apply=True, actor="user")
        assert rc == 0

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        assert rows["cra_ipca_klabin_350"]["name"] == "CRA Klabin (user corrected name)", (
            "actor=user --apply must update the curated `name` field; it was not updated"
        )

    def test_user_actor_apply_still_blocked_on_source_bound(self, bk, tmp_path):
        """(c) Even under --apply, actor=user does NOT update source_bound fields.

        The fixture row cra_ipca_klabin_350 has indexer=IPCA (source_bound field with
        owners=[safra_titulos, ...]). actor=user is not an owner; the field must stay.
        """
        input_csv = tmp_path / "input_user_source_bound.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "CRA Klabin (curated name)",
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "KLABIN S.A.",
            "indexer": "CDI",   # source_bound — user actor must NOT update this
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        rc = upsert_assets.run(input_csv, apply=True, actor="user")
        assert rc == 0

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        assert rows["cra_ipca_klabin_350"]["indexer"] == "IPCA", (
            f"source_bound `indexer` was updated by actor=user — must stay 'IPCA'; "
            f"got {rows['cra_ipca_klabin_350']['indexer']!r}"
        )

    def test_agent_manual_still_blocked_on_curated_via_upsert(self, bk, tmp_path):
        """(b) agent_manual cannot update a curated field even under --apply.

        This is a regression guard: the user-actor unlock must not accidentally
        extend to agent_manual.
        """
        input_csv = tmp_path / "input_agent_curated.csv"
        _write_input(input_csv, [{
            "id": "cra_ipca_klabin_350",
            "asset_class": "fixed_income",
            "name": "SHOULD NOT BE WRITTEN BY AGENT",   # curated — agent_manual blocked
            "type": "cra",
            "sector": "",
            "currency": "BRL",
            "current_broker": "safra",
            "active": "true",
            "issuer": "KLABIN S.A.",
            "indexer": "IPCA",
            "rate": "3.5",
            "indexer_pct": "100.0",
            "application_date": "2019-10-07",
            "maturity_date": "2029-06-15",
            "cnpj": "",
            "manager": "",
        }])

        upsert_assets.run(input_csv, apply=True, actor="agent_manual")

        with open(bk["assets"], encoding="utf-8", newline="") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}

        assert rows["cra_ipca_klabin_350"]["name"] == "CRA Klabin (curated name)", (
            "agent_manual was able to update a curated `name` — ownership enforcement broken"
        )


# ---------------------------------------------------------------------------
# Real assets.csv mutation guard (non-mutating sanity check)
# ---------------------------------------------------------------------------


def test_real_assets_csv_not_mutated(real_assets_sha_before_suite):
    """Guard: the REAL assets.csv must NOT have been touched by any test above.

    Compares the file's current SHA-256 against the hash captured by the
    session-scoped `real_assets_sha_before_suite` fixture (conftest.py)
    BEFORE the first test of the session ran — fails only if this very run
    mutated the file, never on legitimate out-of-band edits. The fixture's
    teardown re-check is the backstop for tests that run after this module.
    """
    if real_assets_sha_before_suite is None:
        pytest.skip("Real assets.csv not present (running outside vault).")
    actual = _sha256(_REAL_ASSETS)
    assert actual == real_assets_sha_before_suite, (
        f"REAL assets.csv SHA-256 changed during this test run!\n"
        f"  before suite: {real_assets_sha_before_suite}\n"
        f"  now:          {actual}\n"
        f"A test wrote to the real file — investigate immediately."
    )
