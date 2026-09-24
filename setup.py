"""Compatibility for tooling that still invokes setup.py; metadata lives in pyproject.toml."""

raise SystemExit("Use python -m pip install . or python -m build (see pyproject.toml).")
