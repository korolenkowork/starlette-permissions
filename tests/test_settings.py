from __future__ import annotations

import pytest

from starlette_permissions import (
    IsAdminUser,
    IsAuthenticated,
    NotAuthenticated,
    PermissionSettings,
    check_permissions,
    configure,
    get_settings,
    has_permissions,
    override_settings,
)
from starlette_permissions.testing import make_context

from .conftest import User


def test_unknown_setting_is_rejected():
    with pytest.raises(TypeError, match="Unknown permission setting"):
        configure(user_gettter=lambda conn: None)


def test_override_settings_restores_the_previous_bundle():
    original = get_settings().denied_message
    with override_settings(denied_message="nope"):
        assert get_settings().denied_message == "nope"
    assert get_settings().denied_message == original


async def test_custom_user_getter():
    """The common case: a token on request.state rather than the ASGI scope."""
    configure(user_getter=lambda conn: getattr(conn.state, "token", None))

    ctx_with = make_context()
    ctx_with.connection.state.token = User()

    assert await has_permissions(IsAuthenticated, ctx_with)
    assert not await has_permissions(IsAuthenticated, make_context())


async def test_custom_admin_attrs():
    user = type("U", (), {"level": "root"})()
    configure(admin_attrs=("level",))
    assert await has_permissions(IsAdminUser, make_context(user=user))


async def test_custom_role_getter():
    user = type("U", (), {"permissions_list": ["editor"]})()
    configure(role_getter=lambda u: getattr(u, "permissions_list", ()))
    ctx = make_context(user=user)
    assert list(ctx.roles) == ["editor"]


async def test_unauthenticated_status_can_be_folded_into_403():
    """Some APIs would rather not tell anonymous callers that a route exists."""
    configure(unauthenticated_status_code=403, unauthenticated_message="Permission denied")
    with pytest.raises(NotAuthenticated) as exc_info:
        await check_permissions(IsAuthenticated, make_context())
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied"


async def test_www_authenticate_header_is_attached_when_configured():
    configure(authenticate_header='Bearer realm="api"')
    with pytest.raises(NotAuthenticated) as exc_info:
        await check_permissions(IsAuthenticated, make_context())
    assert exc_info.value.headers["WWW-Authenticate"] == 'Bearer realm="api"'


async def test_denied_headers_are_attached():
    configure(denied_headers={"X-Reason": "policy"})
    with pytest.raises(Exception) as exc_info:
        await check_permissions(IsAdminUser, make_context(user=User()))
    assert exc_info.value.headers["X-Reason"] == "policy"


async def test_per_app_settings_win_over_the_global_ones():
    class FakeState:
        permission_settings = PermissionSettings(admin_attrs=("chief",))

    class FakeApp:
        state = FakeState()

    user = type("U", (), {"chief": True})()
    ctx = make_context(user=user, app=FakeApp())
    assert await has_permissions(IsAdminUser, ctx)

    # The global bundle does not know about "chief".
    assert not await has_permissions(IsAdminUser, make_context(user=user))


async def test_explicit_settings_on_a_context_win():
    user = type("U", (), {"chief": True})()
    ctx = make_context(user=user, settings=PermissionSettings(admin_attrs=("chief",)))
    assert await has_permissions(IsAdminUser, ctx)


async def test_user_is_resolved_once_and_cached():
    calls = []

    def getter(conn):
        calls.append(1)
        return User()

    ctx = make_context(settings=PermissionSettings(user_getter=getter))
    assert ctx.user is ctx.user
    assert ctx.is_authenticated
    assert len(calls) == 1
