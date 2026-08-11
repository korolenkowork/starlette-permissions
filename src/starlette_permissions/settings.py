"""Global and per-app configuration.

The defaults work with Starlette's ``AuthenticationMiddleware`` out of the box.
Anything else — a token on ``request.state``, a custom user model, roles stored
somewhere unusual — is a one-line :func:`configure` call at startup.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

    from starlette.requests import HTTPConnection

__all__ = ["PermissionSettings", "configure", "get_settings", "override_settings"]

#: Methods considered non-mutating, used by ``ReadOnly`` and friends.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _default_user_getter(conn: HTTPConnection) -> Any:
    """Find the current user without assuming any particular auth setup.

    Order: Starlette's ``AuthenticationMiddleware`` (``scope["user"]``), then
    ``request.state.user``. ``scope.get`` is used rather than ``request.user``
    because the latter asserts that the middleware is installed.
    """
    user = conn.scope.get("user")
    if user is not None:
        return user
    with contextlib.suppress(AttributeError, KeyError):
        return conn.state.user
    return None


def _default_role_getter(user: Any) -> Collection[str]:
    for attr in ("roles", "groups", "role"):
        value = getattr(user, attr, None)
        if value is None:
            continue
        if isinstance(value, str):
            return (value,)
        with contextlib.suppress(TypeError):
            return [str(item) for item in value]
    return ()


def _default_scope_getter(conn: HTTPConnection) -> Collection[str]:
    auth = conn.scope.get("auth")
    scopes = getattr(auth, "scopes", None)
    if scopes is not None:
        with contextlib.suppress(TypeError):
            return [str(item) for item in scopes]
    return ()


@dataclass(frozen=True)
class PermissionSettings:
    """Immutable settings bundle. Use :func:`configure` to change the global one."""

    #: Resolves the current user from the connection. Return ``None`` for anonymous.
    user_getter: Callable[[HTTPConnection], Any] = _default_user_getter
    #: Resolves role names from a user object.
    role_getter: Callable[[Any], Collection[str]] = _default_role_getter
    #: Resolves OAuth-style scopes from the connection.
    scope_getter: Callable[[HTTPConnection], Collection[str]] = _default_scope_getter
    #: Attributes checked, in order, by ``IsAdminUser``.
    admin_attrs: tuple[str, ...] = ("is_admin", "is_staff", "is_superuser")
    #: Attribute consulted by ``IsAuthenticated`` when the user object defines it.
    authenticated_attr: str = "is_authenticated"
    #: Status code and message for a plain denial.
    denied_status_code: int = 403
    denied_message: str = "Permission denied"
    #: Status code and message used when the request has no identity at all.
    #: Set ``unauthenticated_status_code=403`` to stop distinguishing the two,
    #: which avoids leaking whether an endpoint exists to anonymous callers.
    unauthenticated_status_code: int = 401
    unauthenticated_message: str = "Authentication credentials were not provided."
    #: Sent as ``WWW-Authenticate`` on 401 responses. ``None`` omits the header.
    authenticate_header: str | None = None
    #: Extra headers attached to every denial response.
    denied_headers: dict[str, str] = field(default_factory=dict)


_settings = PermissionSettings()


def configure(**kwargs: Any) -> PermissionSettings:
    """Update the global settings in place and return the new bundle.

    ```python
    configure(user_getter=lambda conn: getattr(conn.state.token, "user", None))
    ```
    """
    global _settings  # noqa: PLW0603 - a module-level singleton is the point
    unknown = set(kwargs) - {f.name for f in PermissionSettings.__dataclass_fields__.values()}
    if unknown:
        msg = f"Unknown permission setting(s): {', '.join(sorted(unknown))}"
        raise TypeError(msg)
    _settings = replace(_settings, **kwargs)
    return _settings


def get_settings(conn: HTTPConnection | None = None) -> PermissionSettings:
    """Return the settings for this connection.

    An app can carry its own bundle on ``app.state.permission_settings``, which
    wins over the global one. That keeps mounted sub-applications independent.
    """
    if conn is not None:
        app = conn.scope.get("app")
        local = getattr(getattr(app, "state", None), "permission_settings", None)
        if isinstance(local, PermissionSettings):
            return local
    return _settings


@contextlib.contextmanager
def override_settings(**kwargs: Any) -> Iterator[PermissionSettings]:
    """Temporarily replace global settings. Intended for tests."""
    global _settings  # noqa: PLW0603
    previous = _settings
    try:
        yield configure(**kwargs)
    finally:
        _settings = previous
