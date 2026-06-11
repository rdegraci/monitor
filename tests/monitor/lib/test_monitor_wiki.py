"""Tests for monitor-wiki path resolution and provisioning helpers."""

from __future__ import annotations

import monitor.config as config

from pathlib import Path

import pytest

from monitor.lib import monitor_wiki


@pytest.fixture(autouse=True)
def fake_appdir(monkeypatch, tmp_path):
    """Redirect the monitor appdir to a per-test temporary directory.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        tmp_path: Temporary test directory.

    Yields:
        None. The fixture exists for setup side effects.
    """
    appdir_root = tmp_path / "appdir"
    monkeypatch.setattr(
        monitor_wiki.appdirs,
        "user_config_dir",
        lambda _app_name: str(appdir_root),
    )
    yield


def test_resolve_project_identity_path_uses_repo_root(tmp_path):
    """Resolve the nearest repository root when inside a git working tree.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "Repo"
    nested = repo_root / "src" / "feature"
    nested.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    resolved = monitor_wiki.resolve_project_identity_path(nested)

    assert resolved == repo_root.resolve()


def test_resolve_project_identity_path_falls_back_to_startup_dir(tmp_path):
    """Use the startup directory when no repository root exists.

    Args:
        tmp_path: Temporary test directory.
    """
    startup_dir = tmp_path / "scratch" / "workspace"
    startup_dir.mkdir(parents=True)

    resolved = monitor_wiki.resolve_project_identity_path(startup_dir)

    assert resolved == startup_dir.resolve()


def test_project_slug_from_path_distinguishes_same_basename_repos(tmp_path):
    """Produce distinct slugs for different canonical repository paths.

    Args:
        tmp_path: Temporary test directory.
    """
    path_a = tmp_path / "Users" / "alice" / "demo"
    path_b = tmp_path / "Users" / "bob" / "demo"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    slug_a = monitor_wiki.project_slug_from_path(path_a)
    slug_b = monitor_wiki.project_slug_from_path(path_b)

    assert slug_a != slug_b
    assert slug_a.endswith("users-alice-demo")
    assert slug_b.endswith("users-bob-demo")


def test_project_wiki_dir_for_nested_repo_paths_is_stable(tmp_path):
    """Map nested directories inside one repo to the same project wiki path.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "sample-repo"
    nested_a = repo_root / "a" / "b"
    nested_b = repo_root / "docs"
    nested_a.mkdir(parents=True)
    nested_b.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    wiki_a = monitor_wiki.project_wiki_dir_for_start_path(nested_a)
    wiki_b = monitor_wiki.project_wiki_dir_for_start_path(nested_b)

    assert wiki_a == wiki_b


def test_ensure_project_wiki_creates_root_project_dir_and_index(tmp_path):
    """Provision the wiki root, project directory, and starter index.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "project"
    startup_dir = repo_root / "src"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    project_dir = monitor_wiki.ensure_project_wiki(startup_dir)

    assert project_dir.is_dir()
    assert project_dir.parent == monitor_wiki.monitor_wiki_root()
    index_path = project_dir / "INDEX.md"
    assert index_path.is_file()
    assert "# Project Wiki Index" in index_path.read_text(encoding="utf-8")


def test_ensure_project_wiki_preserves_existing_index_contents(tmp_path):
    """Avoid overwriting an existing project wiki index.

    Args:
        tmp_path: Temporary test directory.
    """
    startup_dir = tmp_path / "workspace"
    startup_dir.mkdir(parents=True)

    project_dir = monitor_wiki.project_wiki_dir_for_start_path(startup_dir)
    project_dir.mkdir(parents=True)
    index_path = project_dir / "INDEX.md"
    index_path.write_text("custom index\n", encoding="utf-8")

    monitor_wiki.ensure_project_wiki(startup_dir)

    assert index_path.read_text(encoding="utf-8") == "custom index\n"


def test_configure_project_wiki_paths_caches_session_context(tmp_path):
    """Cache frozen project wiki context for the active session.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "tracked-repo"
    startup_dir = repo_root / "nested"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    monitor_wiki.configure_project_wiki_paths(startup_dir)

    assert config.PROJECT_WIKI_IDENTITY_PATH == str(repo_root.resolve())
    assert config.PROJECT_WIKI_PATH == str(
        monitor_wiki.project_wiki_dir_for_start_path(startup_dir)
    )


def test_configure_project_wiki_paths_with_none_clears_session_context():
    """Clear cached project wiki context when requested.

    Args:
        None.
    """
    config.PROJECT_WIKI_IDENTITY_PATH = "sentinel"
    config.PROJECT_WIKI_PATH = "sentinel"

    monitor_wiki.configure_project_wiki_paths(None)

    assert config.PROJECT_WIKI_IDENTITY_PATH is None
    assert config.PROJECT_WIKI_PATH is None


