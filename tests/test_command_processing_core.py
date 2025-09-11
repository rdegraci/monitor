import pytest
from unittest.mock import patch, MagicMock

import monitor.core.command_processing as cp

@pytest.fixture(autouse=True)
def patch_logger():
    with patch.object(cp, "logger"):
        yield

@pytest.fixture
def patch_config_macros():
    with patch.object(cp, "config") as mock_config:
        mock_config.MACRO_DELIMITER_OPEN = "<"
        mock_config.MACRO_DELIMITER_CLOSE = ">"
        mock_config.MACRO_DELIMITER_ESCAPE = "!"
        mock_config.SERVER_MODE = False
        yield mock_config

def test_evaluate_command_empty(patch_config_macros):
    result = cp.evaluate_command("")
    assert result.command_type.name == "EMPTY"
    assert result.output is None
    assert not result.exit_requested

@patch.object(cp, "recursive_macro_expand", side_effect=lambda c, *args, **kwargs: c)
@patch.object(cp, "config")
def test_evaluate_command_exit(mock_config, mock_expand, patch_config_macros):
    # patch_config_macros will set the required config with macros before function call
    for cmd in ["exit", "/exit"]:
        result = cp.evaluate_command(cmd)
        assert result.exit_requested
        assert result.command_type.name == "EXIT"

def test_evaluate_command_macro_expansion(patch_config_macros):
    # Macro expansion should be called during process_command
    with patch.object(cp, "recursive_macro_expand", return_value="expanded") as mexpand:
        with patch("monitor.core.command_processing.readline.write_history_file"):
            cp.process_command("hello macro", "/tmp/history.txt")
        mexpand.assert_called()

def test_evaluate_command_cd(patch_config_macros):
    result = cp.evaluate_command("cd somewhere")
    assert result.output == "somewhere"
    assert result.command_type.name == "CD"

@patch.object(cp, "recursive_macro_expand", side_effect=lambda c, *args, **kwargs: c)
@patch.object(cp, "is_interactive_command", return_value=True)
@patch.object(cp, "is_internal_command", return_value=False)
@patch.object(cp, "is_built_in_function", return_value=False)
def test_evaluate_command_unsupported_interactive(mock_expand, mock_is_interactive, mock_is_internal, mock_is_builtin, patch_config_macros):
    cp.config.SERVER_MODE = True
    result = cp.evaluate_command("something interactive")
    assert result.command_type.name == "UNSUPPORTED"
    assert result.error

@patch.object(cp, "recursive_macro_expand", side_effect=lambda c, *args, **kwargs: c)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=True)
@patch.object(cp, "is_built_in_function", return_value=False)
def test_evaluate_command_unsupported_internal(mock_expand, mock_is_interactive, mock_is_internal, mock_is_builtin, patch_config_macros):
    cp.config.SERVER_MODE = True
    result = cp.evaluate_command("unsupported whatever")
    assert result.command_type.name == "UNSUPPORTED"
    assert result.error

@patch.object(cp, "recursive_macro_expand", side_effect=lambda c, *args, **kwargs: c)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=False)
@patch.object(cp, "is_built_in_function", return_value=True)
def test_evaluate_command_unsupported_builtin(mock_expand, mock_is_interactive, mock_is_internal, mock_is_builtin, patch_config_macros):
    cp.config.SERVER_MODE = True
    result = cp.evaluate_command("some builtin")
    assert result.command_type.name == "UNSUPPORTED"
    assert result.error

@patch.object(cp, "recursive_macro_expand", side_effect=lambda c, *args, **kwargs: c)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=False)
@patch.object(cp, "is_built_in_function", return_value=False)
@patch.object(cp, "query", return_value="llm response")
def test_evaluate_command_default_llm(mock_expand, mock_is_interactive, mock_is_internal, mock_is_builtin, mock_query):
    cp.config.MACRO_DELIMITER_OPEN = "<"
    cp.config.MACRO_DELIMITER_CLOSE = ">"
    cp.config.MACRO_DELIMITER_ESCAPE = "!"
    result = cp.evaluate_command("llm stuff")
    assert result.command_type.name == "LLM"
    assert result.output is None

def test_evaluate_command_exception(patch_config_macros):
    with patch.object(cp, "is_interactive_command", side_effect=Exception("fail!")):
        result = cp.evaluate_command("test crash")
        assert result.command_type.name == "ERROR"
        assert "fail!" in result.error


@patch.object(cp, "handle_cd_command", return_value="/mock/dir")
@patch.object(cp, "query")
def test_process_cd_command(mock_query, mock_cd, patch_config_macros):
    res = cp.process_cd_command("cd somewhere", "cd")
    mock_cd.assert_called_once()
    mock_query.assert_called_once()
    assert res is True

def test_process_cd_command_non_cd():
    res = cp.process_cd_command("ls", "ls")
    assert res is False

