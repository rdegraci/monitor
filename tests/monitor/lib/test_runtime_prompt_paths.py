"""Tests for per-project prompt-file overrides resolved from the startup cwd.

configure_runtime_prompt_paths() captures the cwd ONCE at app startup and
checks for MONITOR.md / MONITOR_CONVENTIONS.md there. If found, that file is
used for the rest of the session in preference to the appdir copy. An
interactive :cd later in the session does NOT re-resolve.
"""

import pytest

from monitor.lib import system_prompt


@pytest.fixture(autouse=True)
def reset_overrides():
    """Make sure each test starts from a clean override state and other tests
    don't see leakage from these ones."""
    system_prompt.configure_runtime_prompt_paths(None)
    yield
    system_prompt.configure_runtime_prompt_paths(None)


def test_cwd_with_monitor_md_overrides_appdir(tmp_path):
    (tmp_path / "MONITOR.md").write_text("project-specific instructions\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    out = system_prompt._load_runtime_instructions()
    assert out == "project-specific instructions\n"


def test_cwd_with_monitor_conventions_md_overrides_appdir(tmp_path):
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("project-specific conventions\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    out = system_prompt._load_runtime_coding_conventions()
    assert out == "project-specific conventions\n"


def test_cwd_without_override_falls_back_to_appdir(tmp_path):
    """An empty cwd should not produce an override; the loader must fall
    through to the appdir/packaged source."""
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    instructions = system_prompt._load_runtime_instructions()
    conventions = system_prompt._load_runtime_coding_conventions()
    # The appdir copies (or freshly seeded packaged copies) should be
    # non-empty — both ship with substantive content.
    assert instructions.strip()
    assert conventions.strip()
    # And they should NOT be a freshly-written cwd sentinel (no override
    # active). Use a token unlikely to appear in the packaged source.
    assert "SENTINEL_OVERRIDE_TEXT_xyz123" not in instructions
    assert "SENTINEL_OVERRIDE_TEXT_xyz123" not in conventions


def test_only_one_of_two_files_can_override(tmp_path):
    """Per-project repos may have one but not the other. Each override is
    resolved independently — finding MONITOR.md must not affect the
    conventions fallback path."""
    (tmp_path / "MONITOR.md").write_text("SENTINEL_OVERRIDE_TEXT_xyz123\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "SENTINEL_OVERRIDE_TEXT_xyz123\n"
    # Conventions should still come from the appdir/packaged source.
    conventions = system_prompt._load_runtime_coding_conventions()
    assert "SENTINEL_OVERRIDE_TEXT_xyz123" not in conventions
    assert conventions.strip()


def test_configure_with_none_clears_override(tmp_path):
    """Passing None to the configurator must clear any prior override — this
    is the test-isolation contract relied on by the autouse fixture."""
    (tmp_path / "MONITOR.md").write_text("temporary\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "temporary\n"

    system_prompt.configure_runtime_prompt_paths(None)
    out = system_prompt._load_runtime_instructions()
    assert "temporary" not in out


def test_cd_mid_session_does_not_reresolve(tmp_path, monkeypatch):
    """The cwd snapshot is taken once at startup. Even if the user :cd's into
    another directory mid-session — or if os.getcwd() now returns something
    different — the previously-resolved path must remain in effect."""
    cwd_at_startup = tmp_path / "startup_cwd"
    cwd_at_startup.mkdir()
    (cwd_at_startup / "MONITOR.md").write_text("frozen at startup\n")

    later_cwd = tmp_path / "later_cwd"
    later_cwd.mkdir()
    (later_cwd / "MONITOR.md").write_text("should NOT be picked up\n")

    # Snapshot the startup cwd.
    system_prompt.configure_runtime_prompt_paths(cwd_at_startup)

    # Simulate :cd into a different directory — os.getcwd() now returns
    # later_cwd, but the loaded prompt must still come from the snapshot.
    monkeypatch.chdir(later_cwd)
    assert system_prompt._load_runtime_instructions() == "frozen at startup\n"


def test_directory_named_monitor_md_is_not_treated_as_override(tmp_path):
    """A *directory* named MONITOR.md should not be picked as the override —
    the resolver explicitly checks is_file()."""
    (tmp_path / "MONITOR.md").mkdir()
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    # No override should have been set.
    out = system_prompt._load_runtime_instructions()
    assert out.strip()  # falls back to appdir/packaged


# --- build/ fallback --------------------------------------------------------


def test_build_folder_is_used_when_root_is_missing(tmp_path):
    """If <cwd>/MONITOR.md is absent but <cwd>/build/MONITOR.md exists, the
    build/ copy should be picked up. Useful when a build step generates a
    project-specific MONITOR.md without touching the repo root."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "MONITOR.md").write_text("FROM_BUILD_FOLDER\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "FROM_BUILD_FOLDER\n"


def test_root_wins_over_build_folder(tmp_path):
    """When both <cwd>/MONITOR.md and <cwd>/build/MONITOR.md exist, the root
    file wins — an explicit checked-in file is a stronger signal than a
    build artifact."""
    (tmp_path / "MONITOR.md").write_text("FROM_ROOT\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "MONITOR.md").write_text("FROM_BUILD_FOLDER\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "FROM_ROOT\n"


def test_build_folder_fallback_applies_to_conventions_too(tmp_path):
    """Same root → build/ → appdir order for MONITOR_CONVENTIONS.md."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "MONITOR_CONVENTIONS.md").write_text("CONV_FROM_BUILD\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_coding_conventions() == "CONV_FROM_BUILD\n"


def test_build_folder_directory_named_monitor_md_is_skipped(tmp_path):
    """A directory at <cwd>/build/MONITOR.md should not be picked either —
    the is_file() gate applies to both candidate locations."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "MONITOR.md").mkdir()
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    # Falls through to appdir/packaged source.
    out = system_prompt._load_runtime_instructions()
    assert out.strip()
    assert "FROM_BUILD_FOLDER" not in out


# --- AGENTS.md cross-tool fallback ------------------------------------------


def test_agents_md_used_when_no_monitor_md_anywhere(tmp_path):
    """If neither <cwd>/MONITOR.md nor <cwd>/build/MONITOR.md exists,
    <cwd>/AGENTS.md should be picked up — that's the whole point of the
    cross-tool fallback."""
    (tmp_path / "AGENTS.md").write_text("FROM_AGENTS_MD\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "FROM_AGENTS_MD\n"


def test_root_monitor_md_wins_over_agents_md(tmp_path):
    """When both <cwd>/MONITOR.md and <cwd>/AGENTS.md exist, the
    monitor-specific name beats the cross-tool name — the user explicitly
    chose to author a MONITOR.md."""
    (tmp_path / "MONITOR.md").write_text("FROM_ROOT_MONITOR\n")
    (tmp_path / "AGENTS.md").write_text("FROM_AGENTS_MD\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "FROM_ROOT_MONITOR\n"


def test_build_monitor_md_wins_over_agents_md(tmp_path):
    """build/MONITOR.md is monitor-specific even though it's in a deeper
    folder; it should win over a root AGENTS.md. Per spec: 'monitor-specific
    name beats cross-tool name within the chain.'"""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "MONITOR.md").write_text("FROM_BUILD_MONITOR\n")
    (tmp_path / "AGENTS.md").write_text("FROM_AGENTS_MD\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    assert system_prompt._load_runtime_instructions() == "FROM_BUILD_MONITOR\n"


def test_build_agents_md_is_not_read(tmp_path):
    """Per spec: <cwd>/build/AGENTS.md is NOT in the resolution chain. A
    build-generated AGENTS.md should be ignored; if a build step wants to
    provide monitor instructions, it must use build/MONITOR.md."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "AGENTS.md").write_text("SHOULD_NOT_BE_READ\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    out = system_prompt._load_runtime_instructions()
    assert "SHOULD_NOT_BE_READ" not in out
    # Falls through to appdir/packaged content.
    assert out.strip()


def test_agents_md_does_not_override_conventions(tmp_path):
    """AGENTS.md is general agent guidance, not code conventions; it must
    not be picked up for the MONITOR_CONVENTIONS.md chain."""
    (tmp_path / "AGENTS.md").write_text("FROM_AGENTS_MD\n")
    system_prompt.configure_runtime_prompt_paths(tmp_path)
    conventions = system_prompt._load_runtime_coding_conventions()
    assert "FROM_AGENTS_MD" not in conventions
    assert conventions.strip()
