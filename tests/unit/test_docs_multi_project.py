"""The multi-project local app has to be documented where a researcher will look for it.

`research app` changes the first thing a new user types, so the quick start, the install
page, the Web guide, the HTTP guide, and the index all have to say so — and they have to
keep saying that the one-workspace daemon is unchanged. These assertions are anchors on the
few sentences that carry a promise (Forget deletes nothing, the app binds loopback only, the
browser holds a session token and not the app token), so that rewriting the prose is fine
and quietly dropping the promise is not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCUMENTED_PAGES = (
    "README.md",
    "docs/index.md",
    "docs/guide/install.md",
    "docs/guide/web.md",
    "docs/guide/http.md",
    "docs/guide/troubleshooting.md",
)
"""The pages this feature is allowed to be explained on; nothing else is asserted."""

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\((?!https?:|mailto:|#)([^)#]+)(?:#[^)]*)?\)")
"""A relative Markdown link, without its anchor: exactly what can rot on disk."""


def read(relative: str) -> str:
    """The text of a checked-in documentation page."""
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_readme_and_guides_name_both_app_modes() -> None:
    readme = read("README.md")
    web = read("docs/guide/web.md")
    assert "research app" in readme
    assert "research serve -w" in web
    assert "Forget project" in web
    assert "does not delete" in web


def test_the_quick_start_is_uv_sync_then_research_app() -> None:
    readme = read("README.md")
    assert "uv sync" in readme
    assert "uv run research app" in readme


def test_the_readme_says_uv_run_is_the_repository_form() -> None:
    """An installed user types `research app`; `uv run` is how this repository runs it."""
    readme = read("README.md")
    assert "`research app`" in readme
    assert "uv run" in readme


def test_install_names_the_app_data_location_on_both_platforms() -> None:
    install = read("docs/guide/install.md")
    assert "%LOCALAPPDATA%" in install
    assert "ResearchHarness" in install
    assert "XDG_DATA_HOME" in install
    assert "~/.local/share/research-harness" in install
    assert "projects.json" in install
    assert "app-token" in install


def test_install_says_the_registry_holds_paths_and_not_copies() -> None:
    install = read("docs/guide/install.md")
    assert "projects.json" in install
    assert "research app" in install


def test_the_web_guide_documents_project_home_and_every_lifecycle_action() -> None:
    web = read("docs/guide/web.md")
    for copy in (
        "Your research projects",
        "New project",
        "Open folder",
        "Initialize research project",
        "Locate",
        "Rename",
        "Forget project",
        "Add project",
        "All projects",
        "Show in file manager",
    ):
        assert copy in web, f"the Web guide never mentions {copy!r}"


def test_the_web_guide_explains_the_session_scoped_browser_token() -> None:
    web = read("docs/guide/web.md")
    assert "sessionStorage" in web
    assert "bootstrap" in web
    assert "127.0.0.1" in web
    assert "app-token" in web


def test_the_web_guide_explains_the_folder_picker_per_platform() -> None:
    web = read("docs/guide/web.md")
    assert "zenity" in web
    assert "kdialog" in web
    assert "PowerShell" in web or "FolderBrowserDialog" in web


def test_the_web_guide_states_the_non_goals() -> None:
    web = read("docs/guide/web.md")
    lowered = web.lower()
    assert "desktop" in lowered
    assert "scan" in lowered
    assert "sync" in lowered


def test_the_http_guide_documents_the_project_prefix_and_control_plane() -> None:
    http = read("docs/guide/http.md")
    assert "/api/projects/{project_id}" in http
    for route in (
        "/api/app/health",
        "/api/app/bootstrap",
        "/api/app/session",
        "/api/projects/create",
        "/api/projects/open",
        "/api/projects/initialize",
        "/api/dialogs/folder",
    ):
        assert route in http, f"the HTTP guide never documents {route}"


def test_the_http_guide_lists_the_control_plane_error_codes() -> None:
    http = read("docs/guide/http.md")
    for code in (
        "project_not_found",
        "project_needs_initialization",
        "project_active_runs",
        "project_invalid",
        "picker_unavailable",
        "control_permission_denied",
    ):
        assert code in http, f"the HTTP guide never documents {code}"


def test_the_http_guide_keeps_the_single_workspace_daemon_contract() -> None:
    http = read("docs/guide/http.md")
    assert ".research/daemon-token" in http
    assert "research serve" in http
    assert "unchanged" in http


def test_the_documentation_index_lists_the_local_app() -> None:
    index = read("docs/index.md")
    assert "research app" in index


def test_troubleshooting_covers_an_occupied_port_and_a_used_launch_link() -> None:
    troubleshooting = read("docs/guide/troubleshooting.md")
    assert "research app" in troubleshooting
    assert "--port" in troubleshooting
    assert "already been used or has expired" in troubleshooting


@pytest.mark.parametrize("page", DOCUMENTED_PAGES)
def test_every_relative_link_on_a_documented_page_resolves(page: str) -> None:
    """A new section is worth nothing if the page it points at is not there."""
    source = REPO_ROOT / page
    broken = [
        target
        for target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8"))
        if not (source.parent / target).exists()
    ]
    assert broken == []
