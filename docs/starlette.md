# Starlette

No extra install needed — `starlette` is the only required dependency.

## Render denials as JSON

Starlette's built-in `HTTPException` handler returns `PlainTextResponse`. For
an API you almost certainly want JSON:

```python
from starlette.applications import Starlette
from starlette_permissions import install_exception_handlers

app = Starlette(routes=[...])
install_exception_handlers(app)
```

Or write your own handler:

```python
from starlette_permissions import PermissionDenied


async def on_denied(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.add_exception_handler(PermissionDenied, on_denied)
```

`NotAuthenticated` subclasses `PermissionDenied`, so one handler covers both.

## Function endpoints

```python
from starlette_permissions import IsAuthenticated, permission_required


@permission_required(IsAuthenticated)
async def me(request):
    return JSONResponse({"user": request.scope["user"].name})


app = Starlette(routes=[Route("/me", me)])
```

Starlette passes the request positionally, so nothing special happens here —
no signature rewriting is involved.

## Class-based endpoints

`PermissionMixin` checks before dispatching. It must come **before**
`HTTPEndpoint` in the base list, so its `dispatch` runs first.

```python
from starlette.endpoints import HTTPEndpoint
from starlette_permissions import IsAuthenticated, PermissionMixin


class MeEndpoint(PermissionMixin, HTTPEndpoint):
    permission_classes = [IsAuthenticated]

    async def get(self, request):
        return JSONResponse({"ok": True})
```

### Per-method rules

Once reads and writes differ, use a mapping. The `"*"` entry applies to every
method and **combines** with the method-specific one rather than being replaced
by it:

```python
class PostEndpoint(PermissionMixin, HTTPEndpoint):
    permission_classes = {
        "*": IsAuthenticated,  # every method
        "DELETE": IsAdminUser,  # DELETE needs both
    }

    async def get(self, request): ...
    async def delete(self, request): ...
```

Set `permission_mode = "any"` on the class to require only one rule instead of
all of them.

## Middleware

For a blanket policy — "everything needs a login except these paths":

```python
import re
from starlette.middleware import Middleware
from starlette_permissions import IsAuthenticated, PermissionMiddleware

app = Starlette(
    routes=[...],
    middleware=[
        Middleware(
            PermissionMiddleware,
            permissions=IsAuthenticated,
            exempt=["/health", re.compile(r"/auth/.*")],
        )
    ],
)
```

`exempt` takes exact-match strings and compiled patterns; a `str` is never
treated as a regex, so a path containing a `.` behaves as written.

Restrict to certain methods with `methods=["POST", "PUT", "PATCH", "DELETE"]`.

Two things to know:

!!! note "Path parameters are not available"
    Middleware runs before routing, so `ctx.view_kwargs` is empty and
    `ctx.path_params` is unpopulated. Rules that need a path parameter belong
    on the route.

!!! note "It renders its own response"
    Added via `add_middleware`, it sits *outside* Starlette's
    `ExceptionMiddleware`, where a raised `HTTPException` would surface as a
    500. So it builds the JSON denial itself, and your `PermissionDenied`
    exception handler will not see it. Use route-level guards if you need that
    hook.

### Route-scoped middleware

Applied to one route (or a `Mount`), the rule sits inside the exception
machinery and behaves like the other integration points:

```python
Route(
    "/admin",
    admin_endpoint,
    middleware=[Middleware(PermissionMiddleware, permissions=IsAdminUser)],
)
```

## Working with AuthenticationMiddleware

Starlette's own auth middleware puts the user on `scope["user"]` and scopes on
`scope["auth"]`, which is exactly where the defaults look. No `configure()`
call is needed:

```python
from starlette.middleware.authentication import AuthenticationMiddleware

app = Starlette(
    routes=[...],
    middleware=[Middleware(AuthenticationMiddleware, backend=MyBackend())],
)
```

`IsAuthenticated` then respects `UnauthenticatedUser` (whose
`is_authenticated` is `False`), and `HasScope(...)` reads the
`AuthCredentials` scopes:

```python
@permission_required(HasScope("posts:write"))
async def create_post(request): ...
```

## WebSockets

`PermissionMiddleware` guards WebSocket connections too, closing them with code
`1008` (policy violation) on refusal. The context's `is_websocket` is `True`
and `method` is `""`, so method-based rules such as `ReadOnly` do not apply —
write explicit rules for WebSocket routes.
