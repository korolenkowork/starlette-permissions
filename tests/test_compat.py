"""The migration path for an existing hand-rolled permission system."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from starlette_permissions import IsAuthenticated, has_permissions, permission_required
from starlette_permissions.compat import BasePermission as LegacyBase
from starlette_permissions.compat import LegacyPermission
from starlette_permissions.compat import permission_required as legacy_permission_required
from starlette_permissions.testing import make_context

from .conftest import User


class LegacyIsAuthenticated(LegacyBase):
    @staticmethod
    async def is_permitted(request, *args, **kwargs):
        return getattr(request.state, "token", None) is not None


class LegacyIsService(LegacyBase):
    @staticmethod
    async def is_permitted(request, *args, **kwargs):
        return request.headers.get("X-API-Key") == "s3cret"


@pytest.fixture
def app():
    application = FastAPI()

    @application.middleware("http")
    async def attach_token(request: Request, call_next):
        if request.headers.get("x-user"):
            request.state.token = User()
        return await call_next(request)

    return application


def test_legacy_decorator_still_works(app):
    @app.get("/me")
    @legacy_permission_required([LegacyIsAuthenticated])
    async def me(request: Request):
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/me", headers={"x-user": "ihor"}).status_code == 200

    denied = client.get("/me")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Permission denied"}


def test_legacy_decorator_keeps_its_or_semantics(app):
    """The behaviour the modern decorator deliberately changed."""

    @app.get("/either")
    @legacy_permission_required([LegacyIsAuthenticated, LegacyIsService])
    async def either(request: Request):
        return {"ok": True}

    client = TestClient(app)
    # Neither rule holds -> denied.
    assert client.get("/either").status_code == 403
    # Only the second holds, yet access is granted: that is OR.
    assert client.get("/either", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_legacy_decorator_warns():
    with pytest.warns(DeprecationWarning, match="requires only one permission"):
        legacy_permission_required([LegacyIsAuthenticated])


def test_the_same_list_under_the_modern_decorator_requires_both(app):
    @app.get("/both")
    @permission_required([LegacyIsAuthenticated, LegacyIsService])
    async def both(request: Request):
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/both", headers={"X-API-Key": "s3cret"}).status_code == 403
    assert client.get("/both", headers={"X-API-Key": "s3cret", "x-user": "ihor"}).status_code == 200


async def test_legacy_permissions_are_adapted_automatically():
    """A single-permission list migrates with no behaviour change at all."""
    ctx = make_context(headers={"X-API-Key": "s3cret"})
    assert await has_permissions(LegacyIsService, ctx)
    assert not await has_permissions(LegacyIsService, make_context())


async def test_legacy_permissions_compose_with_modern_ones():
    combined = IsAuthenticated | LegacyIsService
    assert await has_permissions(combined, make_context(headers={"X-API-Key": "s3cret"}))
    assert await has_permissions(combined, make_context(user=User()))
    assert not await has_permissions(combined, make_context())


async def test_legacy_adapter_forwards_view_kwargs():
    class NeedsPathParam(LegacyBase):
        @staticmethod
        async def is_permitted(request, *args, **kwargs):
            return kwargs.get("tenant") == "acme"

    ctx = make_context(view_kwargs={"tenant": "acme"})
    assert await has_permissions(NeedsPathParam, ctx)


async def test_legacy_adapter_drops_a_duplicated_connection_kwarg():
    """FastAPI passes the request by keyword; it must not arrive twice."""

    class Simple(LegacyBase):
        @staticmethod
        async def is_permitted(request, *args, **kwargs):
            return request is not None and not kwargs

    ctx = make_context()
    ctx.view_kwargs = {"request": ctx.connection}  # type: ignore[misc]
    assert await has_permissions(LegacyPermission(Simple), ctx)


async def test_a_sync_legacy_permission_is_accepted():
    class SyncLegacy:
        @staticmethod
        def is_permitted(request, *args, **kwargs):
            return True

    assert await has_permissions(SyncLegacy, make_context())
