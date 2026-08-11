# AGENTS.md

Guidance for AI agents working in this repository. Human contributors will find
it useful too, but it is written for an agent starting cold.

`starlette-permissions` is a small, dependency-light library that other projects
install. That shapes almost every rule below: a mistake here propagates into
everyone's dependency resolution, and there is no application around it to
absorb sloppiness.

## Quick reference

```bash
poetry install --with dev    # set up
poetry run pytest -q         # tests
poetry run ruff check .      # lint
poetry run ruff format .     # format
poetry run mypy              # types (strict)
poetry run mkdocs serve      # docs at /starlette-permissions/, not /
```

All four must pass before anything is done. There is no partial credit: `ruff`
runs with `select = ["ALL"]`, and `mypy` runs `strict`.

## Layout

```
src/starlette_permissions/
├── base.py          BasePermission, the metaclass giving classes & | ~,
│                    and resolve_permission() — the normalisation funnel
├── operators.py     AND / OR / NOT, All() / Any() / Not()
├── context.py       PermissionContext: the only thing a rule receives
├── checks.py        check_permissions() — every path funnels through here
├── resolver.py      finding the Request; rewriting endpoint signatures
├── decorators.py    @permission_required, @object_permission_required
├── dependencies.py  requires() — the only module that imports FastAPI
├── endpoints.py     PermissionMixin for Starlette HTTPEndpoint
├── middleware.py    PermissionMiddleware
├── settings.py      configure() / PermissionSettings
├── compat.py        the legacy is_permitted() shim
└── permissions/     the built-in rules
```

Adding an enforcement surface? It must build a `PermissionContext` and call
`check_permissions`. Do not reimplement evaluation.

## Rules that are load-bearing

These are not style preferences. Each one has a failure behind it.

### 1. Never cap a dependency in `pyproject.toml`

`starlette>=0.35` has no upper bound, deliberately. A cap in library metadata
propagates into every downstream resolution: cap Starlette at 1.6 and the day
1.7 ships, every application depending on both is stuck until we cut a release.

The tested ceiling lives in `ci.yml` as `CEILING_*` and in
`docs/compatibility.md`. That is a claim about what was tested, not a
constraint on what may be installed. `tests/test_compatibility_claims.py`
fails if those drift apart.

### 2. `dependencies.py` must not use `from __future__ import annotations`

FastAPI reads annotations at runtime and resolves any string it finds against
the callable's `__globals__`. `PermissionChecker` is a class *instance* and has
no `__globals__` at all, so a stringified `request: Request` makes older FastAPI
treat it as a **query parameter** instead of injecting the request. Modern
FastAPI happens to resolve it another way, which hides the bug — it only shows
up on the `floor` CI job.

Every other module may use the future import.

### 3. Annotations on wrapped endpoints must be resolved eagerly

The decorator hands the router a wrapper that lives in
`starlette_permissions.decorators`, not the user's module. Use
`resolver.resolved_signature()`, which evaluates annotations against the
*original function's* globals. Attaching an unevaluated `"Request"` string to
that wrapper breaks the same way as above.

Covered by `test_resolver.py::test_annotations_are_resolved_against_the_users_globals`.

### 4. FastAPI stays optional

Nothing outside `dependencies.py` may import FastAPI, even lazily inside a
function. The `starlette-only` CI job uninstalls it and runs the suite; a
subprocess test asserts `fastapi` never lands in `sys.modules` on import.

### 5. Permissions are shared across requests

An instance is built once when the route is defined and reused forever. Store
configuration in `__init__` and nothing else. Per-request state belongs on the
context. A rule that mutates `self` is a data race.

### 6. Multiple permissions mean AND

Matching Django and DRF. Adding a rule to a list must tighten access, never
loosen it. `compat.py` keeps the old OR behaviour for migration and warns; do
not let OR semantics leak back into the main API.

### 7. Denials raise, never return

