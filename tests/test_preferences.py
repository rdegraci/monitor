import os
import tempfile
import shutil
import pytest
import logging
from unittest import mock

import src.monitor.lib.preferences as preferences


def test_get_preference_editor_default(monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    with mock.patch("shutil.which", return_value=None), \
         mock.patch("os.path.isfile", return_value=False), \
         mock.patch("os.access", return_value=False):
        editor = preferences.get_preference_editor()
        assert editor is None  # Simulate /usr/bin/vi not present and no EDITOR. 


def test_get_preference_editor_env_absolute(monkeypatch):
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        editor_path = tf.name
    os.chmod(editor_path, 0o755)
    monkeypatch.setenv("EDITOR", editor_path)
    assert preferences.get_preference_editor() == editor_path
    os.unlink(editor_path)


def test_get_preference_editor_env_relative(monkeypatch):
    monkeypatch.setenv("EDITOR", "nano")
    with mock.patch("shutil.which", return_value="/usr/bin/nano"):
        assert preferences.get_preference_editor() == "/usr/bin/nano"


def test_open_preferences_editor_creates_file(monkeypatch):
    tempdir = tempfile.mkdtemp()
    testfile = os.path.join(tempdir, "prefs.txt")
    monkeypatch.setenv("EDITOR", "echo")
    with mock.patch("shutil.which", return_value="/bin/echo"):
        preferences.open_preferences_editor(testfile)
    assert os.path.exists(testfile)
    shutil.rmtree(tempdir)


def test_open_preferences_editor_handles_editor_failure(monkeypatch, caplog):
    tempdir = tempfile.mkdtemp()
    testfile = os.path.join(tempdir, "prefs.txt")
    monkeypatch.setenv("EDITOR", "/not/a/real/editor")
    caplog.set_level(logging.ERROR)
    with mock.patch("shutil.which", return_value=None):
        result = preferences.open_preferences_editor(testfile)
        assert result is None
    shutil.rmtree(tempdir)


def test_load_user_preferences_prompt_reads(monkeypatch):
    tf = tempfile.NamedTemporaryFile(delete=False, mode="w+")
    tf.write("hello world\n")
    tf.close()
    result = preferences.load_user_preferences_prompt(tf.name)
    assert preferences.PREFERENCE_PROMPT == "hello world"
    os.unlink(tf.name)


def test_load_user_preferences_prompt_missing():
    # File does not exist
    result = preferences.load_user_preferences_prompt("/tmp/thisfiledoesnotexist123.txt")
    assert result == ""


def test_load_user_preferences_prompt_ioerror(monkeypatch, caplog):
    with mock.patch("os.path.exists", side_effect=OSError("fail")):
        caplog.set_level(logging.ERROR)
        result = preferences.load_user_preferences_prompt("irrelevant")
        assert result == ""
        # Should log the error
        assert "Could not read preferences file" in caplog.text
