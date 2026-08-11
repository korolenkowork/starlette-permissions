# FastAPI

Install the extra so `fastapi` is present:

```bash
pip install "starlette-permissions[fastapi]"
```

## Dependencies (recommended)

`requires(...)` returns a `Depends`, so it goes anywhere FastAPI accepts one.

```python
from starlette_permissions import IsAuthenticated, IsAdminUser
from starlette_permissions.dependencies import requires
```

### On one route

```python
@router.get("/me", dependencies=[requires(IsAuthenticated)])
async def get_me(): ...
```

### As a value

The dependency resolves to the `PermissionContext`, so the handler gets the
user without re-deriving it:

```python
from starlette_permissions import PermissionContext


@router.get("/profile")
async def profile(ctx: PermissionContext = requires(IsAuthenticated)):
    return {"name": ctx.user.name, "roles": list(ctx.roles)}
```

### On a whole router

The cleanest way to guard a section of the API:

```python
admin = APIRouter(prefix="/admin", dependencies=[requires(IsAdminUser)])


@admin.get("/stats")
async def stats(): ...


@admin.get("/users")
async def users(): ...


app.include_router(admin)
```

### On the whole app

```python
app = FastAPI(dependencies=[requires(IsAuthenticated)])
```

Prefer this over middleware when everything is a FastAPI route — it runs after
routing, so path parameters are available, and it does not intercept
`/docs` or static mounts.

## Documenting denials in OpenAPI

A dependency cannot add response schemas by itself. Spread the helper into the
route:

```python
from starlette_permissions.dependencies import permission_responses


@router.get(
    "/me",
    dependencies=[requires(IsAuthenticated)],
    responses=permission_responses(),
)
async def get_me(): ...
```

That documents `401` and `403`. Pass `permission_responses(unauthorized=False)`
to document only one.

For a router-wide default: `APIRouter(dependencies=[...], responses=permission_responses())`.

## Decorators

Use the decorator when you want the rule visually next to the handler, or when
sharing code with a plain Starlette app.

```python
from starlette.requests import Request
from starlette_permissions import permission_required


@router.get("/me")
@permission_required(IsAuthenticated)
async def get_me(request: Request):
    return request.state.user
```

!!! danger "Order matters"
    `@permission_required` must be **below** `@router.get`. Above it, the
    router registers the unguarded function and the check never runs.

    ```python
    @router.get("/me")           # 1. registers the guarded function
    @permission_required(...)    # 2. wraps the endpoint
    async def get_me(...): ...
    ```

### You do not need to declare `Request`

If the endpoint has no `Request` parameter, one is added to its signature so
FastAPI supplies it. Your handler never sees it, and it does not appear in the
OpenAPI schema:

```python
@router.get("/me")
@permission_required(IsAuthenticated)
async def get_me():  # no request parameter, works anyway
    return {"ok": True}
```

### Sync endpoints

Supported. FastAPI runs them in a worker thread, and the permission check is
run on the event loop from there — so async permissions work too.

```python
@router.get("/sync")
@permission_required(IsAuthenticated)
def sync_endpoint(request: Request):
    return {"ok": True}
```

## Error responses

`PermissionDenied` subclasses Starlette's `HTTPException`, so FastAPI's default
handler renders it as `{"detail": "..."}` with no setup. To customise:

```python
from starlette_permissions import PermissionDenied


@app.exception_handler(PermissionDenied)
async def on_denied(request: Request, exc: PermissionDenied):
    logger.warning("denied %s by %r", request.url.path, exc.permission)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
```

`exc.permission` is the rule that refused, which makes for far more useful
audit logs than the status code alone.

## Dependency injection alongside permissions

Permissions do not interfere with the rest of the dependency graph:

```python
@router.get("/me")
@permission_required(IsAuthenticated)
@inject
async def get_me(
    request: Request,
    service: UserService = Depends(Provide[Container.user_service]),
): ...
```

With `dependency-injector`, put `@permission_required` above `@inject` so the
permission check runs before the container resolves anything.
