"""The evaluation entry points.

Everything else in the library — the decorator, the dependency, the mixin, the
middleware — funnels into :func:`check_permissions`. You can also call these
directly from a service layer, where there is no HTTP handler to decorate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from starlette_permissions.base import resolve_permissions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette_permissions.base import BasePermission, PermissionLike
    from starlette_permissions.context import PermissionContext

__all__ = [
    "Mode",
    "check_object_permissions",
    "check_permissions",
    "has_object_permissions",
    "has_permissions",
]

#: ``"all"`` requires every permission (the default, matching Django/DRF);
#: ``"any"`` requires at least one.
Mode = Literal["all", "any"]


async def _evaluate(
    permissions: Sequence[BasePermission],
    ctx: PermissionContext,
    mode: Mode,
) -> BasePermission | None:
    """Return the permission that refused, or ``None`` if the request passes."""
    if not permissions:
        return None

    if mode == "all":
        for permission in permissions:
            result = await permission.evaluate(ctx)
            if not result.allowed:
                return result.denied_by or permission
        return None

    first_failure: BasePermission | None = None
    for permission in permissions:
        result = await permission.evaluate(ctx)
        if result.allowed:
            return None
        if first_failure is None:
            first_failure = result.denied_by or permission
    return first_failure


async def _evaluate_object(
    permissions: Sequence[BasePermission],
    ctx: PermissionContext,
    obj: Any,
    mode: Mode,
) -> BasePermission | None:
    if not permissions:
        return None

    if mode == "all":
        for permission in permissions:
            result = await permission.evaluate_object(ctx, obj)
            if not result.allowed:
                return result.denied_by or permission
        return None

    first_failure: BasePermission | None = None
    for permission in permissions:
        result = await permission.evaluate_object(ctx, obj)
        if result.allowed:
            return None
        if first_failure is None:
            first_failure = result.denied_by or permission
    return first_failure


async def check_permissions(
    permissions: PermissionLike | Sequence[PermissionLike],
    ctx: PermissionContext,
    *,
    mode: Mode = "all",
) -> None:
    """Evaluate ``permissions`` and raise if the request is not allowed.

    Raises:
        PermissionDenied: with the message and status code of the rule that
            refused. ``NotAuthenticated`` (401) is a subclass of it.
    """
    resolved = resolve_permissions(permissions)
    denied_by = await _evaluate(resolved, ctx, mode)
    if denied_by is not None:
        raise denied_by.denial(ctx)


async def has_permissions(
    permissions: PermissionLike | Sequence[PermissionLike],
    ctx: PermissionContext,
    *,
    mode: Mode = "all",
) -> bool:
    """Non-raising variant of :func:`check_permissions`.

    Handy for branching in a template or trimming a response, where a denial
    should hide a field rather than fail the request.
    """
    resolved = resolve_permissions(permissions)
    return await _evaluate(resolved, ctx, mode) is None


async def check_object_permissions(
    permissions: PermissionLike | Sequence[PermissionLike],
    ctx: PermissionContext,
    obj: Any,
    *,
    mode: Mode = "all",
) -> None:
    """Run object-level checks against ``obj``, raising on refusal.

    Call this once you have loaded the record — that is the earliest point at
    which a rule like "you may only edit your own posts" can be decided.
    """
    resolved = resolve_permissions(permissions)
    denied_by = await _evaluate_object(resolved, ctx, obj, mode)
    if denied_by is not None:
        raise denied_by.denial(ctx)


async def has_object_permissions(
    permissions: PermissionLike | Sequence[PermissionLike],
    ctx: PermissionContext,
    obj: Any,
    *,
    mode: Mode = "all",
) -> bool:
    """Non-raising variant of :func:`check_object_permissions`."""
    resolved = resolve_permissions(permissions)
    return await _evaluate_object(resolved, ctx, obj, mode) is None
