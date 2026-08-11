"""Apply permissions to a whole app, or to a subtree of routes.

```python
app.add_middleware(
    PermissionMiddleware,
    permissions=IsAuthenticated,
    exempt=["/health", re.compile(r"/auth/.*")],
)
```

Use this for a blanket default ("everything needs a login except these"). For
anything route-specific, the decorator or dependency stays clearer, because the
rule lives next to the handler it guards.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from starlette_permissions.base import resolve_permissions
from starlette_permissions.checks import check_permissions
from starlette_permissions.context import PermissionContext
from starlette_permissions.exceptions import PermissionDenied

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from starlette.types import ASGIApp, Receive, Scope, Send

    from starlette_permissions.base import PermissionLike
    from starlette_permissions.checks import Mode

__all__ = ["PermissionMiddleware"]

#: WebSocket close code for a policy violation (RFC 6455).
WS_POLICY_VIOLATION = 1008


class PermissionMiddleware:
    """ASGI middleware that enforces permissions before the app runs.

    Args:
        app: The wrapped ASGI application.
        permissions: A permission, or any nesting of lists of them.
        mode: ``"all"`` (default) or ``"any"``.
        exempt: Paths that skip the check. A ``str`` must match the path
            exactly; pass ``re.compile(...)`` for a pattern, which is matched
            against the whole path.
        methods: Restrict the check to these HTTP methods. ``None`` checks all.

    Note:
        Added via ``app.add_middleware``, this sits *outside* Starlette's
        ``ExceptionMiddleware``, so it renders its own JSON response rather
        than raising — a raised ``HTTPException`` would surface as a 500 there.

    Note:
        Middleware runs before routing, so ``ctx.view_kwargs`` is empty here.
        Rules that need a path parameter belong on the route itself.
    """

    def __init__(
        self,
        app: ASGIApp,
        permissions: PermissionLike | Sequence[PermissionLike] = (),
        *,
        mode: Mode = "all",
        exempt: Collection[str | re.Pattern[str]] = (),
        methods: Collection[str] | None = None,
    ) -> None:
        self.app = app
        self.permissions = resolve_permissions(permissions)
        self.mode: Mode = mode
        self.exempt_paths = frozenset(item for item in exempt if isinstance(item, str))
        self.exempt_patterns = tuple(item for item in exempt if isinstance(item, re.Pattern))
        self.methods = frozenset(m.upper() for m in methods) if methods else None

    def _is_exempt(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        if path in self.exempt_paths:
            return True
        return any(pattern.fullmatch(path) for pattern in self.exempt_patterns)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.permissions:
            await self.app(scope, receive, send)
            return

        if self._is_exempt(scope):
            await self.app(scope, receive, send)
            return

        if self.methods is not None and str(scope.get("method", "")).upper() not in self.methods:
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope, receive)
        ctx = PermissionContext(connection, view_kwargs=scope.get("path_params") or {})
        try:
            await check_permissions(self.permissions, ctx, mode=self.mode)
        except PermissionDenied as exc:
            await self._deny(exc, scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _deny(
        self,
        exc: PermissionDenied,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION})
            return
        response: Any = JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
        await response(scope, receive, send)
