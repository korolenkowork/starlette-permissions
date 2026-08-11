"""SQLAlchemy 2.0 models for the permissions example.

A small team-based blog: users belong to teams through a membership row that
carries a role, and posts belong to both an author and a team. That is enough
to need all three kinds of rule — one decided from the request, one from a
database lookup, and one from the loaded record.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    api_token: Mapped[str] = mapped_column(String(64), unique=True)
    # IsAdminUser reads this by default; see settings.admin_attrs.
    is_admin: Mapped[bool] = mapped_column(default=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")

    @property
    def roles(self) -> list[str]:
        """Role names, in the shape the default ``role_getter`` expects.

        Reading this walks ``self.memberships``. Under asyncio a lazy load
        raises ``MissingGreenlet``, so whoever loads the user must eager-load
        the relationship — see ``user_by_token`` below.
        """
        return [m.role for m in self.memberships]


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    #: "owner" or "member".
    role: Mapped[str] = mapped_column(String(20), default="member")

    user: Mapped[User] = relationship(back_populates="memberships")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    published: Mapped[bool] = mapped_column(default=False)


def make_engine(url: str = "sqlite+aiosqlite:///:memory:"):
    """Create an engine. The default is in-memory, for the example and tests.

    ``StaticPool`` is not needed here because the example creates one engine
    per application instance and SQLAlchemy's async SQLite driver keeps the
    same connection for an in-memory database within a single pool.
    """
    return create_async_engine(url, future=True)


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed(session: AsyncSession) -> None:
    """Two teams, four users, three posts. Enough to exercise every rule."""
    acme = Team(id=1, name="acme")
    globex = Team(id=2, name="globex")

    root = User(id=1, name="root", api_token="tok-root", is_admin=True)
    ihor = User(id=2, name="ihor", api_token="tok-ihor")
    dana = User(id=3, name="dana", api_token="tok-dana")
    outsider = User(id=4, name="outsider", api_token="tok-outsider")

    session.add_all([acme, globex, root, ihor, dana, outsider])
    await session.flush()

    session.add_all(
        [
            # ihor owns acme; dana is a plain member of acme.
            Membership(user_id=ihor.id, team_id=acme.id, role="owner"),
            Membership(user_id=dana.id, team_id=acme.id, role="member"),
            # outsider belongs to globex only.
            Membership(user_id=outsider.id, team_id=globex.id, role="member"),
        ]
    )
    session.add_all(
        [
            Post(id=1, title="ihor's post", author_id=ihor.id, team_id=acme.id),
            Post(id=2, title="dana's post", author_id=dana.id, team_id=acme.id),
            Post(id=3, title="globex post", author_id=outsider.id, team_id=globex.id),
        ]
    )
    await session.commit()


async def user_by_token(session: AsyncSession, token: str) -> User | None:
    """Load a user and their memberships in one round trip.

    ``selectinload`` matters: ``User.roles`` walks ``memberships``, and a lazy
    load triggered later — outside this await — would raise ``MissingGreenlet``.
    """
    result = await session.execute(
        select(User).where(User.api_token == token).options(selectinload(User.memberships))
    )
    return result.scalar_one_or_none()
