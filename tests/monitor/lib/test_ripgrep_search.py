import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import ripgrep_search
import re


def make_result(stdout="", stderr="", returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock


def get_subprocess_run_args(mock_run, call_index=-1):
    """
    Helper to extract the first argument passed to subprocess.run from a mock.
    Supports both positional and keyword usage, and selecting a specific call index.
    If call_index is -1, use mock_run.call_args (the most recent call).
    Otherwise use mock_run.call_args_list[call_index].
    Returns the value of the first positional argument if present, otherwise the 'args' kwarg if present, else None.
    """
    if call_index == -1:
        call = mock_run.call_args
        if call is None:
            return None
        args, kwargs = call
    else:
        call = mock_run.call_args_list[call_index]
        args, kwargs = call
    if args and len(args) > 0:
        return args[0]
    if kwargs and "args" in kwargs:
        return kwargs["args"]
    return None


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_basic_pattern(mock_run):
    mock_run.return_value = make_result("foo.py:42: hello world", "", 0)
    result = ripgrep_search.ripgrep_search("hello")
    assert "hello world" in result
    mock_run.assert_called()


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_with_filetype(mock_run):
    mock_run.return_value = make_result("foo.py:42: hello world", "", 0)
    result = ripgrep_search.ripgrep_search("hello", filetype="py")
    assert "hello world" in result
    args_used = get_subprocess_run_args(mock_run)
    assert "-t" in args_used and "py" in args_used


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_no_matches(mock_run):
    mock_run.return_value = make_result("", "", 1)
    result = ripgrep_search.ripgrep_search("somethingnotfound")
    assert result == "No matches found. Searched for: somethingnotfound"


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_unknown_filetype_error(mock_run):
    mock_run.return_value = make_result("", "unknown file type: foo", 1)
    result = ripgrep_search.ripgrep_search("test", filetype="foo")
    assert "Error: Unknown file type" in result


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_rg_error_returncode_2(mock_run):
    mock_run.return_value = make_result("", "some ripgrep error", 2)
    result = ripgrep_search.ripgrep_search("foo bar")
    assert str(result).startswith("Error running ripgrep:")
    assert "some ripgrep error" in str(result)


# Testing grep_command usage/dispatch, which internally calls ripgrep_search
@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_simple(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:42: hello world"
    result = ripgrep_search.grep_command("hello")
    assert "hello world" in result
    mock_ripgrep_search.assert_called_once_with(
        "hello",
        filetype=None,
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_filetype_end_token(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:42: hello world"
    ripgrep_search.grep_command("hello py")
    mock_ripgrep_search.assert_called_once_with(
        "hello",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_multiword_quoted(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:1: Multi word search!"
    result = ripgrep_search.grep_command('"Multi word search!" py')
    assert "Multi word search!" in result
    mock_ripgrep_search.assert_called_once_with(
        "Multi word search!",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_invalid_args_prints_usage(mock_ripgrep_search, capsys):
    result = ripgrep_search.grep_command("")
    captured = capsys.readouterr().out
    assert "Usage:\n  :rg" in captured
    assert result is None


@pytest.mark.parametrize("flag", ["-w", "--word-regexp"])
@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_word_flag_sets_word_true(mock_ripgrep_search, flag):
    mock_ripgrep_search.return_value = "foo.py:42: hello world"
    result = ripgrep_search.grep_command(f"hello {flag} py")
    assert "hello world" in result
    mock_ripgrep_search.assert_called_once_with(
        "hello",
        filetype="py",
        directory=".",
        word=True,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_word_true_includes_flag_w(mock_run):
    mock_run.return_value = make_result("foo.py:1: hello world", "", 0)
    ripgrep_search.ripgrep_search("hello", word=True)
    args_used = get_subprocess_run_args(mock_run)
    assert "-w" in args_used


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_quoted_flag_like_is_literal(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:1: -w literal"
    result = ripgrep_search.grep_command('"-w" py')
    assert "-w" in result
    mock_ripgrep_search.assert_called_once_with(
        "-w",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_end_of_options_treats_tokens_literally(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:1: hello -w py"
    result = ripgrep_search.grep_command("hello -- -w py")
    assert "hello -w py" in result
    mock_ripgrep_search.assert_called_once_with(
        "hello -w py",
        filetype=None,
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_exclude_ext_parsing_sets_exclude_extensions(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:42: hello world"
    ripgrep_search.grep_command("--exclude-ext pyc,log foo py")
    mock_ripgrep_search.assert_called_once_with(
        "foo",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=["pyc", "log"],
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_repeated_exclude_ext_merges_lists(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:42: hello world"
    ripgrep_search.grep_command("--exclude-ext pyc foo --exclude-ext log py")
    mock_ripgrep_search.assert_called_once_with(
        "foo",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=["pyc", "log"],
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_exclude_glob_parsing_collects_multiple_globs(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.js:1: foo"
    ripgrep_search.grep_command(
        '--exclude-glob node_modules/** --exclude-glob "*.min.js" foo js'
    )
    mock_ripgrep_search.assert_called_once_with(
        "foo",
        filetype="js",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=["node_modules/**", "*.min.js"],
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_quoted_exclude_ext_is_literal_pattern(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "foo.py:1: --exclude-ext pyc"
    result = ripgrep_search.grep_command('"--exclude-ext pyc" py')
    assert "--exclude-ext pyc" in result
    mock_ripgrep_search.assert_called_once_with(
        "--exclude-ext pyc",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_grep_command_no_default_excludes_flag_sets_use_default_excludes_false(
    mock_ripgrep_search,
):
    mock_ripgrep_search.return_value = "foo.py:1: foo"
    result = ripgrep_search.grep_command("--no-default-excludes foo py")
    assert "foo" in result
    mock_ripgrep_search.assert_called_once_with(
        "foo",
        filetype="py",
        directory=".",
        word=False,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=False,
        regex=False,
    )


# Test to ensure ripgrep_search_tool passes through args to ripgrep_search and returns the result
@patch("monitor.lib.ripgrep_search.ripgrep_search")
def test_ripgrep_search_tool_passes_through(mock_ripgrep_search):
    mock_ripgrep_search.return_value = "ok"
    result = ripgrep_search.ripgrep_search_tool("foo", filetype="py", word=True)
    assert result == "ok"
    mock_ripgrep_search.assert_called_once_with(
        "foo",
        filetype="py",
        directory=".",
        word=True,
        exclude_extensions=None,
        exclude_globs=None,
        use_default_excludes=True,
        regex=False,
    )


# Tests for SAFE_LIMIT truncation behavior
@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_truncates_to_default_safe_limit_when_no_base_limit(
    mock_run, monkeypatch
):
    monkeypatch.setattr(ripgrep_search.config, "base_limit", None, raising=False)
    monkeypatch.setattr(
        ripgrep_search.config, "MODEL_CONTEXT_WINDOW", None, raising=False
    )
    monkeypatch.setattr(ripgrep_search.config, "MAX_TOKEN_COUNT", 0, raising=False)
    monkeypatch.setattr(ripgrep_search, "SEARCH_EVALUATION_DIVISOR", 15, raising=False)
    large_output = "A" * 10000
    mock_run.return_value = make_result(large_output, "", 0)
    result = ripgrep_search.ripgrep_search("A")
    assert isinstance(result, str)
    # Detect optional truncation suffix and compute preserved payload accordingly
    m = re.search(r"\[TRUNCATED (\d+) bytes of output\]", result)
    if m:
        truncated_reported = int(m.group(1))
        preserved_payload = result[: m.start()].rstrip("\n")
    else:
        preserved_payload = result
    assert len(preserved_payload) >= 4096
    assert large_output.startswith(preserved_payload)
    if m:
        truncated_expected = len(large_output) - len(preserved_payload)
        assert truncated_reported == truncated_expected


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_truncates_to_base_limit_divisor(mock_run, monkeypatch):
    monkeypatch.setattr(
        ripgrep_search.config, "MODEL_CONTEXT_WINDOW", 10000, raising=False
    )
    monkeypatch.setattr(ripgrep_search.config, "MAX_TOKEN_COUNT", 0, raising=False)
    monkeypatch.setattr(ripgrep_search, "SEARCH_EVALUATION_DIVISOR", 5, raising=False)
    large_output = "B" * 12000
    mock_run.return_value = make_result(large_output, "", 0)
    result = ripgrep_search.ripgrep_search("B")
    assert isinstance(result, str)
    # With SEARCH_EVALUATION_DIVISOR=5 and MODEL_CONTEXT_WINDOW=10000, expected preserved length is (10000//5)*4 = 8000
    m = re.search(r"\[TRUNCATED (\d+) bytes of output\]", result)
    assert m is not None
    truncated_reported = int(m.group(1))
    preserved_payload = result[: m.start()].rstrip("\n")
    expected_limit = 8000
    assert len(preserved_payload) == expected_limit
    assert large_output.startswith(preserved_payload)
    truncated_expected = len(large_output) - len(preserved_payload)
    assert truncated_reported == truncated_expected


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_falls_back_to_grep(mock_run):
    mock_run.side_effect = [FileNotFoundError(), make_result("grep matched", "", 0)]
    result = ripgrep_search.ripgrep_search("foo")
    assert "grep matched" in result
    assert mock_run.call_count == 2
    second_args = get_subprocess_run_args(mock_run, 1)
    assert second_args[0] == "grep" or "grep" in second_args


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_both_missing_reports_install(mock_run):
    mock_run.side_effect = [FileNotFoundError(), FileNotFoundError()]
    result = ripgrep_search.ripgrep_search("foo")
    res_lower = str(result).lower()
    assert "install ripgrep" in res_lower
    assert "preferred" in res_lower
    assert "grep" in res_lower


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_exclude_flags_in_subprocess_args(mock_run):
    mock_run.return_value = make_result("foo.js:1: foo", "", 0)
    ripgrep_search.ripgrep_search(
        "foo",
        filetype="js",
        exclude_extensions=["pyc"],
        exclude_globs=["node_modules/**"],
    )
    args_used = get_subprocess_run_args(mock_run)
    assert "-g" in args_used
    assert "!*.pyc" in args_used
    assert "!node_modules/**" in args_used
    assert "--" in args_used


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_includes_default_excludes_in_subprocess_args_when_enabled(
    mock_run, monkeypatch
):
    monkeypatch.setattr(
        ripgrep_search,
        "DEFAULT_EXCLUDE_EXTENSIONS",
        ["png"],
        raising=False,
    )
    monkeypatch.setattr(
        ripgrep_search,
        "DEFAULT_EXCLUDE_GLOBS",
        ["node_modules/**"],
        raising=False,
    )
    mock_run.return_value = make_result("foo.py:1: foo", "", 0)
    ripgrep_search.ripgrep_search("foo", filetype="py", use_default_excludes=True)
    args_used = get_subprocess_run_args(mock_run)
    assert "-g" in args_used
    assert "!*.png" in args_used
    assert "!node_modules/**" in args_used
    assert "--" in args_used


@patch("monitor.lib.ripgrep_search.subprocess.run")
def test_ripgrep_search_does_not_include_default_excludes_in_subprocess_args_when_disabled(
    mock_run, monkeypatch
):
    monkeypatch.setattr(
        ripgrep_search,
        "DEFAULT_EXCLUDE_EXTENSIONS",
        ["png"],
        raising=False,
    )
    monkeypatch.setattr(
        ripgrep_search,
        "DEFAULT_EXCLUDE_GLOBS",
        ["node_modules/**"],
        raising=False,
    )
    mock_run.return_value = make_result("foo.py:1: foo", "", 0)
    ripgrep_search.ripgrep_search("foo", filetype="py", use_default_excludes=False)
    args_used = get_subprocess_run_args(mock_run)
    assert "!*.png" not in args_used
    assert "!node_modules/**" not in args_used
    assert "--" in args_used
