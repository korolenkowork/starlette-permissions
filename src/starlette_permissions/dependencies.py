"""FastAPI dependency-based enforcement.

Preferred over the decorator on FastAPI: it needs no signature rewriting, it
composes with the rest of the dependency graph, and it can be attached to a
whole router in one place.

```python
@router.get("/me", dependencies=[requires(IsAuthenticated)])
async def get_me(): ...

router = APIRouter(dependencies=[requires(IsService)])
```

Importing this module requires FastAPI. The rest of the library does not.

Note:
    This module deliberately does **not** use ``from __future__ import
    annotations``. FastAPI reads these annotations at runtime to decide what to
    inject, resolving any string it finds against the callable's
    ``__globals__`` — and a class instance such as :class:`PermissionChecker`
    has none. Stringified annotations therefore make older FastAPI treat
    ``request`` as a query parameter instead of injecting the request. Keeping
    real objects here avoids the whole class of problem.
"""

from collections.abc import Sequence
from typing import Any, Union

from starlette.requests import Request

from starlette_permissions.base import PermissionLike, resolve_permissions
from starlette_permissions.checks import Mode, check_object_permissions, check_permissions
from starlette_permissions.context import PermissionContext
from starlette_permissions.exceptions import PermissionDenied

#: Accepted wherever this module takes permissions.
Permissions = Union[PermissionLike, Sequence[PermissionLike]]  # noqa: UP007

__all__ = [
    "PermissionChecker",
    "permission_responses",
    "requires",
    "requires_object",
]


def _depends() -> Any:
    """Return ``fastapi.Depends``, or explain what is missing.

    FastAPI is only imported here, not at module scope, so that importing this
    module never becomes a hard dependency. The cost is that the failure lands
    at call time — which is why it is worth a real message.
    """
    try:
        from fastapi import Depends
    except ImportError as exc:  # pragma: no cover - depends on environment
        msg = (
            "starlette_permissions.dependencies needs FastAPI. Install it with "
            "'pip install starlette-permissions[fastapi]', or use "
            "@permission_required / PermissionMixin, which work on plain Starlette."
        )
        raise ImportError(msg) from exc
    return Depends


class PermissionChecker:
    """A callable dependency that enforces permissions, or raises.

    Instantiate it directly when you want the object itself — to reuse one
    checker in several places, or to call it from your own dependency.
    """

    def __init__(
        self,
        *permissions: Permissions,
        mode: Mode = "all",
        message: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.permissions = resolve_permissions(list(permissions))
        self.mode: Mode = mode
        self.message = message
        self.status_code = status_code

    async def __call__(self, request: Request) -> PermissionContext:
        ctx = PermissionContext(request, view_kwargs=request.path_params)
        try:
            await check_permissions(self.permissions, ctx, mode=self.mode)
        except PermissionDenied as exc:
            raise self._override(exc) from None
        return ctx

    def _override(self, exc: PermissionDenied) -> PermissionDenied:
        if self.message is None and self.status_code is None:
            return exc
        return PermissionDenied(
            self.message if self.message is not None else exc.detail,
            status_code=self.status_code if self.status_code is not None else exc.status_code,
            headers=exc.headers,
            permission=exc.permission,
        )

    def __repr__(self) -> str:
        rules = ", ".join(repr(p) for p in self.permissions)
        return f"PermissionChecker({rules}, mode={self.mode!r})"


def requires(
    *permissions: Permissions,
    mode: Mode = "all",
    message: str | None = None,
    status_code: int | None = None,
) -> Any:
    """Build a ``Depends(...)`` that enforces ``permissions``.

    The dependency resolves to the :class:`PermissionContext`, so a handler
    that wants the user can take it as a value instead of re-deriving it:

    ```python
    @router.get("/me")
    async def get_me(ctx: PermissionContext = requires(IsAuthenticated)):
        return ctx.user
    ```
    """
    return _depends()(
        PermissionChecker(
            *permissions,
            mode=mode,
            message=message,
            status_code=status_code,
        )
    )


def requires_object(
    *permissions: Permissions,
    mode: Mode = "all",
) -> Any:
    """Build a dependency that resolves to an object-level checker.

    The handler loads the record, then calls the checker with it:

    ```python
    @router.get("/posts/{post_id}")
    async def get_post(post_id: int, check=requires_object(IsOwner("author_id"))):
        post = await posts.get(post_id)
        await check(post)
        return post
    ```
    """
    depends = _depends()
    resolved = resolve_permissions(list(permissions))

    async def dependency(request: Request) -> Any:
        ctx = PermissionContext(request, view_kwargs=request.path_params)

        async def check(obj: Any) -> Any:
            await check_object_permissions(resolved, ctx, obj, mode=mode)
            return obj

        return check

    return depends(dependency)


def permission_responses(
    *,
    forbidden: bool = True,
    unauthorized: bool = True,
) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries for the denial cases.

    A dependency cannot add response schemas to the generated schema on its
    own, so spread this into the route:

    ```python
    @router.get("/me", dependencies=[requires(IsAuthenticated)], responses=permission_responses())
    ```
    """
    schema = {
        "type": "object",
        "properties": {"detail": {"type": "string"}},
    }
    responses: dict[int | str, dict[str, Any]] = {}
    if unauthorized:
        responses[401] = {
            "description": "Authentication credentials were not provided.",
            "content": {"application/json": {"schema": schema}},
        }
    if forbidden:
        responses[403] = {
            "description": "Permission denied.",
            "content": {"application/json": {"schema": schema}},
        }
    return responses


def current_context(request: Request) -> PermissionContext:
    """A dependency resolving to the :class:`PermissionContext`, with no checks.

    ```python
    async def handler(ctx: PermissionContext = Depends(current_context)): ...
    ```
    """
    return PermissionContext(request, view_kwargs=request.path_params)
