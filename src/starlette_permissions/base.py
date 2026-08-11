"""The permission base class and the rules for turning objects into permissions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, Union

from starlette_permissions._utils import maybe_await
from starlette_permissions.exceptions import ConfigurationError, PermissionDenied

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from starlette_permissions.context import PermissionContext

__all__ = [
    "BasePermission",
    "PermissionLike",
    "PermissionResult",
    "resolve_permission",
    "resolve_permissions",
]


class PermissionResult(NamedTuple):
    """The outcome of a check, plus the specific rule that refused.

    Knowing *which* leaf permission failed is what lets a composite like
    ``IsAuthenticated & HasRole("admin")`` return "Requires role: admin"
    instead of a generic message.
    """

    allowed: bool
    denied_by: BasePermission | None = None


class PermissionMeta(type):
    """Gives ``&``, ``|`` and ``~`` to permission *classes*, not just instances.

    Without this, ``IsAuthenticated & IsAdminUser`` would be a ``TypeError``
    and every composition would have to be written ``IsAuthenticated() & ...``.
    """

    def __and__(cls, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import AND

        return AND(cls, other)

    def __rand__(cls, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import AND

        return AND(other, cls)

    # These deliberately shadow ``type.__or__``, which would otherwise build a
    # PEP 604 union. The consequence is that ``IsAuthenticated | None`` is a
    # permission expression, not an ``Optional`` — so write ``Optional[...]``
    # or quote the annotation if you ever need a permission class in a union.
    def __or__(cls, other: PermissionLike) -> BasePermission:  # type: ignore[override]
        from starlette_permissions.operators import OR

        return OR(cls, other)

    def __ror__(cls, other: PermissionLike) -> BasePermission:  # type: ignore[override]
        from starlette_permissions.operators import OR

        return OR(other, cls)

    def __invert__(cls) -> BasePermission:
        from starlette_permissions.operators import NOT

        return NOT(cls)


class BasePermission(metaclass=PermissionMeta):
    """Subclass this and override :meth:`has_permission`.

    ```python
    class IsBetaTester(BasePermission):
        message = "Beta programme members only"

        def has_permission(self, ctx):
            return "beta" in ctx.roles
    ```

    Either method may be ``def`` or ``async def``. Instances are shared across
    requests, so keep them immutable — all per-request state lives on the
    context.
    """

    #: Detail body of the response when this permission refuses.
    message: str = "Permission denied"
    #: Status code for that response. ``None`` uses the configured default (403).
    status_code: int | None = None
    #: Exception raised on refusal. Override to distinguish 401 from 403.
    exception_class: type[PermissionDenied] = PermissionDenied

    # -- override these ---------------------------------------------------

    def has_permission(self, ctx: PermissionContext) -> bool | Awaitable[bool]:
        """Decide based on the request alone. Defaults to allowing everything."""
        return True

    def has_object_permission(
        self,
        ctx: PermissionContext,
        obj: Any,
    ) -> bool | Awaitable[bool]:
        """Decide based on a specific object, once you have loaded it.

        Only consulted by :func:`~starlette_permissions.checks.check_object_permissions`
        and the ``@object_permission_required`` decorator — a rule that needs
        the object cannot run before the handler has fetched it.
        """
        return True

    # -- evaluation -------------------------------------------------------

    async def evaluate(self, ctx: PermissionContext) -> PermissionResult:
        allowed = bool(await maybe_await(self.has_permission(ctx)))
        return PermissionResult(allowed, None if allowed else self)

    async def evaluate_object(self, ctx: PermissionContext, obj: Any) -> PermissionResult:
        allowed = bool(await maybe_await(self.has_object_permission(ctx, obj)))
        return PermissionResult(allowed, None if allowed else self)

    # -- failure ----------------------------------------------------------

    def denial(self, ctx: PermissionContext | None = None) -> PermissionDenied:
        """Build the exception describing this refusal.

        Override for rules that need to vary the response — adding a
        ``Retry-After`` on a throttle, say.
        """
        settings = ctx.settings if ctx is not None else None
        status_code = self.status_code
        if status_code is None and settings is not None:
            status_code = settings.denied_status_code
        headers = dict(settings.denied_headers) if settings else None
        return self.exception_class(
            self.message,
            status_code=status_code,
            headers=headers or None,
            permission=self,
        )

    # -- composition ------------------------------------------------------

    def __and__(self, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import AND

        return AND(self, other)

    def __rand__(self, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import AND

        return AND(other, self)

    def __or__(self, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import OR

        return OR(self, other)

    def __ror__(self, other: PermissionLike) -> BasePermission:
        from starlette_permissions.operators import OR

        return OR(other, self)

    def __invert__(self) -> BasePermission:
        from starlette_permissions.operators import NOT

        return NOT(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


#: Anything accepted where a permission is expected: an instance, the class
#: itself (instantiated for you), or a plain predicate function.
PermissionLike = Union[  # noqa: UP007 - must stay subscriptable at runtime
    BasePermission,
    type,
    Callable[..., Any],
]


def resolve_permission(value: PermissionLike) -> BasePermission:  # noqa: PLR0911
    """Normalise anything permission-shaped into a ``BasePermission`` instance.

    Accepts, in order of preference:

    * a ``BasePermission`` instance — returned unchanged;
    * a ``BasePermission`` subclass — instantiated with no arguments;
    * a duck-typed object with ``has_permission``;
    * a legacy class or object with ``is_permitted`` (see ``compat``);
    * a plain function ``(ctx) -> bool``, wrapped as a predicate.
    """
    if isinstance(value, BasePermission):
        return value

    if isinstance(value, type):
        if issubclass(value, BasePermission):
            try:
                return value()
            except (TypeError, ValueError) as exc:
                # A class handed over bare must be constructible with no
                # arguments. When it is not, say so here rather than letting a
                # bare TypeError surface from somewhere in the router.
                msg = (
                    f"{value.__name__} could not be constructed without arguments "
                    f"({exc}). Pass an instance rather than the class: "
                    f"{value.__name__}(...)"
                )
                raise ConfigurationError(msg) from exc
        if hasattr(value, "is_permitted"):
            from starlette_permissions.compat import LegacyPermission

            return LegacyPermission(value)
        if hasattr(value, "has_permission"):
            return _DuckPermission(value())
        msg = (
            f"{value.__name__} is not a permission: it should subclass "
            f"BasePermission or define has_permission()"
        )
        raise ConfigurationError(msg)

    if hasattr(value, "is_permitted"):
        from starlette_permissions.compat import LegacyPermission

        return LegacyPermission(value)

    if hasattr(value, "has_permission"):
        return _DuckPermission(value)

    if callable(value):
        from starlette_permissions.permissions.common import Predicate

        return Predicate(value)

    # Reachable at runtime even though PermissionLike nominally covers every
    # input: nothing stops a caller passing an int.
    msg = f"Cannot use {value!r} as a permission"  # type: ignore[unreachable]
    raise ConfigurationError(msg)


def resolve_permissions(
    permissions: Any,
) -> tuple[BasePermission, ...]:
    """Normalise one permission, or any nesting of lists/tuples of them.

    ``permission_required(IsAuthenticated)`` and the older
    ``permission_required([IsAuthenticated])`` both land here.
    """
    if permissions is None:
        return ()
    if isinstance(permissions, (list, tuple, set, frozenset)):
        resolved: list[BasePermission] = []
        for item in permissions:
            resolved.extend(resolve_permissions(item))
        return tuple(resolved)
    return (resolve_permission(permissions),)


class _DuckPermission(BasePermission):
    """Adapts an object that has ``has_permission`` but no shared base class."""

    def __init__(self, target: Any) -> None:
        self.target = target
        self.message = getattr(target, "message", BasePermission.message)
        self.status_code = getattr(target, "status_code", None)

    def has_permission(self, ctx: PermissionContext) -> bool | Awaitable[bool]:
        return self.target.has_permission(ctx)  # type: ignore[no-any-return]

    def has_object_permission(
        self,
        ctx: PermissionContext,
        obj: Any,
    ) -> bool | Awaitable[bool]:
        method = getattr(self.target, "has_object_permission", None)
        if method is None:
            return True
        return method(ctx, obj)  # type: ignore[no-any-return]

    def __repr__(self) -> str:
        return f"_DuckPermission({self.target!r})"
