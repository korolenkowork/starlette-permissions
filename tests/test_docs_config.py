"""Guards the documentation site's configuration.

The Search Console tag lives in a theme override rather than mkdocs.yml, which
makes it easy to delete by accident — and the failure is silent: the site keeps
building, Google just quietly stops treating it as verified.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MKDOCS = (ROOT / "mkdocs.yml").read_text()
OVERRIDE = ROOT / "overrides" / "main.html"


def test_the_theme_override_is_wired_up():
    assert "custom_dir: overrides" in MKDOCS, (
        "mkdocs.yml must point at overrides/, or the <head> injection is dropped"
    )
    assert OVERRIDE.is_file(), "overrides/main.html is missing"


def test_the_search_console_tag_is_present_and_in_extrahead():
    html = OVERRIDE.read_text()
    assert "{% extends" in html, "the override must extend Material's base template"
    assert "{% block extrahead %}" in html, (
        "the tag must sit in the extrahead block, which Material renders in <head>"
    )
    tag = re.search(r'<meta name="google-site-verification" content="([^"]+)"', html)
    assert tag, "google-site-verification meta tag is missing"
    assert len(tag.group(1)) > 20, "verification token looks truncated"


DOCS_WORKFLOW = (ROOT / ".github" / "workflows" / "docs.yml").read_text()


class TestAnalytics:
    def test_the_measurement_id_is_not_committed(self):
        """It ships in the page anyway, but keeping it out of the repo stops
        local builds and PR previews reporting into production stats."""
        assert "!ENV [GOOGLE_ANALYTICS_KEY" in MKDOCS, (
            "the Analytics property must come from the environment"
        )
        assert not re.search(r'property:\s*"?G-[A-Z0-9]{6,}', MKDOCS), (
            "a literal Measurement ID is committed in mkdocs.yml"
        )

    def test_the_tracker_is_skipped_when_no_id_is_set(self):
        """Material gates its analytics partial on `provider` alone, so without
        this override an unset ID still emits a tracker with an empty id=."""
        html = OVERRIDE.read_text()
        assert "{% block analytics %}" in html
        assert "config.extra.analytics.property" in html, (
            "the analytics block must check the property, not just the provider"
        )

    def test_consent_is_configured_alongside_analytics(self):
        """gtag.js sets cookies; Material only defers loading until acceptance
        when a consent block exists."""
        assert "consent:" in MKDOCS
        assert "actions: [accept, reject, manage]" in MKDOCS

    def test_ci_injects_the_id_only_for_the_production_deploy(self):
        assert "GOOGLE_ANALYTICS_KEY:" in DOCS_WORKFLOW
        assert "vars.GOOGLE_ANALYTICS_KEY" in DOCS_WORKFLOW
        assert "github.ref == 'refs/heads/main'" in DOCS_WORKFLOW, (
            "pull-request previews must not report into production analytics"
        )
