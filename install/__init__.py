"""sb-os installer package.

Importable as ``install`` from the sb-os repo root. The sibling ``install.py``
is the runnable entry point; this package holds the implementation modules
(`cli`, `fresh`, `upgrade`, `loaders`, `manifest`, `markers`).

The empty ``__init__.py`` is required to make Python prefer this package
over ``install.py`` when resolving ``import install``.
"""
