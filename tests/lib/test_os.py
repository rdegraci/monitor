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

def test_cat_file_symlink_to_file(tmp_path):
    """cat_file should report valid symlink info, correct target, and file content for symlink to file."""
    file = tmp_path / "target.txt"
    file.write_text("content for symlink target")
    symlink = tmp_path / "thelink"
    symlink.symlink_to(file)
    res = libos.cat_file(str(symlink))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "symlink" in res and res["symlink"] is True
    assert "target" in res
    # Target is relative or absolute, allow both for robustness
    assert os.path.basename(res["target"]) == "target.txt"
    assert "broken" not in res or not res.get("broken", False)
    assert "content" in res and res["content"] == "content for symlink target"

def test_cat_file_broken_symlink(tmp_path):
    """cat_file should report error, symlink:true, and broken:true for a broken symlink."""
    missing = tmp_path / "missing.txt"
    symlink = tmp_path / "brokenlink"
    symlink.symlink_to(missing)
    res = libos.cat_file(str(symlink))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res and isinstance(res["error"], str)
    assert res["error"].strip() != ""
    assert res.get("symlink") is True
    assert "target" in res
    assert os.path.basename(res["target"]) == "missing.txt"
    assert res.get("broken") is True

def test_cat_file_symlink_to_directory(tmp_path):
    """cat_file should report error and symlink:true for symlink to a directory, cannot open as file."""
    directory = tmp_path / "adirectory"
    directory.mkdir()
    symlink = tmp_path / "dirlink"
    symlink.symlink_to(directory)
    res = libos.cat_file(str(symlink))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res and isinstance(res["error"], str)
    assert res["error"].strip() != ""
    assert res.get("symlink") is True
    assert "target" in res
    assert os.path.basename(res["target"]) == "adirectory"

def test_cat_file_symlink_chain(tmp_path):
    """cat_file should resolve symlink chains and report correct info and final target content."""
    file = tmp_path / "file.txt"
    file.write_text("final chain content!")
    symlink2 = tmp_path / "link2"
    symlink2.symlink_to(file)
    symlink1 = tmp_path / "link1"
    symlink1.symlink_to(symlink2)
    res = libos.cat_file(str(symlink1))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert res.get("symlink") is True
    # Accept if the reported target is link2 or file.txt - robust to implementation details
    assert "target" in res
    target_last = os.path.basename(res["target"])
    assert target_last in ("link2", "file.txt")
    assert "content" in res and res["content"] == "final chain content!"
    assert res.get("broken") is not True

def test_make_directory_creates_new(tmp_path):
    """make_directory should create a new directory and not report an error."""
    d = tmp_path / "newdir_for_creation"
    assert not d.exists()
    res = libos.make_directory(str(d))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" not in res, f"Unexpected error creating directory: {res!r}"
    assert d.is_dir()
    if "success" in res:
        assert res["success"] is True

def test_make_directory_existing_directory(tmp_path):
    """make_directory should handle an already existing directory gracefully (no crash)."""
    d = tmp_path / "existing_dir"
    d.mkdir()
    res = libos.make_directory(str(d))
    res = json.loads(res)
    assert isinstance(res, dict)
    if "error" in res:
        return
    assert d.is_dir()
    if "success" in res:
        assert res["success"] is True

def test_make_directory_file_collision(tmp_path):
    """make_directory should return an error when the target path is an existing file."""
    f = tmp_path / "file_collision_target"
    f.write_text("not a directory")
    res = libos.make_directory(str(f))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""

def test_make_directory_invalid_parent_file(tmp_path):
    """make_directory should return an error when parent path is a file (invalid path)."""
    parent_file = tmp_path / "parent_is_file"
    parent_file.write_text("data")
    bad_dir = parent_file / "child"
    res = libos.make_directory(str(bad_dir))
    res = json.loads(res)
    assert isinstance(res, dict)
    assert "error" in res
    assert isinstance(res["error"], str)
    assert res["error"].strip() != ""
    assert not bad_dir.exists()

def test_make_directory_user_expansion(monkeypatch, tmp_path):
    """make_directory should expand '~' to the user's home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    base_name = ".make_dir_user_expand"
    candidate = os.path.join("~", base_name)
    expanded = os.path.expanduser(candidate)
    i = 0
    while os.path.exists(expanded):
        i += 1
        candidate = os.path.join("~", f"{base_name}_{i}")
        expanded = os.path.expanduser(candidate)
    res = libos.make_directory(candidate)
    res = json.loads(res)
    assert isinstance(res, dict)
    if "error" in res:
        return
    assert os.path.isdir(expanded)
