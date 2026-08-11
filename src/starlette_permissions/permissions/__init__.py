"""The built-in permission set.

Everything here is also re-exported from the package root, so
``from starlette_permissions import IsAuthenticated`` works.
"""

from starlette_permissions.permissions.api_key import HasAPIKey
from starlette_permissions.permissions.auth import (
    IsAdminUser,
    IsAnonymous,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from starlette_permissions.permissions.common import (
    AllowAny,
    DenyAll,
    HasHeader,
    IsMethod,
    Predicate,
    ReadOnly,
    permission,
)
from starlette_permissions.permissions.objects import (
    IsOwner,
    IsOwnerOrReadOnly,
    ObjectPermission,
)
from starlette_permissions.permissions.roles import (
    HasAllRoles,
    HasAllScopes,
    HasAnyRole,
    HasAnyScope,
    HasRole,
    HasScope,
)

__all__ = [
    "AllowAny",
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
    "ObjectPermission",
    "Predicate",
    "ReadOnly",
    "permission",
]
