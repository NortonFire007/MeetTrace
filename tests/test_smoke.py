"""Smoke test to verify project setup and package import."""

import meettrace


def test_import_and_version() -> None:
    """Check that the meettrace package is importable and exposes version."""
    assert meettrace.__version__ == "0.1.0"
