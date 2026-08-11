"""The SQLAlchemy example is documentation, so it gets tested like everything else.

Every status code asserted here is one the example's docstring promises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="the SQLAlchemy example needs sqlalchemy")
pytest.importorskip("aiosqlite", reason="the SQLAlchemy example needs aiosqlite")

from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROOT_TOKEN = "tok-root"
IHOR = "tok-ihor"  # owner of team acme
DANA = "tok-dana"  # plain member of team acme
OUTSIDER = "tok-outsider"  # member of globex only

ACME, GLOBEX = 1, 2
IHORS_POST, DANAS_POST, GLOBEX_POST = 1, 2, 3


@pytest.fixture
def client():
    from examples.sqlalchemy_app.main import app

    from starlette_permissions import configure

    # The module configures this at import; re-apply because the autouse reset
    # fixture in conftest restores global settings after every test.
    configure(user_getter=lambda conn: getattr(conn.state, "user", None))

    # The TestClient context manager runs lifespan, which builds the schema and
    # seeds a fresh in-memory database.
    with TestClient(app) as test_client:
        yield test_client


def auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


class TestIdentity:
    def test_anonymous_is_401(self, client):
        assert client.get("/me").status_code == 401

    def test_a_bad_token_is_401(self, client):
        assert client.get("/me", headers=auth("nonsense")).status_code == 401

    def test_the_orm_user_reaches_the_context(self, client):
        body = client.get("/me", headers=auth(IHOR)).json()
        assert body == {"id": 2, "name": "ihor", "roles": ["owner"]}

    def test_roles_come_from_the_membership_rows(self, client):
        """Exercises the relationship walk that would break on a lazy load."""
        assert client.get("/me", headers=auth(DANA)).json()["roles"] == ["member"]


class TestQueryBackedRule:
    """IsTeamMember runs a SELECT before any record is loaded."""

    def test_members_may_list_their_teams_posts(self, client):
        response = client.get(f"/teams/{ACME}/posts", headers=auth(DANA))
        assert response.status_code == 200
        assert {p["id"] for p in response.json()} == {IHORS_POST, DANAS_POST}

    def test_non_members_are_refused(self, client):
        response = client.get(f"/teams/{ACME}/posts", headers=auth(OUTSIDER))
        assert response.status_code == 403
        assert response.json() == {"detail": "Team membership required"}

    def test_membership_is_per_team(self, client):
        assert client.get(f"/teams/{GLOBEX}/posts", headers=auth(OUTSIDER)).status_code == 200
        assert client.get(f"/teams/{GLOBEX}/posts", headers=auth(DANA)).status_code == 403

    def test_anonymous_is_refused(self, client):
        assert client.get(f"/teams/{ACME}/posts").status_code == 403


class TestRoleWithinTeam:
    """The decorator narrows the router-level rule for one route."""

    def test_team_owner_may_delete_any_post_in_the_team(self, client):
        response = client.delete(f"/teams/{ACME}/posts/{DANAS_POST}", headers=auth(IHOR))
        assert response.status_code == 200
        assert response.json() == {"deleted": DANAS_POST}

    def test_a_plain_member_may_not(self, client):
        response = client.delete(f"/teams/{ACME}/posts/{IHORS_POST}", headers=auth(DANA))
        assert response.status_code == 403
        assert response.json()["detail"] == "Requires the 'owner' role in this team"

    def test_a_member_may_not_even_delete_their_own(self, client):
        assert (
            client.delete(f"/teams/{ACME}/posts/{DANAS_POST}", headers=auth(DANA)).status_code
            == 403
        )


class TestObjectLevelRules:
    """CanEditPost = IsPostAuthor | IsTeamOwnerOf(), checked after the load."""

    def test_the_author_may_edit(self, client):
        response = client.patch(f"/posts/{DANAS_POST}", headers=auth(DANA))
        assert response.status_code == 200
        assert response.json() == {"id": DANAS_POST, "published": True}

    def test_the_team_owner_may_edit_someone_elses_post(self, client):
        assert client.patch(f"/posts/{DANAS_POST}", headers=auth(IHOR)).status_code == 200

    def test_a_member_may_not_edit_another_members_post(self, client):
        response = client.patch(f"/posts/{IHORS_POST}", headers=auth(DANA))
        assert response.status_code == 403
        assert response.json()["detail"] == "Only the author may modify this post"

    def test_an_outsider_may_not_edit(self, client):
        assert client.patch(f"/posts/{DANAS_POST}", headers=auth(OUTSIDER)).status_code == 403

    def test_the_or_branch_is_genuinely_reached(self, client):
        """The owner is not the author, so only the second branch can allow it."""
        posts = client.get("/admin/posts", headers=auth(ROOT_TOKEN)).json()
        danas = next(p for p in posts if p["id"] == DANAS_POST)
        assert danas["team_id"] == ACME  # ihor owns acme but did not write it
        assert client.patch(f"/posts/{DANAS_POST}", headers=auth(IHOR)).status_code == 200

    def test_deleting_has_no_team_owner_escape_hatch(self, client):
        assert client.delete(f"/posts/{DANAS_POST}", headers=auth(IHOR)).status_code == 403
        assert client.delete(f"/posts/{DANAS_POST}", headers=auth(DANA)).status_code == 200

    def test_a_missing_row_is_404_not_403(self, client):
        """The handler loads before it checks, so absence must not read as denial."""
        assert client.patch("/posts/999", headers=auth(DANA)).status_code == 404


class TestAdmin:
    def test_admin_sees_everything(self, client):
        response = client.get("/admin/posts", headers=auth(ROOT_TOKEN))
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_non_admins_are_refused(self, client):
        assert client.get("/admin/posts", headers=auth(IHOR)).status_code == 403

    def test_admin_flag_comes_from_the_column(self, client):
        assert client.get("/me", headers=auth(ROOT_TOKEN)).json()["name"] == "root"


class TestWiringFailures:
    def test_a_missing_session_raises_rather_than_denying(self):
        """A wiring mistake must not masquerade as a 403."""
        from examples.sqlalchemy_app.permissions import session_of

        from starlette_permissions.testing import make_context

        with pytest.raises(RuntimeError, match="DbSessionMiddleware"):
            session_of(make_context())


class TestDocumentedTestingPatterns:
    """The snippets in docs/sqlalchemy.md, run for real."""

    async def test_object_rules_need_no_database(self):
        from examples.sqlalchemy_app.models import Post, User

        from starlette_permissions import IsOwner, has_object_permissions
        from starlette_permissions.testing import make_context

        ctx = make_context(user=User(id=7, name="x", api_token="t"))
        assert await has_object_permissions(IsOwner("author_id"), ctx, Post(author_id=7))
        assert not await has_object_permissions(IsOwner("author_id"), ctx, Post(author_id=8))

    async def test_a_query_backed_rule_takes_a_session_off_the_context(self):
        from examples.sqlalchemy_app.models import (
            create_schema,
            make_engine,
            make_sessionmaker,
            seed,
            user_by_token,
        )
        from examples.sqlalchemy_app.permissions import IsTeamMember

        from starlette_permissions import has_permissions
        from starlette_permissions.testing import make_context

        engine = make_engine()
        await create_schema(engine)
        try:
            async with make_sessionmaker(engine)() as session:
                await seed(session)
                user = await user_by_token(session, DANA)

                ctx = make_context(user=user, path_params={"team_id": ACME})
                ctx.connection.state.db = session
                assert await has_permissions(IsTeamMember(), ctx)
                assert not await has_permissions(IsTeamMember(role="owner"), ctx)

                globex_ctx = make_context(user=user, path_params={"team_id": GLOBEX})
                globex_ctx.connection.state.db = session
                assert not await has_permissions(IsTeamMember(), globex_ctx)
        finally:
            await engine.dispose()


class TestIsolation:
    """Each test gets a freshly seeded database, so order cannot matter."""

    def test_deletion_does_not_leak_into_the_next_test(self, client):
        assert client.delete(f"/posts/{DANAS_POST}", headers=auth(DANA)).status_code == 200
        assert client.patch(f"/posts/{DANAS_POST}", headers=auth(DANA)).status_code == 404

    def test_the_post_is_back(self, client):
        assert client.patch(f"/posts/{DANAS_POST}", headers=auth(DANA)).status_code == 200
