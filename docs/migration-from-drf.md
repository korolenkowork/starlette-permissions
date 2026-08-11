# Migrating from DRF

If you know `rest_framework.permissions`, most of this library will already be
familiar. This page covers what maps directly and what deliberately differs.

## What maps directly

| DRF | Here |
|---|---|
| `BasePermission` | `BasePermission` |
| `has_permission(request, view)` | `has_permission(ctx)` |
| `has_object_permission(request, view, obj)` | `has_object_permission(ctx, obj)` |
| `permission_classes = [...]` | `permission_classes = [...]` on `PermissionMixin`, or `permission_required(...)` |
| `AllowAny` | `AllowAny` |
| `IsAuthenticated` | `IsAuthenticated` |
| `IsAdminUser` | `IsAdminUser` |
| `IsAuthenticatedOrReadOnly` | `IsAuthenticatedOrReadOnly` |
| `SAFE_METHODS` | `SAFE_METHODS` |
| `message` | `message` |
| `&`, `\|`, `~` on classes | the same |

The most common rewrite is mechanical:

```python
# DRF
class IsEditor(BasePermission):
    message = "Editors only"

    def has_permission(self, request, view):
        return request.user.is_authenticated and "editor" in request.user.roles
```

```python
# here
class IsEditor(BasePermission):
    message = "Editors only"

    def has_permission(self, ctx):
        return ctx.is_authenticated and "editor" in ctx.roles
```

`request` and `view` collapse into one `ctx`: `ctx.connection` is the request,
`ctx.endpoint` is the view, and `ctx.user` / `ctx.roles` / `ctx.is_authenticated`
save the usual boilerplate.

## What differs

### Object permissions are not automatic

DRF's generic views call `check_object_permissions` for you inside
`get_object()`. There is no generic view here, so nothing can know when your
object has been loaded — you call it:

```python
post = await posts.get(post_id)
await check_object_permissions(rules, ctx, post)
```

See [object-level permissions](object-permissions.md) for the decorator and
dependency forms that make this shorter.

### There is no authentication layer

DRF bundles authentication and authorization. This library does authorization
only; how the user gets onto the request is yours to decide. Point
`user_getter` at wherever your auth middleware puts it — see
[settings](settings.md).

A consequence: DRF chooses between 401 and 403 based on whether an
authenticator supplied a `WWW-Authenticate` header. Here, `IsAuthenticated`
simply raises 401 and everything else raises 403, both configurable.

### `has_permission` may be async

DRF's is strictly synchronous. Here either method may be `async def`, which
matters when the rule needs a database or cache lookup.

### Permission instances are shared

DRF instantiates `permission_classes` per request. Here an instance is created
once when the route is defined and reused, which is what makes
`HasRole("admin")` cheap. Keep permissions immutable — store configuration in
`__init__` and nothing else.

### No `DjangoModelPermissions`

There is no ORM to introspect. `IsOwner` covers the common case; anything
model-aware is a rule you write.
