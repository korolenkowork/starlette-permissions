# starlette-permissions

Django-style permission classes for **Starlette** and **FastAPI**.

An authorization rule is an object. It has a name, it can be tested on its own,
it can be reused across endpoints, and it reads as a sentence at the call site:

```python
@router.delete("/posts/{post_id}")
@permission_required(IsAuthenticated & IsAdminUser)
async def delete_post(request: Request, post_id: int): ...
```

That is the whole idea, borrowed from Django REST Framework and adapted to
ASGI. The alternative — a few lines of `if` at the top of every handler — works
until the rules are used in more than one place, or need to be checked in a
test, or need to be combined.

## Why this and not a plain dependency?

FastAPI's `Depends` already lets you reject a request. What it does not give
you is a *vocabulary*. Permissions here are values, so they compose:

```python
IsAuthenticated & (IsAdminUser | IsOwner("author_id")) & ~IsSuspended
```

and they can be inspected, listed per route, and unit-tested without an app:

```python
ctx = make_context(user=User(roles=["editor"]))
assert await has_permissions(HasRole("editor"), ctx)
```

## Design notes

- **Starlette is the only required dependency.** FastAPI is an optional extra,
  and nothing in the core imports it — the FastAPI helpers resolve lazily on
  first access.
- **Denials raise, they do not return.** `PermissionDenied` subclasses
  Starlette's `HTTPException`, so your exception handlers, error logging and
  middleware all see it. A permission layer that quietly returns a response is
  invisible to everything upstream.
- **Multiple permissions mean *all* of them**, as in Django and DRF. Adding a
  rule to a list tightens access; it never loosens it.
- **401 and 403 are distinguished.** A missing identity is `401`, a
  well-identified caller without rights is `403`. Both are configurable if you
  would rather not tell anonymous callers which routes exist.

## Where to go next

- **[Getting started](getting-started.md)** — install, configure, guard a route.
- **[Writing permissions](permissions.md)** — the `BasePermission` contract.
- **[Combining permissions](composition.md)** — `&`, `|`, `~`, `All`, `Any`.
- **[Object-level permissions](object-permissions.md)** — rules that need the record.
- **[FastAPI](fastapi.md)** / **[Starlette](starlette.md)** — framework specifics.
- **[SQLAlchemy](sqlalchemy.md)** — rules that query the database.
- **[Migrating from DRF](migration-from-drf.md)** — what maps to what.
