"""Tests for the :agent dispatcher — notably that the legacy `:agent <text>`
fallthrough-spawn was removed: unknown subcommands now show usage and never
spawn anything.
"""

from unittest.mock import patch

from monitor.lib.agent import dispatcher


def test_unknown_subcommand_shows_usage_not_spawn():
    with patch.object(dispatcher, "agent_usage") as usage:
        dispatcher.dispatch("listt")  # typo — used to spawn "listt"
        usage.assert_called_once()


def test_no_args_shows_usage():
    with patch.object(dispatcher, "agent_usage") as usage:
        dispatcher.dispatch("")
        usage.assert_called_once()


def test_known_subcommand_routes_to_handler():
    with patch.dict(dispatcher._SUBCOMMAND_HANDLERS, clear=False) as _:
        with patch.object(dispatcher, "agent_usage") as usage:
            called = {}
            dispatcher._SUBCOMMAND_HANDLERS["list"] = lambda tokens: called.setdefault("toks", tokens)
            try:
                dispatcher.dispatch("list --full")
            finally:
                # restore handled by patch.dict
                pass
            assert called["toks"] == ["list", "--full"]
            usage.assert_not_called()


def test_dispatcher_has_no_spawn_handler():
    # The fallthrough spawn path is gone; no spawn-like handler remains.
    assert "spawn" not in dispatcher._SUBCOMMAND_HANDLERS
    assert not hasattr(dispatcher, "agent_spawn")
