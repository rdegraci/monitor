"""Direct unit tests for the two :agent helpers with branchy
return-shape handling: ``_resolve_index_to_session_name`` (numeric
index → session name) and ``_extract_info`` (list-row normalizer).

Both originally lived inside the ~740-line monolithic
``run_command_in_screen`` and had no direct coverage — only the
happy-path dict branch was hit by integration tests. These tests
exercise every shape branch (dict / tuple / object / string) plus
the failure paths, so a future regression in any of them surfaces
loudly instead of silently breaking session-index addressing.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from monitor.lib import terminal_commands
from monitor.lib.agent import list as agent_list_mod
from monitor.lib.screen_handler import ScreenHandlerError


# ============================================================================
# _resolve_index_to_session_name
# ============================================================================
#
# Contract: token is the user-supplied identifier. Non-numeric → return
# verbatim. Numeric → ask _SCREEN_HANDLER.get_session_by_index(int(token))
# and extract the session name from whatever shape it returns. Raises
# Exception if no session can be resolved.


def test_resolver_passes_non_numeric_through_verbatim(monkeypatch):
    """If the token isn't all-digits, no handler call happens — the
    string is returned as-is. This is the common case ('mysession')
    so a regression here would force every test to mock the handler."""
    # Probe: handler should not be touched on the non-numeric path.
    handler = mock.Mock()
    monkeypatch.setattr(terminal_commands, "_SCREEN_HANDLER", handler)
    assert terminal_commands._resolve_index_to_session_name("mysession") == "mysession"
    handler.get_session_by_index.assert_not_called()


def test_resolver_dict_with_session_name_key(monkeypatch):
    """The first-preferred key — the ScreenHandler API's canonical
    field name."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: {"session_name": "alpha", "name": "ignored"},
    )
    assert terminal_commands._resolve_index_to_session_name("3") == "alpha"


def test_resolver_dict_with_name_key_only(monkeypatch):
    """Fallback to 'name' when 'session_name' isn't present — some
    handler revisions used the shorter key."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: {"name": "beta"},
    )
    assert terminal_commands._resolve_index_to_session_name("1") == "beta"


def test_resolver_dict_with_session_key_only(monkeypatch):
    """Last fallback key — older handlers used 'session'."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: {"session": "gamma"},
    )
    assert terminal_commands._resolve_index_to_session_name("2") == "gamma"


def test_resolver_tuple_with_dict_payload(monkeypatch):
    """Handler-shape variant: ``(idx, payload)`` where payload is a dict."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: (5, {"session_name": "tup-dict"}),
    )
    assert terminal_commands._resolve_index_to_session_name("5") == "tup-dict"


def test_resolver_tuple_with_str_payload(monkeypatch):
    """Tuple variant where the payload is just the session name as a
    string. Some legacy handlers ship that shape."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: (5, "bare-str-name"),
    )
    assert terminal_commands._resolve_index_to_session_name("5") == "bare-str-name"


def test_resolver_tuple_with_object_payload(monkeypatch):
    """Tuple variant where the payload is a plain object — uses getattr
    for session_name / name / session."""
    payload = SimpleNamespace(name="obj-name")
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: (5, payload),
    )
    assert terminal_commands._resolve_index_to_session_name("5") == "obj-name"


def test_resolver_bare_string_return(monkeypatch):
    """Simplest handler shape — just return the session name as a string."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: "direct-string",
    )
    assert terminal_commands._resolve_index_to_session_name("7") == "direct-string"


def test_resolver_bare_object_return(monkeypatch):
    """Object with session_name attribute — getattr path."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: SimpleNamespace(session_name="obj-direct"),
    )
    assert terminal_commands._resolve_index_to_session_name("8") == "obj-direct"


def test_resolver_object_with_name_attr_only(monkeypatch):
    """Object with only 'name' attribute — second-preference getattr key."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: SimpleNamespace(name="obj-name-only"),
    )
    assert terminal_commands._resolve_index_to_session_name("9") == "obj-name-only"


def test_resolver_dict_with_no_name_keys_raises(monkeypatch):
    """If the dict payload has none of session_name/name/session, the
    function can't extract a name and must raise. Without this, the
    caller would silently get None and produce confusing errors later."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: {"unrelated_key": "value"},
    )
    with pytest.raises(Exception, match="No session found for index 4"):
        terminal_commands._resolve_index_to_session_name("4")


def test_resolver_none_return_raises(monkeypatch):
    """Handler returning None (e.g., index out of range) must raise."""
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        lambda idx: None,
    )
    with pytest.raises(Exception, match="No session found for index 99"):
        terminal_commands._resolve_index_to_session_name("99")


def test_resolver_propagates_screen_handler_error(monkeypatch):
    """ScreenHandlerError from the handler must propagate so the caller
    can distinguish 'handler is broken' from 'index doesn't exist'."""
    def raise_handler_error(idx):
        raise ScreenHandlerError("handler unavailable")
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        raise_handler_error,
    )
    with pytest.raises(ScreenHandlerError, match="handler unavailable"):
        terminal_commands._resolve_index_to_session_name("1")


def test_resolver_propagates_generic_exception(monkeypatch):
    """Other exceptions also propagate — the caller's try/except
    handles user feedback for those cases."""
    def raise_generic(idx):
        raise RuntimeError("something else")
    monkeypatch.setattr(
        terminal_commands._SCREEN_HANDLER,
        "get_session_by_index",
        raise_generic,
    )
    with pytest.raises(RuntimeError, match="something else"):
        terminal_commands._resolve_index_to_session_name("1")


