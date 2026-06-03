"""Tests for the finance-module dashboard entry-HTML render (p1-3 / p1-13).

The installer renders ``finance/dashboard/dashboard.html.template`` to the
vault's ``finance_dashboard_html_path`` (default ``.user/finance/dashboard.html``)
with a vault-root-absolute asset base derived from ``sb_os_path``. Data-fetch
paths are NOT substituted — they are fixed vault-root-absolute constants in
the dashboard JS (``shared.js`` ``FIN_DATA_BASE`` = ``/.user/finance/bookkeeper``,
per the p1-3 fixed-data-paths contract). Install-if-missing: an existing
entry HTML is never overwritten.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> Path:
    # <repo>/install/tests/<this-file>
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


_REPO_ROOT = _bootstrap()

from install import cli, finance, fresh, manifest, upgrade  # noqa: E402


_SB_OS_PATH = "3-resources/tools/sb-os"
_EXPECTED_ASSET_BASE = "/3-resources/tools/sb-os/finance/dashboard"
_DASHBOARD_SCRIPTS = (
    "shared.js",
    "expenses.js",
    "inv-data.js",
    "inv-carteira.js",
    "inv-bolsa.js",
    "inv-balcao.js",
    "inv-crypto.js",
    "inv-proventos.js",
    "inv-historico.js",
    "investments.js",
)


class TestAssetBase(unittest.TestCase):

    def test_asset_base_derived_from_sb_os_path(self) -> None:
        self.assertEqual(
            finance.dashboard_asset_base(_SB_OS_PATH), _EXPECTED_ASSET_BASE
        )

    def test_asset_base_normalizes_slashes(self) -> None:
        for variant in (
            "3-resources/tools/sb-os/",
            "/3-resources/tools/sb-os",
            "3-resources\\tools\\sb-os",
        ):
            self.assertEqual(
                finance.dashboard_asset_base(variant),
                _EXPECTED_ASSET_BASE,
                msg=f"variant {variant!r} did not normalize",
            )

    def test_asset_base_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            finance.dashboard_asset_base("")


class TestRender(unittest.TestCase):

    def test_render_substitutes_placeholder(self) -> None:
        template = (
            '<link rel="stylesheet" href="{{DASHBOARD_ASSET_BASE}}/styles.css">\n'
            '<script src="{{DASHBOARD_ASSET_BASE}}/shared.js"></script>\n'
        )
        rendered = finance.render_dashboard_html(template, _SB_OS_PATH)
        self.assertNotIn("{{DASHBOARD_ASSET_BASE}}", rendered)
        self.assertIn(f'href="{_EXPECTED_ASSET_BASE}/styles.css"', rendered)
        self.assertIn(f'src="{_EXPECTED_ASSET_BASE}/shared.js"', rendered)

    def test_real_template_renders_complete_and_unstale(self) -> None:
        """The shipped template must render with zero stale relative paths.

        Guards the p1-13 path reconciliation: the pre-reorg co-located layout
        used ``scripts/dashboard/...`` relative asset paths, which 404 from
        the install destination. The rendered page must reference every
        asset vault-root-absolutely under the sb_os_path-derived base.
        """
        template_path = _REPO_ROOT / finance.DASHBOARD_TEMPLATE_REL
        self.assertTrue(template_path.is_file(), msg=f"missing {template_path}")
        rendered = finance.render_dashboard_html(
            template_path.read_text(encoding="utf-8"), _SB_OS_PATH
        )
        self.assertNotIn("{{DASHBOARD_ASSET_BASE}}", rendered)
        self.assertNotIn("scripts/dashboard/", rendered, msg="stale pre-reorg asset path")
        self.assertIn(f'href="{_EXPECTED_ASSET_BASE}/styles.css"', rendered)
        for script in _DASHBOARD_SCRIPTS:
            self.assertIn(
                f'src="{_EXPECTED_ASSET_BASE}/{script}"',
                rendered,
                msg=f"script tag for {script} missing or not vault-root-absolute",
            )


class TestInstallIfMissing(unittest.TestCase):

    def _fake_sb_os_root(self, tmp: Path) -> Path:
        sb_os_root = tmp / "repo"
        tdir = sb_os_root / "finance" / "dashboard"
        tdir.mkdir(parents=True)
        (tdir / "dashboard.html.template").write_text(
            '<script src="{{DASHBOARD_ASSET_BASE}}/shared.js"></script>\n',
            encoding="utf-8",
        )
        return sb_os_root

    def test_writes_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sb_os_root = self._fake_sb_os_root(tmp)
            target = tmp / "vault"
            target.mkdir()
            written = finance.install_dashboard_if_missing(
                target_root=target,
                sb_os_root=sb_os_root,
                sb_os_path=_SB_OS_PATH,
                html_path=".user/finance/dashboard.html",
            )
            self.assertEqual(written, target / ".user/finance/dashboard.html")
            text = written.read_text(encoding="utf-8")
            self.assertIn(f'src="{_EXPECTED_ASSET_BASE}/shared.js"', text)
            self.assertNotIn("{{DASHBOARD_ASSET_BASE}}", text)

    def test_skips_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sb_os_root = self._fake_sb_os_root(tmp)
            target = tmp / "vault"
            existing = target / ".user/finance/dashboard.html"
            existing.parent.mkdir(parents=True)
            existing.write_text("user-customized sentinel", encoding="utf-8")
            written = finance.install_dashboard_if_missing(
                target_root=target,
                sb_os_root=sb_os_root,
                sb_os_path=_SB_OS_PATH,
                html_path=".user/finance/dashboard.html",
            )
            self.assertIsNone(written)
            self.assertEqual(
                existing.read_text(encoding="utf-8"), "user-customized sentinel"
            )

    def test_missing_template_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(FileNotFoundError):
                finance.install_dashboard_if_missing(
                    target_root=tmp / "vault",
                    sb_os_root=tmp / "empty-repo",
                    sb_os_path=_SB_OS_PATH,
                    html_path=".user/finance/dashboard.html",
                )

    def test_render_against_real_repo(self) -> None:
        """End-to-end against the real template: file lands, fully rendered."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            written = finance.install_dashboard_if_missing(
                target_root=target,
                sb_os_root=_REPO_ROOT,
                sb_os_path=_SB_OS_PATH,
                html_path=".user/finance/dashboard.html",
            )
            self.assertIsNotNone(written)
            text = written.read_text(encoding="utf-8")
            self.assertNotIn("{{DASHBOARD_ASSET_BASE}}", text)
            self.assertNotIn("scripts/dashboard/", text)


