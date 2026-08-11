# Object-level permissions

Some rules cannot be decided from the request alone. "You may edit your own
posts" needs the post. The check therefore has to happen *after* the record is
loaded, which is why it lives in a separate method.

```python
from starlette_permissions import BasePermission


class IsAuthor(BasePermission):
    message = "Only the author may edit this post"

    def has_object_permission(self, ctx, obj) -> bool:
        return obj.author_id == ctx.user.id
```

`has_permission` still defaults to allowing everything, so a rule like this
never blocks a request before the object exists.

## Running the check

### With a dependency (FastAPI)

`requires_object` hands your handler a checker. Call it with the record:

```python
from starlette_permissions import IsOwner
from starlette_permissions.dependencies import requires_object


@router.patch("/posts/{post_id}")
async def edit_post(post_id: int, body: PostUpdate, check=requires_object(IsOwner("author_id"))):
    post = await posts.get(post_id)
    await check(post)  # raises PermissionDenied unless the user owns it
    return await posts.update(post, body)
```

`check` returns the object, so it can be used inline: `post = await
check(await posts.get(post_id))`.

### With a getter (any framework)

Load and check *before* the handler body runs. Prefer this when the handler
does real work — nothing happens if the caller is refused:

```python
from starlette_permissions import object_permission_required


@router.delete("/posts/{post_id}")
@object_permission_required(IsOwner("author_id"), getter=lambda post_id, **_: posts.get(post_id))
async def delete_post(post_id: int):
    await posts.delete(post_id)
```

The getter receives the endpoint's own keyword arguments and may be sync or
async.

### On the return value

For a plain "fetch and return" route, the handler's return value *is* the
object:

```python
@router.get("/posts/{post_id}")
@object_permission_required(IsOwner("author_id"))
async def get_post(post_id: int):
    return await posts.get(post_id)
```

Simple, but the fetch has already happened by the time the check runs. Use the
getter form when that matters.

### Manually

```python
from starlette_permissions import check_object_permissions, has_object_permissions

await check_object_permissions(IsOwner("author_id"), ctx, post)  # raises
if await has_object_permissions(IsOwner("author_id"), ctx, post):  # returns bool
    ...
```

!!! tip "Using an ORM?"
    [SQLAlchemy](sqlalchemy.md) covers the wiring for rules that query the
    database — sharing the request's session, eager-loading what a rule reads,
    and ordering `|` so the cheap check runs first.

## Built-in object rules

### `IsOwner`

```python
IsOwner()  # compares obj.user_id to user.id
IsOwner("author_id")  # compares obj.author_id to user.id
IsOwner("owner", user_id=lambda user: user.uuid)
```

Reads attributes and dict keys alike, so it works with ORM models,
dataclasses and plain dicts. The user's identifier is the first of `id`, `pk`,
`uuid`, `user_id` that exists, unless you pass `user_id=`.

!!! warning "A missing owner field is an error, not a denial"
    If the object has no such attribute, `IsOwner` raises `AttributeError`
    rather than refusing. A typo in the field name is a bug, and silently
    denying every request would hide it.

### `IsOwnerOrReadOnly`

Anyone may read the object; only the owner may modify it. Takes the same
arguments as `IsOwner`.

## Composition works here too

`&`, `|` and `~` traverse object-level checks exactly as they do request-level
ones:

```python
IsAdminUser | IsOwner("author_id")  # admins bypass ownership
IsAuthenticated & IsOwner("author_id")
```

Rules with no `has_object_permission` — `IsAuthenticated`, `HasRole`, and most
others — allow by default at the object stage, so mixing them in never vetoes
a record.

!!! note "Request-level rules are not re-run"
    `check_object_permissions` only calls `has_object_permission`. If a
    composite mixes both kinds, run both checks:

    ```python
    await check_permissions(rules, ctx)  # before loading
    post = await posts.get(post_id)
    await check_object_permissions(rules, ctx, post)  # after
    ```

    The dependency and decorator forms above do the request-level check for you
    only if you also attach `requires(...)` — they are separate stages by
    design, because only you know when the object is available.
