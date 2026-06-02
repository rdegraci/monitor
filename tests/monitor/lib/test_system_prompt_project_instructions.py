"""Tests for the project-instructions integration into build_system_prompt.

Verifies:
- Project instructions get concatenated into the system prompt output.
- The content is cached in config.PROJECT_INSTRUCTIONS_CONTENT after first read.
- clear_project_instructions_cache forces a fresh read on the next call.
- configure_runtime_prompt_paths clears the cache (so a new project's
  files are picked up when the harness starts in a new directory).
- build_user_prompt_prefix now returns "" so user messages don't carry
  the MONITOR.md prefix anymore.
"""

import pytest

# Pre-import config to break the known import cycle for tests touching history.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib.system_prompt import (
    build_system_prompt,
    build_user_prompt_prefix,
    clear_project_instructions_cache,
    configure_runtime_prompt_paths,
    SYSTEM_PROMPT_TEMPLATE,
)


@pytest.fixture(autouse=True)
def _reset_project_instructions_cache():
    """Each test starts with a clean cache slate."""
    clear_project_instructions_cache()
    yield
    clear_project_instructions_cache()
    # Also clear any override paths set by tests.
    configure_runtime_prompt_paths(None)


def test_build_system_prompt_includes_project_instructions(tmp_path, monkeypatch):
    (tmp_path / "MONITOR.md").write_text("PROJECT_TOKEN_ALPHA\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("PROJECT_TOKEN_BETA\n")
    configure_runtime_prompt_paths(tmp_path)

    out = build_system_prompt()

    # Platform invariants kept verbatim.
    assert SYSTEM_PROMPT_TEMPLATE in out
    # Project instructions concatenated.
    assert "PROJECT_TOKEN_ALPHA" in out
    assert "PROJECT_TOKEN_BETA" in out
    # Visible separator so the model can tell platform from project.
    assert "--- Project instructions ---" in out


def test_build_system_prompt_caches_content(tmp_path, monkeypatch):
    """First call reads the files; second call must use the cached content
    without re-reading. We verify the cache by setting paths, doing one
    read, then mutating the underlying files — the cached content should
    NOT reflect the mutation."""
    (tmp_path / "MONITOR.md").write_text("ORIGINAL_CONTENT\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("ORIGINAL_CONV\n")
    configure_runtime_prompt_paths(tmp_path)

    first = build_system_prompt()
    assert "ORIGINAL_CONTENT" in first

    # Mutate the file after first read.
    (tmp_path / "MONITOR.md").write_text("MUTATED_CONTENT\n")
    second = build_system_prompt()

    # Cache should serve the original content, not the new file content.
    assert "ORIGINAL_CONTENT" in second
    assert "MUTATED_CONTENT" not in second


def test_clear_project_instructions_cache_forces_reread(tmp_path):
    """After clearing the cache, the next build_system_prompt picks up
    fresh file contents."""
    (tmp_path / "MONITOR.md").write_text("V1\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("V1_CONV\n")
    configure_runtime_prompt_paths(tmp_path)

    first = build_system_prompt()
    assert "V1" in first

    (tmp_path / "MONITOR.md").write_text("V2\n")
    clear_project_instructions_cache()
    second = build_system_prompt()
    assert "V2" in second
    assert "V1\n" not in second  # the V1 content is gone from the prompt


def test_configure_runtime_prompt_paths_clears_cache(tmp_path):
    """Switching projects mid-test (uncommon, but configure_* is callable
    from tests) must drop the cached content so the new project's
    instructions are loaded."""
    proj_a = tmp_path / "project_a"
    proj_a.mkdir()
    (proj_a / "MONITOR.md").write_text("FROM_PROJECT_A\n")

    proj_b = tmp_path / "project_b"
    proj_b.mkdir()
    (proj_b / "MONITOR.md").write_text("FROM_PROJECT_B\n")

    configure_runtime_prompt_paths(proj_a)
    assert "FROM_PROJECT_A" in build_system_prompt()

    configure_runtime_prompt_paths(proj_b)
    out = build_system_prompt()
    assert "FROM_PROJECT_B" in out
    assert "FROM_PROJECT_A" not in out


def test_session_id_appended_after_project_instructions(tmp_path):
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)

    out = build_system_prompt(session_id="abc-123")

    assert "PROJ" in out
    assert "Session ID: abc-123" in out
    # Session ID should appear AFTER the project instructions.
    assert out.index("PROJ") < out.index("Session ID:")


def test_build_user_prompt_prefix_returns_empty():
    """The project instructions used to live here. They've been moved into
    the system prompt to avoid per-user-message prefix duplication. The
    function is kept callable for backward compat but must now return
    nothing."""
    assert build_user_prompt_prefix() == ""


def test_build_prefixed_model_text_no_longer_prefixes_user_input():
    """End-to-end: with build_user_prompt_prefix returning "", the
    build_prefixed_model_text helper must pass user text through unchanged.
    This is what eliminates the per-user-message cost of MONITOR.md."""
    from monitor.core.conversation import build_prefixed_model_text
    user_input = "fix the bug in foo.py"
    assert build_prefixed_model_text(user_input) == user_input
