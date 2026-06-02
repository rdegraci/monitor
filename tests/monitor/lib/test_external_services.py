import json
import os
from types import SimpleNamespace

import pytest

# Pre-import config to break a pre-existing import cycle in this test file:
# external_services → config → tool_definitions → built_in_commands →
# external_services (which is mid-load). Loading config first lets it
# settle before external_services pulls on it.
import monitor.config  # noqa: F401

from monitor.lib import external_services as es
from monitor import config


class DummyResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def reset_globals(tmp_path, monkeypatch):
    # Ensure external services module globals are in a predictable state per test.
    # CODE_LENS_HOST/PORT was consolidated into config.EMBEDCODESERV_HOST/PORT;
    # configure_external_services no longer accepts host/port args. Tests that
    # exercise the embedcodeserv endpoints should monkeypatch the config globals
    # directly (see the helper below).
    es.JOKES.clear()
    es.configure_external_services(
        artifact_server="http://artifact.local/ingest",
        jokes_file=str(tmp_path / "jokes.txt"),
    )
    # embedcodeserv config used by send_file_to_indexing_service,
    # send_query_to_indexing_service, send_analyze_request_to_indexing_service.
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "localhost", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "5000", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_TIMEOUT", 30, raising=False)
    # Keep model simple for LLM-dependent calls
    monkeypatch.setattr(config, "MODEL", "test-model", raising=False)
    yield


def test_send_artifact_no_external_services(monkeypatch):
    # When EXTERNAL_SERVICES is False, do not attempt any HTTP
    monkeypatch.setattr(config, "EXTERNAL_SERVICES", False, raising=False)

    called = {"count": 0}

    def fake_post(*args, **kwargs):
        called["count"] += 1
        return DummyResponse(200)

    monkeypatch.setattr(es.requests, "post", fake_post)

    es.send_artifact("hello world")
    assert called["count"] == 0


