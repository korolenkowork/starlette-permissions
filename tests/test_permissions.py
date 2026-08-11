from __future__ import annotations

import pytest
from starlette.authentication import AuthCredentials, SimpleUser

from starlette_permissions import (
    AllowAny,
    DenyAll,
    HasAllRoles,
    HasAllScopes,
    HasAnyRole,
    HasAPIKey,
    HasHeader,
    HasScope,
    IsAdminUser,
    IsAnonymous,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
    IsMethod,
    IsOwner,
    IsOwnerOrReadOnly,
    NotAuthenticated,
    Predicate,
    ReadOnly,
    check_permissions,
    has_object_permissions,
    has_permissions,
    permission,
)
from starlette_permissions.testing import make_context

from .conftest import User


class TestAuth:
    async def test_allow_any_and_deny_all(self):
        ctx = make_context()
        assert await has_permissions(AllowAny, ctx)
        assert not await has_permissions(DenyAll, ctx)

    async def test_is_authenticated(self):
        assert await has_permissions(IsAuthenticated, make_context(user=User()))
        assert not await has_permissions(IsAuthenticated, make_context())
        assert not await has_permissions(IsAuthenticated, make_context(user=None))

    async def test_is_authenticated_raises_401_not_403(self):
        with pytest.raises(NotAuthenticated) as exc_info:
            await check_permissions(IsAuthenticated, make_context())
        assert exc_info.value.status_code == 401

    async def test_user_object_may_declare_itself_unauthenticated(self):
        """Starlette's UnauthenticatedUser sets is_authenticated = False."""

        class Anonymous:
            is_authenticated = False

        assert not await has_permissions(IsAuthenticated, make_context(user=Anonymous()))

    async def test_starlette_simple_user_is_recognised(self):
        assert await has_permissions(IsAuthenticated, make_context(user=SimpleUser("ihor")))

    async def test_is_anonymous(self):
        assert await has_permissions(IsAnonymous, make_context())
        assert not await has_permissions(IsAnonymous, make_context(user=User()))

    @pytest.mark.parametrize("attr", ["is_admin", "is_staff", "is_superuser"])
    async def test_is_admin_user_accepts_any_configured_flag(self, attr):
        user = type("U", (), {attr: True})()
        assert await has_permissions(IsAdminUser, make_context(user=user))

    async def test_is_admin_user_rejects_plain_users(self):
        assert not await has_permissions(IsAdminUser, make_context(user=User()))
        assert not await has_permissions(IsAdminUser, make_context())

    @pytest.mark.parametrize(
        ("method", "anonymous_allowed"),
        [("GET", True), ("HEAD", True), ("OPTIONS", True), ("POST", False), ("DELETE", False)],
    )
    async def test_is_authenticated_or_read_only(self, method, anonymous_allowed):
        ctx = make_context(method=method)
        assert await has_permissions(IsAuthenticatedOrReadOnly, ctx) is anonymous_allowed
        authed = make_context(method=method, user=User())
        assert await has_permissions(IsAuthenticatedOrReadOnly, authed)


class TestMethods:
    @pytest.mark.parametrize(
        ("method", "expected"),
        [("GET", True), ("HEAD", True), ("OPTIONS", True), ("POST", False), ("PATCH", False)],
    )
    async def test_read_only(self, method, expected):
        assert await has_permissions(ReadOnly, make_context(method=method)) is expected

    async def test_is_method(self):
        rule = IsMethod("post", "put")
        assert await has_permissions(rule, make_context(method="POST"))
        assert await has_permissions(rule, make_context(method="PUT"))
        assert not await has_permissions(rule, make_context(method="GET"))
        assert rule.message == "Allowed methods: POST, PUT"


class TestRoles:
    async def test_has_any_role(self):
        ctx = make_context(user=User(roles=["editor", "reviewer"]))
        assert await has_permissions(HasAnyRole("editor"), ctx)
        assert await has_permissions(HasAnyRole("admin", "reviewer"), ctx)
        assert not await has_permissions(HasAnyRole("admin"), ctx)

    async def test_has_all_roles(self):
        ctx = make_context(user=User(roles=["editor", "reviewer"]))
        assert await has_permissions(HasAllRoles("editor", "reviewer"), ctx)
        assert not await has_permissions(HasAllRoles("editor", "admin"), ctx)

    async def test_a_single_string_role_attribute_is_accepted(self):
        user = type("U", (), {"role": "admin"})()
        assert await has_permissions(HasAnyRole("admin"), make_context(user=user))

    async def test_anonymous_users_have_no_roles(self):
        assert not await has_permissions(HasAnyRole("admin"), make_context())

    def test_at_least_one_role_is_required(self):
        with pytest.raises(ValueError, match="At least one role"):
            HasAnyRole()

    async def test_scopes_come_from_starlette_credentials(self):
        ctx = make_context(
            user=SimpleUser("ihor"),
            auth=AuthCredentials(["posts:read", "posts:write"]),
        )
        assert await has_permissions(HasScope("posts:write"), ctx)
        assert await has_permissions(HasAllScopes("posts:read", "posts:write"), ctx)
        assert not await has_permissions(HasScope("admin"), ctx)


