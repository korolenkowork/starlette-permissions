"""Note: deliberately *no* ``from __future__ import annotations`` here, so that
annotations on the test endpoints stay real objects — that is what exercises the
non-string branch of the signature inspection."""

import asyncio
import inspect

import anyio
import anyio.to_thread
import pytest
from starlette.requests import HTTPConnection, Request
from starlette.websockets import WebSocket

from starlette_permissions import (
    AllowAny,
    DenyAll,
    IsAuthenticated,
    MissingRequestError,
    SyncCheckError,
    get_permissions,
    object_permission_required,
    permission_required,
)
from starlette_permissions.base import BasePermission
from starlette_permissions.resolver import (
    INJECTED_PARAM,
    _declares_connection,
    find_connection,
)
from starlette_permissions.testing import make_request


class TestConnectionDiscovery:
    def test_found_positionally(self):
        request = make_request()
        assert find_connection((request,), {}) is request

    def test_found_by_keyword(self):
        request = make_request()
        assert find_connection((), {"request": request}) is request

    def test_injected_keyword_wins(self):
        injected, declared = make_request(path="/a"), make_request(path="/b")
        found = find_connection((declared,), {INJECTED_PARAM: injected})
        assert found is injected

    def test_absent(self):
        assert find_connection((1, "x"), {"y": None}) is None


class TestSignatureInjection:
    def test_parameter_added_when_absent(self):
        @permission_required(AllowAny)
        async def endpoint(item_id: int):
            return item_id

        params = inspect.signature(endpoint).parameters
        assert INJECTED_PARAM in params
        assert params[INJECTED_PARAM].annotation is Request

    @pytest.mark.parametrize("annotation", [Request, WebSocket, HTTPConnection])
    def test_parameter_not_added_when_already_declared(self, annotation):
        @permission_required(AllowAny)
        async def endpoint(conn: annotation):
            return conn

        assert INJECTED_PARAM not in inspect.signature(endpoint).parameters

    @pytest.mark.parametrize(
        "annotation",
        ["Request", "WebSocket", "starlette.requests.Request", '"Request"', " Request "],
    )
    def test_string_annotations_are_recognised(self, annotation):
        """Modules using PEP 563 hand us the annotation as text, not a class."""
        parameter = inspect.Parameter(
            "request",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=annotation,
        )
        assert _declares_connection(inspect.Signature([parameter]))

    def test_unrelated_string_annotations_are_not_mistaken_for_a_connection(self):
        parameter = inspect.Parameter(
            "item",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation="Item",
        )
        assert not _declares_connection(inspect.Signature([parameter]))

    def test_var_keyword_stays_last(self):
        @permission_required(AllowAny)
        async def endpoint(item_id: int, **extra):
            return item_id

        kinds = [p.kind for p in inspect.signature(endpoint).parameters.values()]
        assert kinds[-1] is inspect.Parameter.VAR_KEYWORD

    def test_annotations_are_resolved_against_the_users_globals(self):
        """A regression guard for `from __future__ import annotations` modules.

        The wrapper lives in starlette_permissions.decorators, whose globals do
        not contain `Request`. If the signature carried the unevaluated string
        "Request", a framework resolving it against the wrapper's globals would
        fail and treat the parameter as a query field. Older FastAPI does
        exactly that, so the annotation must be resolved here.
        """
        source = (
            "from __future__ import annotations\n"
            "from starlette.requests import Request\n"
            "async def endpoint(request: Request): pass\n"
        )
        namespace: dict[str, object] = {}
        exec(compile(source, "usermod", "exec"), namespace)  # noqa: S102

        guarded = permission_required(AllowAny)(namespace["endpoint"])
        annotation = inspect.signature(guarded).parameters["request"].annotation

        assert annotation is Request, f"got {annotation!r}, expected the class"
        assert "Request" not in guarded.__globals__

    def test_unresolvable_annotations_fall_back_instead_of_raising(self):
        """TYPE_CHECKING-only imports must not break decoration."""
        source = (
            "from __future__ import annotations\n"
            "async def endpoint(item: SomeTypeCheckingOnlyModel): pass\n"
        )
        namespace: dict[str, object] = {}
        exec(compile(source, "usermod", "exec"), namespace)  # noqa: S102

        guarded = permission_required(AllowAny)(namespace["endpoint"])
        assert INJECTED_PARAM in inspect.signature(guarded).parameters

    def test_original_parameters_are_preserved(self):
        @permission_required(AllowAny)
        async def endpoint(a: int, b: str = "x"):
            return a, b

        params = inspect.signature(endpoint).parameters
        assert list(params)[:2] == ["a", "b"]
        assert params["b"].default == "x"


class TestMissingRequest:
    async def test_actionable_error_when_no_connection_reaches_the_endpoint(self):
        @permission_required(AllowAny)
        async def endpoint(item_id: int):
            return item_id

        # Calling directly, as a misplaced decorator would leave it.
        with pytest.raises(MissingRequestError, match="No Request or WebSocket"):
            await endpoint(item_id=1)


class TestSyncEndpoints:
    def test_sync_endpoint_with_a_sync_permission_works_outside_a_loop(self):
        @permission_required(AllowAny)
        def endpoint(request):
            return "ok"

        assert endpoint(make_request()) == "ok"

    def test_sync_endpoint_denial_outside_a_loop(self):
        @permission_required(DenyAll)
        def endpoint(request):
            return "ok"

        with pytest.raises(Exception, match="not available"):
            endpoint(make_request())

    def test_non_suspending_async_permission_works_outside_a_loop(self):
        """An 'async def' that never awaits real I/O completes in one step."""

        class AsyncButImmediate(BasePermission):
            async def has_permission(self, ctx):
                return True

        @permission_required(AsyncButImmediate)
        def endpoint(request):
            return "ok"

        assert endpoint(make_request()) == "ok"

    def test_a_genuinely_suspending_permission_says_so_clearly(self):
        class NeedsTheLoop(BasePermission):
            async def has_permission(self, ctx):
                await asyncio.sleep(0)
                return True

        @permission_required(NeedsTheLoop)
        def endpoint(request):
            return "ok"

        with pytest.raises(SyncCheckError, match="suspended"):
            endpoint(make_request())

    def test_a_suspending_permission_is_fine_in_a_worker_thread(self):
        """The path FastAPI and Starlette actually use to serve 'def' endpoints."""

        class NeedsTheLoop(BasePermission):
            async def has_permission(self, ctx):
                await asyncio.sleep(0)
                return True

        @permission_required(NeedsTheLoop)
        def endpoint(request):
            return "ok"

        async def main():
            return await anyio.to_thread.run_sync(endpoint, make_request())

        assert asyncio.run(main()) == "ok"


class TestIntrospection:
    def test_permissions_are_readable_from_the_endpoint(self):
        @permission_required(IsAuthenticated, AllowAny)
        async def endpoint(request: Request):
            return None

        permissions = get_permissions(endpoint)
        assert len(permissions) == 2
        assert isinstance(permissions[0], IsAuthenticated)
        assert endpoint.__sp_mode__ == "all"

    def test_undecorated_endpoints_report_nothing(self):
        async def endpoint(request):
            return None

        assert get_permissions(endpoint) == ()

    def test_metadata_is_preserved(self):
        @permission_required(AllowAny)
        async def endpoint(request: Request):
            """Docstring survives."""

        assert endpoint.__name__ == "endpoint"
        assert endpoint.__doc__ == "Docstring survives."


def test_object_permission_required_rejects_sync_endpoints():
    with pytest.raises(TypeError, match="async def"):

        @object_permission_required(AllowAny)
        def endpoint(request):
            return None
