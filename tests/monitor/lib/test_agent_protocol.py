"""Tests for the sub-agent frame protocol (PLAN_AGENT_ORCHESTRATION Part 1)."""

import json

import pytest

from monitor.lib import agent_protocol as ap


# --- round trip -------------------------------------------------------------


def test_encode_decode_round_trip():
    frame = ap.status("a1", 5, "running linter")
    dec = ap.FrameDecoder()
    out = dec.feed(ap.encode_frame(frame))
    assert len(out) == 1
    got = out[0]
    assert got["type"] == ap.STATUS
    assert got["agent_id"] == "a1"
    assert got["seq"] == 5
    assert got["body"]["label"] == "running linter"
    assert got["v"] == ap.PROTOCOL_VERSION


def test_multiple_frames_in_one_feed():
    blob = ap.encode(ap.HELLO, "a1", 1, {"depth": 1, "cmd": "x", "pid": 9, "name": "n"})
    blob += ap.encode(ap.STATUS, "a1", 2, {"label": "go"})
    blob += ap.encode(ap.EXIT, "a1", 3, {"code": 0})
    out = ap.FrameDecoder().feed(blob)
    assert [f["type"] for f in out] == [ap.HELLO, ap.STATUS, ap.EXIT]
    assert [f["seq"] for f in out] == [1, 2, 3]


# --- partial reads (the SOCK_STREAM hazard) ---------------------------------


def test_partial_reads_reassemble():
    blob = ap.encode(ap.STDOUT, "a1", 7, {"chunk": "hello world"})
    dec = ap.FrameDecoder()
    # Feed one byte at a time; a frame only emerges once fully arrived.
    emitted = []
    for i in range(len(blob)):
        emitted += dec.feed(blob[i : i + 1])
    assert len(emitted) == 1
    assert emitted[0]["body"]["chunk"] == "hello world"
    assert dec.buffered == 0


def test_split_length_prefix():
    blob = ap.encode(ap.STATUS, "a1", 1, {"label": "x"})
    dec = ap.FrameDecoder()
    assert dec.feed(blob[:2]) == []      # half the length prefix
    assert dec.feed(blob[2:5]) == []     # rest of prefix + a little body
    out = dec.feed(blob[5:])             # remainder
    assert len(out) == 1


def test_two_frames_split_across_feeds():
    a = ap.encode(ap.STATUS, "a1", 1, {"label": "one"})
    b = ap.encode(ap.STATUS, "a1", 2, {"label": "two"})
    blob = a + b
    dec = ap.FrameDecoder()
    mid = len(a) + 3  # partway into frame b
    first = dec.feed(blob[:mid])
    second = dec.feed(blob[mid:])
    assert len(first) == 1 and first[0]["body"]["label"] == "one"
    assert len(second) == 1 and second[0]["body"]["label"] == "two"


# --- oversize / version / malformed -----------------------------------------


def test_encode_rejects_oversize():
    huge = "x" * (ap.MAX_FRAME_BYTES + 10)
    with pytest.raises(ap.ProtocolError):
        ap.encode(ap.STDOUT, "a1", 1, {"chunk": huge})


def test_decode_rejects_oversize_prefix():
    # Hand-craft a length prefix that claims a frame larger than the cap.
    bad = (ap.MAX_FRAME_BYTES + 1).to_bytes(4, "big") + b"{}"
    with pytest.raises(ap.ProtocolError):
        ap.FrameDecoder().feed(bad)


def test_decode_rejects_version_mismatch():
    frame = ap.status("a1", 1, "x")
    frame["v"] = 999
    blob = ap.encode_frame(frame)
    with pytest.raises(ap.ProtocolError):
        ap.FrameDecoder().feed(blob)


def test_decode_rejects_bad_json():
    body = b"not json at all"
    bad = len(body).to_bytes(4, "big") + body
    with pytest.raises(ap.ProtocolError):
        ap.FrameDecoder().feed(bad)


def test_decode_rejects_unknown_type():
    frame = {"v": ap.PROTOCOL_VERSION, "type": "bogus", "agent_id": "a1", "seq": 1, "body": {}}
    blob = ap.encode_frame(frame)
    with pytest.raises(ap.ProtocolError):
        ap.FrameDecoder().feed(blob)


def test_decode_rejects_missing_agent_id():
    frame = {"v": ap.PROTOCOL_VERSION, "type": ap.STATUS, "seq": 1, "body": {}}
    blob = ap.encode_frame(frame)
    with pytest.raises(ap.ProtocolError):
        ap.FrameDecoder().feed(blob)


def test_make_frame_rejects_unknown_type():
    with pytest.raises(ap.ProtocolError):
        ap.make_frame("nope", "a1", 1)


# --- constructors + helpers --------------------------------------------------


def test_terminal_classification():
    assert ap.is_terminal(ap.result("a", 1, ok=True, summary="done"))
    assert ap.is_terminal(ap.error("a", 1, kind="x", message="m"))
    assert ap.is_terminal(ap.exit_frame("a", 1, 0))
    assert not ap.is_terminal(ap.status("a", 1, "x"))
    assert not ap.is_terminal(ap.heartbeat("a", 1))


def test_result_omits_data_when_none():
    f = ap.result("a", 1, ok=True, summary="s")
    assert "data" not in f["body"]
    f2 = ap.result("a", 1, ok=True, summary="s", data={"k": 1})
    assert f2["body"]["data"] == {"k": 1}


def test_cancel_is_orch_to_child():
    assert ap.CANCEL in ap.ORCH_TYPES
    assert ap.CANCEL not in ap.CHILD_TYPES


def test_ts_is_set_and_overridable():
    f = ap.make_frame(ap.STATUS, "a", 1, {"label": "x"}, ts=123.0)
    assert f["ts"] == 123.0
    f2 = ap.status("a", 1, "x")
    assert isinstance(f2["ts"], float)
