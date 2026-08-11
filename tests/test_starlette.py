from __future__ import annotations

import re

import pytest
from starlette.applications import Starlette
from starlette.endpoints import HTTPEndpoint
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from starlette_permissions import (
    HasRole,
    IsAdminUser,
    IsAuthenticated,
    PermissionMiddleware,
    PermissionMixin,
    configure,
    install_exception_handlers,
    permission_required,
)

from .conftest import User


class AttachUser:
    """Minimal auth middleware: the X-User header names the user."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            raw = headers.get(b"x-user")
            if raw == b"admin":
                scope["user"] = User(id=2, name="root", roles=["admin"], is_admin=True)
            elif raw:
                scope["user"] = User(id=1, name=raw.decode(), roles=["editor"])
        await self.app(scope, receive, send)


@pytest.fixture(autouse=True)
def _default_settings():
    configure()


def build(routes, middleware=None, json_errors=True):
    app = Starlette(
        routes=routes,
        middleware=[Middleware(AttachUser), *(middleware or [])],
    )
    if json_errors:
        install_exception_handlers(app)
    return TestClient(app)


# -- decorator ---------------------------------------------------------------


def test_decorator_on_a_function_endpoint():
    @permission_required(IsAuthenticated)
    async def me(request):
        return JSONResponse({"user": request.scope["user"].name})

    client = build([Route("/me", me)])
    assert client.get("/me", headers={"x-user": "ihor"}).json() == {"user": "ihor"}

    denied = client.get("/me")
    assert denied.status_code == 401
    assert denied.json() == {"detail": "Authentication credentials were not provided."}


def test_starlette_passes_the_request_positionally():
    """No signature rewriting is involved here — Starlette ignores signatures."""

    @permission_required(HasRole("admin"))
    async def admin(request):
        return JSONResponse({"ok": True})

    client = build([Route("/admin", admin)])
    assert client.get("/admin", headers={"x-user": "admin"}).status_code == 200
    assert client.get("/admin", headers={"x-user": "ihor"}).status_code == 403


def test_without_installed_handlers_denials_are_plain_text():
    @permission_required(IsAuthenticated)
    async def me(request):
        return JSONResponse({"ok": True})

    client = build([Route("/me", me)], json_errors=False)
    response = client.get("/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("text/plain")


# -- class-based endpoints ---------------------------------------------------


def test_permission_mixin_with_a_flat_list():
    class MeEndpoint(PermissionMixin, HTTPEndpoint):
        permission_classes = [IsAuthenticated]

        async def get(self, request):
            return JSONResponse({"user": request.scope["user"].name})

    client = build([Route("/me", MeEndpoint)])
    assert client.get("/me", headers={"x-user": "ihor"}).status_code == 200
    assert client.get("/me").status_code == 401


def test_permission_mixin_per_method_rules_combine_with_the_wildcard():
    class PostEndpoint(PermissionMixin, HTTPEndpoint):
        permission_classes = {"*": IsAuthenticated, "DELETE": IsAdminUser}

        async def get(self, request):
            return JSONResponse({"read": True})

        async def delete(self, request):
            return JSONResponse({"deleted": True})

    client = build([Route("/posts", PostEndpoint)])
    assert client.get("/posts", headers={"x-user": "ihor"}).status_code == 200
    assert client.delete("/posts", headers={"x-user": "ihor"}).status_code == 403
    assert client.delete("/posts", headers={"x-user": "admin"}).status_code == 200
    assert client.get("/posts").status_code == 401


def test_permission_mixin_with_no_rules_allows():
    class OpenEndpoint(PermissionMixin, HTTPEndpoint):
        async def get(self, request):
            return JSONResponse({"ok": True})

    client = build([Route("/open", OpenEndpoint)])
    assert client.get("/open").status_code == 200


# -- middleware --------------------------------------------------------------


async def handler(request):
    return JSONResponse({"ok": True})


def test_middleware_guards_everything_except_exemptions():
    client = build(
        [Route("/health", handler), Route("/private", handler), Route("/auth/login", handler)],
        middleware=[
            Middleware(
                PermissionMiddleware,
                permissions=IsAuthenticated,
                exempt=["/health", re.compile(r"/auth/.*")],
            )
        ],
    )

    assert client.get("/health").status_code == 200
    assert client.get("/auth/login").status_code == 200

    denied = client.get("/private")
    assert denied.status_code == 401
    # Rendered by the middleware itself, since it sits outside ExceptionMiddleware.
    assert denied.json() == {"detail": "Authentication credentials were not provided."}
    assert client.get("/private", headers={"x-user": "ihor"}).status_code == 200


def test_middleware_can_be_limited_to_certain_methods():
    client = build(
        [Route("/items", handler, methods=["GET", "POST"])],
        middleware=[
            Middleware(
                PermissionMiddleware,
                permissions=IsAuthenticated,
                methods=["POST"],
            )
        ],
    )

    assert client.get("/items").status_code == 200
    assert client.post("/items").status_code == 401
    assert client.post("/items", headers={"x-user": "ihor"}).status_code == 200


def test_middleware_with_no_permissions_is_a_passthrough():
    client = build(
        [Route("/x", handler)],
        middleware=[Middleware(PermissionMiddleware)],
    )
    assert client.get("/x").status_code == 200


def test_route_scoped_middleware():
    client = build(
        [
            Route("/open", handler),
            Route(
                "/closed",
                handler,
                middleware=[Middleware(PermissionMiddleware, permissions=IsAdminUser)],
            ),
        ]
    )
    assert client.get("/open").status_code == 200
    assert client.get("/closed", headers={"x-user": "ihor"}).status_code == 403
    assert client.get("/closed", headers={"x-user": "admin"}).status_code == 200
