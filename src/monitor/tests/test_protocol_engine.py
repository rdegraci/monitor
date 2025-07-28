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
    bad_text = "This code is unchanged and the rest of the file is unchanged."
    good_text = "def foo():\n    return 1"
    assert engine._has_prohibited_summary_marker(bad_text) is True
    assert engine._has_prohibited_summary_marker(good_text) is False
    found = engine._find_prohibited_phrases_in_text(bad_text)
    assert "unchanged" in next(iter(found)) or "rest of the file is unchanged" in found

def test_parse_chunks_standard():
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    response = "<chunk_1>print('foo')</chunk_1><chunk_2 last=\"true\">print('bar')</chunk_2>"
    chunks, is_last = engine._parse_chunks(response)
    assert chunks == ["print('foo')", "print('bar')"]
    assert is_last is True

def test_parse_chunks_no_tags():
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    response = "def foo():\n    return 2"
    chunks, is_last = engine._parse_chunks(response)
    assert chunks == [response]
    assert is_last is True

def test_checkpoint_save_load_and_remove(tmp_path):
    file_path = tmp_path / "testfile.py"
    checkpoint_path = str(file_path) + ".resume.json"
    # Create dummy file for hashing
    with open(file_path, "w") as f:
        f.write("xxx")
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    engine.source_file = str(file_path)
    mod_req = "Test"
    engine._save_checkpoint(["foo"], 1, mod_req)
    assert os.path.exists(checkpoint_path)
    loaded = engine._load_checkpoint(mod_req)
    assert loaded["completed_chunks"] == ["foo"]
    engine._remove_checkpoint()
    assert not os.path.exists(checkpoint_path)

def test_assemble_and_save(tmp_path):
    file_path = tmp_path / "testfile.py"
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    engine.source_file = str(file_path)
    engine.chunks = ["a = 1", "b = 2"]
    result = engine._assemble_and_save()
    with open(file_path) as f:
        content = f.read()
    assert "a = 1" in content and "b = 2" in content
    assert "Task completed successfully" in result

def test_assemble_and_save_partial(tmp_path):
    file_path = tmp_path / "testfile.py"
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    engine.source_file = str(file_path)
    engine.chunks = ["import os", "print(1)"]
    res = engine._assemble_and_save_partial()
    with open(str(file_path) + ".partial") as f:
        c = f.read()
    assert "import os" in c and "print(1)" in c
    assert "Task not completed successfully" in res

def test_send_request_and_retry_logic(monkeypatch):
    mock_llm = Mock()
    # Will first return a prohibited output, then a correct one
    bad_output = "the file is unchanged"
    good_output = "<chunk_1 last=\"true\">print(1)</chunk_1>"
    mock_llm.completion.side_effect = [
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": bad_output}})]}),
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": good_output}})]}),
    ]
    engine = protocol_engine.ProtocolEngine("model", "sys", middleware=mock_llm)
    result = engine._send_request_with_compliance_retry("query", 1, False)
    assert "print(1)" in result
    # Also triggers warning logger; further check not shown but could be with caplog

def test_fetch_modified_script(monkeypatch, tmp_path):
    # Setup: patch _send_request_with_compliance_retry to always return correct chunk
    file_path = tmp_path / "testfile.py"
    engine = protocol_engine.ProtocolEngine(
        model="test",
        system_prompt="test"
    )
    engine.source_file = str(file_path)
    script = "print('hi')"
    monkeypatch.setattr(engine, "_send_request_with_compliance_retry", lambda *a, **k: "<chunk_1 last=\"true\">print('hix')</chunk_1>")
    # Patch _save_checkpoint and _remove_checkpoint for no side-effects
    monkeypatch.setattr(engine, "_save_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_remove_checkpoint", lambda *a, **k: None)
    res = engine.fetch_modified_script(script, "replace hi with hix", str(file_path))
    assert "Task completed successfully" in res

def test_modify_source_code_file_not_found(tmp_path):
    bad_file = tmp_path / "no_such_file.py"
    result = protocol_engine.modify_source_code(str(bad_file), "change anything", model="test")
    assert result.startswith("Error reading file")

def test_modify_source_code_success(tmp_path, monkeypatch):
    file_path = tmp_path / "file.py"
    with open(file_path, "w") as f:
        f.write("foo")
    
    class DummyEngine(protocol_engine.ProtocolEngine):
        def fetch_modified_script(self, script_content, modification_request, source_file):
            return "all done!\nTask completed successfully."
    
    monkeypatch.setattr(protocol_engine, "ProtocolEngine", DummyEngine)
    out = protocol_engine.modify_source_code(str(file_path), "bar")
    assert "Task completed successfully" in out

