"""Discover live Monitor processes and focus their terminal tabs.

``monitor --status-all`` scans the process table for Monitor instances and
prints each PID, controlling TTY, and cwd.

``monitor --activate <tty>`` brings the matching Terminal.app / iTerm2 tab
to the foreground via AppleScript (macOS only).
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_SHELL_BASENAMES = frozenset({"zsh", "bash", "sh", "dash", "fish", "csh", "tcsh"})
_SCANNER_BASENAMES = frozenset({"rg", "grep", "ag", "ack"})

# macOS libproc: PROC_PIDVNODEPATHINFO → current working directory.
_PROC_PIDVNODEPATHINFO = 9
_MAXPATHLEN = 1024


@dataclass(frozen=True)
class MonitorInstance:
    """One live Monitor process."""

    pid: int
    tty: str  # e.g. "ttys002", "??", or ""
    cwd: str
    command: str

    @property
    def tty_path(self) -> str:
        """Full device path, or ``-`` when there is no controlling TTY."""
        if not self.tty or self.tty in {"??", "-", "?"}:
            return "-"
        if self.tty.startswith("/dev/"):
            return self.tty
        return f"/dev/{self.tty}"


def normalize_tty(spec: str) -> str:
    """Normalize a user TTY token to ``/dev/ttysNNN``.

    Accepts ``002``, ``20``, ``tty002``, ``ttys002``, ``/dev/ttys002``.
    Numeric forms shorter than three digits are zero-padded (macOS convention).
    """
    raw = (spec or "").strip()
    if not raw:
        raise ValueError("TTY is empty")

    name = raw[5:] if raw.startswith("/dev/") else raw
    match = re.fullmatch(r"tty[s]?(\d+)", name, flags=re.IGNORECASE)
    if match is None:
        match = re.fullmatch(r"(\d+)", name)
    if match is None:
        raise ValueError(
            f"Unrecognized TTY '{spec}'. Examples: ttys002, tty002, 002, /dev/ttys002"
        )

    digits = match.group(1)
    if len(digits) < 3:
        digits = digits.zfill(3)
    return f"/dev/ttys{digits}"


def is_monitor_command(command: str) -> bool:
    """Return True when *command* looks like a Monitor entrypoint process."""
    if not command or not command.strip():
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return False

    basename0 = os.path.basename(tokens[0])
    if basename0 in _SHELL_BASENAMES or basename0 in _SCANNER_BASENAMES:
        return False

    # Skip the discovery/activate CLI itself so it does not list itself.
    if any(tok in {"--status-all", "--activate"} for tok in tokens):
        return False

    if basename0 == "monitor":
        return True

    if not basename0.startswith("python"):
        return False

    for index, token in enumerate(tokens[1:], start=1):
        if token == "-m":
            if index + 1 < len(tokens) and tokens[index + 1] == "monitor":
                return True
            continue
        if os.path.basename(token) == "monitor":
            return True
        if token.endswith("/monitor/__main__.py") or token.endswith("monitor/__main__.py"):
            return True
    return False


def _parse_ps_line(line: str) -> Optional[Tuple[int, str, str]]:
    """Parse ``pid tty command`` from ``ps -axo pid=,tty=,command=``."""
    match = re.match(r"^\s*(\d+)\s+(\S+)\s+(.*)$", line)
    if not match:
        return None
    pid = int(match.group(1))
    tty = match.group(2)
    command = match.group(3).rstrip()
    return pid, tty, command


class _VnodeInfoPath(ctypes.Structure):
    _fields_ = [
        ("vip_vi", ctypes.c_byte * 152),
        ("vip_path", ctypes.c_char * _MAXPATHLEN),
    ]


class _ProcVnodePathInfo(ctypes.Structure):
    _fields_ = [
        ("pvi_cdir", _VnodeInfoPath),
        ("pvi_rdir", _VnodeInfoPath),
    ]


def _cwd_via_libproc(pid: int) -> Optional[str]:
    """Return cwd for *pid* via macOS ``proc_pidinfo``, or None on failure."""
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = _ProcVnodePathInfo()
        n = lib.proc_pidinfo(
            ctypes.c_int(pid),
            ctypes.c_int(_PROC_PIDVNODEPATHINFO),
            ctypes.c_uint64(0),
            ctypes.byref(buf),
            ctypes.c_int(ctypes.sizeof(buf)),
        )
    except (OSError, AttributeError, ValueError):
        return None
    if n <= 0:
        return None
    path = buf.pvi_cdir.vip_path.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return path or None


def _cwd_via_procfs(pid: int) -> Optional[str]:
    proc_cwd = f"/proc/{pid}/cwd"
    if not (os.path.islink(proc_cwd) or os.path.exists(proc_cwd)):
        return None
    try:
        return os.readlink(proc_cwd)
    except OSError:
        return None


def _cwd_via_lsof_batch(pids: Sequence[int]) -> Dict[int, str]:
    """Resolve cwds for many PIDs with one ``lsof`` invocation."""
    if not pids:
        return {}
    plist = ",".join(str(pid) for pid in pids)
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-a", "-d", "cwd", "-p", plist, "-F", "pcn"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    out: Dict[int, str] = {}
    current_pid: Optional[int] = None
    for line in result.stdout.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            try:
                current_pid = int(value)
            except ValueError:
                current_pid = None
        elif tag == "n" and current_pid is not None and value:
            out[current_pid] = value
    return out


def cwd_for_pids(pids: Sequence[int]) -> Dict[int, str]:
    """Best-effort cwd map for *pids* (libproc / procfs, then batched lsof)."""
    out: Dict[int, str] = {}
    missing: List[int] = []

    for pid in pids:
        path = _cwd_via_procfs(pid)
        if path is None and sys.platform == "darwin":
            path = _cwd_via_libproc(pid)
        if path:
            out[pid] = path
        else:
            missing.append(pid)

    if missing:
        out.update(_cwd_via_lsof_batch(missing))

    for pid in pids:
        out.setdefault(pid, "?")
    return out


def _cwd_for_pid(pid: int) -> str:
    """Best-effort cwd for a single *pid* (tests / callers)."""
    return cwd_for_pids([pid]).get(pid, "?")


def list_monitor_instances(
    *,
    exclude_pid: Optional[int] = None,
    ps_output: Optional[str] = None,
    cwd_resolver=None,
) -> List[MonitorInstance]:
    """Return live Monitor instances discovered from the process table.

    Args:
        exclude_pid: PID to skip (usually the current process).
        ps_output: Optional pre-fetched ``ps`` text for tests.
        cwd_resolver: Optional ``callable(pid) -> str`` for tests. When omitted,
            cwds are resolved in one batched pass.
    """
    if exclude_pid is None:
        exclude_pid = os.getpid()

    if ps_output is None:
        try:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,tty=,command="],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("ps failed: %s", exc)
            return []
        ps_output = completed.stdout or ""

    prelim: List[Tuple[int, str, str]] = []
    for line in ps_output.splitlines():
        parsed = _parse_ps_line(line)
        if parsed is None:
            continue
        pid, tty, command = parsed
        if pid == exclude_pid:
            continue
        if not is_monitor_command(command):
            continue
        prelim.append((pid, tty, command))

    if cwd_resolver is None:
        cwd_map = cwd_for_pids([pid for pid, _tty, _cmd in prelim])
    else:
        cwd_map = {pid: cwd_resolver(pid) for pid, _tty, _cmd in prelim}

    instances = [
        MonitorInstance(
            pid=pid,
            tty=tty,
            cwd=cwd_map.get(pid, "?"),
            command=command,
        )
        for pid, tty, command in prelim
    ]
    instances.sort(key=lambda item: (item.tty_path, item.pid))
    return instances


def format_status_all(instances: Sequence[MonitorInstance]) -> str:
    """Format instances as a simple PID / TTY / CWD table."""
    if not instances:
        return "No running Monitor instances found."

    pid_width = max(3, max(len(str(item.pid)) for item in instances))
    tty_width = max(3, max(len(item.tty_path) for item in instances))
    lines = [
        f"{'PID'.ljust(pid_width)}  {'TTY'.ljust(tty_width)}  CWD",
        f"{'-' * pid_width}  {'-' * tty_width}  ---",
    ]
    for item in instances:
        lines.append(
            f"{str(item.pid).ljust(pid_width)}  {item.tty_path.ljust(tty_width)}  {item.cwd}"
        )
    return "\n".join(lines)


def print_status_all() -> int:
    """Print ``--status-all`` output. Returns a process exit code."""
    instances = list_monitor_instances()
    print(format_status_all(instances))
    return 0


def _running_gui_apps() -> set[str]:
    """Return names of interesting frontmost-capable apps, best-effort."""
    if sys.platform != "darwin":
        return set()
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of every process '
                "whose background only is false",
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()
    return {part.strip() for part in result.stdout.split(",") if part.strip()}


def _applescript_focus_terminal(tty_path: str) -> str:
    """AppleScript that focuses a Terminal.app tab by tty path."""
    # tty_path is normalized to /dev/ttysNNN; also match a bare ttysNNN suffix.
    short = tty_path.rsplit("/", 1)[-1]
    return f'''
set targetTTY to "{tty_path}"
set shortTTY to "{short}"
tell application "Terminal"
    repeat with w in windows
        try
            set tabTTY to tty of tab 1 of w
            if tabTTY is equal to targetTTY or tabTTY ends with shortTTY then
                set index of w to 1
                set selected of tab 1 of w to true
                activate
                return "focused Terminal " & tabTTY
            end if
        end try
    end repeat
end tell
error "No Terminal.app tab for " & targetTTY
'''


def _applescript_focus_iterm(tty_path: str) -> str:
    """AppleScript that focuses an iTerm2 session by tty path."""
    short = tty_path.rsplit("/", 1)[-1]
    return f'''
set targetTTY to "{tty_path}"
set shortTTY to "{short}"
tell application "iTerm"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                try
                    set sessionTTY to tty of s
                    if sessionTTY is equal to targetTTY or sessionTTY ends with shortTTY then
                        select w
                        select t
                        select s
                        activate
                        return "focused iTerm " & sessionTTY
                    end if
                end try
            end repeat
        end repeat
    end repeat
end tell
error "No iTerm tab for " & targetTTY
'''


def _run_osascript(script: str) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["osascript"],
            input=script,
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except FileNotFoundError:
        return 1, "", "osascript not found"
    except subprocess.TimeoutExpired:
        return 1, "", "osascript timed out"
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def activate_tty(spec: str, *, gui_apps: Optional[Iterable[str]] = None) -> Tuple[int, str]:
    """Focus the terminal tab for *spec*. Returns ``(exit_code, message)``."""
    try:
        tty_path = normalize_tty(spec)
    except ValueError as exc:
        return 2, str(exc)

    if sys.platform != "darwin":
        return (
            1,
            f"Focus via AppleScript is only supported on macOS (wanted {tty_path}).",
        )

    apps = set(gui_apps) if gui_apps is not None else _running_gui_apps()
    # Prefer whichever terminal is actually running. If detection fails (empty
    # set), try Terminal.app then iTerm.
    candidates: List[Tuple[str, str]] = []
    try_terminal = ("Terminal" in apps) or (not apps)
    try_iterm = ("iTerm2" in apps) or ("iTerm" in apps) or (not apps)
    if try_terminal:
        candidates.append(("Terminal", _applescript_focus_terminal(tty_path)))
    if try_iterm:
        # AppleScript application name is typically "iTerm".
        candidates.append(("iTerm", _applescript_focus_iterm(tty_path)))

    errors: List[str] = []
    for label, script in candidates:
        code, stdout, stderr = _run_osascript(script)
        if code == 0:
            return 0, stdout or f"Focused {tty_path} via {label}"
        detail = stderr or stdout or f"{label} focus failed"
        errors.append(detail)

    hint = (
        "Grant Automation permission: System Settings → Privacy & Security → "
        "Automation (allow your terminal app to control Terminal/iTerm). "
        "Accessibility may also be required for System Events."
    )
    return 1, f"Could not focus {tty_path}.\n" + "\n".join(errors) + f"\n{hint}"


def print_activate(spec: str) -> int:
    """CLI entry for ``--activate``. Prints a status line and returns exit code."""
    code, message = activate_tty(spec)
    print(message)
    return code