class TestPlanWiring(unittest.TestCase):

    def test_fresh_plan_includes_render_when_finance_selected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = fresh.build_fresh_plan(
                Path(td),
                _REPO_ROOT,
                selected_modules=("core", "finance"),
                excluded_components=(),
                finance_dashboard_html_path=".user/finance/dashboard.html",
            )
        targets = [a.target for a in plan.actions]
        self.assertIn(".user/finance/dashboard.html", targets)

    def test_fresh_plan_excludes_render_without_finance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan = fresh.build_fresh_plan(
                Path(td),
                _REPO_ROOT,
                selected_modules=("core",),
                excluded_components=(),
                finance_dashboard_html_path=".user/finance/dashboard.html",
            )
        targets = [a.target for a in plan.actions]
        self.assertNotIn(".user/finance/dashboard.html", targets)

    def test_upgrade_plan_includes_render_when_finance_selected(self) -> None:
        plan = upgrade.build_upgrade_plan(
            "3-resources/knowledge-base/",
            ".user/context/",
            ("core", "finance"),
            set(),
            install_wiki=False,
            finance_dashboard_html_path=".user/finance/dashboard.html",
        )
        targets = [a.target for a in plan.actions]
        self.assertIn(".user/finance/dashboard.html", targets)

    def test_upgrade_plan_excludes_render_without_finance(self) -> None:
        plan = upgrade.build_upgrade_plan(
            "3-resources/knowledge-base/",
            ".user/context/",
            ("core",),
            set(),
            install_wiki=False,
            finance_dashboard_html_path=".user/finance/dashboard.html",
        )
        targets = [a.target for a in plan.actions]
        self.assertNotIn(".user/finance/dashboard.html", targets)


