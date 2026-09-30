"""Tests for Monitor interactive ``shell`` prompt-prefix helpers."""

import os
import shutil

from monitor.lib.built_ins_shell_utils import (
    MONITOR_SHELL_PROMPT_PREFIX,
    build_monitor_shell_command,
    prepare_monitor_shell_zdotdir,
)


def test_prepare_monitor_shell_zdotdir_writes_prefix_hook():
    zdot = prepare_monitor_shell_zdotdir()
    try:
        zshrc = os.path.join(zdot, ".zshrc")
        assert os.path.isfile(zshrc)
        body = open(zshrc, encoding="utf-8").read()
        assert MONITOR_SHELL_PROMPT_PREFIX in body
        assert "add-zsh-hook precmd _monitor_prompt_prefix" in body
        assert "MONITOR_USER_ZDOTDIR" in body
    finally:
        shutil.rmtree(zdot, ignore_errors=True)


def test_build_monitor_shell_command_sets_zdotdir_and_zsh(monkeypatch):
    monkeypatch.setenv("ZDOTDIR", "/custom/zdot")
    cmd, zdot = build_monitor_shell_command()
    try:
        assert "ZDOTDIR=" in cmd
        assert zdot in cmd
        assert "MONITOR_USER_ZDOTDIR=/custom/zdot" in cmd or "MONITOR_USER_ZDOTDIR='/custom/zdot'" in cmd
        assert cmd.rstrip().endswith("zsh") or " zsh" in cmd
        assert os.path.isdir(zdot)
    finally:
        shutil.rmtree(zdot, ignore_errors=True)


def test_build_monitor_shell_command_appends_extra_args(monkeypatch):
    monkeypatch.delenv("ZDOTDIR", raising=False)
    cmd, zdot = build_monitor_shell_command("-l")
    try:
        assert cmd.endswith("zsh -l")
    finally:
        shutil.rmtree(zdot, ignore_errors=True)
