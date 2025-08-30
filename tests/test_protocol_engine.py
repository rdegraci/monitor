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
        return "all done!\nTask completed successfully."

    # Ensure the module-level ENGINE is initialized before we monkeypatch it.
    protocol_engine.configure_protocol_engine()
    # Replace the ENGINE singleton with a fake for this test
    fake_engine = mock = Mock()
    monkeypatch.setattr(protocol_engine, "ENGINE", fake_engine, raising=False)
    monkeypatch.setattr(protocol_engine.ENGINE, "fetch_modified_script", mock_fetch_modified_script, raising=False)

    out = protocol_engine.modify_source_code(str(file_path), "bar")
    assert isinstance(out, str)

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

    # The current modify_source_code implementation should NOT raise an exception
    # when fetch_modified_script returns a string (even an error string)
    result = protocol_engine.modify_source_code(str(file_path), "test modification")
    assert isinstance(result, str)
    assert "Modification process failed after all automatic retries" in result

