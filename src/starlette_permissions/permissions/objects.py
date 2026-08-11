"""Object-level permissions — rules that need the record, not just the request.

These only take effect through :func:`~starlette_permissions.check_object_permissions`,
``@object_permission_required`` or ``requires_object``. A request-level check
cannot decide "you may edit your own post" before the post has been loaded, so
``has_permission`` on these classes deliberately allows everything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette_permissions.base import BasePermission
from starlette_permissions.settings import SAFE_METHODS

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette_permissions.context import PermissionContext

__all__ = ["IsOwner", "IsOwnerOrReadOnly", "ObjectPermission"]

_MISSING = object()


class ObjectPermission(BasePermission):
    """Base for rules that apply only once an object is available."""

    def has_permission(self, ctx: PermissionContext) -> bool:
        return True

    def has_object_permission(self, ctx: PermissionContext, obj: Any) -> bool:
        raise NotImplementedError


def _default_user_id(user: Any) -> Any:
    for attr in ("id", "pk", "uuid", "user_id"):
        value = getattr(user, attr, _MISSING)
        if value is not _MISSING:
            return value
    return user


class IsOwner(ObjectPermission):
    """Allows access only to the object's owner.

    Args:
        owner_field: Attribute (or dict key) on the object holding the owner's
            identifier. Defaults to ``user_id``.
        user_id: How to get the comparable identifier from the current user.
            Defaults to the first of ``id``, ``pk``, ``uuid``, ``user_id`` that
            exists, falling back to the user object itself.
        message: Overrides the refusal message.

    ```python
    await check_object_permissions(IsOwner("author_id"), ctx, post)
    ```
    """

    message = "You do not have access to this object"

    def __init__(
        self,
        owner_field: str = "user_id",
        *,
        user_id: Callable[[Any], Any] = _default_user_id,
        message: str | None = None,
    ) -> None:
        self.owner_field = owner_field
        self.user_id = user_id
        if message is not None:
            self.message = message

    def _owner_of(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return obj.get(self.owner_field, _MISSING)
        return getattr(obj, self.owner_field, _MISSING)

    def has_object_permission(self, ctx: PermissionContext, obj: Any) -> bool:
        if not ctx.is_authenticated:
            return False
        owner = self._owner_of(obj)
        if owner is _MISSING:
            # An object with no owner field is a programming error, not an
            # access decision — refusing loudly beats allowing silently.
            msg = (
                f"{type(obj).__name__} has no {self.owner_field!r} attribute, so "
                f"{type(self).__name__} cannot determine its owner"
            )
            raise AttributeError(msg)
        return bool(owner == self.user_id(ctx.user))

    def __repr__(self) -> str:
        return f"IsOwner({self.owner_field!r})"


class IsOwnerOrReadOnly(IsOwner):
    """Anyone may read the object; only its owner may modify it."""

    message = "Only the owner may modify this object"

    def has_object_permission(self, ctx: PermissionContext, obj: Any) -> bool:
        if ctx.method in SAFE_METHODS:
            return True
        return super().has_object_permission(ctx, obj)
