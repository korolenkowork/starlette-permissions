from __future__ import annotations

import pytest

from starlette_permissions import (
    AND,
    NOT,
    OR,
    All,
    AllowAny,
    Any,
    BasePermission,
    DenyAll,
    HasRole,
    IsAdminUser,
    IsAuthenticated,
    IsOwner,
    Not,
    PermissionDenied,
    check_object_permissions,
    check_permissions,
    has_object_permissions,
    has_permissions,
)
from starlette_permissions.testing import make_context

from .conftest import User

ALLOW = AllowAny()
DENY = DenyAll()


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (ALLOW & ALLOW, True),
        (ALLOW & DENY, False),
        (DENY & ALLOW, False),
        (DENY | ALLOW, True),
        (DENY | DENY, False),
        (~DENY, True),
        (~ALLOW, False),
        (ALLOW & ALLOW & DENY, False),
        ((ALLOW | DENY) & ALLOW, True),
        (~(DENY | DENY), True),
    ],
)
async def test_truth_table(expression, expected):
    assert await has_permissions(expression, make_context()) is expected


async def test_operators_work_on_classes_not_just_instances():
    combined = IsAuthenticated & IsAdminUser
    assert isinstance(combined, AND)
    ctx = make_context(user=User(is_admin=True))
    assert await has_permissions(combined, ctx)


def test_reflected_operators():
    assert isinstance(AllowAny & DenyAll(), AND)
    assert isinstance(AllowAny() & DenyAll, AND)
    assert isinstance(AllowAny | DenyAll(), OR)
    assert isinstance(~AllowAny, NOT)


async def test_and_short_circuits():
    calls = []

    class Recording(BasePermission):
        def __init__(self, name, allowed):
            self.name = name
            self.allowed = allowed

        def has_permission(self, ctx):
            calls.append(self.name)
            return self.allowed

    await has_permissions(Recording("first", False) & Recording("second", True), make_context())
    assert calls == ["first"]


async def test_or_short_circuits():
    calls = []

    class Recording(BasePermission):
        def __init__(self, name, allowed):
            self.name = name
            self.allowed = allowed

        def has_permission(self, ctx):
            calls.append(self.name)
            return self.allowed

    await has_permissions(Recording("first", True) | Recording("second", True), make_context())
    assert calls == ["first"]


async def test_and_reports_the_failing_branch_message():
    ctx = make_context(user=User(roles=["editor"]))
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(IsAuthenticated & HasRole("admin"), ctx)
    assert exc_info.value.detail == "Requires role: admin"


async def test_or_reports_the_left_branch_when_both_fail():
    ctx = make_context(user=User())
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(HasRole("admin") | HasRole("editor"), ctx)
    assert exc_info.value.detail == "Requires role: admin"


async def test_not_reports_itself_with_a_custom_message():
    inverted = Not(AllowAny, message="Must not be allowed")
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(inverted, make_context())
    assert exc_info.value.detail == "Must not be allowed"


class TestHelpers:
    async def test_all_with_no_arguments_allows(self):
        assert await has_permissions(All(), make_context())

    async def test_any_with_no_arguments_denies(self):
        assert not await has_permissions(Any(), make_context())

    async def test_all_chains_every_permission(self):
        ctx = make_context(user=User(roles=["editor"], is_admin=True))
        assert await has_permissions(All(IsAuthenticated, IsAdminUser, HasRole("editor")), ctx)
        assert not await has_permissions(All(IsAuthenticated, HasRole("root")), ctx)

    async def test_any_needs_only_one(self):
        ctx = make_context(user=User(roles=["editor"]))
        assert await has_permissions(Any(IsAdminUser, HasRole("editor")), ctx)


class TestObjectLevelComposition:
    """Object-level checks must traverse combinators too, not just the top rule."""

    async def test_and_applies_object_rules_on_both_sides(self):
        ctx = make_context(user=User(id=1))
        combined = IsAuthenticated & IsOwner("owner_id")
        assert await has_object_permissions(combined, ctx, {"owner_id": 1})
        assert not await has_object_permissions(combined, ctx, {"owner_id": 2})

    async def test_or_allows_when_either_object_rule_passes(self):
        ctx = make_context(user=User(id=1, is_admin=True))
        combined = IsAdminUser | IsOwner("owner_id")
        assert await has_object_permissions(combined, ctx, {"owner_id": 999})

    async def test_not_inverts_object_rules(self):
        ctx = make_context(user=User(id=1))
        assert await has_object_permissions(~IsOwner("owner_id"), ctx, {"owner_id": 2})
        assert not await has_object_permissions(~IsOwner("owner_id"), ctx, {"owner_id": 1})

    async def test_request_level_rules_do_not_block_object_checks(self):
        """IsAuthenticated has no object rule, so it must not veto by default."""
        ctx = make_context(user=User(id=1))
        await check_object_permissions(IsAuthenticated, ctx, object())
