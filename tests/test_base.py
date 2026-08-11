from __future__ import annotations

import pytest

from starlette_permissions import (
    AllowAny,
    BasePermission,
    ConfigurationError,
    DenyAll,
    HasRole,
    IsAuthenticated,
    PermissionDenied,
    check_permissions,
    has_permissions,
    resolve_permission,
    resolve_permissions,
)
from starlette_permissions.base import _DuckPermission
from starlette_permissions.testing import make_context

from .conftest import User


class SyncPermission(BasePermission):
    message = "sync denied"

    def has_permission(self, ctx):
        return ctx.method == "GET"


class AsyncPermission(BasePermission):
    message = "async denied"

    async def has_permission(self, ctx):
        return ctx.method == "GET"


@pytest.mark.parametrize("cls", [SyncPermission, AsyncPermission])
async def test_sync_and_async_has_permission_both_work(cls):
    assert await has_permissions(cls, make_context(method="GET"))
    assert not await has_permissions(cls, make_context(method="POST"))


async def test_check_permissions_raises_with_the_failing_message():
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(SyncPermission, make_context(method="POST"))
    assert exc_info.value.detail == "sync denied"
    assert exc_info.value.status_code == 403
    assert isinstance(exc_info.value.permission, SyncPermission)


async def test_empty_permission_list_allows():
    assert await has_permissions([], make_context())
    await check_permissions([], make_context())


async def test_mode_all_requires_every_permission():
    ctx = make_context(user=User(roles=["editor"]))
    assert not await has_permissions([IsAuthenticated, HasRole("admin")], ctx)
    assert await has_permissions([IsAuthenticated, HasRole("editor")], ctx)


async def test_mode_any_requires_only_one():
    ctx = make_context(user=User(roles=["editor"]))
    assert await has_permissions([HasRole("admin"), HasRole("editor")], ctx, mode="any")
    assert not await has_permissions([HasRole("admin"), HasRole("root")], ctx, mode="any")


async def test_mode_any_reports_the_first_failure():
    ctx = make_context(user=User())
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions([HasRole("admin"), HasRole("root")], ctx, mode="any")
    assert exc_info.value.detail == "Requires role: admin"


class TestResolution:
    def test_class_is_instantiated(self):
        assert isinstance(resolve_permission(AllowAny), AllowAny)

    def test_instance_passes_through(self):
        instance = AllowAny()
        assert resolve_permission(instance) is instance

    def test_nested_lists_are_flattened(self):
        resolved = resolve_permissions([AllowAny, [DenyAll, (IsAuthenticated,)]])
        assert len(resolved) == 3
        assert isinstance(resolved[1], DenyAll)

    def test_none_resolves_to_empty(self):
        assert resolve_permissions(None) == ()

    def test_plain_function_becomes_a_predicate(self):
        resolved = resolve_permission(lambda ctx: True)
        assert resolved.has_permission(make_context()) is True

    def test_duck_typed_object_is_adapted(self):
        class Custom:
            message = "nope"

            def has_permission(self, ctx):
                return False

        resolved = resolve_permission(Custom())
        assert isinstance(resolved, _DuckPermission)
        assert resolved.message == "nope"

    def test_class_needing_arguments_gives_an_actionable_error(self):
        with pytest.raises(ConfigurationError, match=r"Pass an instance.*HasAnyRole\(\.\.\.\)"):
            resolve_permission(HasRole)

    def test_unusable_value_is_rejected(self):
        with pytest.raises(ConfigurationError, match="Cannot use"):
            resolve_permission(42)


async def test_permission_may_override_status_code():
    class Teapot(BasePermission):
        message = "I am a teapot"
        status_code = 418

        def has_permission(self, ctx):
            return False

    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(Teapot, make_context())
    assert exc_info.value.status_code == 418
