"""Django-style permission classes for Starlette and FastAPI.

```python
from starlette_permissions import IsAuthenticated, permission_required

@router.get("/me")
@permission_required(IsAuthenticated)
async def get_me(request: Request):
    return request.state.user
```

The package root re-exports everything you normally need. ``requires`` is the
one exception: it lives in :mod:`starlette_permissions.dependencies` because it
needs FastAPI, which is an optional dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette_permissions.base import (
    BasePermission,
    PermissionLike,
    PermissionResult,
    resolve_permission,
    resolve_permissions,
)
from starlette_permissions.checks import (
    Mode,
    check_object_permissions,
    check_permissions,
    has_object_permissions,
    has_permissions,
)
from starlette_permissions.context import PermissionContext
from starlette_permissions.decorators import (
    get_permissions,
    object_permission_required,
    permission_required,
)
from starlette_permissions.endpoints import PermissionMixin
from starlette_permissions.exceptions import (
    ConfigurationError,
    MissingRequestError,
    NotAuthenticated,
    PermissionDenied,
    SyncCheckError,
    install_exception_handlers,
)
from starlette_permissions.middleware import PermissionMiddleware
from starlette_permissions.operators import AND, NOT, OR, All, Not
from starlette_permissions.operators import Any_ as Any_permission
from starlette_permissions.permissions import (
    AllowAny,
    DenyAll,
    HasAllRoles,
    HasAllScopes,
    HasAnyRole,
    HasAnyScope,
    HasAPIKey,
    HasHeader,
    HasRole,
    HasScope,
    IsAdminUser,
    IsAnonymous,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
    IsMethod,
    IsOwner,
    IsOwnerOrReadOnly,
    ObjectPermission,
    Predicate,
    ReadOnly,
    permission,
)
from starlette_permissions.settings import (
    SAFE_METHODS,
    PermissionSettings,
    configure,
    get_settings,
    override_settings,
)

__version__ = "0.1.0"

#: ``Any(A, B)`` requires at least one of the permissions. Named to mirror
#: :func:`All`; ``Any_permission`` is the alias for code that also uses
#: ``typing.Any`` and would rather not shadow it.
Any = Any_permission

__all__ = [
    "AND",
    "NOT",
    "OR",
    "SAFE_METHODS",
    "All",
    "AllowAny",
    "Any",
    "Any_permission",
    "BasePermission",
    "ConfigurationError",
    "DenyAll",
    "HasAPIKey",
    "HasAllRoles",
    "HasAllScopes",
    "HasAnyRole",
    "HasAnyScope",
    "HasHeader",
    "HasRole",
    "HasScope",
    "IsAdminUser",
    "IsAnonymous",
    "IsAuthenticated",
    "IsAuthenticatedOrReadOnly",
    "IsMethod",
    "IsOwner",
    "IsOwnerOrReadOnly",
    "MissingRequestError",
    "Mode",
    "Not",
    "NotAuthenticated",
    "ObjectPermission",
    "PermissionChecker",
    "PermissionContext",
    "PermissionDenied",
    "PermissionLike",
    "PermissionMiddleware",
    "PermissionMixin",
    "PermissionResult",
    "PermissionSettings",
    "Predicate",
    "ReadOnly",
    "SyncCheckError",
    "__version__",
    "check_object_permissions",
    "check_permissions",
    "configure",
    "get_permissions",
    "get_settings",
    "has_object_permissions",
    "has_permissions",
    "install_exception_handlers",
    "object_permission_required",
    "override_settings",
    "permission",
    "permission_required",
    "permission_responses",
    "requires",
    "requires_object",
    "resolve_permission",
    "resolve_permissions",
]

if TYPE_CHECKING:
    from starlette_permissions.dependencies import (
        PermissionChecker,
        permission_responses,
        requires,
        requires_object,
    )

_FASTAPI_EXPORTS = {
    "PermissionChecker",
    "permission_responses",
    "requires",
    "requires_object",
}


def __getattr__(name: str) -> object:
    """Expose the FastAPI helpers lazily.

    Importing them eagerly would make FastAPI a hard dependency for Starlette-only
    users, so they are resolved on first access instead — with an error that
    names the missing package rather than an opaque ImportError.
    """
    if name in _FASTAPI_EXPORTS:
        try:
            from starlette_permissions import dependencies
        except ImportError as exc:  # pragma: no cover - depends on environment
            msg = (
                f"starlette_permissions.{name} needs FastAPI. "
                f"Install it with: pip install 'starlette-permissions[fastapi]'"
            )
            raise ImportError(msg) from exc
        return getattr(dependencies, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
