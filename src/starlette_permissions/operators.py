"""Boolean combinators: ``&``, ``|``, ``~`` and the ``All``/``Any`` helpers.

Combinators are permissions themselves, so they nest freely::

    IsAuthenticated & (IsAdminUser | IsOwner("user_id")) & ~IsBanned
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette_permissions.base import (
    BasePermission,
    PermissionLike,
    PermissionResult,
    resolve_permission,
    resolve_permissions,
)

if TYPE_CHECKING:
    from starlette_permissions.context import PermissionContext

__all__ = ["AND", "NOT", "OR", "All", "Any_", "Not"]


class _Binary(BasePermission):
    """Shared plumbing for two-sided operators."""

    symbol = "?"

    def __init__(self, left: PermissionLike, right: PermissionLike) -> None:
        self.left = resolve_permission(left)
        self.right = resolve_permission(right)

    def __repr__(self) -> str:
        return f"({self.left!r} {self.symbol} {self.right!r})"


class AND(_Binary):
    """Both sides must allow. Short-circuits on the first refusal."""

    symbol = "&"

    async def evaluate(self, ctx: PermissionContext) -> PermissionResult:
        result = await self.left.evaluate(ctx)
        if not result.allowed:
            return result
        return await self.right.evaluate(ctx)

    async def evaluate_object(self, ctx: PermissionContext, obj: Any) -> PermissionResult:
        result = await self.left.evaluate_object(ctx, obj)
        if not result.allowed:
            return result
        return await self.right.evaluate_object(ctx, obj)


class OR(_Binary):
    """Either side may allow.

    When both refuse, the failure is reported as the *left* side's — the rule
    written first, which is normally the broader one. This keeps the message a
    caller sees stable no matter which branch was evaluated last.
    """

    symbol = "|"

    async def evaluate(self, ctx: PermissionContext) -> PermissionResult:
        left = await self.left.evaluate(ctx)
        if left.allowed:
            return left
        right = await self.right.evaluate(ctx)
        if right.allowed:
            return right
        return left

    async def evaluate_object(self, ctx: PermissionContext, obj: Any) -> PermissionResult:
        left = await self.left.evaluate_object(ctx, obj)
        if left.allowed:
            return left
        right = await self.right.evaluate_object(ctx, obj)
        if right.allowed:
            return right
        return left


class NOT(BasePermission):
    """Inverts a permission.

    The wrapped rule's message would be misleading here (it explains why it
    *allows*), so the refusal is reported against the ``NOT`` itself.
    """

    def __init__(self, permission: PermissionLike, *, message: str | None = None) -> None:
        self.permission = resolve_permission(permission)
        if message is not None:
            self.message = message

    async def evaluate(self, ctx: PermissionContext) -> PermissionResult:
        result = await self.permission.evaluate(ctx)
        return PermissionResult(not result.allowed, None if not result.allowed else self)

    async def evaluate_object(self, ctx: PermissionContext, obj: Any) -> PermissionResult:
        result = await self.permission.evaluate_object(ctx, obj)
        return PermissionResult(not result.allowed, None if not result.allowed else self)

    def __repr__(self) -> str:
        return f"~{self.permission!r}"


def All(*permissions: PermissionLike) -> BasePermission:  # noqa: N802 - reads as a rule name
    """Require every permission. The explicit form of chained ``&``.

    ``All()`` with no arguments allows everything, matching ``all([])``.
    """
    resolved = resolve_permissions(list(permissions))
    if not resolved:
        from starlette_permissions.permissions.common import AllowAny

        return AllowAny()
    combined = resolved[0]
    for permission in resolved[1:]:
        combined = AND(combined, permission)
    return combined


def Any_(*permissions: PermissionLike) -> BasePermission:  # noqa: N802 - reads as a rule name
    """Require at least one permission. The explicit form of chained ``|``.

    Exported as ``Any`` from the package root; the trailing underscore here
    only keeps it from shadowing ``typing.Any`` inside this module.

    ``Any_()`` with no arguments denies everything, matching ``any([])``.
    """
    resolved = resolve_permissions(list(permissions))
    if not resolved:
        from starlette_permissions.permissions.common import DenyAll

        return DenyAll()
    combined = resolved[0]
    for permission in resolved[1:]:
        combined = OR(combined, permission)
    return combined


def Not(permission: PermissionLike, *, message: str | None = None) -> BasePermission:  # noqa: N802
    """Invert a permission. The explicit form of ``~``."""
    return NOT(permission, message=message)