@patch("monitor.core.command_processing.readline.write_history_file")
def test_process_command_empty(mock_write, patch_config_macros):
    # Should not raise, should return False
    assert not cp.process_command("   ", "/tmp/history.txt")
    mock_write.assert_not_called()


@patch.object(cp, "handle_exit_command", return_value=True)
def test_process_command_exit(mock_exit, patch_config_macros):
    with patch("monitor.core.command_processing.readline.write_history_file"):
        # Exit command, should return True
        assert cp.process_command("exit", "dummy_history")
        mock_exit.assert_called_once()

@patch.object(cp, "handle_exit_command", return_value=False)
@patch.object(cp, "handle_cd_command", return_value="/mock/dir")
@patch.object(cp, "query")
def test_process_command_cd(mock_query, mock_handle_cd, mock_exit, patch_config_macros):
    with patch("monitor.core.command_processing.readline.write_history_file"):
        assert not cp.process_command("cd somewhere", "dummy_history")
        mock_handle_cd.assert_called_once()
        mock_query.assert_called_once()

@patch.object(cp, "handle_exit_command", return_value=False)
@patch.object(cp, "process_cd_command", return_value=False)
@patch.object(cp, "is_interactive_command", return_value=True)
@patch.object(cp, "execute_interactive_command")
def test_process_command_interactive(mock_exec, mock_inter, mock_cd, mock_exit, patch_config_macros):
    with patch("monitor.core.command_processing.readline.write_history_file"):
        assert not cp.process_command("inter stuff", "dummy_history")
        mock_exec.assert_called_once()


# Internal command path
@patch.object(cp, "handle_exit_command", return_value=False)
@patch.object(cp, "process_cd_command", return_value=False)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=True)
@patch.object(cp, "execute_internal_command")
def test_process_command_internal(mock_exec, mock_is_internal, mock_inter, mock_cd, mock_exit, patch_config_macros):
    with patch("monitor.core.command_processing.readline.write_history_file"):
        assert not cp.process_command("internal stuff", "dummy_history")
        mock_exec.assert_called_once()


# Built-in function path
@patch.object(cp, "handle_exit_command", return_value=False)
@patch.object(cp, "process_cd_command", return_value=False)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=False)
@patch.object(cp, "is_built_in_function", return_value=True)
@patch.object(cp, "execute_built_in_function")
def test_process_command_built_in(mock_exec, mock_builtin, mock_is_internal, mock_inter, mock_cd, mock_exit, patch_config_macros):
    with patch("monitor.core.command_processing.readline.write_history_file"):
        assert not cp.process_command("built in", "dummy_history")
        mock_exec.assert_called_once()


# LLM, command_type LLM path
@patch.object(cp, "handle_exit_command", return_value=False)
@patch.object(cp, "process_cd_command", return_value=False)
@patch.object(cp, "is_interactive_command", return_value=False)
@patch.object(cp, "is_internal_command", return_value=False)
@patch.object(cp, "is_built_in_function", return_value=False)
@patch.object(cp, "evaluate_command")
@patch.object(cp, "send_artifact")
@patch.object(cp, "display_query_result")
@patch.object(cp, "prepare_query_context")
@patch.object(cp, "query", return_value="resp")
def test_process_command_llm(mock_query, mock_ctx, mock_disp, mock_art, mock_eval, mock_builtin, mock_is_internal, mock_inter, mock_cd, mock_exit, patch_config_macros):
    mock_eval.return_value = cp.CommandResult(output="llm", command_type=cp.CommandType.LLM)
    with patch("monitor.core.command_processing.readline.write_history_file"):
        assert not cp.process_command("some query", "dummy_history")
        mock_art.assert_called()
        mock_disp.assert_called()
        mock_ctx.assert_called()

@patch("monitor.core.command_processing.signal.signal")
def test_handle_exit_command_cmd(mock_signal):
    with patch("monitor.core.command_processing.yellow", "yy"), patch("monitor.core.command_processing.reset", "rr"):
        with patch("builtins.print") as mprint:
            assert cp.handle_exit_command("/exit")
            mprint.assert_called()
    with patch("monitor.core.command_processing.logger") as mlogger:
        assert cp.handle_exit_command("exit")
        mlogger.info.assert_called()

def test_handle_exit_command_nonexit():
    # Not an exit command
    assert not cp.handle_exit_command("nope")

@patch.object(cp, "evaluate_command", return_value=cp.CommandResult(output="ok", command_type=cp.CommandType.LLM))
@patch.object(cp, "execute_command", return_value=cp.CommandResult(output="ok", command_type=cp.CommandType.LLM))
def test_internalize_command(mock_exec, mock_eval, patch_config_macros):
    out = cp.internalize_command("echo something")
    assert out == {"output": "ok", "error": None, "command_type": "llm", "exit_requested": False}
    mock_eval.assert_called_once_with("echo something")
    mock_exec.assert_called_once()
