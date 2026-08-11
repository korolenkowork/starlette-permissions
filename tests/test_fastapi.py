from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from starlette_permissions import (
    HasAPIKey,
    HasRole,
    IsAdminUser,
    IsAuthenticated,
    IsOwner,
    PermissionContext,
    ReadOnly,
    configure,
    object_permission_required,
    permission_required,
)
from starlette_permissions.dependencies import (
    permission_responses,
    requires,
    requires_object,
)

from .conftest import User


@pytest.fixture
def app():
    """A FastAPI app whose 'auth' is a header, so tests can pick a user freely."""
    configure(user_getter=lambda conn: getattr(conn.state, "user", None))
    application = FastAPI()

    @application.middleware("http")
    async def attach_user(request: Request, call_next):
        header = request.headers.get("x-user")
        if header == "admin":
            request.state.user = User(id=2, name="root", roles=["admin"], is_admin=True)
        elif header:
            request.state.user = User(id=1, name=header, roles=["editor"])
        return await call_next(request)

    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=True)


# -- decorator ---------------------------------------------------------------


def test_decorator_allows_and_denies(app, client):
    @app.get("/me")
    @permission_required(IsAuthenticated)
    async def me(request: Request):
        return {"user": request.state.user.name}

    assert client.get("/me", headers={"x-user": "ihor"}).json() == {"user": "ihor"}

    denied = client.get("/me")
    assert denied.status_code == 401
    assert denied.json() == {"detail": "Authentication credentials were not provided."}


def test_decorator_injects_request_when_endpoint_does_not_declare_one(app, client):
    """The whole point of the signature rewrite: no handler edits required."""

    @app.get("/no-request")
    @permission_required(IsAuthenticated)
    async def no_request():
        return {"ok": True}

    assert client.get("/no-request", headers={"x-user": "ihor"}).status_code == 200
    assert client.get("/no-request").status_code == 401


def test_injected_parameter_stays_out_of_the_openapi_schema(app, client):
    @app.get("/hidden")
    @permission_required(IsAuthenticated)
    async def hidden():
        return {"ok": True}

    schema = client.get("/openapi.json").json()
    params = schema["paths"]["/hidden"]["get"].get("parameters", [])
    assert not [p for p in params if "sp_request" in p["name"]]


def test_decorator_preserves_other_parameters(app, client):
    @app.get("/items/{item_id}")
    @permission_required(IsAuthenticated)
    async def item(item_id: int, q: str = "none"):
        return {"item_id": item_id, "q": q}

    response = client.get("/items/7?q=hi", headers={"x-user": "ihor"})
    assert response.json() == {"item_id": 7, "q": "hi"}


def test_decorator_on_sync_endpoint(app, client):
    @app.get("/sync")
    @permission_required(IsAuthenticated)
    def sync_endpoint(request: Request):
        return {"user": request.state.user.name}

    assert client.get("/sync", headers={"x-user": "ihor"}).json() == {"user": "ihor"}
    assert client.get("/sync").status_code == 401


def test_multiple_permissions_default_to_all(app, client):
    @app.get("/admin")
    @permission_required(IsAuthenticated, HasRole("admin"))
    async def admin_only():
        return {"ok": True}

    assert client.get("/admin", headers={"x-user": "admin"}).status_code == 200
    assert client.get("/admin", headers={"x-user": "ihor"}).status_code == 403


def test_mode_any(app, client):
    @app.post("/either")
    @permission_required(IsAdminUser, HasRole("editor"), mode="any")
    async def either():
        return {"ok": True}

    assert client.post("/either", headers={"x-user": "ihor"}).status_code == 200
    assert client.post("/either", headers={"x-user": "admin"}).status_code == 200
    assert client.post("/either").status_code == 403


def test_composed_permissions(app, client):
    @app.post("/composed")
    @permission_required(IsAuthenticated & (IsAdminUser | HasRole("editor")))
    async def composed():
        return {"ok": True}

    assert client.post("/composed", headers={"x-user": "ihor"}).status_code == 200
    assert client.post("/composed", headers={"x-user": "admin"}).status_code == 200
    assert client.post("/composed").status_code == 401


