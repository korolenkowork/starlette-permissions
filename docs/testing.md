# Testing

The point of permissions-as-objects is that you can test the rule without
standing up an app, and test the wiring separately.

## Testing a rule directly

`make_context` builds a `PermissionContext` from keyword arguments:

```python
from starlette_permissions import has_permissions
from starlette_permissions.testing import make_context


async def test_editors_may_publish():
    ctx = make_context(user=User(roles=["editor"]), method="POST")
    assert await has_permissions(CanPublish, ctx)


async def test_readers_may_not():
    ctx = make_context(user=User(roles=["reader"]), method="POST")
    assert not await has_permissions(CanPublish, ctx)
```

Available arguments: `user`, `auth`, `method`, `path`, `headers`,
`query_string`, `path_params`, `app`, plus `view_kwargs`, `endpoint` and
`settings` for the context itself.

```python
make_context(
    user=User(id=1),
    method="DELETE",
    headers={"X-API-Key": "s3cret"},
    path_params={"post_id": 7},
)
```

`user` is placed on the ASGI scope where `AuthenticationMiddleware` would put
it, so the default `user_getter` finds it. If you have configured a custom
getter, pass a matching `settings` bundle instead:

```python
from starlette_permissions import PermissionSettings

ctx = make_context(settings=PermissionSettings(user_getter=lambda conn: my_user))
```

## Asserting on the refusal

```python
import pytest
from starlette_permissions import PermissionDenied, check_permissions


async def test_message_and_status():
    with pytest.raises(PermissionDenied) as exc_info:
        await check_permissions(HasRole("admin"), make_context(user=User()))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Requires role: admin"
    assert isinstance(exc_info.value.permission, HasAnyRole)
```

## Object-level rules

```python
from starlette_permissions import has_object_permissions


async def test_authors_own_their_posts():
    ctx = make_context(user=User(id=7))
    assert await has_object_permissions(IsOwner("author_id"), ctx, {"author_id": 7})
    assert not await has_object_permissions(IsOwner("author_id"), ctx, {"author_id": 8})
```

A plain dict is enough — `IsOwner` reads dict keys and attributes alike.

## Testing the wiring

Rules are unit-tested above; here you are checking that the right rule is on
the right route. A `TestClient` and one request per outcome is plenty:

```python
from fastapi.testclient import TestClient


def test_admin_route_rejects_regular_users(client):
    assert client.delete("/posts/1", headers={"x-user": "ihor"}).status_code == 403
    assert client.delete("/posts/1", headers={"x-user": "admin"}).status_code == 200
    assert client.delete("/posts/1").status_code == 401
```

## Reading permissions off a route

`get_permissions` returns what a decorated endpoint is guarded by — useful for
a test that asserts no route was left unguarded by accident:

```python
from starlette_permissions import get_permissions


def test_every_admin_route_is_guarded():
    for route in admin_router.routes:
        assert get_permissions(route.endpoint), f"{route.path} has no permissions"
```

## Resetting configuration between tests

`configure()` mutates a module-level singleton, so a test that changes it will
leak into the next one. Add an autouse fixture:

```python
@pytest.fixture(autouse=True)
def _reset_settings():
    import starlette_permissions.settings as module

    original = module._settings
    yield
    module._settings = original
```

Or scope the change with the context manager:

```python
from starlette_permissions import override_settings


def test_with_custom_admins():
    with override_settings(admin_attrs=("is_root",)):
        ...
```

## A note on sync endpoints

A decorated `def` endpoint can be called directly in a test, with no event loop
involved, as long as its permissions are synchronous — or asynchronous but
non-suspending:

```python
def test_sync_endpoint_directly():
    assert my_endpoint(make_request()) == expected
```

A permission that performs real I/O needs a loop; call it through a
`TestClient`, or make the endpoint `async def`. The error message says as much
if you hit it.
