"""Small internal helpers. Not part of the public API."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

T = TypeVar("T")

__all__ = ["maybe_await", "run_coroutine_from_sync"]


async def maybe_await(value: T | Awaitable[T]) -> T:
    """Await ``value`` if it is awaitable, otherwise return it as-is.

    Lets a permission define ``has_permission`` as either ``def`` or
    ``async def`` without the caller caring which.
    """
    if inspect.isawaitable(value):
        return await value
    return value


def _no_portal_errors() -> tuple[type[BaseException], ...]:
    """The exception anyio raises when there is no event loop to hand work to.

    Recent anyio raises ``NoEventLoopError``; older versions raise a plain
    ``RuntimeError``. Matching the narrow type where it exists matters: it is
    what lets us distinguish "no portal" from "the permission itself raised a
    RuntimeError", and so avoid running user code twice.
    """
    try:
        from anyio import NoEventLoopError
    except ImportError:  # pragma: no cover - anyio < 4.11
        return (RuntimeError,)
    return (NoEventLoopError,)


def run_coroutine_from_sync(make_coroutine: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run an async check from a synchronous endpoint.

    Two paths, tried in order:

    1. **An AnyIO worker thread.** FastAPI and Starlette run ``def`` endpoints
       in one, so there is a portal back to the event loop and the coroutine
       runs there properly. This is the path taken when actually serving.
    2. **No event loop at all** — a decorated endpoint called directly, which
       is mostly unit tests. The coroutine is stepped once by hand. Checks
       that never truly suspend (every synchronous permission, and any async
       one that does no I/O) complete on that single step.

    A permission that genuinely suspends with no loop to suspend into cannot
    be run, and raises :class:`SyncCheckError` rather than deadlocking or
    quietly allowing the request.

    Note:
        The portal is probed before any user code runs, so a permission is
        never executed twice across the two paths.
    """
    from starlette_permissions.exceptions import SyncCheckError

    try:
        from anyio.from_thread import run as run_from_thread
    except ImportError:  # pragma: no cover - anyio ships with starlette
        pass
    else:
        try:
            return run_from_thread(make_coroutine)
        except _no_portal_errors():
            pass

    coroutine = make_coroutine()
    try:
        coroutine.send(None)
    except StopIteration as stop:
        return stop.value  # type: ignore[no-any-return]

    coroutine.close()
    msg = (
        "An asynchronous permission suspended while being checked from a "
        "synchronous endpoint with no running event loop. Declare the endpoint "
        "as 'async def', or make the permission's has_permission() a plain 'def'."
    )
    raise SyncCheckError(msg)
