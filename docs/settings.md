# Settings

One call at startup, before any request is served:

```python
from starlette_permissions import configure

configure(
    user_getter=lambda conn: getattr(conn.state.token, "user", None),
    admin_attrs=("is_admin",),
    unauthenticated_status_code=403,
)
```

An unknown key raises `TypeError` rather than being silently ignored.

## Reference

| Setting | Default | Purpose |
|---|---|---|
| `user_getter` | reads `scope["user"]`, then `state.user` | Resolves the current user. Return `None` for anonymous. |
| `role_getter` | reads `roles`, `groups`, `role` | Resolves role names from a user object. |
| `scope_getter` | reads `scope["auth"].scopes` | Resolves OAuth-style scopes from the connection. |
| `admin_attrs` | `("is_admin", "is_staff", "is_superuser")` | Attributes `IsAdminUser` checks, in order. |
| `authenticated_attr` | `"is_authenticated"` | Attribute consulted when the user object defines it. |
| `denied_status_code` | `403` | Status for a plain refusal. |
| `denied_message` | `"Permission denied"` | Default detail for a refusal. |
| `unauthenticated_status_code` | `401` | Status when no identity is attached. |
| `unauthenticated_message` | `"Authentication credentials were not provided."` | Detail for that case. |
| `authenticate_header` | `None` | Sent as `WWW-Authenticate` on 401s. |
| `denied_headers` | `{}` | Extra headers on every denial. |

## Finding the user

This is the one setting almost every project needs.

### Token on request.state

```python
configure(user_getter=lambda conn: getattr(conn.state.token, "user", None))
```

### User on request.state

```python
configure(user_getter=lambda conn: getattr(conn.state, "user", None))
```

### Starlette AuthenticationMiddleware

    Nothing to do — this is the default.

### Decoding a JWT per request

```python
def user_from_jwt(conn):
    header = conn.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return User(**jwt.decode(header[7:], KEY, algorithms=["HS256"]))
    except jwt.PyJWTError:
        return None


configure(user_getter=user_from_jwt)
```

    The result is cached on the context, so it is decoded once per request even
    if several permissions ask for the user.

!!! warning "`state` raises when the attribute is missing"
    Use `getattr(conn.state, "user", None)`, not `conn.state.user` — the
    latter raises `AttributeError` on an anonymous request.

## Roles and scopes

The default `role_getter` covers the common shapes: a list on `user.roles`, on
`user.groups`, or a single string on `user.role`. For anything else:

```python
configure(role_getter=lambda user: [g.name for g in user.groups])
```

Scopes come from the connection rather than the user, because that is where
`AuthenticationMiddleware` puts them:

```python
configure(scope_getter=lambda conn: getattr(conn.state.token, "scopes", ()))
```

## 401 versus 403

By default a missing identity gets `401` and an insufficient one gets `403`.
Some APIs prefer not to reveal that a route exists to anonymous callers:

```python
configure(
    unauthenticated_status_code=403,
    unauthenticated_message="Permission denied",
)
```

To send a `WWW-Authenticate` challenge, which some clients need in order to
retry with credentials:

```python
configure(authenticate_header='Bearer realm="api"')
```

## Per-application settings

Mounted sub-applications can carry their own bundle, which wins over the global
one:

```python
from starlette_permissions import PermissionSettings

internal_app.state.permission_settings = PermissionSettings(
    admin_attrs=("is_service_admin",),
    unauthenticated_status_code=403,
)
```

This is resolved per request from `scope["app"]`, so a mount and its parent can
use different rules without interfering.

## In tests

`override_settings` restores the previous bundle on exit:

```python
from starlette_permissions import override_settings

with override_settings(denied_message="nope"):
    ...
```

For a test suite that calls `configure()`, reset between tests:

```python
@pytest.fixture(autouse=True)
def _reset_settings():
    import starlette_permissions.settings as module

    original = module._settings
    yield
    module._settings = original
```
