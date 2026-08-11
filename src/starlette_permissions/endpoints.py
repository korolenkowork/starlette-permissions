"""Class-based enforcement for Starlette's ``HTTPEndpoint``.

```python
class PostEndpoint(PermissionMixin, HTTPEndpoint):
    permission_classes = [IsAuthenticated]

    async def get(self, request): ...
    async def delete(self, request): ...
```

Per-method rules are supported too, which is usually what you want once read
and write differ:

```python
class PostEndpoint(PermissionMixin, HTTPEndpoint):
    permission_classes = {
        "*": IsAuthenticated,
        "DELETE": IsAdminUser,
    }
```
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from starlette.requests import Request

from starlette_permissions.base import resolve_permissions
from starlette_permissions.checks import check_permissions
from starlette_permissions.context import PermissionContext

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from starlette_permissions.base import BasePermission, PermissionLike
    from starlette_permissions.checks import Mode

__all__ = ["PermissionMixin"]

#: Key used for rules that apply to every method not listed explicitly.
ANY_METHOD = "*"


class PermissionMixin:
    """Checks ``permission_classes`` before dispatching to the handler.

    Must come *before* ``HTTPEndpoint`` in the base list, so that its
    ``dispatch`` runs first.
    """

    #: A permission, a list of them, or a ``{method: permissions}`` mapping.
    permission_classes: ClassVar[Any] = ()
    #: ``"all"`` (default) or ``"any"``.
    permission_mode: ClassVar[Mode] = "all"

    @classmethod
    def get_permissions(cls, method: str) -> tuple[BasePermission, ...]:
        """Resolve the permissions applying to ``method``.

        A mapping combines the wildcard entry with the method-specific one, so
        ``{"*": IsAuthenticated, "DELETE": IsAdminUser}`` requires both on
        DELETE rather than replacing one with the other.
        """
        declared = cls.permission_classes
        if isinstance(declared, dict):
            mapping: Mapping[str, PermissionLike | Sequence[PermissionLike]] = declared
            applicable: list[Any] = []
            if ANY_METHOD in mapping:
                applicable.append(mapping[ANY_METHOD])
            if method in mapping:
                applicable.append(mapping[method])
            return resolve_permissions(applicable)
        return resolve_permissions(declared)

    async def dispatch(self) -> None:
        request = Request(self.scope, receive=self.receive)  # type: ignore[attr-defined]
        permissions = self.get_permissions(request.method.upper())
        if permissions:
            ctx = PermissionContext(
                request,
                endpoint=type(self),
                view_kwargs=request.path_params,
            )
            await check_permissions(permissions, ctx, mode=self.permission_mode)
        await super().dispatch()  # type: ignore[misc]
