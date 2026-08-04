"""Tests for live Monitor instance discovery and TTY activation."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from monitor.lib import instances


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("002", "/dev/ttys002"),
        ("20", "/dev/ttys020"),
        ("tty002", "/dev/ttys002"),
        ("ttys002", "/dev/ttys002"),
        ("/dev/ttys002", "/dev/ttys002"),
        ("TTYS018", "/dev/ttys018"),
    ],
)
def test_normalize_tty(spec, expected):
    assert instances.normalize_tty(spec) == expected


def test_normalize_tty_rejects_garbage():
    with pytest.raises(ValueError):
        instances.normalize_tty("not-a-tty")


@pytest.mark.parametrize(
    "command,expected",
    [
        ("/Users/x/miniconda3/bin/python /Users/x/miniconda3/bin/monitor", True),
        ("python -m monitor", True),
        ("/usr/bin/python3 -m monitor --tui", True),
        ("monitor", True),
        ("/Users/x/bin/monitor", True),
        ("python /tmp/monitor/__main__.py", True),
        ("/bin/zsh -c 'python /Users/x/bin/monitor'", False),
        ("rg /bin/monitor|python -m monitor", False),
        ("/Users/x/bin/python /Users/x/bin/monitor --status-all", False),
        ("/Users/x/bin/python /Users/x/bin/monitor --activate ttys002", False),
        ("python myscript.py", False),
        ("", False),
    ],
)
def test_is_monitor_command(command, expected):
    assert instances.is_monitor_command(command) is expected


def test_list_monitor_instances_from_ps_output():
    ps = """
17886 ttys002  /Users/x/bin/python /Users/x/bin/monitor
62729 ttys006  /Users/x/bin/python /Users/x/bin/monitor
  99 ??       /bin/zsh -c snap=... /Users/x/bin/monitor
 100 ttys001  rg /bin/monitor
 101 ttys003  /Users/x/bin/python /Users/x/bin/monitor --status-all
"""

    def fake_cwd(pid: int) -> str:
        return {17886: "/tmp/a", 62729: "/tmp/b"}.get(pid, "?")

    found = instances.list_monitor_instances(
        exclude_pid=0,
        ps_output=ps,
        cwd_resolver=fake_cwd,
    )
    assert [item.pid for item in found] == [17886, 62729]
    assert found[0].tty_path == "/dev/ttys002"
    assert found[0].cwd == "/tmp/a"
    assert found[1].tty_path == "/dev/ttys006"


def test_list_monitor_instances_batches_cwd_lookup():
    ps = """
17886 ttys002  /Users/x/bin/python /Users/x/bin/monitor
62729 ttys006  /Users/x/bin/python /Users/x/bin/monitor
"""
    with patch(
        "monitor.lib.instances.cwd_for_pids",
        return_value={17886: "/tmp/a", 62729: "/tmp/b"},
    ) as batch:
        found = instances.list_monitor_instances(exclude_pid=0, ps_output=ps)
    batch.assert_called_once_with([17886, 62729])
    assert [item.cwd for item in found] == ["/tmp/a", "/tmp/b"]


def test_cwd_via_lsof_batch_parses_pcn():
    sample = "p17886\nfcwd\nn/tmp/a\np62729\nfcwd\nn/tmp/b\n"
    with patch("monitor.lib.instances.subprocess.run") as run:
        run.return_value = type(
            "R",
            (),
            {"stdout": sample, "returncode": 0},
        )()
        mapping = instances._cwd_via_lsof_batch([17886, 62729])
    assert mapping == {17886: "/tmp/a", 62729: "/tmp/b"}
    assert run.call_args.args[0][:3] == ["lsof", "-nP", "-a"]


def test_format_status_all_empty():
    assert "No running" in instances.format_status_all([])


def test_format_status_all_table():
    rows = [
        instances.MonitorInstance(17886, "ttys002", "/tmp/a", "monitor"),
        instances.MonitorInstance(9, "??", "/tmp/b", "monitor"),
    ]
    text = instances.format_status_all(rows)
    assert "17886" in text
    assert "/dev/ttys002" in text
    assert "/tmp/a" in text
    assert "PID" in text
    # No controlling TTY → "-" device column (not "/dev/??").
    assert any(
        line.split()[:2] == ["9", "-"] for line in text.splitlines() if line.startswith("9")
    )


def test_activate_tty_bad_spec():
    code, message = instances.activate_tty("nope")
    assert code == 2
    assert "Unrecognized" in message


def test_activate_tty_non_darwin():
    with patch.object(instances.sys, "platform", "linux"):
        code, message = instances.activate_tty("ttys002")
    assert code == 1
    assert "macOS" in message


def test_activate_tty_success_terminal():
    with patch.object(instances.sys, "platform", "darwin"), patch(
        "monitor.lib.instances._running_gui_apps", return_value={"Terminal"}
    ), patch(
        "monitor.lib.instances._run_osascript",
        return_value=(0, "focused Terminal /dev/ttys002", ""),
    ) as run:
        code, message = instances.activate_tty("002")
    assert code == 0
    assert "focused Terminal" in message
    script = run.call_args.args[0]
    assert '/dev/ttys002' in script
    assert "tell application \"Terminal\"" in script


def test_activate_tty_tries_iterm_after_terminal_miss():
    def fake_run(script: str):
        if "tell application \"Terminal\"" in script:
            return 1, "", "No Terminal.app tab for /dev/ttys002"
        return 0, "focused iTerm /dev/ttys002", ""

    with patch.object(instances.sys, "platform", "darwin"), patch(
        "monitor.lib.instances._running_gui_apps",
        return_value={"Terminal", "iTerm2"},
    ), patch("monitor.lib.instances._run_osascript", side_effect=fake_run):
        code, message = instances.activate_tty("ttys002")
    assert code == 0
    assert "iTerm" in message


def test_activate_tty_permission_hint_on_failure():
    with patch.object(instances.sys, "platform", "darwin"), patch(
        "monitor.lib.instances._running_gui_apps", return_value={"Terminal"}
    ), patch(
        "monitor.lib.instances._run_osascript",
        return_value=(1, "", "Not authorized to send Apple events"),
    ):
        code, message = instances.activate_tty("/dev/ttys002")
    assert code == 1
    assert "Automation" in message
