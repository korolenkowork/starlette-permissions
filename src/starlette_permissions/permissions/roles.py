"""Role- and scope-based permissions.

Roles come from ``settings.role_getter``, which by default reads ``roles``,
``groups`` or ``role`` off the user object. Scopes come from
``settings.scope_getter``, which by default reads Starlette's
``AuthenticationMiddleware`` credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette_permissions.base import BasePermission

if TYPE_CHECKING:
    from starlette_permissions.context import PermissionContext

__all__ = [
    "HasAllRoles",
    "HasAllScopes",
    "HasAnyRole",
    "HasAnyScope",
    "HasRole",
    "HasScope",
]


class _RoleBase(BasePermission):
    require_all = False
    noun = "role"

    def __init__(self, *names: str, message: str | None = None) -> None:
        if not names:
            msg = f"At least one {self.noun} must be given"
            raise ValueError(msg)
        self.names = frozenset(names)
        joiner = " and " if self.require_all else " or "
        self.message = message or (f"Requires {self.noun}: {joiner.join(sorted(self.names))}")

    def _available(self, ctx: PermissionContext) -> frozenset[str]:
        raise NotImplementedError

    def has_permission(self, ctx: PermissionContext) -> bool:
        available = self._available(ctx)
        if self.require_all:
            return self.names <= available
        return bool(self.names & available)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(sorted(self.names))})"


class HasAnyRole(_RoleBase):
    """Requires at least one of the given roles."""

    require_all = False
    noun = "role"

    def _available(self, ctx: PermissionContext) -> frozenset[str]:
        return frozenset(ctx.roles)


class HasAllRoles(_RoleBase):
    """Requires every one of the given roles."""

    require_all = True
    noun = "role"

    def _available(self, ctx: PermissionContext) -> frozenset[str]:
        return frozenset(ctx.roles)


class HasAnyScope(_RoleBase):
    """Requires at least one of the given OAuth-style scopes."""

    require_all = False
    noun = "scope"

    def _available(self, ctx: PermissionContext) -> frozenset[str]:
        return frozenset(ctx.scopes)


class HasAllScopes(_RoleBase):
    """Requires every one of the given OAuth-style scopes."""

    require_all = True
    noun = "scope"

    def _available(self, ctx: PermissionContext) -> frozenset[str]:
        return frozenset(ctx.scopes)


#: ``HasRole("admin")`` reads better than ``HasAnyRole("admin")`` for the
#: common single-role case; with several names it means "any of these".
HasRole = HasAnyRole
#: Likewise for scopes.
HasScope = HasAnyScope
