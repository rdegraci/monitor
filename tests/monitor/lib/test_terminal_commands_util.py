"""Tests for terminal_commands_util helpers.

These tests exercise registration and removal of orchestrator pollers and
arbitrary orchestrator-managed entries. They are designed to be fast and
self-contained.
"""

from __future__ import annotations

import time
import threading

import pytest

from monitor.lib import terminal_commands_util as util


def test_register_and_remove_poller_threaded() -> None:
    """Register a threaded poller and ensure remove requests stop and join it.

    The poller will run in a background thread and check the provided
    stop_event. After removal via the helper, the stop_event must be set and
    the thread should no longer be alive.
    """
    started = []

    def poller(stop_event: threading.Event) -> None:
        # mark started and wait until stop_event is set
        started.append(True)
        while not stop_event.is_set():
            # wait with timeout to be responsive to stop_event
            stop_event.wait(0.01)

    # Register and start the poller in a background thread
    util.register_orchestrator_poller("test_target_poller", poller, start_thread=True, daemon=True)

    # Give the thread a brief moment to start
    time.sleep(0.05)
    assert started, "Poller did not start"

    # Remove and request shutdown; this should set stop_event and join the thread
    entries = util.remove_orchestrator_pollers_by_target("test_target_poller", join_timeout=1.0)

    assert isinstance(entries, list)
    assert entries, "Expected at least one PollerEntry to be returned"

    # Each returned entry should have had its stop_event set
    for entry in entries:
        assert entry.stop_event.is_set(), "stop_event was not set for poller entry"
        # If a thread object was created, it should no longer be alive (join was attempted)
        if entry.thread is not None:
            assert not entry.thread.is_alive(), "Poller thread did not stop"


def test_register_and_remove_entry_with_poller_metadata() -> None:
    """Register a dict-like entry with callable poller metadata and ensure it is stopped.

    The registration code detects a mapping with a 'poller' key that is
    callable. We provide a small poller-like object that is callable and that
    implements stop() and join() so that the removal helper will exercise
    both code paths.
    """

    class DummyPoller:
        def __init__(self) -> None:
            self.stopped = False
            self.joined = False

        def __call__(self, *args, **kwargs):
            # callable so the registration helper captures it as poller metadata
            return None

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout=None) -> None:
            # simulate quick join behavior
            self.joined = True

    dp = DummyPoller()
    entry_obj = {"poller": dp}

    # Register under two keys
    util.register_orchestrator_entry(entry_obj, ["kA", "kB"])

    # Now remove entries registered under kA
    removed = util.remove_orchestrator_entries_by_target("kA", join_timeout=0.1)

    assert isinstance(removed, dict)
    assert "kA" in removed
    assert removed["kA"], "Expected at least one removed entry for key kA"

    # The removed entry dict should contain poller metadata we provided
    rem_entry = removed["kA"][0]
    # util stores the original mapping under 'entry' and detected poller under 'poller'
    detected_poller = rem_entry.get("poller")
    assert detected_poller is dp
    # stop() and join() should have been invoked by the removal helper
    assert dp.stopped is True
    assert dp.joined is True


if __name__ == "__main__":
    # Allow running tests directly for quick local checks
    pytest.main([__file__])
