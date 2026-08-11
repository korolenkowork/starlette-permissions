# starlette-permissions

Django-style permission classes for **Starlette** and **FastAPI**.

If you have written Django REST Framework permissions, this will look familiar:
declare a rule as a class, combine rules with `&`, `|` and `~`, and attach them
to a route. If you haven't, the whole idea is that authorization rules are
*objects* — testable on their own, reusable across endpoints, and readable at
the call site.

```python
from starlette_permissions import IsAuthenticated, IsAdminUser, permission_required


@router.delete("/posts/{post_id}")
@permission_required(IsAuthenticated & IsAdminUser)
async def delete_post(request: Request, post_id: int): ...
```

- **Starlette-first.** The only required dependency is `starlette`. FastAPI is
  an optional extra, and nothing in the core imports it.
- **Three ways in.** A decorator, a FastAPI dependency, and a mixin for
  `HTTPEndpoint` — all driven by the same permission objects.
- **Composable.** `IsAuthenticated & (IsAdminUser | IsOwner("author_id"))`
  means what it looks like it means.
- **Object-level rules.** "You may edit your own posts" is a first-class case,
  not something you hand-roll in every handler.
- **Typed.** Ships `py.typed`; the public API is fully annotated.

## Install

```bash
pip install starlette-permissions
```

For FastAPI's `requires(...)` dependency:

```bash
pip install "starlette-permissions[fastapi]"
```

### Supported versions

| | Minimum | Newest tested |
|---|---|---|
| Python | 3.10 | **3.14** |
| Starlette | 0.35 | **1.6.0** |
| FastAPI *(extra)* | 0.110 | **0.141.1** |

Both ends are pinned and exercised by CI, not merely declared — see
[compatibility](docs/compatibility.md). The package metadata deliberately sets
no upper bound, so newer releases install freely; the ceiling records what has
actually been tested. FastAPI below 0.110 pins Starlette under 0.28 and cannot
be combined with a supported Starlette.

## Quick start

Tell the library how to find your user, once, at startup:

```python
from starlette_permissions import configure

configure(user_getter=lambda conn: getattr(conn.state, "user", None))
```

If you use Starlette's `AuthenticationMiddleware`, you can skip that — the
default reads `scope["user"]` and `request.state.user` already.

### FastAPI

The dependency form is the idiomatic one. It needs no `Request` parameter, it
shows up in the dependency graph, and it can be attached to a whole router:

```python
from fastapi import APIRouter
from starlette_permissions import IsAuthenticated, PermissionContext
from starlette_permissions.dependencies import requires

router = APIRouter()


@router.get("/me", dependencies=[requires(IsAuthenticated)])
async def get_me(): ...


# Or take the context as a value, and get the user for free:
@router.get("/profile")
async def profile(ctx: PermissionContext = requires(IsAuthenticated)):
    return ctx.user


# Or guard everything under one router:
admin = APIRouter(dependencies=[requires(IsAdminUser)])
```

### Starlette

```python
from starlette.applications import Starlette
from starlette.routing import Route
from starlette_permissions import IsAuthenticated, permission_required, install_exception_handlers


@permission_required(IsAuthenticated)
async def me(request):
    return JSONResponse({"user": request.state.user.name})


app = Starlette(routes=[Route("/me", me)])
install_exception_handlers(app)  # renders denials as JSON instead of plain text
```

Class-based endpoints get a mixin:

```python
class PostEndpoint(PermissionMixin, HTTPEndpoint):
    permission_classes = {"*": IsAuthenticated, "DELETE": IsAdminUser}
```

## Writing a permission

Subclass `BasePermission` and override `has_permission`. It receives a
`PermissionContext` — the connection, the resolved user, roles, scopes, and the
endpoint's own arguments — and returns a bool. Sync or async, your choice.

```python
from starlette_permissions import BasePermission


class HasActiveSubscription(BasePermission):
    message = "An active subscription is required"

    async def has_permission(self, ctx):
        return await billing.is_active(ctx.user.id)
```

For one-off rules, a function is enough:

```python
from starlette_permissions import permission


@permission(message="Requests must come from the office network")
def from_office(ctx):
    return ctx.connection.client.host.startswith("10.")
```

## Object-level rules

Some rules can't be decided until the record is loaded. Those go in
`has_object_permission`, and run through `check_object_permissions`:

```python
from starlette_permissions import IsOwner, check_object_permissions
from starlette_permissions.dependencies import requires_object


@router.patch("/posts/{post_id}")
async def edit_post(post_id: int, check=requires_object(IsOwner("author_id"))):
    post = await posts.get(post_id)
    await check(post)  # raises 403 unless ctx.user owns it
    return await posts.update(post, ...)
```

## Built-in permissions

| Permission | Allows when |
|---|---|
| `AllowAny` | always |
| `DenyAll` | never |
| `IsAuthenticated` | a user is attached (401 otherwise) |
| `IsAnonymous` | no user is attached |
| `IsAdminUser` | user has `is_admin` / `is_staff` / `is_superuser` |
| `IsAuthenticatedOrReadOnly` | always for GET/HEAD/OPTIONS, else authenticated |
| `ReadOnly` | method is GET/HEAD/OPTIONS |
| `IsMethod("POST", ...)` | method is listed |
| `HasRole("admin")` | user has any of the given roles |
| `HasAllRoles("a", "b")` | user has every given role |
| `HasScope("posts:write")` | credentials carry any of the given scopes |
| `HasAPIKey(key=...)` | request carries a matching API key |
| `HasHeader("X-Tenant")` | header is present (and matches, if a value is given) |
| `IsOwner("user_id")` | *(object-level)* the object belongs to the user |
| `IsOwnerOrReadOnly()` | *(object-level)* anyone reads, only the owner writes |

## Combining

`&`, `|` and `~` work on classes and instances alike:

```python
permission_required(IsAuthenticated & ~IsBanned)
permission_required(ReadOnly | IsAdminUser)
permission_required(All(IsAuthenticated, HasRole("editor"), ~IsSuspended))
```

Multiple permissions default to **all must pass**, as in Django and DRF:

```python
permission_required(IsAuthenticated, HasRole("editor"))  # both
permission_required(IsAuthenticated, HasRole("editor"), mode="any")  # either
```

## Documentation

Full docs: <https://korolenkowork.github.io/starlette-permissions/>

- [Getting started](docs/getting-started.md)
- [Writing permissions](docs/permissions.md)
- [Composition](docs/composition.md)
- [Object-level permissions](docs/object-permissions.md)
- [FastAPI guide](docs/fastapi.md) · [Starlette guide](docs/starlette.md) · [SQLAlchemy guide](docs/sqlalchemy.md)
- [Settings](docs/settings.md) · [Testing](docs/testing.md)
- [Migrating from DRF](docs/migration-from-drf.md)

## Contributing

```bash
poetry install --with dev
poetry run pytest -q && poetry run ruff check . && poetry run mypy
```

[AGENTS.md](AGENTS.md) documents the conventions and the handful of rules that
are load-bearing rather than cosmetic — why dependencies are never capped, why
`dependencies.py` cannot use `from __future__ import annotations`, and what the
four CI environments each prove. Written for AI agents, useful for anyone.

Releases publish to PyPI **only** from a pushed tag matching
`v[0-9]+.[0-9]+.[0-9]+*`; see the release steps in AGENTS.md.

## License

MIT
