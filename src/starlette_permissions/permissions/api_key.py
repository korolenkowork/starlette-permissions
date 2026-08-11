"""API-key permissions, for service-to-service calls.

This is the generalisation of a hand-rolled ``IsService`` check:

```python
IsService = HasAPIKey(key=lambda: settings.service_api_token)
```

Passing a callable keeps the comparison against the *current* configured value,
which matters when settings are loaded lazily or rotated at runtime.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

from starlette_permissions.base import BasePermission

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from starlette_permissions.context import PermissionContext

__all__ = ["HasAPIKey"]


class HasAPIKey(BasePermission):
    """Requires a matching API key in a header (or query parameter).

    Args:
        key: The accepted key, a collection of accepted keys, or a callable
            returning either. A callable is re-invoked on every request.
        header: Header carrying the key. Defaults to ``X-API-Key``.
        query_param: Optional query parameter to accept the key from as well.
            Off by default — keys in URLs end up in access logs.
        message: Overrides the refusal message.

    Comparison uses :func:`secrets.compare_digest`, so a wrong key takes the
    same time to reject regardless of how much of it was right.
    """

    message = "Invalid or missing API key"

    def __init__(
        self,
        key: str | Collection[str] | Callable[[], str | Collection[str]],
        *,
        header: str = "X-API-Key",
        query_param: str | None = None,
        message: str | None = None,
    ) -> None:
        self._key = key
        self.header = header
        self.query_param = query_param
        if message is not None:
            self.message = message

    def _accepted_keys(self) -> tuple[str, ...]:
        value: Any = self._key() if callable(self._key) else self._key
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value)

    def has_permission(self, ctx: PermissionContext) -> bool:
        provided = ctx.headers.get(self.header)
        if provided is None and self.query_param:
            provided = ctx.connection.query_params.get(self.query_param)
        if not provided:
            return False

        # Encode before comparing: compare_digest rejects str containing
        # non-ASCII, and header values reach us latin-1 decoded.
        supplied = provided.encode("utf-8", "surrogateescape")
        # Compare against every candidate rather than breaking early, so the
        # number of comparisons does not depend on which key was supplied.
        matched = False
        for candidate in self._accepted_keys():
            if candidate and secrets.compare_digest(
                supplied, candidate.encode("utf-8", "surrogateescape")
            ):
                matched = True
        return matched

    def __repr__(self) -> str:
        return f"HasAPIKey(header={self.header!r})"
