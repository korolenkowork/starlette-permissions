"""FastAPI + SQLAlchemy 2.0 (async) with database-backed permissions.

    uvicorn examples.sqlalchemy_app.main:app --reload

Authentication is a bearer token matching ``users.api_token``; the seeded
tokens are ``tok-root`` (admin), ``tok-ihor`` (owner of team acme),
``tok-dana`` (member of acme) and ``tok-outsider`` (globex only).

    A=Authorization
    curl -i localhost:8000/me                     -H "$A: Bearer tok-ihor"
    curl -i localhost:8000/teams/1/posts          -H "$A: Bearer tok-dana"     # 200
    curl -i localhost:8000/teams/1/posts          -H "$A: Bearer tok-outsider" # 403
    curl -i -X PATCH localhost:8000/posts/2       -H "$A: Bearer tok-dana"     # 200, own post
    curl -i -X PATCH localhost:8000/posts/2       -H "$A: Bearer tok-ihor"     # 200, team owner
    curl -i -X PATCH localhost:8000/posts/1       -H "$A: Bearer tok-dana"     # 403
    curl -i -X DELETE localhost:8000/teams/1/posts/2 -H "$A: Bearer tok-dana"  # 403, owners only
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from examples.sqlalchemy_app.models import (
    Post,
    create_schema,
    make_engine,
    make_sessionmaker,
    seed,
    user_by_token,
)
from examples.sqlalchemy_app.permissions import (
    CanEditPost,
    IsPostAuthor,
    IsTeamMember,
)
from fastapi import APIRouter, FastAPI, HTTPException
from sqlalchemy import select
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from starlette_permissions import (
    IsAdminUser,
    IsAuthenticated,
    PermissionContext,
    check_object_permissions,
    configure,
    permission_required,
)
from starlette_permissions.dependencies import permission_responses, requires

# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    app.state.sessionmaker = make_sessionmaker(engine)
    await create_schema(engine)
    async with app.state.sessionmaker() as session:
        await seed(session)
    yield
    await engine.dispose()


class DbSessionMiddleware:
    """Open one session per request, and resolve the caller from its token.

    Both land on ``request.state``: the session so permissions can query
    without opening their own, and the user so ``user_getter`` stays a plain
    attribute read rather than an await — permissions are checked often, and
    the lookup should happen once per request, not once per rule.

    Written as pure ASGI rather than ``@app.middleware("http")``. Starlette's
    ``BaseHTTPMiddleware`` runs the rest of the app in a separate task, which
    costs a pair of memory object streams per request and interferes with
    streaming responses. Nothing here needs that machinery.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        sessionmaker = scope["app"].state.sessionmaker
        async with sessionmaker() as session:
            # request.state reads straight through to scope["state"].
            state = scope.setdefault("state", {})
            state["db"] = session

            header = Headers(scope=scope).get("authorization", "")
            if header.startswith("Bearer "):
                state["user"] = await user_by_token(session, header.removeprefix("Bearer "))

            await self.app(scope, receive, send)


app = FastAPI(title="starlette-permissions + SQLAlchemy", lifespan=lifespan)
app.add_middleware(DbSessionMiddleware)

# The user is already on request.state by the time any permission runs.
configure(user_getter=lambda conn: getattr(conn.state, "user", None))


async def get_post(request: Request, post_id: int) -> Post:
    post = await request.state.db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/me", responses=permission_responses())
async def me(ctx: PermissionContext = requires(IsAuthenticated)):
    """The context resolves to the ORM User, roles included."""
    return {"id": ctx.user.id, "name": ctx.user.name, "roles": list(ctx.roles)}


# -- request-level rule backed by a query -----------------------------------

teams = APIRouter(prefix="/teams/{team_id}", dependencies=[requires(IsTeamMember())])


@teams.get("/posts")
async def list_team_posts(request: Request, team_id: int):
    result = await request.state.db.execute(select(Post).where(Post.team_id == team_id))
    return [{"id": p.id, "title": p.title} for p in result.scalars()]


@teams.delete("/posts/{post_id}")
@permission_required(IsTeamMember(role="owner"))
async def delete_team_post(request: Request, team_id: int, post_id: int):
    """Only team owners may delete, whoever wrote it.

    The router-level dependency already required membership; this narrows it
    further for this one route.
    """
    post = await get_post(request, post_id)
    await request.state.db.delete(post)
    await request.state.db.commit()
    return {"deleted": post_id}


app.include_router(teams)


# -- object-level rules, checked after the row is loaded --------------------


@app.patch("/posts/{post_id}", responses=permission_responses())
async def edit_post(
    request: Request,
    post_id: int,
    ctx: PermissionContext = requires(IsAuthenticated),
):
    """Authors edit their own posts; team owners edit anything in their team.

    The ownership rule cannot be decided before the row exists, so the check
    happens here rather than as a dependency.
    """
    post = await get_post(request, post_id)
    await check_object_permissions(CanEditPost, ctx, post)

    post.published = True
    await request.state.db.commit()
    return {"id": post.id, "published": post.published}


@app.delete("/posts/{post_id}")
async def delete_own_post(
    request: Request,
    post_id: int,
    ctx: PermissionContext = requires(IsAuthenticated),
):
    """Strictly the author — no team-owner escape hatch."""
    post = await get_post(request, post_id)
    await check_object_permissions(IsPostAuthor, ctx, post)

    await request.state.db.delete(post)
    await request.state.db.commit()
    return {"deleted": post_id}


# -- admin ------------------------------------------------------------------


@app.get("/admin/posts", dependencies=[requires(IsAdminUser)])
async def all_posts(request: Request):
    result = await request.state.db.execute(select(Post))
    return [{"id": p.id, "title": p.title, "team_id": p.team_id} for p in result.scalars()]
