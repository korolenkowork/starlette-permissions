"""Keeps the documented support range honest.

The compatibility table, the CI pins and the package classifiers are three
statements of the same fact, and they drift apart silently. These tests make
that drift a test failure instead of a wrong promise to users.

Deliberately regex-based rather than YAML/TOML-parsed: this must not add a
dependency to run, and the lines it reads are fixed-format.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
PUBLISH = (ROOT / ".github" / "workflows" / "publish.yml").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()
COMPAT_DOC = (ROOT / "docs" / "compatibility.md").read_text()
README = (ROOT / "README.md").read_text()


def _ci_env(name: str) -> str:
    match = re.search(rf"^  {name}:\s*\"([^\"]+)\"", CI, re.MULTILINE)
    assert match, f"{name} not found in ci.yml env block"
    return match.group(1)


def _ci_python_matrix() -> list[str]:
    match = re.search(r"^        python-version: \[([^\]]+)\]", CI, re.MULTILINE)
    assert match, "python-version matrix not found in ci.yml"
    return re.findall(r"\"([^\"]+)\"", match.group(1))


CEILING_STARLETTE = _ci_env("CEILING_STARLETTE")
CEILING_FASTAPI = _ci_env("CEILING_FASTAPI")


class TestCeilingIsConsistent:
    def test_ceiling_job_pins_the_env_vars_rather_than_literals(self):
        """A hardcoded pin in the job would silently diverge from the env block."""
        assert '"starlette==${CEILING_STARLETTE}"' in CI
        assert '"fastapi==${CEILING_FASTAPI}"' in CI

    @pytest.mark.parametrize("document", ["compatibility.md", "README.md"])
    def test_documented_ceiling_matches_ci(self, document):
        text = COMPAT_DOC if document == "compatibility.md" else README
        assert CEILING_STARLETTE in text, (
            f"{document} does not mention the pinned Starlette ceiling "
            f"{CEILING_STARLETTE}; bump the table when bumping ci.yml"
        )
        assert CEILING_FASTAPI in text, (
            f"{document} does not mention the pinned FastAPI ceiling {CEILING_FASTAPI}"
        )

    def test_ceiling_is_not_below_the_floor(self):
        floor_starlette = re.search(r'"starlette==([\d.]+)"', CI)
        assert floor_starlette, "floor job pin not found"

        def parts(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        assert parts(CEILING_STARLETTE) > parts(floor_starlette.group(1))


class TestFloorIsConsistent:
    def test_declared_minimum_matches_the_floor_job(self):
        declared = re.search(r'dependencies = \["starlette>=([\d.]+)"\]', PYPROJECT)
        assert declared, "starlette lower bound not found in pyproject.toml"
        pinned = re.search(r'"starlette==([\d.]+)"', CI)
        assert pinned, "floor job pin not found in ci.yml"

        def parts(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        # The job must test at or above what the metadata promises.
        assert parts(pinned.group(1)) >= parts(declared.group(1))

    def test_metadata_declares_no_upper_bound(self):
        """An upper bound here would propagate into every downstream resolve."""
        assert "starlette<" not in PYPROJECT.replace("starlette<0.28", "")
        assert re.search(r'fastapi = \["fastapi>=[\d.]+"\]', PYPROJECT)


class TestPublishIsTagOnly:
    """Publishing must never be reachable from an ordinary push.

    These read the workflow as text rather than parsing YAML, so the tests
    stay dependency-free — see the module docstring.
    """

    def test_the_only_automatic_trigger_is_a_tag_push(self):
        triggers = PUBLISH.split("permissions:")[0]
        assert "push:\n    tags:" in triggers, "publish must trigger on tag pushes"
        assert "branches:" not in triggers, (
            "publish.yml must not trigger on any branch push — releases come from tags only"
        )

    def test_the_tag_pattern_requires_a_full_version(self):
        assert '- "v[0-9]+.[0-9]+.[0-9]+*"' in PUBLISH, (
            "the tag filter must require v<major>.<minor>.<patch>, so that an "
            "arbitrary tag like 'demo' cannot publish"
        )

    def test_release_published_is_not_also_a_trigger(self):
        """Both triggers together fire twice and the second upload fails."""
        assert "types: [published]" not in PUBLISH

    def test_the_version_guards_are_present(self):
        for guard in ("does not match pyproject", "does not match __version__"):
            assert guard in PUBLISH, f"missing release guard: {guard}"

    def test_the_tag_must_be_on_main(self):
        assert "--is-ancestor" in PUBLISH, "a release cut from a feature branch must be rejected"

    def test_the_suite_runs_before_upload(self):
        """A tag push does not wait for CI, so publish re-runs the gate."""
        assert "poetry run pytest -q" in PUBLISH
        assert "poetry run mypy" in PUBLISH

    def test_upload_jobs_depend_on_the_build(self):
        assert "needs: [verify, build]" in PUBLISH
        assert "needs: build" in PUBLISH


class TestAgentsDoc:
    def test_agents_doc_exists_and_covers_the_load_bearing_rules(self):
        agents = (ROOT / "AGENTS.md").read_text()
        for topic in (
            "from __future__ import annotations",  # the dependencies.py rule
            "resolved_signature",  # the wrapper-annotation rule
            "Never cap a dependency",  # the metadata rule
            "starlette-only",  # the optional-FastAPI rule
        ):
            assert topic in agents, f"AGENTS.md no longer documents: {topic}"

    def test_agents_doc_release_steps_match_the_workflow(self):
        agents = (ROOT / "AGENTS.md").read_text()
        assert "v[0-9]+.[0-9]+.[0-9]+*" in agents, (
            "AGENTS.md must state the same tag pattern the workflow enforces"
        )


class TestPythonVersions:
    def test_matrix_covers_every_declared_classifier(self):
        classifiers = set(re.findall(r"Programming Language :: Python :: (3\.\d+)", PYPROJECT))
        matrix = set(_ci_python_matrix())
        assert classifiers == matrix, (
            f"classifiers {sorted(classifiers)} != CI matrix {sorted(matrix)}"
        )

    def test_requires_python_matches_the_lowest_tested(self):
        declared = re.search(r'requires-python = ">=(\d+\.\d+)"', PYPROJECT)
        assert declared
        assert declared.group(1) == min(
            _ci_python_matrix(), key=lambda v: tuple(map(int, v.split(".")))
        )

    def test_python_314_is_supported(self):
        assert "3.14" in _ci_python_matrix()
        assert "Programming Language :: Python :: 3.14" in PYPROJECT

    def test_the_running_interpreter_is_a_supported_one(self):
        running = f"{sys.version_info.major}.{sys.version_info.minor}"
        assert running in _ci_python_matrix(), (
            f"running on Python {running}, which CI does not cover"
        )