class TestAPIKey:
    async def test_static_key(self):
        rule = HasAPIKey("s3cret")
        assert await has_permissions(rule, make_context(headers={"X-API-Key": "s3cret"}))
        assert not await has_permissions(rule, make_context(headers={"X-API-Key": "nope"}))
        assert not await has_permissions(rule, make_context())

    async def test_callable_key_is_read_per_request(self):
        current = {"value": "one"}
        rule = HasAPIKey(key=lambda: current["value"])
        assert await has_permissions(rule, make_context(headers={"X-API-Key": "one"}))
        current["value"] = "two"
        assert not await has_permissions(rule, make_context(headers={"X-API-Key": "one"}))
        assert await has_permissions(rule, make_context(headers={"X-API-Key": "two"}))

    async def test_multiple_accepted_keys(self):
        rule = HasAPIKey(["a", "b"])
        assert await has_permissions(rule, make_context(headers={"X-API-Key": "b"}))

    async def test_unset_key_never_matches(self):
        rule = HasAPIKey(key=lambda: None)
        assert not await has_permissions(rule, make_context(headers={"X-API-Key": ""}))
        assert not await has_permissions(rule, make_context(headers={"X-API-Key": "anything"}))

    async def test_custom_header(self):
        rule = HasAPIKey("k", header="X-Service-Token")
        assert await has_permissions(rule, make_context(headers={"X-Service-Token": "k"}))
        assert not await has_permissions(rule, make_context(headers={"X-API-Key": "k"}))

    async def test_query_param_is_opt_in(self):
        off = HasAPIKey("k")
        on = HasAPIKey("k", query_param="api_key")
        assert not await has_permissions(off, make_context(query_string="api_key=k"))
        assert await has_permissions(on, make_context(query_string="api_key=k"))


class TestHeaders:
    async def test_presence_only(self):
        rule = HasHeader("X-Tenant")
        assert await has_permissions(rule, make_context(headers={"X-Tenant": "acme"}))
        assert not await has_permissions(rule, make_context())

    async def test_specific_values(self):
        rule = HasHeader("X-Tenant", ["acme", "globex"])
        assert await has_permissions(rule, make_context(headers={"X-Tenant": "globex"}))
        assert not await has_permissions(rule, make_context(headers={"X-Tenant": "other"}))


class TestPredicates:
    async def test_bare_function(self):
        assert await has_permissions(lambda ctx: ctx.method == "GET", make_context())

    async def test_async_function(self):
        async def check(ctx):
            return ctx.method == "GET"

        assert await has_permissions(Predicate(check), make_context())

    async def test_decorator_form_with_message(self):
        @permission(message="Office network only")
        def from_office(ctx):
            return False

        with pytest.raises(Exception, match="Office network only"):
            await check_permissions(from_office, make_context())

    async def test_docstring_becomes_the_message(self):
        @permission
        def has_beta_flag(ctx):
            """Beta programme members only."""
            return False

        with pytest.raises(Exception, match="Beta programme members only"):
            await check_permissions(has_beta_flag, make_context())


class TestObjectPermissions:
    async def test_is_owner_matches_on_the_user_id(self):
        ctx = make_context(user=User(id=7))
        assert await has_object_permissions(IsOwner(), ctx, {"user_id": 7})
        assert not await has_object_permissions(IsOwner(), ctx, {"user_id": 8})

    async def test_is_owner_reads_attributes_as_well_as_dict_keys(self):
        ctx = make_context(user=User(id=7))
        obj = type("Post", (), {"author_id": 7})()
        assert await has_object_permissions(IsOwner("author_id"), ctx, obj)

    async def test_anonymous_users_own_nothing(self):
        assert not await has_object_permissions(IsOwner(), make_context(), {"user_id": 1})

    async def test_a_missing_owner_field_is_an_error_not_a_denial(self):
        ctx = make_context(user=User(id=7))
        with pytest.raises(AttributeError, match="has no 'author_id'"):
            await has_object_permissions(IsOwner("author_id"), ctx, {"id": 1})

    async def test_custom_user_id_extractor(self):
        ctx = make_context(user=User(id=7, name="ihor"))
        rule = IsOwner("owner", user_id=lambda user: user.name)
        assert await has_object_permissions(rule, ctx, {"owner": "ihor"})

    async def test_owner_or_read_only(self):
        rule = IsOwnerOrReadOnly()
        reader = make_context(method="GET", user=User(id=1))
        writer = make_context(method="PATCH", user=User(id=1))
        assert await has_object_permissions(rule, reader, {"user_id": 999})
        assert not await has_object_permissions(rule, writer, {"user_id": 999})
        assert await has_object_permissions(rule, writer, {"user_id": 1})

    async def test_object_rules_do_not_apply_at_request_level(self):
        assert await has_permissions(IsOwner(), make_context(user=User()))
