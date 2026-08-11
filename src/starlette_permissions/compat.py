"""Drop-in replacement for a hand-rolled ``permission_required``.

This exists so an existing codebase can adopt the library with an import swap
and migrate afterwards, one module at a time. It reproduces the older
behaviour exactly, including the parts the main API deliberately changed:

* **OR semantics** — a list passes if *any* permission passes. The main
  ``permission_required`` requires all of them, matching Django and DRF.
* **A returned response** rather than a raised exception, so exception
  handlers and error-logging middleware never see the denial.
* **Permissions defined as** ``is_permitted(request, *args, **kwargs)``.

Every use emits a ``DeprecationWarning``. To migrate a call site:

```python
# before
from starlette_permissions.compat import permission_required
@permission_required([IsAuthenticated])

# after
from starlette_permissions import permission_required
@permission_required(IsAuthenticated)
```

With a single permission in the list the two are equivalent, so most call
sites can move without any behaviour change at all.
"""

from __future__ import annotations

import warnings
from functools import wraps
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

from starlette_permissions._utils import maybe_await
from starlette_permissions.base import BasePermission as _BasePermission
from starlette_permissions.resolver import INJECTED_PARAM, resolved_signature

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from starlette_permissions.context import PermissionContext

__all__ = ["BasePermission", "LegacyPermission", "permission_required"]


class BasePermission:
    """The legacy base class: a static ``is_permitted`` taking the request.

    New code should subclass :class:`starlette_permissions.BasePermission`,
    whose ``has_permission`` receives a
    :class:`~starlette_permissions.PermissionContext` instead.
    """

    @staticmethod
    async def is_permitted(request: Any, *args: Any, **kwargs: Any) -> bool:
        return True


class LegacyPermission(_BasePermission):
    """Adapts an ``is_permitted``-style permission to the current interface.

    Produced automatically by
    :func:`~starlette_permissions.base.resolve_permission`, so legacy
    permissions can be mixed into ``&``/``|`` expressions and passed to the
    modern decorator without being rewritten first.
    """

    def __init__(self, target: Any) -> None:
        self.target = target
        self.message = getattr(target, "message", _BasePermission.message)

    async def has_permission(self, ctx: PermissionContext) -> bool:
        # The endpoint's own arguments are forwarded so legacy permissions that
        # read a path parameter keep working. Any argument that *is* the
        # connection is dropped, since it is already passed positionally.
        extra = {
            name: value for name, value in ctx.view_kwargs.items() if value is not ctx.connection
        }
        result = self.target.is_permitted(ctx.connection, **extra)
        return bool(await maybe_await(result))

    def __repr__(self) -> str:
        name = getattr(self.target, "__name__", None) or type(self.target).__name__
        return f"LegacyPermission({name})"


def permission_required(permissions: Sequence[Any]) -> Callable[..., Any]:
    """Legacy decorator: OR semantics, returns a 403 response instead of raising.

    Deprecated since 0.1. Use :func:`starlette_permissions.permission_required`.
    """
    warnings.warn(
        "starlette_permissions.compat.permission_required is deprecated: it "
        "requires only one permission to pass and returns a response instead "
        "of raising. Use starlette_permissions.permission_required, which "
        "requires all of them.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop(INJECTED_PARAM, None)
            for item in permissions:
                # Forwarded exactly as the original decorator did: the request
                # arrives as whichever argument the endpoint declared it as.
                result = item.is_permitted(*args, **kwargs)
                if await maybe_await(result):
                    return await func(*args, **kwargs)
            return JSONResponse(content={"detail": "Permission denied"}, status_code=403)

        # No parameter is injected here — the legacy behaviour is reproduced
        # exactly — but the signature still has to carry resolved annotations,
        # or a framework will try to resolve them against *this* module's
        # globals and fail. See resolver.resolved_signature.
        signature = resolved_signature(func)
        if signature is not None:
            wrapper.__signature__ = signature  # type: ignore[attr-defined]
        return wrapper

    return decorator
