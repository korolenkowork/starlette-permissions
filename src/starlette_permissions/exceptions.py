"""Exceptions raised when a permission check fails.

Both exceptions derive from Starlette's ``HTTPException``, so FastAPI's default
handler renders them as ``{"detail": ...}`` JSON with no extra setup. Plain
Starlette renders ``HTTPException`` as *plain text*; call
:func:`install_exception_handlers` if you want JSON there too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.exceptions import HTTPException

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.applications import Starlette

    from starlette_permissions.base import BasePermission

__all__ = [
    "ConfigurationError",
    "MissingRequestError",
    "NotAuthenticated",
    "PermissionDenied",
    "SyncCheckError",
    "install_exception_handlers",
]


class PermissionDenied(HTTPException):
    """Raised when one or more permission checks fail. Renders as 403."""

    status_code = 403
    default_detail = "Permission denied"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        headers: Mapping[str, str] | None = None,
        permission: BasePermission | None = None,
    ) -> None:
        # The permission that produced the failure is kept on the exception so
        # logging middleware and custom handlers can report *which* rule denied
        # the request, not just that something did.
        self.permission = permission
        super().__init__(
            status_code=status_code if status_code is not None else self.status_code,
            detail=detail if detail is not None else self.default_detail,
            headers=dict(headers) if headers else None,
        )


class NotAuthenticated(PermissionDenied):
    """Raised when the request carries no identity at all. Renders as 401."""

    status_code = 401
    default_detail = "Authentication credentials were not provided."


class ConfigurationError(RuntimeError):
    """The library was handed something it cannot use as a permission."""


class MissingRequestError(ConfigurationError):
    """No ``Request``/``WebSocket`` could be found for the endpoint being guarded."""


class SyncCheckError(ConfigurationError):
    """An async permission was evaluated from a context that cannot await it."""


async def _permission_denied_handler(_request: Any, exc: Exception) -> Any:
    from starlette.responses import JSONResponse

    if not isinstance(exc, HTTPException):  # pragma: no cover - registered per type
        raise exc
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


def install_exception_handlers(app: Starlette) -> None:
    """Render permission failures as JSON on a plain Starlette app.

    FastAPI already does this for every ``HTTPException``, so calling it there
    is a no-op in practice. On Starlette the built-in handler returns
    ``PlainTextResponse``, which is rarely what an API wants.
    """
    app.add_exception_handler(PermissionDenied, _permission_denied_handler)
    app.add_exception_handler(NotAuthenticated, _permission_denied_handler)