def test_message_and_status_override(app, client):
    @app.get("/custom")
    @permission_required(IsAdminUser, message="Nope", status_code=404)
    async def custom():
        return {"ok": True}

    response = client.get("/custom", headers={"x-user": "ihor"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Nope"}


# -- dependency --------------------------------------------------------------


def test_requires_as_route_dependency(app, client):
    @app.get("/dep", dependencies=[requires(IsAuthenticated)])
    async def dep():
        return {"ok": True}

    assert client.get("/dep", headers={"x-user": "ihor"}).status_code == 200
    assert client.get("/dep").status_code == 401


def test_requires_resolves_to_the_context(app, client):
    @app.get("/ctx")
    async def ctx_endpoint(ctx: PermissionContext = requires(IsAuthenticated)):
        return {"user": ctx.user.name, "roles": list(ctx.roles)}

    response = client.get("/ctx", headers={"x-user": "ihor"})
    assert response.json() == {"user": "ihor", "roles": ["editor"]}


def test_requires_on_a_whole_router(app, client):
    router = APIRouter(prefix="/admin", dependencies=[requires(IsAdminUser)])

    @router.get("/stats")
    async def stats():
        return {"ok": True}

    @router.get("/users")
    async def users():
        return {"ok": True}

    app.include_router(router)

    assert client.get("/admin/stats", headers={"x-user": "admin"}).status_code == 200
    assert client.get("/admin/users", headers={"x-user": "ihor"}).status_code == 403


def test_permission_responses_documents_denials(app, client):
    @app.get(
        "/documented",
        dependencies=[requires(IsAuthenticated)],
        responses=permission_responses(),
    )
    async def documented():
        return {"ok": True}

    schema = client.get("/openapi.json").json()
    responses = schema["paths"]["/documented"]["get"]["responses"]
    assert "401" in responses
    assert "403" in responses


# -- object level ------------------------------------------------------------


def test_requires_object_checks_the_loaded_record(app, client):
    posts = {1: {"id": 1, "author_id": 1}, 2: {"id": 2, "author_id": 99}}

    @app.get("/posts/{post_id}")
    async def get_post(post_id: int, check=requires_object(IsOwner("author_id"))):
        return await check(posts[post_id])

    assert client.get("/posts/1", headers={"x-user": "ihor"}).status_code == 200
    assert client.get("/posts/2", headers={"x-user": "ihor"}).status_code == 403


def test_object_permission_required_with_a_getter(app, client):
    posts = {1: {"id": 1, "author_id": 1}, 2: {"id": 2, "author_id": 99}}
    loaded = []

    def load(post_id, **_):
        loaded.append(post_id)
        return posts[post_id]

    @app.get("/guarded/{post_id}")
    @object_permission_required(IsOwner("author_id"), getter=load)
    async def guarded(post_id: int):
        return {"handled": True}

    assert client.get("/guarded/1", headers={"x-user": "ihor"}).json() == {"handled": True}
    denied = client.get("/guarded/2", headers={"x-user": "ihor"})
    assert denied.status_code == 403
    assert loaded == [1, 2]


def test_object_permission_required_checks_the_return_value(app, client):
    @app.get("/returned/{author_id}")
    @object_permission_required(IsOwner("author_id"))
    async def returned(author_id: int):
        return {"author_id": author_id}

    assert client.get("/returned/1", headers={"x-user": "ihor"}).status_code == 200
    assert client.get("/returned/99", headers={"x-user": "ihor"}).status_code == 403


# -- api key -----------------------------------------------------------------


def test_api_key_permission(app, client):
    is_service = HasAPIKey(key=lambda: "s3cret")

    @app.post("/internal", dependencies=[requires(is_service)])
    async def internal():
        return {"ok": True}

    assert client.post("/internal", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.post("/internal", headers={"X-API-Key": "wrong"}).status_code == 403
    assert client.post("/internal").status_code == 403


def test_read_only_combined_with_admin(app, client):
    @app.api_route("/articles", methods=["GET", "POST"])
    @permission_required(ReadOnly | IsAdminUser)
    async def articles():
        return {"ok": True}

    assert client.get("/articles").status_code == 200
    assert client.post("/articles").status_code == 403
    assert client.post("/articles", headers={"x-user": "admin"}).status_code == 200


def test_permission_stacks_with_other_dependencies(app, client):
    def dependency():
        return "injected"

    @app.get("/stacked")
    @permission_required(IsAuthenticated)
    async def stacked(value: str = Depends(dependency)):
        return {"value": value}

    assert client.get("/stacked", headers={"x-user": "ihor"}).json() == {"value": "injected"}
