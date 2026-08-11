"""The example apps are documentation, so they get tested like everything else."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fastapi_client():
    from examples.fastapi_app.main import app

    from starlette_permissions import configure

    # The module calls configure() at import time, but it is only imported
    # once while the autouse reset fixture runs for every test — so re-apply it.
    configure(user_getter=lambda conn: getattr(conn.state, "user", None))
    return TestClient(app)


@pytest.fixture
def starlette_client():
    from examples.starlette_app.main import app

    return TestClient(app)


class TestFastAPIExample:
    @pytest.mark.parametrize(
        ("path", "headers", "status"),
        [
            ("/me", {}, 401),
            ("/me", {"X-User": "ihor"}, 200),
            ("/profile", {}, 401),
            ("/profile", {"X-User": "ihor"}, 200),
            ("/articles", {}, 200),
            ("/admin/stats", {"X-User": "ihor"}, 403),
            ("/admin/stats", {"X-User": "admin"}, 200),
            ("/posts/1", {"X-User": "ihor"}, 200),
            ("/posts/2", {"X-User": "ihor"}, 403),
            ("/tenant-only", {"X-User": "ihor"}, 403),
            ("/tenant-only", {"X-User": "ihor", "X-Tenant": "acme"}, 200),
        ],
    )
    def test_documented_responses(self, fastapi_client, path, headers, status):
        assert fastapi_client.get(path, headers=headers).status_code == status

    def test_write_paths(self, fastapi_client):
        assert fastapi_client.post("/articles").status_code == 403
        assert fastapi_client.post("/articles", headers={"X-User": "admin"}).status_code == 200
        assert fastapi_client.post("/internal", headers={"X-API-Key": "s3cret"}).status_code == 200
        assert fastapi_client.post("/internal", headers={"X-API-Key": "no"}).status_code == 403

    def test_context_dependency_returns_the_user(self, fastapi_client):
        body = fastapi_client.get("/me", headers={"X-User": "ihor"}).json()
        assert body == {"name": "ihor", "roles": ["editor"]}

    def test_openapi_schema_builds(self, fastapi_client):
        schema = fastapi_client.get("/openapi.json").json()
        assert "403" in schema["paths"]["/me"]["get"]["responses"]


class TestStarletteExample:
    @pytest.mark.parametrize(
        ("path", "headers", "status"),
        [
            ("/health", {}, 200),
            ("/me", {}, 401),
            ("/me", {"X-User": "ihor"}, 200),
            ("/posts", {"X-User": "ihor"}, 200),
        ],
    )
    def test_documented_responses(self, starlette_client, path, headers, status):
        assert starlette_client.get(path, headers=headers).status_code == status

    def test_per_method_rules(self, starlette_client):
        assert starlette_client.delete("/posts", headers={"X-User": "ihor"}).status_code == 403
        assert starlette_client.delete("/posts", headers={"X-User": "admin"}).status_code == 200

    def test_denials_are_json(self, starlette_client):
        response = starlette_client.get("/me")
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
