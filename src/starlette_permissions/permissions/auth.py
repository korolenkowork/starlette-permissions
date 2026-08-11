"""Identity-based permissions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette_permissions.base import BasePermission
from starlette_permissions.exceptions import NotAuthenticated

if TYPE_CHECKING:
    from starlette_permissions.context import PermissionContext
    from starlette_permissions.exceptions import PermissionDenied

__all__ = [
    "IsAdminUser",
    "IsAnonymous",
    "IsAuthenticated",
    "IsAuthenticatedOrReadOnly",
]


class IsAuthenticated(BasePermission):
    """Requires a user on the request.

    Refuses with 401 rather than 403, since the caller can fix this by
    authenticating. Set ``unauthenticated_status_code=403`` in
    :func:`~starlette_permissions.configure` if you would rather not
    distinguish the two.
    """

    exception_class = NotAuthenticated

    def has_permission(self, ctx: PermissionContext) -> bool:
        return ctx.is_authenticated

    def denial(self, ctx: PermissionContext | None = None) -> PermissionDenied:
        settings = ctx.settings if ctx is not None else None
        if settings is None:
            return super().denial(ctx)
        headers = dict(settings.denied_headers)
        if settings.authenticate_header:
            headers["WWW-Authenticate"] = settings.authenticate_header
        return NotAuthenticated(
            settings.unauthenticated_message,
            status_code=settings.unauthenticated_status_code,
            headers=headers or None,
            permission=self,
        )


class IsAnonymous(BasePermission):
    """Requires that no user is attached. For login and signup routes."""

    message = "Already authenticated"

    def has_permission(self, ctx: PermissionContext) -> bool:
        return not ctx.is_authenticated


class IsAdminUser(BasePermission):
    """Requires an authenticated user flagged as an administrator.

    Checks each of ``settings.admin_attrs`` in turn — by default
    ``is_admin``, ``is_staff``, ``is_superuser`` — and allows if any is truthy.
    """

    message = "Administrator access required"

    def has_permission(self, ctx: PermissionContext) -> bool:
        if not ctx.is_authenticated:
            return False
        user = ctx.user
        return any(getattr(user, attr, False) for attr in ctx.settings.admin_attrs)


class IsAuthenticatedOrReadOnly(BasePermission):
    """Anyone may read; only authenticated users may write."""

    exception_class = NotAuthenticated
    message = "Authentication required for write operations"

    def has_permission(self, ctx: PermissionContext) -> bool:
        return ctx.is_safe_method or ctx.is_authenticated
