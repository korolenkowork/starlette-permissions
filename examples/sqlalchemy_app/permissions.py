"""Permissions backed by the database.

Three kinds, in increasing order of what they need:

* ``IsTeamMember`` — decided from the request plus a query. It reads the team
  id out of the path and asks the database. No record has been loaded yet.
* ``IsPostAuthor`` — decided from the loaded row alone, no query at all.
* ``CanEditPost`` — needs both the row and a query, because a team owner may
  edit anyone's post in their team.

All three take the session from ``request.state.db``, which the application
puts there for the duration of the request. Sharing the request's session
matters: a permission that opened its own would run outside the handler's
transaction and take a second connection from the pool for every check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from examples.sqlalchemy_app.models import Membership, Post
from sqlalchemy import select

from starlette_permissions import BasePermission, PermissionContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def session_of(ctx: PermissionContext) -> AsyncSession:
    """Fetch the request-scoped session, or fail with a useful message.

    Returning ``False`` when the session is missing would read as "access
    denied" and hide a wiring mistake behind a 403.
    """
    session = getattr(ctx.connection.state, "db", None)
    if session is None:
        msg = (
            "No AsyncSession on request.state.db. Add DbSessionMiddleware "
            "(see examples/sqlalchemy_app/main.py) before using database-backed "
            "permissions."
        )
        raise RuntimeError(msg)
    return session


class IsTeamMember(BasePermission):
    """Requires membership of the team named in the path.

    Args:
        param: Path parameter holding the team id.
        role: Require this exact role (``"owner"``) rather than any membership.
    """

    def __init__(self, param: str = "team_id", role: str | None = None) -> None:
        self.param = param
        self.role = role
        self.message = (
            f"Requires the {role!r} role in this team" if role else "Team membership required"
        )

    async def has_permission(self, ctx: PermissionContext) -> bool:
        if not ctx.is_authenticated:
            return False

        # view_kwargs carries the endpoint's arguments; path_params is the
        # router's own view of them. Checking both means the rule works under
        # the decorator and the dependency alike.
        raw = ctx.view_kwargs.get(self.param, ctx.path_params.get(self.param))
        if raw is None:
            return False

        query = select(Membership.id).where(
            Membership.user_id == ctx.user.id,
            Membership.team_id == int(raw),
        )
        if self.role is not None:
            query = query.where(Membership.role == self.role)

        result = await session_of(ctx).execute(query.limit(1))
        return result.scalar_one_or_none() is not None

    def __repr__(self) -> str:
        return f"IsTeamMember(param={self.param!r}, role={self.role!r})"


class IsPostAuthor(BasePermission):
    """Object-level: the post belongs to the current user.

    ``IsOwner("author_id")`` from the library does exactly this; the explicit
    version is here to show the shape of a hand-written object rule.
    """

    message = "Only the author may modify this post"

    def has_object_permission(self, ctx: PermissionContext, obj: Post) -> bool:
        return ctx.is_authenticated and obj.author_id == ctx.user.id


class IsTeamOwnerOf(BasePermission):
    """Object-level: the current user owns the team the record belongs to."""

    message = "Requires ownership of the team this post belongs to"

    def __init__(self, team_field: str = "team_id") -> None:
        self.team_field = team_field

    async def has_object_permission(self, ctx: PermissionContext, obj: Post) -> bool:
        if not ctx.is_authenticated:
            return False
        result = await session_of(ctx).execute(
            select(Membership.id)
            .where(
                Membership.user_id == ctx.user.id,
                Membership.team_id == getattr(obj, self.team_field),
                Membership.role == "owner",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


#: Authors edit their own posts; team owners edit anything in their team.
#: Evaluation order matters — the author check is free, the ownership check is
#: a query, and `|` short-circuits, so the query only runs when it has to.
CanEditPost = IsPostAuthor | IsTeamOwnerOf()
