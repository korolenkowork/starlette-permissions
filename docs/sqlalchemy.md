# SQLAlchemy

The library has no ORM dependency and never touches your database. What it
gives you is a place to put rules that do. This page covers the wiring that
makes database-backed permissions cheap instead of a per-request tax.

A complete runnable version of everything below is in
[`examples/sqlalchemy_app/`](https://github.com/korolenkowork/starlette-permissions/tree/main/examples/sqlalchemy_app),
and it is covered by the test suite.

## The one thing to get right: share the session

A permission that opens its own session runs outside the handler's
transaction and takes a second connection from the pool on every check. Put
one session on the request and let everything read it:

```python
@app.middleware("http")
async def db_session_and_user(request: Request, call_next):
    async with request.app.state.sessionmaker() as session:
        request.state.db = session

        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            request.state.user = await user_by_token(session, header.removeprefix("Bearer "))

        return await call_next(request)


configure(user_getter=lambda conn: getattr(conn.state, "user", None))
```

Resolving the user in the middleware rather than in `user_getter` is
deliberate. `user_getter` is synchronous and runs for every rule that mentions
the user; doing the query once per request and leaving a plain attribute behind
keeps it to a single round trip.

Permissions then take the session from the request:

```python
def session_of(ctx) -> AsyncSession:
    session = getattr(ctx.connection.state, "db", None)
    if session is None:
        raise RuntimeError("No AsyncSession on request.state.db")
    return session
```

!!! warning "Raise, do not return `False`"
    A missing session is a wiring mistake. Returning `False` would render it as
    a 403 and send you looking for a permissions bug that isn't there.

## Eager-load anything a permission reads

The default `role_getter` reads `user.roles`. If that walks a relationship,
it must be loaded before the rule runs — a lazy load under asyncio raises
`MissingGreenlet`, and it will happen inside a permission check, far from the
query that caused it.

```python
class User(Base):
    memberships: Mapped[list[Membership]] = relationship(back_populates="user")

    @property
    def roles(self) -> list[str]:
        return [m.role for m in self.memberships]


async def user_by_token(session, token):
    result = await session.execute(
        select(User)
        .where(User.api_token == token)
        .options(selectinload(User.memberships))  # <- not optional
    )
    return result.scalar_one_or_none()
```

`lazy="selectin"` on the relationship works too, and removes the chance of
forgetting at a call site.

## Three kinds of rule

### Decided from the request, plus a query

Nothing is loaded yet — the rule reads a path parameter and asks the database.
This runs *before* the handler body, so an unauthorised caller costs one
`SELECT` and no work.

```python
class IsTeamMember(BasePermission):
    def __init__(self, param: str = "team_id", role: str | None = None) -> None:
        self.param = param
        self.role = role
        self.message = (
            f"Requires the {role!r} role in this team" if role else "Team membership required"
        )

    async def has_permission(self, ctx) -> bool:
        if not ctx.is_authenticated:
            return False
        raw = ctx.view_kwargs.get(self.param, ctx.path_params.get(self.param))
        if raw is None:
            return False

        query = select(Membership.id).where(
            Membership.user_id == ctx.user.id,
            Membership.team_id == int(raw),
        )
        if self.role is not None:
            query = query.where(Membership.role == self.role)

        result = await session_of(ctx).execute(query.limit(1))
        return result.scalar_one_or_none() is not None
```

Reading `view_kwargs` with `path_params` as the fallback makes the same rule
work under the decorator and the dependency alike.

Attach it to a whole router:

```python
teams = APIRouter(prefix="/teams/{team_id}", dependencies=[requires(IsTeamMember())])
```

…and narrow it on the routes that need more:

```python
@teams.delete("/posts/{post_id}")
@permission_required(IsTeamMember(role="owner"))
async def delete_team_post(request: Request, team_id: int, post_id: int): ...
```

### Decided from the loaded row

No query at all — the answer is already in the object:

```python
class IsPostAuthor(BasePermission):
    message = "Only the author may modify this post"

    def has_object_permission(self, ctx, obj) -> bool:
        return ctx.is_authenticated and obj.author_id == ctx.user.id
```

`IsOwner("author_id")` from the library does exactly this, and reads ORM
attributes and dict keys alike.

### Decided from the row *and* a query

"A team owner may edit anything in their team" needs the post's `team_id`
before it can ask anything:

```python
class IsTeamOwnerOf(BasePermission):
    async def has_object_permission(self, ctx, obj) -> bool:
        result = await session_of(ctx).execute(
            select(Membership.id)
            .where(
                Membership.user_id == ctx.user.id,
                Membership.team_id == obj.team_id,
                Membership.role == "owner",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
```

## Composing, with the cheap rule first

```python
CanEditPost = IsPostAuthor | IsTeamOwnerOf()
```

`|` short-circuits, so for the common case — the author editing their own post
— the query never runs. Put free checks on the left and queries on the right.

## Checking after the load

Object rules cannot run until the row exists, so the handler loads first and
checks second. Load-then-404 before checking, so a missing row does not come
back as a denial:

```python
@app.patch("/posts/{post_id}")
async def edit_post(
    request: Request,
    post_id: int,
    ctx: PermissionContext = requires(IsAuthenticated),
):
    post = await request.state.db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    await check_object_permissions(CanEditPost, ctx, post)

    post.published = True
    await request.state.db.commit()
    return {"id": post.id, "published": post.published}
```

The `requires(IsAuthenticated)` dependency does the request-level half and
hands back the context; `check_object_permissions` does the object-level half.
They are separate stages because only your handler knows when the row arrived.

!!! tip "404 or 403?"
    Checking existence first means a stranger probing `/posts/999` learns the
    post does not exist. Reverse the order — check permissions against the row,
    treating "not found" as a denial — if you would rather not confirm which
    ids are real.

## Testing rules without an app

Object rules take a plain object, so most of them need no database at all:

```python
async def test_authors_own_their_posts():
    ctx = make_context(user=User(id=7))
    assert await has_object_permissions(IsOwner("author_id"), ctx, Post(author_id=7))
    assert not await has_object_permissions(IsOwner("author_id"), ctx, Post(author_id=8))
```

For a rule that queries, give the context a session the same way the
middleware would:

```python
ctx = make_context(user=user)
ctx.connection.state.db = session
assert await has_permissions(IsTeamMember(), ctx)
```

## Other ORMs

Nothing here is SQLAlchemy-specific beyond the query syntax. The pattern —
a request-scoped handle on `request.state`, a helper that fetches it, rules
that use it — applies unchanged to Tortoise, Piccolo, databases, or a plain
connection pool.
