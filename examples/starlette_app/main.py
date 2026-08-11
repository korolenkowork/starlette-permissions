"""A runnable Starlette app: decorator, class-based endpoint, and middleware.

uvicorn examples.starlette_app.main:app --reload

curl -i localhost:8000/health                      # 200 (exempt)
curl -i localhost:8000/me                          # 401
curl -i localhost:8000/me -H 'X-User: ihor'        # 200
curl -i localhost:8000/posts -X DELETE -H 'X-User: ihor'   # 403
curl -i localhost:8000/posts -X DELETE -H 'X-User: admin'  # 200
"""

import re
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.endpoints import HTTPEndpoint
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from starlette_permissions import (
    IsAdminUser,
    IsAuthenticated,
    PermissionMiddleware,
    PermissionMixin,
    install_exception_handlers,
    permission_required,
)


@dataclass
class User:
    id: int
    name: str
    roles: list[str] = field(default_factory=list)
    is_admin: bool = False


class FakeAuthMiddleware:
    """Stand-in for real authentication.

    Writes the user to ``scope["user"]``, which is where Starlette's own
    AuthenticationMiddleware puts it — so no configure() call is needed.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            name = dict(scope["headers"]).get(b"x-user")
            if name == b"admin":
                scope["user"] = User(2, "root", ["admin"], is_admin=True)
            elif name:
                scope["user"] = User(1, name.decode(), ["editor"])
        await self.app(scope, receive, send)


async def health(request):
    return JSONResponse({"status": "ok"})


@permission_required(IsAuthenticated)
async def me(request):
    return JSONResponse({"user": request.scope["user"].name})


class PostEndpoint(PermissionMixin, HTTPEndpoint):
    """Everyone authenticated may read; only admins may delete."""

    permission_classes = {"*": IsAuthenticated, "DELETE": IsAdminUser}

    async def get(self, request):
        return JSONResponse({"posts": []})

    async def delete(self, request):
        return JSONResponse({"deleted": True})


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/me", me),
        Route("/posts", PostEndpoint),
    ],
    middleware=[
        Middleware(FakeAuthMiddleware),
        # A blanket policy, with the public paths carved out.
        Middleware(
            PermissionMiddleware,
            permissions=IsAuthenticated,
            exempt=["/health", re.compile(r"/auth/.*")],
        ),
    ],
)

# Starlette renders HTTPException as plain text by default; this makes
# denials JSON instead.
install_exception_handlers(app)
