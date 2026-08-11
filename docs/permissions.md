# Writing permissions

## The contract

Subclass `BasePermission` and override one method:

```python
from starlette_permissions import BasePermission


class IsBetaTester(BasePermission):
    message = "Beta programme members only"

    def has_permission(self, ctx) -> bool:
        return "beta" in ctx.roles
```

| Attribute | Purpose |
|---|---|
| `has_permission(ctx)` | The decision. `def` or `async def`; returns a bool. |
| `has_object_permission(ctx, obj)` | The decision for one record. See [object-level](object-permissions.md). |
| `message` | Response detail when this rule refuses. |
| `status_code` | Overrides the refusal status. `None` uses the configured default (403). |
| `exception_class` | The exception raised. Use `NotAuthenticated` for a 401. |

!!! warning "Instances are shared between requests"
    A permission instance is created once, when the route is defined, and
    reused for every request. Keep them immutable — store configuration on
    `self` in `__init__`, and nothing else. All per-request state belongs on
    the context.

## The context

`has_permission` receives a `PermissionContext`:

| Attribute | What it gives you |
|---|---|
| `ctx.connection` | The `Request` or `WebSocket`. `ctx.request` is an alias. |
| `ctx.user` | The current user, or `None`. Resolved once, then cached. |
| `ctx.is_authenticated` | Whether an identity is attached. |
| `ctx.roles` | Role names, via the configured `role_getter`. |
| `ctx.scopes` | OAuth-style scopes, via the configured `scope_getter`. |
| `ctx.method` | The HTTP method, uppercased. `""` for WebSockets. |
| `ctx.is_safe_method` | `True` for GET, HEAD, OPTIONS. |
| `ctx.headers` | The request headers. |
| `ctx.path_params` | Path parameters from the router. |
| `ctx.view_kwargs` | The arguments the endpoint was called with. |
| `ctx.settings` | The settings bundle in force for this connection. |
| `ctx.endpoint` | The view function, when the check runs on one. |

`view_kwargs` is the one worth explaining. For a route like
`/tenants/{tenant}/posts`, it lets a rule read the path parameter directly:

```python
class BelongsToTenant(BasePermission):
    message = "Not a member of this tenant"

    async def has_permission(self, ctx):
        tenant = ctx.view_kwargs.get("tenant") or ctx.path_params.get("tenant")
        return tenant in ctx.user.tenants
```

!!! note
    `view_kwargs` is empty when the check runs from
    [`PermissionMiddleware`](starlette.md#middleware), because middleware runs
    before routing. Use `ctx.path_params`, or move the rule onto the route.

## Parametrized permissions

Because permissions are objects, they take arguments:

```python
class HasPlan(BasePermission):
    def __init__(self, *plans: str) -> None:
        self.plans = frozenset(plans)
        self.message = f"Requires plan: {' or '.join(sorted(self.plans))}"

    def has_permission(self, ctx) -> bool:
        return ctx.user is not None and ctx.user.plan in self.plans
```

```python
@permission_required(HasPlan("pro", "enterprise"))
async def reports(request: Request): ...
```

Anywhere a permission is expected you may pass a class (instantiated for you)
or an instance. A class that *needs* arguments must be passed as an instance —
you get a clear error if you forget.

## Functions as permissions

For a rule used once, a class is overkill:

```python
from starlette_permissions import permission


@permission(message="Requests must come from the office network")
def from_office(ctx):
    return ctx.connection.client.host.startswith("10.")


@permission_required(from_office)
async def internal(request: Request): ...
```

Without arguments, the decorator uses the docstring's first line as the
message:

```python
@permission
def has_beta_flag(ctx):
    """Beta programme members only."""
    return "beta" in ctx.roles
```

A bare lambda works too, and is wrapped automatically:

```python
@permission_required(lambda ctx: ctx.headers.get("x-tenant") == "acme")
async def acme_only(request: Request): ...
```

## Customising the refusal

Return `False` and the rule's `message` and `status_code` are used. To vary the
response — adding a `Retry-After`, say — override `denial`:

```python
from starlette_permissions import BasePermission, PermissionDenied


class NotRateLimited(BasePermission):
    message = "Rate limit exceeded"
    status_code = 429

    def has_permission(self, ctx):
        return not limiter.is_limited(ctx.user)

    def denial(self, ctx=None):
        return PermissionDenied(
            self.message,
            status_code=self.status_code,
            headers={"Retry-After": "60"},
            permission=self,
        )
```

To answer `401` instead of `403`, point `exception_class` at
`NotAuthenticated`:

```python
from starlette_permissions import NotAuthenticated


class HasValidToken(BasePermission):
    exception_class = NotAuthenticated
    message = "Token expired"
```

## Async permissions and sync endpoints

`has_permission` can be `async def` even when the endpoint is `def` — FastAPI
and Starlette run sync endpoints in a worker thread, and the check is run on
the event loop from there.

The one case that cannot work is calling a decorated `def` endpoint *directly*,
outside any event loop, with a permission that does real I/O. That raises
`SyncCheckError` with an explanation rather than deadlocking. Sync permissions,
and async ones that never actually suspend, work fine even then — which keeps
plain unit tests of decorated endpoints simple.

## Checking outside a handler

The same rules work in a service layer, where there is no endpoint to decorate:

```python
from starlette_permissions import check_permissions, has_permissions, PermissionContext

ctx = PermissionContext(request)

await check_permissions(IsAuthenticated & HasPlan("pro"), ctx)  # raises
if await has_permissions(IsAdminUser, ctx):  # returns bool
    payload["internal_notes"] = notes
```

`has_permissions` is the right tool when a denial should trim the response
rather than fail the request.
