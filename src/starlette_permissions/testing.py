"""Helpers for unit-testing permissions without standing up an app.

```python
ctx = make_context(user=User(id=1, roles=["admin"]), method="DELETE")
assert await has_permissions(HasRole("admin"), ctx)
```
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request

from starlette_permissions.context import PermissionContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette_permissions.settings import PermissionSettings

__all__ = ["make_context", "make_request"]

_UNSET = object()


def make_request(  # noqa: PLR0913 - a test helper; every field is optional
    *,
    method: str = "GET",
    path: str = "/",
    headers: Mapping[str, str] | None = None,
    query_string: str = "",
    user: Any = _UNSET,
    auth: Any = None,
    path_params: Mapping[str, Any] | None = None,
    app: Any = None,
) -> Request:
    """Build a ``Request`` with just enough ASGI scope to check permissions.

    ``user`` is placed on the scope where Starlette's ``AuthenticationMiddleware``
    would put it, so the default ``user_getter`` finds it.
    """
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query_string.encode(),
        "headers": raw_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": dict(path_params or {}),
        "state": {},
    }
    if user is not _UNSET:
        scope["user"] = user
    if auth is not None:
        scope["auth"] = auth
    if app is not None:
        scope["app"] = app
    return Request(scope)


def make_context(
    *,
    settings: PermissionSettings | None = None,
    view_kwargs: Mapping[str, Any] | None = None,
    endpoint: Any = None,
    **request_kwargs: Any,
) -> PermissionContext:
    """Build a :class:`PermissionContext` directly. Arguments as :func:`make_request`."""
    request = make_request(**request_kwargs)
    return PermissionContext(
        request,
        endpoint=endpoint,
        view_kwargs=view_kwargs if view_kwargs is not None else request.path_params,
        settings=settings,
    )
