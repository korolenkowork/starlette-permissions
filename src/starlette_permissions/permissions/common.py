"""Permissions that depend only on the request, not on who is making it."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from starlette_permissions.base import BasePermission

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

    from starlette_permissions.context import PermissionContext

__all__ = [
    "AllowAny",
    "DenyAll",
    "HasHeader",
    "IsMethod",
    "Predicate",
    "ReadOnly",
    "permission",
]


class AllowAny(BasePermission):
    """Allows everything. Useful as an explicit "this endpoint is public" marker."""

    def has_permission(self, ctx: PermissionContext) -> bool:
        return True


class DenyAll(BasePermission):
    """Refuses everything. Handy for disabling a route without deleting it."""

    message = "This endpoint is not available"

    def has_permission(self, ctx: PermissionContext) -> bool:
        return False

    def has_object_permission(self, ctx: PermissionContext, obj: Any) -> bool:
        return False


class ReadOnly(BasePermission):
    """Allows only GET, HEAD and OPTIONS.

    Usually combined: ``ReadOnly | IsAdminUser`` gives everyone read access and
    admins write access.
    """

    message = "This endpoint is read-only"

    def has_permission(self, ctx: PermissionContext) -> bool:
        return ctx.is_safe_method


class IsMethod(BasePermission):
    """Allows only the listed HTTP methods."""

    def __init__(self, *methods: str) -> None:
        self.methods = frozenset(method.upper() for method in methods)
        self.message = f"Allowed methods: {', '.join(sorted(self.methods))}"

    def has_permission(self, ctx: PermissionContext) -> bool:
        return ctx.method in self.methods

    def __repr__(self) -> str:
        return f"IsMethod({', '.join(sorted(self.methods))})"


class Predicate(BasePermission):
    """Wraps a plain function as a permission.

    The function takes the context and returns a bool; it may be async. This is
    what makes bare functions usable anywhere a permission is expected:

    ```python
    permission_required(lambda ctx: ctx.headers.get("x-tenant") == "acme")
    ```
    """

    def __init__(
        self,
        func: Callable[[PermissionContext], bool | Awaitable[bool]],
        *,
        message: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.func = func
        docstring = getattr(func, "__doc__", None)
        if message is not None:
            self.message = message
        elif docstring:
            # A one-line docstring makes a serviceable refusal message, and
            # saves declaring the same sentence twice.
            self.message = inspect.cleandoc(docstring).splitlines()[0]
        self.status_code = status_code

    def has_permission(self, ctx: PermissionContext) -> bool | Awaitable[bool]:
        return self.func(ctx)

    def __repr__(self) -> str:
        return f"Predicate({getattr(self.func, '__name__', self.func)!r})"


def permission(
    func: Callable[[PermissionContext], bool | Awaitable[bool]] | None = None,
    *,
    message: str | None = None,
    status_code: int | None = None,
) -> Any:
    """Turn a function into a permission, with or without arguments.

    ```python
    @permission(message="Requests must come from the office network")
    def from_office(ctx):
        return ctx.connection.client.host.startswith("10.")
    ```
    """

    def wrap(target: Callable[[PermissionContext], bool | Awaitable[bool]]) -> Predicate:
        return Predicate(target, message=message, status_code=status_code)

    if func is not None:
        return wrap(func)
    return wrap


class HasHeader(BasePermission):
    """Requires a header to be present, and optionally to hold a given value."""

    def __init__(
        self,
        header: str,
        value: str | Collection[str] | None = None,
        *,
        message: str | None = None,
    ) -> None:
        self.header = header.lower()
        if value is None:
            self.values: frozenset[str] | None = None
        elif isinstance(value, str):
            self.values = frozenset({value})
        else:
            self.values = frozenset(value)
        self.message = message or f"Missing or invalid {header} header"

    def has_permission(self, ctx: PermissionContext) -> bool:
        present = ctx.headers.get(self.header)
        if present is None:
            return False
        return self.values is None or present in self.values

    def __repr__(self) -> str:
        return f"HasHeader({self.header!r})"