def test_ensure_configured_project_wiki_provisions_from_cached_context(tmp_path):
    """Provision the frozen session wiki directory on first wiki-aware use.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "cached-repo"
    startup_dir = repo_root / "src"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    monitor_wiki.configure_project_wiki_paths(startup_dir)
    project_dir = monitor_wiki.ensure_configured_project_wiki()

    assert project_dir == monitor_wiki.project_wiki_dir_for_start_path(startup_dir)
    assert project_dir.is_dir()
    index_path = project_dir / "INDEX.md"
    assert index_path.is_file()
    assert monitor_wiki.configured_project_wiki_index_path() == index_path


def test_ensure_configured_project_wiki_returns_none_without_context():
    """Skip provisioning when the session has no frozen wiki context.

    Args:
        None.
    """
    monitor_wiki.configure_project_wiki_paths(None)

    assert monitor_wiki.ensure_configured_project_wiki() is None
    assert monitor_wiki.configured_project_wiki_index_path() is None


def test_has_substantive_configured_project_wiki_false_for_starter_template(tmp_path):
    """Treat a starter-only configured wiki as non-substantive.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "starter-only-repo"
    startup_dir = repo_root / "src"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    monitor_wiki.configure_project_wiki_paths(startup_dir)
    monitor_wiki.ensure_configured_project_wiki()

    assert monitor_wiki.has_substantive_configured_project_wiki() is False


def test_has_substantive_configured_project_wiki_true_for_customized_index(tmp_path):
    """Treat a modified configured wiki index as substantive content.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "customized-repo"
    startup_dir = repo_root / "src"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    monitor_wiki.configure_project_wiki_paths(startup_dir)
    project_dir = monitor_wiki.ensure_configured_project_wiki()
    index_path = project_dir / "INDEX.md"
    index_path.write_text("# Project Wiki Index\n\nCustom content\n", encoding="utf-8")

    assert monitor_wiki.has_substantive_configured_project_wiki() is True


def test_configured_project_wiki_additional_pages_returns_up_to_two_existing_pages(tmp_path):
    """Return up to two additional existing wiki pages referenced by INDEX.

    Args:
        tmp_path: Temporary test directory.
    """
    repo_root = tmp_path / "linked-pages-repo"
    startup_dir = repo_root / "src"
    startup_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    monitor_wiki.configure_project_wiki_paths(startup_dir)
    project_dir = monitor_wiki.ensure_configured_project_wiki()
    (project_dir / "ARCHITECTURE.md").write_text("architecture\n", encoding="utf-8")
    (project_dir / "CONVENTIONS.md").write_text("conventions\n", encoding="utf-8")
    (project_dir / "TESTING.md").write_text("testing\n", encoding="utf-8")
    (project_dir / "INDEX.md").write_text(
        "# Project Wiki Index\n\nSee ARCHITECTURE.md and CONVENTIONS.md and TESTING.md\n",
        encoding="utf-8",
    )

    pages = monitor_wiki.configured_project_wiki_additional_pages(max_pages=2)

    assert len(pages) == 2
    assert [page.name for page in pages] == ["ARCHITECTURE.md", "CONVENTIONS.md"]


def test_ensure_project_wiki_returns_none_when_directory_creation_fails(tmp_path, monkeypatch):
    """Degrade safely when the project wiki directory cannot be created.

    Args:
        tmp_path: Temporary test directory.
        monkeypatch: Pytest monkeypatch fixture.
    """
    startup_dir = tmp_path / "workspace"
    startup_dir.mkdir(parents=True)

    original_mkdir = Path.mkdir

    def fail_for_wiki_root(self, *args, **kwargs):
        if self == monitor_wiki.monitor_wiki_root():
            raise OSError("mkdir denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_for_wiki_root)

    assert monitor_wiki.ensure_project_wiki(startup_dir) is None


def test_ensure_project_wiki_returns_none_when_index_write_fails(tmp_path, monkeypatch):
    """Degrade safely when the starter index cannot be written.

    Args:
        tmp_path: Temporary test directory.
        monkeypatch: Pytest monkeypatch fixture.
    """
    startup_dir = tmp_path / "workspace"
    startup_dir.mkdir(parents=True)

    original_write_text = Path.write_text

    def fail_for_index(self, *args, **kwargs):
        if self.name == "INDEX.md":
            raise OSError("write denied")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_for_index)

    assert monitor_wiki.ensure_project_wiki(startup_dir) is None


def test_ensure_configured_project_wiki_returns_none_when_provisioning_fails(tmp_path, monkeypatch):
    """Keep configured wiki provisioning non-fatal on filesystem errors.

    Args:
        tmp_path: Temporary test directory.
        monkeypatch: Pytest monkeypatch fixture.
    """
    startup_dir = tmp_path / "workspace"
    startup_dir.mkdir(parents=True)
    monitor_wiki.configure_project_wiki_paths(startup_dir)

    original_write_text = Path.write_text

    def fail_for_index(self, *args, **kwargs):
        if self.name == "INDEX.md":
            raise OSError("write denied")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_for_index)

    assert monitor_wiki.ensure_configured_project_wiki() is None
