"""Locating the connection for an endpoint, and making sure one exists.

The fragile part of decorator-based permissions is getting hold of the
``Request``. Starlette passes it positionally; FastAPI passes it by keyword,
and *only* if the endpoint declared it. This module handles both, and adds the
parameter to the signature when the endpoint did not ask for one — so guarding
a handler never forces you to edit its arguments.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from starlette.requests import HTTPConnection, Request
from starlette.websockets import WebSocket

from starlette_permissions.exceptions import MissingRequestError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "INJECTED_PARAM",
    "find_connection",
    "inject_request_parameter",
    "resolved_signature",
]

#: Name of the parameter added to endpoints that do not declare a ``Request``.
#: Deliberately unlikely to collide with a real argument.
INJECTED_PARAM = "__sp_request"


def find_connection(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> HTTPConnection | None:
    """Pick the ``Request``/``WebSocket`` out of an endpoint's arguments.

    Checks the injected keyword first, then positional arguments (plain
    Starlette), then the remaining keywords (FastAPI).
    """
    injected = kwargs.get(INJECTED_PARAM)
    if isinstance(injected, HTTPConnection):
        return injected

    for value in args:
        if isinstance(value, HTTPConnection):
            return value

    for name, value in kwargs.items():
        if name == INJECTED_PARAM:
            continue
        if isinstance(value, HTTPConnection):
            return value

    return None


def require_connection(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> HTTPConnection:
    connection = find_connection(args, kwargs)
    if connection is None:
        name = getattr(func, "__qualname__", repr(func))
        msg = (
            f"No Request or WebSocket was passed to {name!r}, so its permissions "
            f"cannot be checked. Add a 'request: Request' parameter to the "
            f"endpoint, or apply @permission_required directly beneath the route "
            f"decorator so the parameter can be injected for you."
        )
        raise MissingRequestError(msg)
    return connection


def resolved_signature(func: Callable[..., Any]) -> inspect.Signature | None:
    """Return ``func``'s signature with string annotations already evaluated.

    This matters because the wrapper we hand to the router carries this
    signature, but lives in *this* module — so its ``__globals__`` are ours,
    not the user's. A module using ``from __future__ import annotations`` gives
    us ``"Request"`` as a plain string, and a framework resolving that against
    our globals would not find the name. Evaluating here, against the original
    function's own globals, keeps the annotation meaningful wherever the
    wrapper ends up.

    Falls back to the unevaluated signature when a name cannot be resolved,
    which is normal for annotations that only exist under ``TYPE_CHECKING``.
    """
    try:
        return inspect.signature(func, eval_str=True)
    except (NameError, AttributeError, SyntaxError):
        # An annotation referencing a TYPE_CHECKING-only import. The string
        # branch of _declares_connection still handles the common cases.
        pass
    except (TypeError, ValueError):  # pragma: no cover - builtins, C callables
        return None

    try:
        return inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - builtins, C callables
        return None


def _declares_connection(signature: inspect.Signature) -> bool:
    for parameter in signature.parameters.values():
        annotation = parameter.annotation
        if isinstance(annotation, str):
            # Unresolved string annotation, from PEP 563 or a quoted hint.
            # Matching on the trailing name is imprecise, but the cost of a
            # miss is a redundant injected parameter, never a wrong decision at
            # request time.
            name = annotation.strip().strip("\"'").split("[")[0].rsplit(".", 1)[-1]
            if name in {"Request", "WebSocket", "HTTPConnection"}:
                return True
            continue
        if isinstance(annotation, type) and issubclass(
            annotation, (Request, WebSocket, HTTPConnection)
        ):
            return True
    return False


def inject_request_parameter(
    func: Callable[..., Any],
    wrapper: Callable[..., Any],
) -> bool:
    """Give ``wrapper`` a ``Request`` parameter if ``func`` lacks one.

    FastAPI reads the signature to decide what to pass, so adding a
    keyword-only ``Request`` parameter is enough to have one supplied. Plain
    Starlette ignores signatures entirely and keeps passing the request
    positionally, so this is inert there.

    Returns whether a parameter was added.
    """
    signature = resolved_signature(func)
    if signature is None:
        return False

    if _declares_connection(signature):
        wrapper.__signature__ = signature  # type: ignore[attr-defined]
        return False

    parameters = list(signature.parameters.values())
    injected = inspect.Parameter(
        INJECTED_PARAM,
        inspect.Parameter.KEYWORD_ONLY,
        annotation=Request,
    )

    # A **kwargs parameter has to stay last, so slot the new one in front of it.
    var_keyword_at = next(
        (
            index
            for index, parameter in enumerate(parameters)
            if parameter.kind is inspect.Parameter.VAR_KEYWORD
        ),
        len(parameters),
    )
    parameters.insert(var_keyword_at, injected)

    wrapper.__signature__ = signature.replace(parameters=parameters)  # type: ignore[attr-defined]
    return True
