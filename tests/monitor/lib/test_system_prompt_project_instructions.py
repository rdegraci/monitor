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
from monitor.lib.tool_definitions import GEMINI_TOOL_DESCRIPTIONS, TOOL_DESCRIPTIONS
from monitor.lib.tool_loading import add_openai_editor_tools

from monitor import config
from monitor.lib.monitor_wiki import configure_project_wiki_paths
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
    configure_project_wiki_paths(None)
    yield
    clear_project_instructions_cache()
    configure_project_wiki_paths(None)
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


def test_build_system_prompt_includes_project_wiki_pointer(tmp_path):
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)
    configure_project_wiki_paths(tmp_path)

    project_wiki_dir = tmp_path / "appdir" / "monitor-wiki" / "tmp"
    project_wiki_dir.mkdir(parents=True)
    (project_wiki_dir / "INDEX.md").write_text(
        "# Project Wiki Index\n\nCustom content\n",
        encoding="utf-8",
    )
    config.PROJECT_WIKI_PATH = str(project_wiki_dir)

    out = build_system_prompt()

    assert "--- Project wiki ---" in out
    assert "Project wiki context is available for this session" in out
    assert "INDEX.md" in out
    assert "Index excerpt:" in out
    assert "Custom content" in out


def test_build_system_prompt_limits_project_wiki_excerpt_length(tmp_path):
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)
    configure_project_wiki_paths(tmp_path)

    project_wiki_dir = tmp_path / "appdir" / "monitor-wiki" / "long"
    project_wiki_dir.mkdir(parents=True)
    long_index = "\n".join(f"line {number}" for number in range(1, 21)) + "\n"
    (project_wiki_dir / "INDEX.md").write_text(long_index, encoding="utf-8")
    config.PROJECT_WIKI_PATH = str(project_wiki_dir)

    out = build_system_prompt()

    assert "line 1" in out
    assert "line 12" in out
    assert "line 13" not in out


def test_build_system_prompt_includes_up_to_two_additional_wiki_pages(tmp_path):
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)
    configure_project_wiki_paths(tmp_path)

    project_wiki_dir = tmp_path / "appdir" / "monitor-wiki" / "linked"
    project_wiki_dir.mkdir(parents=True)
    (project_wiki_dir / "ARCHITECTURE.md").write_text("Architecture details\n", encoding="utf-8")
    (project_wiki_dir / "CONVENTIONS.md").write_text("Convention details\n", encoding="utf-8")
    (project_wiki_dir / "TESTING.md").write_text("Testing details\n", encoding="utf-8")
    (project_wiki_dir / "INDEX.md").write_text(
        "# Project Wiki Index\n\nSee ARCHITECTURE.md and CONVENTIONS.md and TESTING.md\n",
        encoding="utf-8",
    )
    config.PROJECT_WIKI_PATH = str(project_wiki_dir)

    out = build_system_prompt()

    assert "ARCHITECTURE.md:" in out
    assert "Architecture details" in out
    assert "CONVENTIONS.md:" in out
    assert "Convention details" in out
    assert "TESTING.md:" not in out


def test_build_system_prompt_includes_wiki_location_for_starter_only_wiki(tmp_path):
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)
    configure_project_wiki_paths(tmp_path)

    # Point at a fresh tmp wiki dir so provisioning writes the placeholder
    # there (not into the real appdir) and the wiki stays non-substantive.
    project_wiki_dir = tmp_path / "appdir" / "monitor-wiki" / "starter"
    project_wiki_dir.mkdir(parents=True)
    config.PROJECT_WIKI_PATH = str(project_wiki_dir)

    out = build_system_prompt()

    # The location pointer is present even with only the starter template, so
    # the model can populate the wiki from a cold start...
    assert "--- Project wiki ---" in out
    assert "currently empty" in out
    assert str(project_wiki_dir) in out
    # ...but no substantive index/page content is injected yet.
    assert "Index excerpt:" not in out
    assert "Project wiki context is available for this session" not in out



def test_build_system_prompt_omits_project_wiki_pointer_when_provisioning_fails(tmp_path, monkeypatch):
    """Keep system prompt construction non-fatal when wiki provisioning fails.

    Args:
        tmp_path: Temporary test directory.
        monkeypatch: Pytest monkeypatch fixture.
    """
    (tmp_path / "MONITOR.md").write_text("PROJ\n")
    (tmp_path / "MONITOR_CONVENTIONS.md").write_text("CONV\n")
    configure_runtime_prompt_paths(tmp_path)
    configure_project_wiki_paths(tmp_path)

    def fail_provision():
        return None

    monkeypatch.setattr(
        "monitor.lib.system_prompt.ensure_configured_project_wiki",
        fail_provision,
    )

    out = build_system_prompt()

    assert "--- Project wiki ---" not in out

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


def test_build_system_prompt_includes_tool_routing_guidance():
    out = build_system_prompt()
    assert "inspect -> plan -> exact edit -> verify" in out
    assert "Inspect first when the target file, file layout, or exact text is not already known" in out
    assert "bulk_replace_in_files for mechanical repeated edits" in out


def test_build_system_prompt_includes_post_write_verification_guidance():
    out = build_system_prompt()
    assert "After any write, always inspect the diff before claiming success" in out
    assert "type-check Python changes" in out
    assert "If no relevant automated check is clearly applicable, say so plainly" in out


def test_modify_source_code_tool_descriptions_include_updated_guidance():
    description = next(
        tool["function"]["description"]
        for tool in TOOL_DESCRIPTIONS
        if tool["function"]["name"] == "modify_source_code"
    )
    gemini_description = next(
        tool["description"]
        for tool in GEMINI_TOOL_DESCRIPTIONS
        if tool["name"] == "modify_source_code"
    )

    for text in (
        "Inspect first when the exact target text or file context is not already known",
        "bulk_replace_in_files for mechanical repeated edits",
        "After any write, inspect the diff before claiming success",
    ):
        assert text in description
        assert text in gemini_description


def test_add_openai_editor_tools_uses_updated_modify_source_code_guidance():
    tool_descriptions = []
    gemini_tool_descriptions = []
    tool_state = {}

    add_openai_editor_tools(tool_descriptions, gemini_tool_descriptions, tool_state)

    description = next(
        tool["function"]["description"]
        for tool in tool_descriptions
        if tool["function"]["name"] == "modify_source_code"
    )

    assert (
        "Inspect first when the exact target text or file context is not already known"
        in description
    )
    assert "bulk_replace_in_files for mechanical repeated edits" in description
    assert "After any write, inspect the diff before claiming success" in description
