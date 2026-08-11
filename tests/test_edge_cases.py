"""Paths that are easy to get wrong and hard to notice."""

from __future__ import annotations

import pytest

from starlette_permissions import (
    AllowAny,
    BasePermission,
    DenyAll,
    IsAdminUser,
    IsOwner,
    PermissionDenied,
    check_object_permissions,
    has_object_permissions,
    resolve_permission,
)
from starlette_permissions.base import _DuckPermission
from starlette_permissions.compat import LegacyPermission
from starlette_permissions.testing import make_context

from .conftest import User


class TestObjectLevelModes:
    async def test_mode_any_needs_only_one_object_rule(self):
        ctx = make_context(user=User(id=1, is_admin=True))
        rules = [IsOwner("owner_id"), IsAdminUser]
        assert await has_object_permissions(rules, ctx, {"owner_id": 999}, mode="any")

    async def test_mode_any_reports_the_first_failure(self):
        ctx = make_context(user=User(id=1))
        rules = [IsOwner("owner_id"), DenyAll]
        with pytest.raises(PermissionDenied) as exc_info:
            await check_object_permissions(rules, ctx, {"owner_id": 2}, mode="any")
        assert isinstance(exc_info.value.permission, IsOwner)

    async def test_no_object_rules_allows(self):
        await check_object_permissions([], make_context(), object())


class TestResolutionOfLooseObjects:
    def test_a_duck_typed_class_is_instantiated_and_adapted(self):
        class Custom:
            def has_permission(self, ctx):
                return True

        resolved = resolve_permission(Custom)
        assert isinstance(resolved, _DuckPermission)

    async def test_a_duck_typed_object_without_object_rules_allows(self):
        class Custom:
            def has_permission(self, ctx):
                return True

        resolved = resolve_permission(Custom())
        assert await has_object_permissions(resolved, make_context(), object())

    async def test_a_duck_typed_object_may_define_object_rules(self):
        class Custom:
            def has_permission(self, ctx):
                return True

            def has_object_permission(self, ctx, obj):
                return obj == "allowed"

        resolved = resolve_permission(Custom())
        ctx = make_context()
        assert await has_object_permissions(resolved, ctx, "allowed")
        assert not await has_object_permissions(resolved, ctx, "denied")

    def test_a_legacy_class_is_adapted(self):
        class Legacy:
            @staticmethod
            async def is_permitted(request, *args, **kwargs):
                return True

        assert isinstance(resolve_permission(Legacy), LegacyPermission)

    def test_repr_is_readable_for_every_wrapper(self):
        class Legacy:
            @staticmethod
            async def is_permitted(request, *args, **kwargs):
                return True

        assert repr(resolve_permission(Legacy)) == "LegacyPermission(Legacy)"
        assert repr(AllowAny()) == "AllowAny()"
        assert repr(IsOwner("author_id")) == "IsOwner('author_id')"
        assert repr(AllowAny() & DenyAll()) == "(AllowAny() & DenyAll())"
        assert repr(~AllowAny()) == "~AllowAny()"


class TestReflectedOperators:
    """`__rand__` / `__ror__`, which fire when the left operand is not a permission."""

    async def test_a_function_on_the_left_still_composes(self):
        """`fn & Permission`: a function has no __and__, so __rand__ fires."""
        combined = (lambda ctx: True) & AllowAny
        assert await has_object_permissions(combined, make_context(), object())

    def test_reflected_operators_build_the_right_shape(self):
        from starlette_permissions.operators import AND, OR

        # A plain function on the left, reaching the metaclass and the
        # instance implementations respectively.
        def predicate(ctx):
            return True

        assert isinstance(predicate & AllowAny, AND)
        assert isinstance(predicate | AllowAny, OR)
        assert isinstance(predicate & AllowAny(), AND)
        assert isinstance(predicate | AllowAny(), OR)


class TestContextEdges:
    def test_websocket_scope_is_recognised(self):
        ctx = make_context()
        # A real WebSocket scope carries no method at all.
        ctx.connection.scope["type"] = "websocket"
        del ctx.connection.scope["method"]
        assert ctx.is_websocket
        assert ctx.method == ""
        assert not ctx.is_safe_method

    def test_repr_does_not_explode_on_an_anonymous_request(self):
        assert "user=None" in repr(make_context())

    def test_path_params_are_exposed(self):
        ctx = make_context(path_params={"post_id": 7})
        assert ctx.path_params == {"post_id": 7}
        assert ctx.view_kwargs == {"post_id": 7}


class TestDenialDetails:
    async def test_the_failing_permission_is_attached_for_logging(self):
        class Custom(BasePermission):
            message = "nope"

            def has_permission(self, ctx):
                return False

        with pytest.raises(PermissionDenied) as exc_info:
            await check_object_permissions(DenyAll, make_context(), object())
        assert isinstance(exc_info.value.permission, DenyAll)

        rule = Custom()
        denial = rule.denial(make_context())
        assert denial.permission is rule
        assert denial.detail == "nope"

    def test_denial_works_without_a_context(self):
        """Permissions can be evaluated outside a request, e.g. in a unit test."""
        denial = DenyAll().denial()
        assert denial.status_code == 403
