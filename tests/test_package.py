"""The shape of the public API itself."""

from __future__ import annotations

import subprocess
import sys

import pytest

import starlette_permissions as sp


def test_everything_in_dunder_all_is_importable():
    missing = [name for name in sp.__all__ if not hasattr(sp, name)]
    assert missing == []


def test_fastapi_helpers_resolve_lazily():
    """They are not imported eagerly, so Starlette-only users never need FastAPI."""
    assert sp.requires is not None
    assert sp.requires_object is not None
    assert sp.PermissionChecker is not None
    assert sp.permission_responses is not None


def test_unknown_attribute_still_raises_attribute_error():
    with pytest.raises(AttributeError, match="has no attribute 'nope'"):
        _ = sp.nope


def test_core_modules_do_not_import_fastapi():
    """The load-bearing claim behind 'FastAPI is optional'.

    Run in a subprocess: reloading the package in-process would orphan the
    settings singleton that every other test holds a reference to.
    """
    script = (
        "import starlette_permissions, sys; "
        "assert 'fastapi' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_version_is_exposed():
    assert sp.__version__.count(".") == 2


def test_any_and_all_are_both_exported():
    assert sp.Any is sp.Any_permission
    assert callable(sp.All)
