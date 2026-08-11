from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from starlette_permissions import PermissionSettings, configure


@dataclass
class User:
    id: int = 1
    name: str = "ihor"
    roles: list[str] = field(default_factory=list)
    is_admin: bool = False


@pytest.fixture(autouse=True)
def _reset_settings():
    """Keep global configure() calls from leaking between tests."""
    import starlette_permissions.settings as settings_module

    original = settings_module._settings
    yield
    settings_module._settings = original


@pytest.fixture
def user():
    return User()


@pytest.fixture
def admin():
    return User(id=2, name="root", roles=["admin"], is_admin=True)


@pytest.fixture
def state_user_settings():
    """Resolve the user from ``request.state.user`` instead of the ASGI scope."""

    def getter(conn):
        return getattr(conn.state, "user", None)

    return configure(user_getter=getter)


def make_settings(**kwargs) -> PermissionSettings:
    return PermissionSettings(**kwargs)