def test_multi_chunk_modification(tmp_path, monkeypatch):
    """
    Simulate a large (multi-chunk) modification workflow.
    """
    # Dummy file content and path
    file_path = tmp_path / "bigfile.py"
    with open(file_path, "w") as f:
        f.write("line1\nline2\nline3\nline4\nline5")
    
    # Prepare ProtocolEngine and middleware mock
    model = "test"
    system_prompt = "test"
    # Simulate two correct chunked outputs (as the LLM would generate them)
    chunk1 = "<chunk_1>line1\nline2\n</chunk_1>"
    chunk2 = "<chunk_2 last=\"true\">line3\nline4\nline5\n</chunk_2>"
    # The mock will sequentially output those two responses
    from unittest.mock import Mock
    mock_llm = Mock()
    mock_llm.completion.side_effect = [
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": chunk1}})]}),
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": chunk2}})]}),
    ]
    
    engine = protocol_engine.ProtocolEngine(
        model=model,
        system_prompt=system_prompt,
        middleware=mock_llm
    )
    # Run the modification
    result = engine.fetch_modified_script(
        script_content="line1\nline2\nline3\nline4\nline5",
        modification_request="identity",  # ask for no real change, just chunking
        source_file=str(file_path)
    )
    # Read modified file and check all lines are present
    with open(file_path) as f:
        output = f.read()
    assert "line1" in output
    assert "line2" in output
    assert "line3" in output
    assert "line4" in output
    assert "line5" in output
    assert "Task completed successfully" in result

def test_checkpoint_recovery_logic(tmp_path):
    """
    Simulate checkpoint recovery for a multi-chunk modification.
    After an interruption, ProtocolEngine should resume from checkpoint.
    """
    from unittest.mock import Mock
    # Setup file to modify
    file_path = tmp_path / "recoverfile.py"
    with open(file_path, "w") as f:
        f.write("alpha\nbeta\ngamma\ndelta\n")
    # Setup model/system_prompt, and chunk sequence
    model = "test"
    system_prompt = "test"

    # First run: Only provide the first chunk, simulate interruption after it
    first_chunk = "<chunk_1>alpha\nbeta\n</chunk_1>"
    mock_llm_1 = Mock()
    mock_llm_1.completion.side_effect = [
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": first_chunk}})]}),
    ]
    engine1 = protocol_engine.ProtocolEngine(
        model=model, system_prompt=system_prompt, middleware=mock_llm_1
    )
    # Intentionally break after first chunk by mocking _collect_chunks to stop after 1 iteration
    orig_collect_chunks = engine1._collect_chunks
    def one_chunk_then_interrupt(*a, **k):
        # Only collect the first chunk, save the checkpoint, then simulate interruption
        orig_collect_chunks(*a, **k)
        raise Exception("Simulated interruption!")
    engine1._collect_chunks = one_chunk_then_interrupt

    # Start the modifying script, expect exception
    with pytest.raises(Exception, match="Simulated interruption!"):
        engine1.fetch_modified_script(
            script_content="alpha\nbeta\ngamma\ndelta\n",
            modification_request="identity",
            source_file=str(file_path)
        )

    # Now, simulate process restart and resume with the second chunk in the response
    second_chunk = "<chunk_2 last=\"true\">gamma\ndelta\n</chunk_2>"
    mock_llm_2 = Mock()
    mock_llm_2.completion.side_effect = [
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": second_chunk}})]}),
    ]
    engine2 = protocol_engine.ProtocolEngine(
        model=model, system_prompt=system_prompt, middleware=mock_llm_2
    )
    # This should detect and load the checkpoint, process only the remaining chunk
    result = engine2.fetch_modified_script(
        script_content="alpha\nbeta\ngamma\ndelta\n",
        modification_request="identity",
        source_file=str(file_path)
    )
    # Validate the checkpoint file is removed
    assert not os.path.exists(str(file_path) + ".resume.json")
    # Validate that file contains all content and is marked as completed
    with open(file_path) as f:
        content = f.read()
    assert "alpha" in content
    assert "beta" in content
    assert "gamma" in content
    assert "delta" in content
    assert "Task completed successfully" in result

def test_global_retry_logic(tmp_path, monkeypatch):
    """
    Tests that ProtocolEngine performs a global retry after all per-chunk retries fail,
    and stops after the allowed global retries are exhausted, raising ValueError.
    """
    from unittest.mock import Mock

    # Setup: create a file to modify
    file_path = tmp_path / "retryfile.py"
    with open(file_path, "w") as f:
        f.write("foo\nbar\nbaz\n")

    # All LLM chunk outputs will be non-compliant for both retries and global retries
    non_compliant_chunk = "file is unchanged"
    # Set MAX_GLOBAL_MODIFICATION_RETRIES and MAX_RETRIES_PER_CHUNK for the test
    model = "test"
    system_prompt = "test"

    class CustomEngine(protocol_engine.ProtocolEngine):
        MAX_RETRIES_PER_CHUNK = 2
        MAX_GLOBAL_MODIFICATION_RETRIES = 2

    mock_llm = Mock()
    mock_llm.completion.side_effect = [
        type("Resp", (), {"choices": [type("Msg", (), {"message": {"content": non_compliant_chunk}})]}),
    ] * 10

    engine = CustomEngine(model=model, system_prompt=system_prompt, middleware=mock_llm)

    # Silence checkpoint and partial save
    monkeypatch.setattr(engine, "_save_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_remove_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_assemble_and_save_partial", lambda *a, **k: None)

    # Now, expect a ValueError due to repeated non-compliance after all retries
    import pytest
    with pytest.raises(ValueError) as exc:
        engine.fetch_modified_script(
            script_content="foo\nbar\nbaz\n",
            modification_request="identity",
            source_file=str(file_path),
        )
    assert "Non-compliant output at chunk" in str(exc.value)
    