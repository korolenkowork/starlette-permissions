# Getting started

## Install

### pip

```bash
pip install starlette-permissions
```

### poetry

```bash
poetry add starlette-permissions
```

### uv

```bash
uv add starlette-permissions
```

The FastAPI dependency helpers need FastAPI itself:

```bash
pip install "starlette-permissions[fastapi]"
```

Python 3.10 through 3.14, Starlette 0.35 or newer, and — for the FastAPI
helpers — FastAPI 0.110 or newer. The full range is verified in CI; see
[compatibility](compatibility.md) for the tested ceiling.

## 1. Tell the library where the user is

Every permission that talks about "the user" calls one function to find it.
Configure that once, at startup, before any request is served:

```python
from starlette_permissions import configure

configure(user_getter=lambda conn: getattr(conn.state, "user", None))
```

If your auth layer puts a token on the request instead:

```python
configure(user_getter=lambda conn: getattr(conn.state.token, "user", None))
```

!!! tip "Using Starlette's AuthenticationMiddleware?"
    Then you can skip this entirely. The default getter reads `scope["user"]`
    (where `AuthenticationMiddleware` puts it) and falls back to
    `request.state.user`.

The getter returns `None` for an anonymous request. Anything else counts as a
user — unless the object itself says otherwise via an `is_authenticated`
attribute, which is how Starlette's `UnauthenticatedUser` is understood.

## 2. Guard a route

### FastAPI (dependency)

```python
from fastapi import APIRouter
from starlette_permissions import IsAuthenticated
from starlette_permissions.dependencies import requires

router = APIRouter()


@router.get("/me", dependencies=[requires(IsAuthenticated)])
async def get_me(): ...
```

### FastAPI (decorator)

```python
from starlette.requests import Request
from starlette_permissions import IsAuthenticated, permission_required


@router.get("/me")
@permission_required(IsAuthenticated)
async def get_me(request: Request): ...
```

The decorator goes **below** the route decorator. Above it, the router
would register the unguarded function.

### Starlette

```python
from starlette_permissions import IsAuthenticated, permission_required


@permission_required(IsAuthenticated)
async def me(request):
    return JSONResponse({"ok": True})
```

An anonymous request now gets `401`; a request from a user who fails a
different rule gets `403`.

## 3. Make denials render as JSON

FastAPI already does — its default `HTTPException` handler returns
`{"detail": ...}`.

Plain Starlette renders `HTTPException` as **plain text**, which is rarely
what an API wants. One call fixes it:

```python
from starlette_permissions import install_exception_handlers

app = Starlette(routes=[...])
install_exception_handlers(app)
```

## 4. Write your own rule

```python
from starlette_permissions import BasePermission


class HasActiveSubscription(BasePermission):
    message = "An active subscription is required"

    async def has_permission(self, ctx):
        return await billing.is_active(ctx.user.id)
```

Use it exactly like the built-ins:

```python
@permission_required(IsAuthenticated & HasActiveSubscription)
async def premium(request: Request): ...
```

`has_permission` may be `def` or `async def`. It receives a
[`PermissionContext`](permissions.md#the-context) and returns a bool.

## What next

- [Writing permissions](permissions.md) — the full contract.
- [Combining permissions](composition.md) — `&`, `|`, `~`.
- [Settings](settings.md) — roles, scopes, status codes, per-app config.