`PermissionDenied` subclasses Starlette's `HTTPException` so exception handlers
and error logging see it. Returning a `JSONResponse` makes the permission layer
invisible to everything upstream. The one exception is `PermissionMiddleware`,
which sits outside `ExceptionMiddleware` and must render its own response — a
raise there becomes a 500.

### 8. A wiring mistake is an error, not a denial

If a rule cannot reach what it needs — no session on `request.state`, an
owner field that does not exist — raise. Returning `False` renders it as a
403 and sends someone hunting a permissions bug that is not there.

## Testing

`tests/` mirrors the surfaces, plus:

- `test_compatibility_claims.py` — asserts `ci.yml`, `pyproject.toml`,
  `README.md` and `docs/compatibility.md` agree about supported versions.
  If you bump a version anywhere, this tells you what else to update.
- `test_examples.py`, `test_sqlalchemy_example.py` — the `examples/` apps are
  documentation, so they are tested like everything else. Changing an example
  means changing its test.
- `testing.py` ships `make_context()` / `make_request()`; use them instead of
  hand-rolling ASGI scopes.

Four environments must stay green. Before claiming a change works, run at least
the ceiling and the floor:

| | Versions |
|---|---|
| ceiling | latest Starlette + FastAPI, Python 3.10–3.14 |
| floor | `starlette==0.36.3`, `fastapi==0.110.0`, `httpx<0.28` |
| starlette-only | FastAPI uninstalled |
| upstream | latest unpinned, non-blocking |

`configure()` mutates a module-level singleton. `tests/conftest.py` has an
autouse fixture restoring it; do not remove it, and do not add a test that
reloads `starlette_permissions` modules in-process — that orphans the singleton
and breaks unrelated tests.

## Documentation

`docs/` is a MkDocs site published to GitHub Pages from `main` by `docs.yml`.
It builds with `--strict`, so a broken internal link fails the build.

Docs are treated as claims. If you write a snippet that could be wrong, add a
test for it — `test_sqlalchemy_example.py::TestDocumentedTestingPatterns` does
exactly that. A new page needs a `mkdocs.yml` nav entry, or `--strict` fails.

## Releasing

Publishing runs **only** on a pushed tag matching `v[0-9]+.[0-9]+.[0-9]+*`.
Nothing else reaches PyPI — not a push to main, not a merged PR.

1. Bump `version` in `pyproject.toml` **and** `__version__` in
   `src/starlette_permissions/__init__.py`. The workflow fails if they disagree
   with each other or with the tag.
2. Move the `[Unreleased]` changelog entries under the new version. The
   workflow fails if `CHANGELOG.md` has no section for it.
3. `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0`

The tag must be an ancestor of `origin/main`; releases cannot be cut from a
branch. A tag push does not wait for CI, so `publish.yml` re-runs lint, mypy
and the suite on 3.10 and 3.14, then installs the built wheel and imports it
before uploading.

Use the Actions tab → "Run workflow" for a TestPyPI dry run.

## Things to leave alone unless asked

- The `Any` export at the package root shadows `typing.Any` on purpose, to pair
  with `All`. `Any_permission` is the alias for modules that need both.
- The `ignore:Unclosed <MemoryObject:ResourceWarning` filter in
  `pyproject.toml` works around a Starlette <1.0 TestClient leak. It is matched
  on the exact message so a real leak still fails. Do not broaden it to all
  `ResourceWarning`s.
- `PermissionMeta.__or__` shadows `type.__or__`, so a permission class cannot
  appear in a `X | None` annotation. That is the cost of `IsA | IsB` working on
  classes, and it is documented.
- Ruff ignores in `pyproject.toml` each carry a comment explaining why. Do not
  add a bare ignore.

## Conventions

- Comments explain *why*, never *what*. Match the density of surrounding code.
- Public API is fully annotated; the package ships `py.typed`.
- Error messages tell the reader what to do, not just what failed.
- Google-style docstrings on public classes and functions. `__init__` arguments
  are documented on the class.
