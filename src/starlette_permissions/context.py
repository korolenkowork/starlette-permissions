"""The object every permission receives.

A permission never digs through ``*args``/``**kwargs`` itself — it is handed a
:class:`PermissionContext` with the connection, the resolved user, and the
endpoint's own arguments already sorted out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette_permissions.settings import SAFE_METHODS, PermissionSettings, get_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

    from starlette.datastructures import Headers
    from starlette.requests import HTTPConnection

__all__ = ["PermissionContext"]

_MISSING = object()


class PermissionContext:
    """Everything a permission needs to decide, with user lookup cached.

    Attributes:
        connection: The ``Request`` or ``WebSocket`` being guarded.
        endpoint: The view function, when the check runs on one.
        view_kwargs: The arguments the endpoint was called with. Useful for
            object-level rules that key off a path parameter.
    """

    __slots__ = ("_settings", "_user", "connection", "endpoint", "view_kwargs")

    def __init__(
        self,
        connection: HTTPConnection,
        *,
        endpoint: Callable[..., Any] | None = None,
        view_kwargs: Mapping[str, Any] | None = None,
        settings: PermissionSettings | None = None,
    ) -> None:
        self.connection = connection
        self.endpoint = endpoint
        self.view_kwargs: Mapping[str, Any] = view_kwargs or {}
        self._settings = settings
        self._user: Any = _MISSING

    # -- plumbing ---------------------------------------------------------

    @property
    def settings(self) -> PermissionSettings:
        if self._settings is None:
            self._settings = get_settings(self.connection)
        return self._settings

    @property
    def request(self) -> HTTPConnection:
        """Alias for :attr:`connection`, for readability in HTTP-only code."""
        return self.connection

    @property
    def is_websocket(self) -> bool:
        return self.connection.scope.get("type") == "websocket"

    # -- request data -----------------------------------------------------

    @property
    def method(self) -> str:
        """The HTTP method, uppercased. ``""`` for WebSocket connections."""
        return str(self.connection.scope.get("method", "")).upper()

    @property
    def headers(self) -> Headers:
        return self.connection.headers

    @property
    def path_params(self) -> Mapping[str, Any]:
        return self.connection.path_params

    @property
    def is_safe_method(self) -> bool:
        return self.method in SAFE_METHODS

    # -- identity ---------------------------------------------------------

    @property
    def user(self) -> Any:
        """The current user, or ``None``. Resolved once, then cached."""
        if self._user is _MISSING:
            self._user = self.settings.user_getter(self.connection)
        return self._user

    @property
    def is_authenticated(self) -> bool:
        """Whether the request carries an identity.

        A user object may say so itself via ``is_authenticated`` (Starlette's
        ``BaseUser`` and Django's user both do). Otherwise, merely having a
        non-``None`` user counts.
        """
        user = self.user
        if user is None:
            return False
        flag = getattr(user, self.settings.authenticated_attr, _MISSING)
        if flag is _MISSING:
            return True
        return bool(flag)

    @property
    def roles(self) -> Collection[str]:
        user = self.user
        return () if user is None else self.settings.role_getter(user)

    @property
    def scopes(self) -> Collection[str]:
        return self.settings.scope_getter(self.connection)

    def __repr__(self) -> str:
        return (
            f"<PermissionContext {self.method or 'WS'} "
            f"{self.connection.scope.get('path', '')!r} user={self.user!r}>"
        )
