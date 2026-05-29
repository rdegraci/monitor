import pytest
import tempfile
import os
import json
from unittest.mock import Mock, patch

from monitor.lib import protocol_engine

@pytest.fixture
def simple_engine(tmp_path):
    """
    Returns a ProtocolEngine instance ready for unit testing.
    """
    mock_llm = Mock()
    engine = protocol_engine.ProtocolEngine(
        model="test-model",
        system_prompt="You are a system.",
        middleware=mock_llm
    )
    engine.source_file = str(tmp_path / "testfile.py")
    return engine, mock_llm

def test_has_prohibited_summary_marker_and_finder():
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    # Test text with prohibited phrases in comments (new behavior)
    bad_text_in_comment = "def foo():\n    # This code is unchanged\n    return 1"
    # Plain text without comments should not trigger
    bad_text_plain = "This code is unchanged and the rest of the file is unchanged."
    good_text = "def foo():\n    return 1"
    
    assert engine._has_prohibited_summary_marker(bad_text_plain) is True
    assert engine._has_prohibited_summary_marker(good_text) is False
    
    # Test the new comment-based detection
    found_in_comment = engine._find_prohibited_phrases_in_text(bad_text_in_comment)
    found_plain = engine._find_prohibited_phrases_in_text(bad_text_plain)
    
    # Should find prohibited phrases in comments
    assert len(found_in_comment) > 0
    assert any("unchanged" in phrase for phrase in found_in_comment)
    
    # Should NOT find prohibited phrases in plain text (new behavior)
    assert len(found_plain) == 0

def test_modify_source_code_success(tmp_path, monkeypatch):
    file_path = tmp_path / "file.py"
    with open(file_path, "w") as f:
        f.write("foo")

    # Mock the global ENGINE's fetch_modified_script method
    def mock_fetch_modified_script(script_content, modification_request, source_file):
        # Simulate the engine writing the file
        with open(source_file, "w") as out:
            out.write("foo\nadded line\n")
        return "Done."

    protocol_engine.configure_protocol_engine()
    fake_engine = Mock()
    monkeypatch.setattr(protocol_engine, "ENGINE", fake_engine, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "fetch_modified_script", mock_fetch_modified_script, raising=False)

    out = protocol_engine.modify_source_code(str(file_path), "bar")
    assert isinstance(out, dict)
    assert out["ok"] is True
    assert out["file"] == str(file_path)
    assert out["message"].startswith("Modified ")
    assert isinstance(out["diff"], str)
    # Engine added a line; lines_changed should reflect a net delta of 1 or 2
    # depending on whether the original had a trailing newline.
    assert out["lines_changed"] in (1, 2)

def test_global_retry_logic_in_modify_source_code(tmp_path, monkeypatch):
    from unittest.mock import Mock

    # Setup: create a file to modify
    file_path = tmp_path / "retryfile.py"
    with open(file_path, "w") as f:
        f.write("foo\nbar\nbaz\n")

    # Mock the ENGINE to return an error string (simulating retry exhaustion)
    def mock_fetch_modified_script(script_content, modification_request, source_file):
        return "Modification process failed after all automatic retries. Manual intervention required."

    # Ensure ENGINE exists and then patch it
    protocol_engine.configure_protocol_engine()
    fake_engine = Mock()
    monkeypatch.setattr(protocol_engine, "ENGINE", fake_engine, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "fetch_modified_script", mock_fetch_modified_script, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "reset_state", lambda: None, raising=False)

    # When the engine returns a sentinel failure string, modify_source_code
    # must surface that as ok=False with the engine's message in `error` —
    # not silently pass it back as a "success" payload.
    result = protocol_engine.modify_source_code(str(file_path), "test modification")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "Modification process failed after all automatic retries" in result["error"]



def test_modify_source_code_rejects_oversize_file(tmp_path, monkeypatch):
    """Files larger than MAX_SOURCE_FILE_BYTES are refused before any LLM work."""
    from unittest.mock import Mock

    file_path = tmp_path / "huge.py"
    # Write just over the limit using a sparse-ish approach.
    with open(file_path, "wb") as f:
        f.write(b"x" * (protocol_engine.MAX_SOURCE_FILE_BYTES + 1))

    # Mock engine — but we expect modify_source_code to bail before calling it.
    protocol_engine.configure_protocol_engine()
    fake_engine = Mock()
    fetch = Mock()
    monkeypatch.setattr(protocol_engine, "ENGINE", fake_engine, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "fetch_modified_script", fetch, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "reset_state", lambda: None, raising=False)

    result = protocol_engine.modify_source_code(str(file_path), "anything")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "exceeds" in result["error"]
    assert "1 MiB" in result["error"]
    fetch.assert_not_called()


def test_modify_source_code_file_not_found_returns_dict(tmp_path):
    """Missing files return a structured error, not a bare string."""
    result = protocol_engine.modify_source_code(str(tmp_path / "nope.py"), "x")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "Does not exist" in result["error"]


def test_modify_source_code_does_not_inject_swift_guidance(tmp_path, monkeypatch):
    """The .swift logging block was moved into MONITOR_CONVENTIONS.md; the
    modification_request must reach the engine unchanged regardless of
    file extension."""
    from unittest.mock import Mock

    file_path = tmp_path / "Foo.swift"
    with open(file_path, "w") as f:
        f.write("import Foundation\n")

    seen_requests = []

    def mock_fetch_modified_script(script_content, modification_request, source_file):
        seen_requests.append(modification_request)
        return "ok"

    protocol_engine.configure_protocol_engine()
    fake_engine = Mock()
    monkeypatch.setattr(protocol_engine, "ENGINE", fake_engine, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "fetch_modified_script", mock_fetch_modified_script, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "reset_state", lambda: None, raising=False)

    protocol_engine.modify_source_code(str(file_path), "Add logging.")
    assert seen_requests == ["Add logging."]  # not appended with swift block
