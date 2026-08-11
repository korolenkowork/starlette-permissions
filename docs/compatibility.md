# Compatibility

Every combination in the table below is exercised by CI on each run. Nothing
here is inferred from changelogs — the full test suite runs against these exact
versions.

## Supported versions

| | Minimum | Newest tested |
|---|---|---|
| **Python** | 3.10 | **3.14** |
| **Starlette** | 0.35 | **1.6.0** |
| **FastAPI** *(optional extra)* | 0.110 | **0.141.1** |

Starlette is the only required dependency. FastAPI is needed solely for
`requires(...)` and `requires_object(...)`; see [FastAPI](fastapi.md).

## How each bound is verified

| CI job | What it pins | What it proves |
|---|---|---|
| `test` | nothing — resolves current | Works on Python 3.10 – 3.14, Linux/macOS/Windows |
| `floor` | `starlette==0.36.3`, `fastapi==0.110.0` | The declared minimum is real |
| `ceiling` | `starlette==1.6.0`, `fastapi==0.141.1` | The documented maximum is real |
| `starlette-only` | FastAPI uninstalled | FastAPI is genuinely optional |
| `upstream` | latest, unpinned, non-blocking | Warns when a newer release lands |

The `ceiling` job asserts that the pins actually resolved to the requested
versions, so a silent downgrade cannot make it pass for the wrong reason.

## Why there is no upper bound in the metadata

`pyproject.toml` declares `starlette>=0.35` with no cap, even though the tested
ceiling is pinned above. That is deliberate.

An upper bound in package metadata propagates into every downstream
resolution. If this package capped Starlette at 1.6, then the day 1.7 ships,
every application depending on both would be forced to either hold Starlette
back or drop this library — and only a new release here could unblock them. A
stale line in this file is a much cheaper mistake.

So the cap lives in CI, where it is a *claim about what has been tested* rather
than a *constraint on what may be installed*. Newer versions very likely work;
they simply have not been verified here yet.

## When a newer release appears

The `upstream` job runs weekly against the latest releases and is allowed to
fail without blocking anything. Two outcomes:

- **It passes** and reports drift. Bump `CEILING_STARLETTE` /
  `CEILING_FASTAPI` in [`.github/workflows/ci.yml`](https://github.com/korolenkowork/starlette-permissions/blob/main/.github/workflows/ci.yml)
  and the table above, in one commit backed by that passing run.
- **It fails.** Upstream changed something. The frozen `ceiling` job still
  passes, so released versions of this library keep working while the break is
  fixed.

## Known version-specific notes

### FastAPI pins Starlette narrowly

Every FastAPI release constrains Starlette to a tight range, so the two floors
cannot be chosen independently. FastAPI 0.110 is the first release permitting
Starlette 0.36.3; anything older requires Starlette < 0.28, which is below this
library's minimum. If you see a resolver conflict mentioning both, this is why.

### Annotations under PEP 563 and PEP 649

The decorator rewrites the endpoint's signature, so the wrapper it returns
lives in `starlette_permissions.decorators` rather than your module. Annotations
are therefore resolved eagerly, against your function's own globals, before the
signature is attached — otherwise a module using
`from __future__ import annotations` would hand the framework the bare string
`"Request"` to resolve against the wrong namespace.

This is covered on every supported interpreter, including Python 3.14, where
[PEP 649](https://peps.python.org/pep-0649/) makes lazy annotations the default.
Both the stringified and the lazily-evaluated paths are tested.

### Starlette's TestClient and httpx

Not a runtime concern, only relevant if you are running this library's own test
suite against an older Starlette: `TestClient` used the `app=` shortcut that
httpx removed in 0.28. Starlette 1.0 and later use `httpx2` instead. The `floor`
job therefore installs `httpx<0.28`, and the others install `httpx2`.

### Python 3.14

Fully supported and in the test matrix. No behavioural differences from 3.13
in this library.
