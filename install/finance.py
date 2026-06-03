"""Finance module install step — render the dashboard entry HTML.

The finance module ships the dashboard as code under
``{sb_os_path}/finance/dashboard/`` plus a single entry-HTML *template*
(``dashboard.html.template``). At install time the template is rendered to
the user-chosen ``finance_dashboard_html_path`` (default
``.user/finance/dashboard.html``, persisted in ``sb-os.json``) so the
dashboard server — which serves the vault root as docroot — loads every
asset with zero 404s regardless of where the sb-os repo or the entry HTML
lives.

Path model (p1-3; architecture §11):

* **Asset (CSS/JS) base** — install-specific. Derived from ``sb_os_path``
  as ``/{sb_os_path}/finance/dashboard`` and substituted into the
  template's ``{{DASHBOARD_ASSET_BASE}}`` placeholder here.
* **Data (ledgers/config) base** — fixed by the finance contract at
  ``/.user/finance/bookkeeper`` and hardcoded in the dashboard JS
  (``shared.js`` ``FIN_DATA_BASE``). Not install-specific, so never
  substituted.

Install-if-missing: the entry HTML is rendered on fresh install and, on
upgrade, only when the target file does not already exist — a user who
moved or hand-edited it is never clobbered (mirrors the template
semantics in ``loaders.install_template_if_missing``).

Pure stdlib (pathlib).
"""
from __future__ import annotations

from pathlib import Path

DASHBOARD_TEMPLATE_REL = "finance/dashboard/dashboard.html.template"
ASSET_BASE_PLACEHOLDER = "{{DASHBOARD_ASSET_BASE}}"


def dashboard_asset_base(sb_os_path: str | Path) -> str:
    """Return the vault-root-absolute base URL for the dashboard CSS/JS.

    ``sb_os_path`` is the vault-relative sb-os clone location (e.g.
    ``3-resources/tools/sb-os``). The dashboard server serves the vault
    root as docroot, so the asset base is that path made root-absolute
    with the module's ``finance/dashboard`` suffix. No trailing slash —
    the template joins ``{base}/styles.css`` etc. Normalization mirrors
    ``loaders._normalize_sb_os_path`` (POSIX separators, stripped slashes)
    so asset URLs and loader paths derive from ``sb_os_path`` identically.
    """
    base = str(sb_os_path).replace("\\", "/").strip("/")
    if not base:
        raise ValueError("sb_os_path must be a non-empty path")
    return f"/{base}/finance/dashboard"


def render_dashboard_html(template_text: str, sb_os_path: str | Path) -> str:
    """Render the entry HTML by substituting the asset base placeholder.

    Only the asset base is install-specific. Data-fetch paths are fixed
    vault-root-absolute constants baked into the dashboard JS (see module
    docstring) — identical for every install, so nothing else is rendered.
    """
    return template_text.replace(
        ASSET_BASE_PLACEHOLDER, dashboard_asset_base(sb_os_path)
    )


def install_dashboard_if_missing(
    target_root: Path | str,
    sb_os_root: Path | str,
    sb_os_path: str | Path,
    html_path: str,
) -> Path | None:
    """Render the entry HTML to ``html_path`` if it does not already exist.

    ``html_path`` is the vault-relative ``finance_dashboard_html_path``
    (callers resolve it from the prompt / ``sb-os.json``). Returns the
    written path on render, or ``None`` when the target already exists
    (no-op — install-if-missing preserves a user-placed/edited file).
    Raises ``FileNotFoundError`` when the template source is missing (a
    broken sb-os checkout).
    """
    src = Path(sb_os_root) / DASHBOARD_TEMPLATE_REL
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os dashboard template missing: {src}. Re-clone the sb-os repo."
        )
    dst = Path(target_root) / html_path
    if dst.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_dashboard_html(src.read_text(encoding="utf-8"), sb_os_path)
    dst.write_text(rendered, encoding="utf-8")
    return dst


__all__ = [
    "DASHBOARD_TEMPLATE_REL",
    "ASSET_BASE_PLACEHOLDER",
    "dashboard_asset_base",
    "render_dashboard_html",
    "install_dashboard_if_missing",
]
