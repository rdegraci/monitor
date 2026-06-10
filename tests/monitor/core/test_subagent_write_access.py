import monitor.config as config
from monitor.core import tooling


EXPECTED_WRITE_GUARDED_TOOLS = {
    "bulk_replace_in_files",
    "create_file",
    "modify_source_code",
    "str_replace_based_edit_tool",
    "str_replace_editor",
    "text_file_create",
    "text_file_insert_text_at_line",
    "text_file_str_replace_in_file",
}


def test_write_guarded_tools_match_expected_set():
    assert tooling.WRITE_GUARDED_TOOLS == EXPECTED_WRITE_GUARDED_TOOLS
    assert set(tooling.WRITE_TARGET_EXTRACTORS) == EXPECTED_WRITE_GUARDED_TOOLS


def test_subagent_delegated_reports_invalid_paths_entries_as_policy_error(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": ["src/foo.py", 123]}',
    )

    assert result is None
    assert error == (
        "Delegated sub-agent write for tool 'bulk_replace_in_files' has invalid "
        "targets: paths entries must all be strings"
    )


def test_subagent_delegated_reports_empty_paths_entries_as_policy_error(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": ["src/foo.py", "   "]}',
    )

    assert result is None
    assert error == (
        "Delegated sub-agent write for tool 'bulk_replace_in_files' has invalid "
        "targets: paths entries must not be empty"
    )


def test_subagent_none_blocks_write_tool_call(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "none", raising=False)

    tool_call = {
        "id": "call_1",
        "function": {
            "name": "create_file",
            "arguments": "{\"path\": \"tmp.txt\", \"contents\": \"hello\"}",
        },
    }

    result, error = tooling.execute_tool_call(tool_call)

    assert result is None
    assert "SUBAGENT_WRITE_ACCESS=none" in error
    assert "create_file" in error


def test_subagent_none_blocks_write_function_call(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "none", raising=False)

    result, error = tooling.execute_function(
        "modify_source_code",
        '{"source_file": "a.py", "modification_request": "change it"}',
    )

    assert result is None
    assert "SUBAGENT_WRITE_ACCESS=none" in error
    assert "modify_source_code" in error


def test_subagent_none_allows_read_tool_call(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "none", raising=False)

    tool_call = {
        "id": "call_1",
        "function": {
            "name": "list_directory_contents",
            "arguments": "{\"path\": \".\"}",
        },
    }

    result, error = tooling.execute_tool_call(tool_call)

    assert error is None
    assert result is not None


def test_subagent_full_allows_write_function_call(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "full", raising=False)

    calls = []

    def fake_create_file(path, contents, overwrite=False):
        calls.append((path, contents, overwrite))
        return "ok"

    monkeypatch.setitem(tooling.AVAILABLE_TOOLS, "create_file", fake_create_file)

    result, error = tooling.execute_function(
        "create_file",
        '{"path": "tmp.txt", "contents": "hello"}',
    )

    assert error is None
    assert result == "ok"
    assert calls == [("tmp.txt", "hello", False)]


def test_subagent_unknown_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "mystery", raising=False)

    result, error = tooling.execute_function(
        "modify_source_code",
        '{"source_file": "a.py", "modification_request": "change it"}',
    )

    assert result is None
    assert "not recognized" in error
    assert "mystery" in error


def test_subagent_delegated_blocks_without_grant(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.delenv("MONITOR_SUBAGENT_WRITE_GRANTED", raising=False)
    monkeypatch.delenv("MONITOR_SUBAGENT_WRITE_SCOPE", raising=False)

    result, error = tooling.execute_function(
        "modify_source_code",
        '{"source_file": "a.py", "modification_request": "change it"}',
    )

    assert result is None
    assert "requires explicit delegation" in error


def test_subagent_delegated_allows_granted_write_in_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "allowed.py")

    calls = []

    def fake_modify_source_code(source_file, modification_request):
        calls.append((source_file, modification_request))
        return "ok"

    monkeypatch.setitem(tooling.AVAILABLE_TOOLS, "modify_source_code", fake_modify_source_code)

    result, error = tooling.execute_function(
        "modify_source_code",
        '{"source_file": "allowed.py", "modification_request": "change it"}',
    )

    assert error is None
    assert result == "ok"
    assert calls == [("allowed.py", "change it")]


def test_subagent_delegated_blocks_granted_write_out_of_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "allowed.py")

    result, error = tooling.execute_function(
        "modify_source_code",
        '{"source_file": "other.py", "modification_request": "change it"}',
    )

    assert result is None
    assert "outside the granted scope" in error


def test_subagent_delegated_allows_multi_path_write_in_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src\ntests")

    calls = []

    def fake_bulk_replace_in_files(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setitem(tooling.AVAILABLE_TOOLS, "bulk_replace_in_files", fake_bulk_replace_in_files)

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": ["src/foo.py", "tests/test_foo.py"]}',
    )

    assert error is None
    assert result == "ok"
    assert calls == [{"old": "a", "new": "b", "paths": ["src/foo.py", "tests/test_foo.py"]}]


def test_subagent_delegated_blocks_multi_path_write_when_any_target_is_out_of_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": ["src/foo.py", "tests/test_foo.py"]}',
    )

    assert result is None
    assert "outside the granted scope" in error
    assert "tests/test_foo.py" in error


def test_subagent_delegated_blocks_bulk_replace_glob_even_when_root_is_in_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": "src/**/*.py"}',
    )

    assert result is None
    assert "must use explicit file paths" in error
    assert "src/**/*.py" in error


def test_subagent_delegated_blocks_bulk_replace_glob_out_of_scope(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": "tests/**/*.py"}',
    )

    assert result is None
    assert "must use explicit file paths" in error
    assert "tests/**/*.py" in error


def test_subagent_delegated_blocks_complex_glob_with_parent_traversal(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": "src/**/../tests/*.py"}',
    )

    assert result is None
    assert "must use explicit file paths" in error


def test_subagent_delegated_blocks_complex_glob_with_non_terminal_concrete_suffix(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": "src/*/fixed/file.py"}',
    )

    assert result is None
    assert "must use explicit file paths" in error


def test_subagent_delegated_blocks_ambiguous_glob_write(monkeypatch):
    monkeypatch.setattr(config, "AGENT", True, raising=False)
    monkeypatch.setattr(config, "SUBAGENT_WRITE_ACCESS", "delegated", raising=False)
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_GRANTED", "1")
    monkeypatch.setenv("MONITOR_SUBAGENT_WRITE_SCOPE", "src")

    result, error = tooling.execute_function(
        "bulk_replace_in_files",
        '{"old": "a", "new": "b", "paths": "**/*.py"}',
    )

    assert result is None
    assert "must use explicit file paths" in error
