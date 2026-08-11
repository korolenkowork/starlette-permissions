"""Decorator-based enforcement.

```python
@router.get("/me")
@permission_required(IsAuthenticated)
async def get_me(request: Request): ...
```

The decorator must sit *below* the route decorator, so the router registers the
guarded function rather than the bare one. Works on FastAPI and Starlette
endpoints, sync and async.
"""

from __future__ import annotations

import inspect
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

from starlette_permissions._utils import run_coroutine_from_sync
from starlette_permissions.base import resolve_permissions
from starlette_permissions.checks import check_object_permissions, check_permissions
from starlette_permissions.context import PermissionContext
from starlette_permissions.exceptions import PermissionDenied
from starlette_permissions.resolver import (
    INJECTED_PARAM,
    inject_request_parameter,
    require_connection,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from starlette_permissions.base import BasePermission, PermissionLike
    from starlette_permissions.checks import Mode

__all__ = ["object_permission_required", "permission_required"]

F = TypeVar("F", bound="Callable[..., Any]")


def _override(
    exc: PermissionDenied,
    message: str | None,
    status_code: int | None,
) -> PermissionDenied:
    """Apply per-endpoint message/status overrides to a refusal."""
    if message is None and status_code is None:
        return exc
    return PermissionDenied(
        message if message is not None else exc.detail,
        status_code=status_code if status_code is not None else exc.status_code,
        headers=exc.headers,
        permission=exc.permission,
    )


def permission_required(
    *permissions: PermissionLike | Sequence[PermissionLike],
    mode: Mode = "all",
    message: str | None = None,
    status_code: int | None = None,
) -> Callable[[F], F]:
    """Guard an endpoint with one or more permissions.

    Args:
        *permissions: Permission classes, instances, or predicate functions.
            A single list is accepted too, so ``permission_required([A, B])``
            and ``permission_required(A, B)`` are the same thing.
        mode: ``"all"`` (default) requires every permission to pass;
            ``"any"`` requires at least one.
        message: Overrides the failing permission's message for this endpoint.
        status_code: Overrides the refusal status code for this endpoint.

    Raises:
        MissingRequestError: at request time, if no ``Request`` reached the
            endpoint. This only happens when the decorator is applied *above*
            the route decorator, which stops the signature fix from taking
            effect.
    """
    resolved = resolve_permissions(list(permissions))

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                connection = require_connection(func, args, kwargs)
                kwargs.pop(INJECTED_PARAM, None)
                ctx = PermissionContext(
                    connection,
                    endpoint=func,
                    view_kwargs=kwargs,
                )
                try:
                    await check_permissions(resolved, ctx, mode=mode)
                except PermissionDenied as exc:
                    raise _override(exc, message, status_code) from None
                return await func(*args, **kwargs)

            wrapper: Callable[..., Any] = async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                connection = require_connection(func, args, kwargs)
                kwargs.pop(INJECTED_PARAM, None)
                ctx = PermissionContext(
                    connection,
                    endpoint=func,
                    view_kwargs=kwargs,
                )
                try:
                    run_coroutine_from_sync(lambda: check_permissions(resolved, ctx, mode=mode))
                except PermissionDenied as exc:
                    raise _override(exc, message, status_code) from None
                return func(*args, **kwargs)

            wrapper = sync_wrapper

        inject_request_parameter(func, wrapper)
        wrapper.__sp_permissions__ = resolved  # type: ignore[attr-defined]
        wrapper.__sp_mode__ = mode  # type: ignore[attr-defined]
        return cast("F", wrapper)

    return decorator


def object_permission_required(
    *permissions: PermissionLike | Sequence[PermissionLike],
    mode: Mode = "all",
    getter: Callable[..., Any] | None = None,
    message: str | None = None,
    status_code: int | None = None,
) -> Callable[[F], F]:
    """Guard an endpoint with object-level permissions.

    Two shapes, depending on when the object becomes available:

    * With ``getter``, the object is loaded and checked *before* the handler
      runs. The getter receives the endpoint's own keyword arguments and may
      be sync or async. Prefer this — nothing happens if the caller is
      refused.
    * Without ``getter``, the handler's **return value** is the object, and it
      is checked *after* the handler runs. Convenient for a plain "fetch and
      return" route, but the fetch has already happened by then.

    ```python
    @router.get("/posts/{post_id}")
    @object_permission_required(IsOwner("author_id"))
    async def get_post(request: Request, post_id: int):
        return await posts.get(post_id)
    ```
    """
    resolved = resolve_permissions(list(permissions))

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            msg = (
                "@object_permission_required needs an 'async def' endpoint; "
                "loading the object is inherently asynchronous."
            )
            raise TypeError(msg)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            connection = require_connection(func, args, kwargs)
            kwargs.pop(INJECTED_PARAM, None)
            ctx = PermissionContext(connection, endpoint=func, view_kwargs=kwargs)

            async def check(obj: Any) -> None:
                try:
                    await check_object_permissions(resolved, ctx, obj, mode=mode)
                except PermissionDenied as exc:
                    raise _override(exc, message, status_code) from None

            if getter is not None:
                obj = getter(**kwargs)
                if inspect.isawaitable(obj):
                    obj = await obj
                await check(obj)
                return await func(*args, **kwargs)

            result = await func(*args, **kwargs)
            await check(result)
            return result

        inject_request_parameter(func, wrapper)
        wrapper.__sp_permissions__ = resolved  # type: ignore[attr-defined]
        wrapper.__sp_mode__ = mode  # type: ignore[attr-defined]
        return cast("F", wrapper)

    return decorator


def get_permissions(endpoint: Callable[..., Any]) -> tuple[BasePermission, ...]:
    """Read back the permissions attached to an endpoint.

    Useful in tests, and for generating an access matrix from a router.
    """
    return getattr(endpoint, "__sp_permissions__", ())
