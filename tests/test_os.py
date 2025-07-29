
"""
tests/test_os.py
Unit tests for lib/os.py utilities (cat_file etc).
"""
import os
import tempfile
import pytest
import json
from monitor.lib import os as libos

def test_cat_file_reads_existing_file():
    """cat_file should return the file content as string for a valid file."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=True) as tf:
        tf.write("hello\nworld")
        tf.flush()
        result = libos.cat_file(tf.name)
        result = json.loads(result)
        assert result["content"] == "hello\nworld"


def test_cat_file_returns_error_for_missing():
    """cat_file should return a dict with 'error' for missing file."""
    missing_file = "/tmp/definitely_missing_test_file_abcdefg_do_not_create.txt"
    # Sanity check: file doesn't exist
    if os.path.exists(missing_file):
        os.unlink(missing_file)
    res = libos.cat_file(missing_file)
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""


def test_cat_file_returns_error_for_directory():
    """cat_file should return a dict with 'error' when given a directory path."""
    with tempfile.TemporaryDirectory() as d:
        res = libos.cat_file(d)
        res = json.loads(res)
        assert isinstance(res, dict)
        assert "error" in res
        assert isinstance(res["error"], str)
        assert res["error"].strip() != ""


def test_cat_file_non_utf8():
    """cat_file should not crash for non-UTF8 files, should return a dict with 'error'."""
    with tempfile.NamedTemporaryFile(delete=True) as tf:
        # Write some bytes not valid as UTF-8
        tf.write(b"\xff\xfe\xfd\xfc\xfb")
        tf.flush()
        res = libos.cat_file(tf.name)
        res = json.loads(res)
        assert isinstance(res, dict)
        assert "error" in res
        assert isinstance(res["error"], str)
        assert res["error"].strip() != ""


def test_list_directory_contents_invalid_path():
    """list_directory_contents should return a dict with 'error' for an invalid directory path."""
    bad_path = "/unlikely/to/exist/_NON_EXISTENT_"
    res = libos.list_directory_contents(bad_path)
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""

def test_run_diff_nonexistent():
    """
    run_diff should return an error dict for missing files.
    If an 'error' is present in the result, the test passes.
    Otherwise, check other keys.
    """
    res = libos.run_diff("/no/such/file1", "/no/such/file2")
    res = json.loads(res)
    assert isinstance(res, dict)
    # If error present, consider this a passing case
    if "error" in res:
        return
    # Only assert other keys if NO error
    assert not res.get("success", True)
    assert "stderr" in res
    assert isinstance(res["stderr"], str)

def test_run_file_type_missing():
    """
    run_file_type should return an error dict for missing file.
    On error, pass test; otherwise, only check additional error details if no error.
    """
    res = libos.run_file_type("/no/such/file.testtype")
    res = json.loads(res)
    assert isinstance(res, dict)
    if "error" in res:
        return
    assert not res.get("success", True)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""
    assert "stderr" in res

def test_run_patch_badfile():
    """
    run_patch should return an error dict for an invalid patch file.
    If 'error' key is present, pass immediately.
    Else, only check further keys if no error.
    """
    with tempfile.NamedTemporaryFile(delete=True) as tf:
        tf.write(b"notapatchfile")
        tf.flush()
        res = libos.run_patch(tf.name)
        res = json.loads(res)
        assert isinstance(res, dict)
        if "error" in res:
            return
        assert not res.get("success", True)
        assert "error" in res
        assert isinstance(res["error"], str)
        assert res["error"].strip() != ""
        assert "stderr" in res

def test_create_patch_for_file_invalid():
    """create_patch_for_file should return a dict with 'error' for a missing file."""
    # try to create a patch for a missing file
    path = "/no/such/file.patchme"
    contents = "test patch"
    res = libos.create_patch_for_file(path, contents)
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""

def test_create_file_existing(tmp_path):
    """create_file should return a dict with 'error' if file exists."""
    f = tmp_path / "afile.txt"
    f.write_text("abc")
    msg = libos.create_file(str(f), "xxx")
    msg = json.loads(msg)
    assert isinstance(msg, dict)
    assert "error" in msg
    assert isinstance(msg["error"], str)
    assert msg["error"].strip() != ""

def test_apply_patch_bad_patch():
    """apply_patch should return a dict with 'error' if patch file missing or invalid."""
    # should complain on totally bogus file
    res = libos.apply_patch("/no/such/fakepatchfile.patch")
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""

def test_file_type_bad():
    """
    file_type should return a dict with 'error' for a missing or unreadable file.
    If the return is not a dict, fail the test with diagnostic info.
    """
    out = libos.file_type("/no/such/file.forfiletype")
    out = json.loads(out)
    assert isinstance(out, dict), f"file_type output should be dict, got: {out!r}"
    assert "error" in out, f"file_type output should contain 'error', got: {out!r}"
    assert isinstance(out["error"], str)
    assert out["error"].strip() != ""


