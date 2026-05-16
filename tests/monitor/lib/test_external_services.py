import json
import os
from types import SimpleNamespace

import pytest

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
    # Ensure external services module globals are in a predictable state per test
    es.JOKES.clear()
    es.configure_external_services(
        artifact_server="http://artifact.local/ingest",
        code_lens_host="localhost",
        code_lens_port="5000",
        jokes_file=str(tmp_path / "jokes.txt"),
    )
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
        code_lens_host="localhost",
        code_lens_port="5000",
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
        code_lens_host="code.lens",
        code_lens_port="8080",
        jokes_file=str(tmp_path / "jokes.txt"),
    )

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


def test_send_analyze_request_to_indexing_service_success(monkeypatch, capsys):
    es.configure_external_services(
        artifact_server="",
        code_lens_host="lens",
        code_lens_port="9090",
        jokes_file="",
    )

    payload = {"metadatas": [[{"filename": "a.py", "summary": "sum"}]], "results": [1]}

    def fake_post(url, json=None, timeout=None):
        assert url == "http://lens:9090/analyze"
        assert json == {"query": "what?"}
        return DummyResponse(200, json_data=payload)

    # Capture that print_all_metadata is invoked
    called = {"data": None}
    monkeypatch.setattr(es, "print_all_metadata", lambda d: called.update({"data": d}))

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_analyze_request_to_indexing_service("what?")
    assert data == payload
    assert called["data"] == payload
    assert "Successful retrieval-augmented generation" in capsys.readouterr().out


def test_send_query_to_indexing_service_success(monkeypatch):
    es.configure_external_services("", "lens", "9091", "")

    expected = {"answer": "42"}

    def fake_post(url, json=None, timeout=None):
        assert url == "http://lens:9091/query"
        assert json == {"query": "life?"}
        return DummyResponse(200, json_data=expected)

    monkeypatch.setattr(es.requests, "post", fake_post)

    data = es.send_query_to_indexing_service("life?")
    assert data == expected


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