# ============================================================================
# _extract_info (lib/agent/list.py)
# ============================================================================
#
# Contract: input is one row from list_indexed_sessions. Output is a
# 6-key dict (index/name/token/state/created_at/meta_path) with empty
# strings for any missing field — never None. Handles three input shapes:
# (idx, payload) tuples, bare dicts, and bare objects.


def test_extract_info_tuple_with_dict_payload():
    """Most common shape from a modern handler: ``(index, dict)``."""
    item = (
        7,
        {
            "name": "alpha",
            "token": "1.alpha",
            "state": "attached",
            "created_at": "2026-06-01T10:00:00Z",
            "meta_path": "/tmp/alpha-meta",
        },
    )
    info = agent_list_mod._extract_info(item)
    assert info["index"] == 7
    assert info["name"] == "alpha"
    assert info["token"] == "1.alpha"
    assert info["state"] == "attached"
    assert info["created_at"] == "2026-06-01T10:00:00Z"
    assert info["meta_path"] == "/tmp/alpha-meta"


def test_extract_info_bare_dict():
    """Some handlers return a list of bare dicts (no enclosing tuple)
    where 'index' lives inside the dict."""
    item = {
        "index": 3,
        "name": "beta",
        "state": "detached",
    }
    info = agent_list_mod._extract_info(item)
    assert info["index"] == 3
    assert info["name"] == "beta"
    assert info["state"] == "detached"
    # Missing keys must default to "" — not None — so the table renderer
    # can call .ljust() on them without a TypeError.
    assert info["token"] == ""
    assert info["created_at"] == ""
    assert info["meta_path"] == ""


def test_extract_info_dict_with_idx_alias():
    """Some handlers used 'idx' instead of 'index'. Both should resolve."""
    item = {"idx": 5, "name": "x"}
    info = agent_list_mod._extract_info(item)
    assert info["index"] == 5


def test_extract_info_dict_with_session_name_alias():
    """'session_name' is an accepted alias for 'name' (matches the
    handler API's canonical key in some revisions)."""
    item = {"index": 0, "session_name": "alpha-via-alias"}
    info = agent_list_mod._extract_info(item)
    assert info["name"] == "alpha-via-alias"


def test_extract_info_tuple_with_object_payload():
    """Tuple variant where the payload is a plain object (not a dict).
    The function falls through to getattr-based extraction."""
    payload = SimpleNamespace(
        name="obj-row",
        token="tok-1",
        state="running",
        created_at="2026-06-02",
        meta_path="/tmp/obj-meta",
    )
    info = agent_list_mod._extract_info((0, payload))
    assert info["index"] == 0
    assert info["name"] == "obj-row"
    assert info["token"] == "tok-1"
    assert info["state"] == "running"
    assert info["meta_path"] == "/tmp/obj-meta"


def test_extract_info_object_with_alternate_attrs():
    """Object with status/created (instead of state/created_at). The
    function tries each plausible attr name and uses the first match."""
    payload = SimpleNamespace(
        session_name="obj-alt",
        screen_token="alt-tok",
        status="up",
        created="2026-06-03",
        metadata="/tmp/alt-meta",
    )
    info = agent_list_mod._extract_info((1, payload))
    assert info["name"] == "obj-alt"
    assert info["token"] == "alt-tok"
    assert info["state"] == "up"
    assert info["created_at"] == "2026-06-03"
    assert info["meta_path"] == "/tmp/alt-meta"


def test_extract_info_bare_string_payload():
    """If the handler returns a bare string (rare but possible for
    legacy minimal handlers), the string becomes the name and every
    other field defaults to empty."""
    info = agent_list_mod._extract_info("session-name-only")
    assert info["name"] == "session-name-only"
    assert info["index"] == ""
    assert info["token"] == ""
    assert info["state"] == ""
    assert info["created_at"] == ""
    assert info["meta_path"] == ""


def test_extract_info_all_missing_fields_default_to_empty_string():
    """Critical invariant for the table renderer: every key MUST be a
    string (not None) so column-width calculation via len() and
    .ljust() don't blow up. An empty dict input is the worst case."""
    info = agent_list_mod._extract_info({})
    for key in ("index", "name", "token", "state", "created_at", "meta_path"):
        assert info[key] == "", f"key={key!r} was {info[key]!r}, expected ''"


def test_extract_info_three_element_tuple_treated_as_object():
    """A 3-tuple isn't the ``(idx, payload)`` shape — fall through to
    treating the whole tuple as the payload and try attribute access.
    This won't yield much info, but it should not crash."""
    info = agent_list_mod._extract_info((1, 2, 3))
    # The tuple has no attributes — every field defaults to "".
    assert info["index"] == ""
    assert info["name"] == ""


def test_extract_info_tuple_with_non_indexable_first_element():
    """Tuple where the first element isn't (int, str) — falls through
    to treating the whole tuple as the payload."""
    item = (None, {"name": "edge"})
    info = agent_list_mod._extract_info(item)
    # Not interpreted as (idx, payload); the payload becomes the whole tuple.
    # The tuple has no attributes named 'name'/'session_name'/'session', so
    # name extraction via getattr returns None, then "".
    assert info["name"] == ""