class TestManifestKnob(unittest.TestCase):

    def test_create_initial_includes_field_when_given(self) -> None:
        m = manifest.create_initial(
            vault_root="ignored",
            mode="fresh",
            wiki_root="3-resources/knowledge-base/",
            user_context_root=".user/context/",
            sb_os_path="3-resources/tools/sb-os/",
            finance_dashboard_html_path=".user/finance/dashboard.html",
        )
        self.assertEqual(
            m["finance_dashboard_html_path"], ".user/finance/dashboard.html"
        )

    def test_create_initial_omits_field_when_none(self) -> None:
        m = manifest.create_initial(
            vault_root="ignored",
            mode="fresh",
            wiki_root="3-resources/knowledge-base/",
            user_context_root=".user/context/",
            sb_os_path="3-resources/tools/sb-os/",
        )
        self.assertNotIn("finance_dashboard_html_path", m)

    def test_update_for_upgrade_backfills_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            manifest.write(vault, manifest.create_initial(
                vault_root=vault,
                mode="fresh",
                wiki_root="w/",
                user_context_root="c/",
                sb_os_path="s/",
            ))
            updated = manifest.update_for_upgrade(
                vault,
                finance_dashboard_html_path=".user/finance/dashboard.html",
            )
            self.assertEqual(
                updated["finance_dashboard_html_path"],
                ".user/finance/dashboard.html",
            )

    def test_update_for_upgrade_preserves_existing_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            seeded = manifest.create_initial(
                vault_root=vault,
                mode="fresh",
                wiki_root="w/",
                user_context_root="c/",
                sb_os_path="s/",
                finance_dashboard_html_path="custom/place/dashboard.html",
            )
            manifest.write(vault, seeded)
            updated = manifest.update_for_upgrade(
                vault,
                finance_dashboard_html_path=".user/finance/dashboard.html",
            )
            self.assertEqual(
                updated["finance_dashboard_html_path"],
                "custom/place/dashboard.html",
            )

    def test_written_manifest_key_order_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            manifest.write(vault, manifest.create_initial(
                vault_root=vault,
                mode="fresh",
                wiki_root="w/",
                user_context_root="c/",
                sb_os_path="s/",
                finance_dashboard_html_path=".user/finance/dashboard.html",
            ))
            data = json.loads((vault / manifest.MANIFEST_FILENAME).read_text(encoding="utf-8"))
            keys = list(data.keys())
            self.assertLess(
                keys.index("sb_os_path"), keys.index("finance_dashboard_html_path")
            )


class TestDashboardJsDataPaths(unittest.TestCase):
    """Guard the data-path reconciliation in the shipped dashboard JS.

    Data fetches must be vault-root-absolute under the fixed
    ``/.user/finance/bookkeeper`` contract (p1-3) — never relative to the
    entry HTML, whose location is configurable.
    """

    def _read(self, name: str) -> str:
        return (_REPO_ROOT / "finance" / "dashboard" / name).read_text(encoding="utf-8")

    def test_shared_defines_fin_data_base(self) -> None:
        self.assertIn(
            "const FIN_DATA_BASE = '/.user/finance/bookkeeper'",
            self._read("shared.js"),
        )

    def test_data_consumers_use_fin_data_base(self) -> None:
        for name in ("expenses.js", "inv-data.js", "inv-historico.js"):
            text = self._read(name)
            self.assertIn("FIN_DATA_BASE", text, msg=f"{name} ignores FIN_DATA_BASE")
            self.assertNotIn(
                "'./ledgers", text, msg=f"{name} still has a relative ledgers path"
            )
            self.assertNotIn(
                "`./ledgers", text, msg=f"{name} still has a relative ledgers path"
            )
            self.assertNotIn(
                "./config/", text, msg=f"{name} still has a relative config path"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
