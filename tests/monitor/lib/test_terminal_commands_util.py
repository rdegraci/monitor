"""Tests for terminal_commands_util helpers.

Exercises registration and removal of orchestrator-managed entries — the
single API that backs :agent session lifecycle. Designed to be fast and
self-contained.

A second "poller" API (register_orchestrator_poller / PollerEntry) used
to live in this module too; it was removed because nothing in production
called it. Its tests were removed alongside.
"""

from __future__ import annotations

import threading

import pytest

from monitor.lib import terminal_commands_util as util


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