def test_send_artifact_success(monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_SERVICES", True, raising=False)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(200)

    monkeypatch.setattr(es.requests, "post", fake_post)

    es.send_artifact("hello")

    assert captured["url"] == "http://artifact.local/ingest"
    assert captured["json"] == {"text": "hello"}


def test_send_twitter_message_success(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return DummyResponse(201)

    monkeypatch.setattr(es.requests, "post", fake_post)
    es.send_twitter_message("tweet text")

    assert sent["url"].endswith("/twitter/tweet")
    assert sent["json"]["text"] == "tweet text"


def test_send_twitter_message_ignores_empty(monkeypatch):
    called = {"count": 0}

    def fake_post(*args, **kwargs):
        called["count"] += 1
        return DummyResponse(400)

    monkeypatch.setattr(es.requests, "post", fake_post)
    es.send_twitter_message("")
    assert called["count"] == 0


def test_send_twitch_message_command_success(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return DummyResponse(200)

    monkeypatch.setattr(es.requests, "post", fake_post)
    es.send_twitch_message_command("hello twitch")  # should not raise


def test_send_twitch_message_command_error_no_raise(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return DummyResponse(500, text="server error")

    monkeypatch.setattr(es.requests, "post", fake_post)

    es.send_twitch_message_command("oops")


def test_send_linkedin_message_success(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return DummyResponse(200)

    monkeypatch.setattr(es.requests, "post", fake_post)
    es.send_linkedin_message("linkedin post")


def test_joke_for_twitch_generates_and_saves(tmp_path, monkeypatch, capsys):
    # Prepare jokes file with a pre-existing joke
    jokes_path = tmp_path / "jokes.txt"
    jokes_path.write_text("old joke\n", encoding="utf-8")

    # Update module to use this jokes file
    es.configure_external_services(
        artifact_server="http://artifact.local/ingest",
        jokes_file=str(jokes_path),
    )

    # Mock LLM completion to return a new joke
    mock_completion = SimpleNamespace(
        choices=[SimpleNamespace(message={"content": "brand new joke"})]
    )
    monkeypatch.setattr(es.litellm, "completion", lambda **kwargs: mock_completion)

    sent = {"message": None}
    monkeypatch.setattr(es, "send_twitch_message_command", lambda msg: sent.update({"message": msg}))

    es.joke_for_twitch()

    out = capsys.readouterr().out
    assert "Generated joke:" in out
    assert sent["message"] == "brand new joke"

    # Ensure joke appended to file and in-memory list
    saved_content = jokes_path.read_text(encoding="utf-8").strip().splitlines()
    assert saved_content[-1] == "brand new joke"
    assert es.JOKES[-1] == "brand new joke"


def test_send_file_to_indexing_service_success(tmp_path, monkeypatch):
    src = tmp_path / "file.py"
    src.write_text("print('hi')", encoding="utf-8")

    es.configure_external_services(
        artifact_server="http://artifact.local/ingest",
        jokes_file=str(tmp_path / "jokes.txt"),
    )
    # Override the embedcodeserv host for this test.
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "code.lens", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "8080", raising=False)

    expected = {"ok": True, "id": 123}

    def fake_post(url, json=None, timeout=None):
        assert url == "http://code.lens:8080/embed_source"
        assert json["file_name"] == "file.py"
        assert "print('hi')" in json["source_code"]
        return DummyResponse(202, json_data=expected)

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_file_to_indexing_service(str(src))
    assert data == expected


def test_send_file_to_indexing_service_failure_status(tmp_path, monkeypatch):
    src = tmp_path / "file.py"
    src.write_text("print('hi')", encoding="utf-8")

    def fake_post(url, json=None, timeout=None):
        return DummyResponse(400, text="bad")

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_file_to_indexing_service(str(src))
    assert data is None


def test_send_analyze_request_to_indexing_service_success(monkeypatch):
    """/analyze takes query_text + prompt (the server's documented contract)
    and returns {results, analysis}. The signature changed from the legacy
    single-`query` arg to the proper two-arg form."""
    es.configure_external_services(
        artifact_server="",
        jokes_file="",
    )
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "lens", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "9090", raising=False)

    payload = {"results": [], "analysis": "an answer"}

    def fake_post(url, json=None, timeout=None):
        assert url == "http://lens:9090/analyze"
        assert json == {"query_text": "what?", "prompt": "Explain"}
        return DummyResponse(200, json_data=payload)

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_analyze_request_to_indexing_service("what?", "Explain")
    assert data == payload


def test_send_query_to_indexing_service_success(monkeypatch):
    es.configure_external_services(artifact_server="", jokes_file="")
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "lens", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "9091", raising=False)

    expected = {"results": []}

    def fake_post(url, json=None, timeout=None):
        assert url == "http://lens:9091/query"
        assert json == {"query": "life?"}
        return DummyResponse(200, json_data=expected)

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_query_to_indexing_service("life?")
    assert data == expected


def test_send_query_to_indexing_service_with_comment_top_k(monkeypatch):
    """comment_top_k=0 disables LLM commenting (faster, cheaper queries).
    Verify the param is forwarded when provided."""
    es.configure_external_services(artifact_server="", jokes_file="")
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "lens", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "9091", raising=False)

    def fake_post(url, json=None, timeout=None):
        assert json == {"query": "fast", "comment_top_k": 0}
        return DummyResponse(200, json_data={"results": []})

    monkeypatch.setattr(es.requests, "post", fake_post)

    es.send_query_to_indexing_service("fast", comment_top_k=0)


def test_send_file_to_indexing_service_passes_optional_metadata(monkeypatch, tmp_path):
    """When the caller supplies chunk_type / symbol_name / doc_comment, those
    fields are forwarded to the server. Required fields (file_name,
    source_code) still appear in every payload."""
    src = tmp_path / "f.py"
    src.write_text("def greet(): pass", encoding="utf-8")

    es.configure_external_services(artifact_server="", jokes_file="")
    monkeypatch.setattr(config, "EMBEDCODESERV_HOST", "h", raising=False)
    monkeypatch.setattr(config, "EMBEDCODESERV_PORT", "9", raising=False)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return DummyResponse(202, json_data={"ok": True})

    monkeypatch.setattr(es.requests, "post", fake_post)

    es.send_file_to_indexing_service(
        str(src),
        chunk_type="function",
        symbol_name="greet",
        doc_comment="Says hi.",
    )

    assert captured["file_name"] == "f.py"
    assert captured["source_code"] == "def greet(): pass"
    assert captured["chunk_type"] == "function"
    assert captured["symbol_name"] == "greet"
    assert captured["doc_comment"] == "Says hi."


def test_print_all_metadata_outputs(capsys):
    data = {
        "metadatas": [
            [
                {"filename": "a.py", "summary": "A summary"},
                {"filename": "b.py", "summary": "B summary"},
            ]
        ]
    }
    es.print_all_metadata(data)
    out = capsys.readouterr().out
    assert "Filename: a.py" in out
    assert "A summary" in out
    assert "Filename: b.py" in out
    assert "B summary" in out


def test_print_first_metadata_outputs(capsys):
    data = {
        "metadatas": [
            {"filename": "main.py", "summary": "top", "raw_code_full": "print('x')"}
        ]
    }
    es.print_first_metadata(data)
    out = capsys.readouterr().out
    assert "Filename: main.py" in out
    assert "top" in out
    assert "print('x')" in out
