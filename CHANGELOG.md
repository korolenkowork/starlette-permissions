# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-11

First release.

### Added

- `BasePermission` with `has_permission` and `has_object_permission`, either of
  which may be sync or async.
- Composition with `&`, `|` and `~` on permission classes and instances, plus
  the explicit `All(...)`, `Any(...)` and `Not(...)` helpers.
- Three ways to enforce, all sharing the same permission objects:
  - `@permission_required(...)` and `@object_permission_required(...)`
    decorators, which add a `Request` parameter to endpoints that do not
    declare one;
  - `requires(...)` and `requires_object(...)` FastAPI dependencies, plus
    `permission_responses()` for OpenAPI;
  - `PermissionMixin` for Starlette's `HTTPEndpoint`, with per-method rules.
- `PermissionMiddleware` for app-wide or route-scoped policies, with path
  exemptions and method filtering.
- Built-in permissions: `AllowAny`, `DenyAll`, `ReadOnly`, `IsMethod`,
  `HasHeader`, `IsAuthenticated`, `IsAnonymous`, `IsAdminUser`,
  `IsAuthenticatedOrReadOnly`, `HasRole`/`HasAnyRole`/`HasAllRoles`,
  `HasScope`/`HasAnyScope`/`HasAllScopes`, `HasAPIKey`, `IsOwner`,
  `IsOwnerOrReadOnly`.
- `Predicate` and the `@permission` decorator, so a plain function can be used
  wherever a permission is expected.
- `configure()` / `PermissionSettings` for user, role and scope resolution,
  status codes, messages and headers — globally or per mounted application.
- `check_permissions` / `has_permissions` and their object-level counterparts,
  for use outside a request handler.
- `starlette_permissions.testing` with `make_request` and `make_context`.
- Runnable examples for FastAPI, Starlette and SQLAlchemy (async, 2.0 style),
  each covered by the test suite. The SQLAlchemy one shows request-scoped
  session sharing, query-backed rules and object-level rules on ORM rows;
  see `docs/sqlalchemy.md`.
- `install_exception_handlers(app)` to render denials as JSON on plain
  Starlette, which otherwise returns plain text.
- `starlette_permissions.compat`, a drop-in replacement for a hand-rolled
  `permission_required` that keeps the older OR semantics and response-returning
  behaviour while emitting a `DeprecationWarning`. Legacy `is_permitted`
  permissions are adapted automatically, so they work with the modern API
  unchanged.

### Notes

- Supported: Python 3.10–3.14, Starlette 0.35–1.6.0, FastAPI 0.110–0.141.1
  (`fastapi` extra). Both ends are pinned in CI and run against the full
  suite, so the range is tested rather than asserted. No upper bound is
  declared in the package metadata — see `docs/compatibility.md` for why.
- FastAPI pins Starlette narrowly in every release, so older FastAPI (which
  requires Starlette < 0.28) cannot be combined with a supported Starlette.
- Multiple permissions require **all** of them, as in Django and DRF. Pass
  `mode="any"` for the alternative.
- Denials **raise** `PermissionDenied` (a Starlette `HTTPException`) rather
  than returning a response, so exception handlers and error logging see them.
- `IsAuthenticated` answers `401`; every other rule answers `403`. Both are
  configurable.

[Unreleased]: https://github.com/korolenkowork/starlette-permissions/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/korolenkowork/starlette-permissions/releases/tag/v0.1.0
