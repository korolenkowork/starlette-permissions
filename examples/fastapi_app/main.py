"""A runnable FastAPI app showing every integration point.

    uvicorn examples.fastapi_app.main:app --reload

Then, with no auth header:

    curl -i localhost:8000/me                      # 401
    curl -i localhost:8000/me -H 'X-User: ihor'    # 200
    curl -i localhost:8000/admin/stats -H 'X-User: ihor'   # 403
    curl -i localhost:8000/admin/stats -H 'X-User: admin'  # 200
    curl -i localhost:8000/internal -H 'X-API-Key: s3cret' # 200
    curl -i localhost:8000/posts/1 -H 'X-User: ihor'       # 200 (owned)
    curl -i localhost:8000/posts/2 -H 'X-User: ihor'       # 403 (not owned)
"""

from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI
from starlette.requests import Request

from starlette_permissions import (
    HasAPIKey,
    IsAdminUser,
    IsAuthenticated,
    IsOwner,
    PermissionContext,
    ReadOnly,
    configure,
    permission,
    permission_required,
)
from starlette_permissions.dependencies import (
    permission_responses,
    requires,
    requires_object,
)

SERVICE_API_KEY = "s3cret"  # an example value, not a real secret


@dataclass
class User:
    id: int
    name: str
    roles: list[str] = field(default_factory=list)
    is_admin: bool = False


POSTS = {
    1: {"id": 1, "title": "Hello", "author_id": 1},
    2: {"id": 2, "title": "Private", "author_id": 99},
}

# Tell the library where the user lives. Everything else follows from this.
configure(user_getter=lambda conn: getattr(conn.state, "user", None))

app = FastAPI(title="starlette-permissions example")


@app.middleware("http")
async def fake_auth(request: Request, call_next):
    """Stand-in for real authentication: the X-User header names the user."""
    name = request.headers.get("x-user")
    if name == "admin":
        request.state.user = User(id=2, name="root", roles=["admin"], is_admin=True)
    elif name:
        request.state.user = User(id=1, name=name, roles=["editor"])
    return await call_next(request)


# -- 1. The dependency form, and taking the context as a value ---------------


@app.get("/me", responses=permission_responses())
async def me(ctx: PermissionContext = requires(IsAuthenticated)):
    return {"name": ctx.user.name, "roles": list(ctx.roles)}


# -- 2. The decorator form; note there is no Request parameter ---------------


@app.get("/profile")
@permission_required(IsAuthenticated)
async def profile():
    return {"ok": True}


# -- 3. A composed rule on a router: anyone reads, only admins write ---------

articles = APIRouter(dependencies=[requires(ReadOnly | IsAdminUser)])


@articles.get("/articles")
async def list_articles():
    return {"articles": []}


@articles.post("/articles")
async def create_article():
    return {"created": True}


app.include_router(articles)


# -- 4. A whole router behind one rule --------------------------------------

admin = APIRouter(prefix="/admin", dependencies=[requires(IsAdminUser)])


@admin.get("/stats")
async def stats():
    return {"users": 2}


app.include_router(admin)


# -- 5. Service-to-service calls --------------------------------------------

is_service = HasAPIKey(key=lambda: SERVICE_API_KEY)


@app.post("/internal", dependencies=[requires(is_service)])
async def internal():
    return {"ok": True}


# -- 6. Object-level: you may only read your own posts -----------------------

owns_post = requires_object(IsOwner("author_id"))


@app.get("/posts/{post_id}")
async def get_post(post_id: int, check=owns_post):
    return await check(POSTS[post_id])


# -- 7. A one-off rule as a function ----------------------------------------


@permission(message="Requests must carry a tenant header")
def has_tenant(ctx):
    return ctx.headers.get("x-tenant") is not None


@app.get("/tenant-only")
@permission_required(IsAuthenticated & has_tenant)
async def tenant_only():
    return {"ok": True}
