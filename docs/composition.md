# Combining permissions

## Operators

`&`, `|` and `~` work on permission classes and instances alike:

```python
IsAuthenticated & IsAdminUser  # both
ReadOnly | IsAdminUser  # either
IsAuthenticated & ~IsSuspended  # authenticated, and not suspended
IsAuthenticated & (IsAdminUser | IsOwner("author_id"))
```

The result is itself a permission, so it can be stored, reused and passed
anywhere a single rule is expected:

```python
CanEditPost = IsAuthenticated & (IsAdminUser | IsOwner("author_id"))


@router.patch("/posts/{post_id}", dependencies=[requires(CanEditPost)])
async def edit_post(post_id: int): ...
```

## Lists mean AND

Passing several permissions requires **all** of them, as in Django and DRF:

```python
permission_required(IsAuthenticated, HasRole("editor"))  # both must pass
permission_required([IsAuthenticated, HasRole("editor")])  # the same thing
```

Switch with `mode`:

```python
permission_required(IsAdminUser, HasRole("editor"), mode="any")
```

The same `mode` argument is accepted by `requires`, `check_permissions`,
`has_permissions`, `PermissionMiddleware` and `PermissionMixin`.

## All and Any

The explicit forms, useful when the rules are built at runtime or when a flat
list reads better than a chain of `&`:

```python
from starlette_permissions import All, Any

All(IsAuthenticated, HasRole("editor"), ~IsSuspended)
Any(IsAdminUser, IsOwner("author_id"))

Any(*[HasRole(name) for name in allowed_roles])
```

Empty arguments follow Python's built-ins: `All()` allows (like `all([])`),
`Any()` denies (like `any([])`).

!!! note "`Any` shadows `typing.Any`"
    In a module that uses both, import the alias instead:
    `from starlette_permissions import Any_permission as AnyPermission`.

## Which message comes back?

Only one rule can explain the refusal, so:

- **`&`** reports the side that failed. Short-circuits: if the left side
  refuses, the right side never runs.
- **`|`** reports the **left** side when both fail. The first rule you wrote is
  usually the broader one, and this keeps the message stable regardless of
  evaluation order.
- **`~`** reports itself — the wrapped rule's message explains why it
  *allows*, which would be actively misleading here. Give it your own:

    ```python
    Not(IsSuspended, message="This account is suspended")
    ```

- A **list** in `mode="all"` reports the first failure; in `mode="any"`, the
  first rule's failure.

```python
ctx = make_context(user=User(roles=["editor"]))
await check_permissions(IsAuthenticated & HasRole("admin"), ctx)
# PermissionDenied: "Requires role: admin"    <- not "Permission denied"
```

The failing rule is also on the exception, for logging:

```python
except PermissionDenied as exc:
    logger.warning("denied by %r", exc.permission)
```

## Status codes in a composite

The status code comes from whichever rule reported the failure. So
`IsAuthenticated & IsAdminUser` answers `401` for an anonymous caller (the
authentication rule failed first) and `403` for a logged-in non-admin. That is
usually what you want; override it per endpoint if not:

```python
permission_required(IsAuthenticated & IsAdminUser, status_code=404)
```

## Short-circuiting is a feature

Both `&` and `|` stop as soon as the answer is known. Order expensive rules
last:

```python
# The database is only touched for callers who are already authenticated.
IsAuthenticated & HasActiveSubscription
```

## A caveat on `|` in annotations

`PermissionMeta` overrides `__or__` on permission *classes*, which is what
makes `IsAuthenticated | IsAdminUser` build a rule instead of a PEP 604 union.
The cost is that a permission class cannot appear in a `X | None` annotation —
write `Optional[IsAuthenticated]`, or quote the annotation. In practice this
comes up almost never, since permission classes are rarely used as types.
