import time
import requests
import os
import signal
import socket
import pytest
import json
from unittest.mock import patch, MagicMock

from monitor.lib.server import make_flask_app
import monitor.lib.server as server

def wait_for_server(host: str, port: int, timeout: float = 10.0, poll_interval: float = 0.1):
    """Wait up to `timeout` seconds for a TCP server to accept a connection."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(poll_interval)
    return False

def test_flask_server_cli():
    app = make_flask_app()
    with app.test_client() as client:
        # Test normal command
        response = client.post("/cli", json={"command": "echo test"})
        assert response.status_code == 200
        json_response = response.get_json()
        # The server returns the structure from internalize_command: {output, error, command_type, exit_requested}
        assert json_response is not None
        assert "output" in json_response or "error" in json_response

        # Test exit command (clean shutdown)
        response_exit = client.post("/cli", json={"command": "/exit"})
        assert response_exit.status_code == 200

        # Test that /exit returns expected shutdown message (if implemented)
        exit_json = response_exit.get_json()
        msg = exit_json.get("message", "")
        msg = msg.lower()
        assert "shutting down" in msg or "exit" in msg

        # Test error response when 'command' field is missing
        response_missing = client.post("/cli", json={})
        assert response_missing.status_code >= 400
        resp_json = response_missing.get_json()
        assert resp_json is not None
        assert "error" in resp_json

        # Test error response with a failing/invalid command
        response_invalid = client.post("/cli", json={"command": "nonexistentcommandthatshouldfail"})
        assert response_invalid.status_code == 200  # Server returns 200 with error in the response structure
        invalid_json = response_invalid.get_json()
        assert invalid_json is not None
        # The response should contain the internalize_command structure with error details
        assert "error" in invalid_json or ("output" in invalid_json and invalid_json["output"])

        # Check submitting another normal command after exit command within same context
        # (behavior may depend on server implementation; for Flask test_client() the app restarts per test_client context)
        followup = client.post("/cli", json={"command": "echo after-exit"})
        assert followup.status_code == 200
        followup_json = followup.get_json()
        assert followup_json is not None
        # Should have the internalize_command response structure
        assert "output" in followup_json or "error" in followup_json

def test_models_endpoint_fields_and_active_model_behavior_without_api_key(monkeypatch):
    # Ensure API key enforcement is disabled
    monkeypatch.setattr(server, "ENFORCE_API_KEY", False, raising=False)
    # Patch config MODEL_MAPPING and MODEL
    if not hasattr(server, "config"):
        pytest.skip("server.config is not available")
    monkeypatch.setattr(server.config, "MODEL_MAPPING", {"test-model-123": {"family": "test"}, "other-model": {"family": "test2"}}, raising=False)
    monkeypatch.setattr(server.config, "MODEL", "test-model-123", raising=False)

    app = make_flask_app()
    with app.test_client() as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        # Standard "list" envelope
        assert data.get("object") == "list"
        models = data.get("data")
        assert isinstance(models, list)
        assert len(models) >= 1
        # Ensure standard fields exist on at least one model
        first = models[0]
        assert "id" in first
        assert first.get("object") in (None, "model", "models") or isinstance(first.get("object"), str)
        # Active model should match patched config.MODEL
        active = data.get("active_model")
        assert active == "test-model-123"

def test_models_endpoint_requires_api_key_when_enforced_and_accepts_valid_key(monkeypatch):
    # Set API key via environment variable
    monkeypatch.setenv("MONITOR_SERVER_API_KEY", "sekret")
    app = make_flask_app()
    with app.test_client() as client:
        # Missing key should fail with 401
        resp_fail = client.get("/v1/models")
        assert resp_fail.status_code == 401
        resp_fail.get_data()
        # Correct key should succeed
        headers = {"Authorization": "Bearer sekret"}
        resp_ok = client.get("/v1/models", headers=headers)
        assert resp_ok.status_code == 200
        data = resp_ok.get_json()
        assert isinstance(data, dict)
        assert data.get("object") == "list"
        assert isinstance(data.get("data"), list)

def test_chat_completions_non_streaming_basic_and_passthrough():
    fake_result = {"output": "Hello from internalize", "error": None, "command_type": "chat", "exit_requested": False}
    with patch.object(server, "ENFORCE_API_KEY", False, create=True):
        with patch.object(server, "internalize_command", return_value=fake_result) as mock_int:
            app = make_flask_app()
            with app.test_client() as client:
                payload = {
                    "model": "any",
                    "messages": [{"role": "user", "content": "Hi there"}],
                }
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 200
                body = resp.get_json()
                assert isinstance(body, dict)
                assert "choices" in body and isinstance(body["choices"], list) and len(body["choices"]) >= 1
                content = body["choices"][0].get("message", {}).get("content", "")
                assert isinstance(content, str)
                assert "Hello from internalize" in content
                assert mock_int.call_count == 1

def test_chat_completions_non_streaming_dict_fallback_via_json_string():
    # internalize_command returns a JSON string; endpoint should parse it and use "output"
    json_string_result = json.dumps({"output": "Parsed from JSON string", "error": ""})
    with patch.object(server, "ENFORCE_API_KEY", False, create=True):
        with patch.object(server, "internalize_command", return_value=json_string_result) as mock_int:
            app = make_flask_app()
            with app.test_client() as client:
                payload = {
                    "model": "any",
                    "messages": [{"role": "user", "content": "Please respond"}],
                }
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 200
                body = resp.get_json()
                assert isinstance(body, dict)
                assert "choices" in body and isinstance(body["choices"], list) and len(body["choices"]) >= 1
                content = body["choices"][0].get("message", {}).get("content", "")
                assert isinstance(content, str)
                assert "Parsed from JSON string" in content
                assert mock_int.call_count == 1

def test_chat_completions_list_content_concatenation_calls_internalize_command():
    with patch.object(server, "ENFORCE_API_KEY", False, create=True):
        mocked = MagicMock(return_value={"output": "ok", "error": ""})
        with patch.object(server, "internalize_command", mocked):
            app = make_flask_app()
            with app.test_client() as client:
                parts = [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": " second"},
                    # Non-text part should be ignored if present
                    {"type": "image_url", "image_url": {"url": "http://example.com/a.png"}},
                ]
                payload = {"model": "any", "messages": [{"role": "user", "content": parts}]}
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 200
                # Verify internalize_command got concatenated text "first second"
                assert mocked.call_count == 1
                args, kwargs = mocked.call_args
                # Expect the first positional argument to contain the concatenated text
                assert len(args) >= 1
                concatenated = "first second"
                assert concatenated in str(args[0])

def test_chat_completions_streaming_sends_sse_with_role_and_done():
    fake_result = {"output": "streamed content", "error": "", "command_type": "chat", "exit_requested": False}
    with patch.object(server, "ENFORCE_API_KEY", False, create=True):
        with patch.object(server, "internalize_command", return_value=fake_result):
            app = make_flask_app()
            with app.test_client() as client:
                payload = {
                    "model": "any",
                    "messages": [{"role": "user", "content": "Start stream"}],
                    "stream": True,
                }
                resp = client.post("/v1/chat/completions", json=payload)
                # SSE mimetype
                assert resp.mimetype == "text/event-stream" or resp.headers.get("Content-Type", "").startswith("text/event-stream")
                # Gather full stream
                if hasattr(resp, "response"):
                    data = b"".join(resp.response).decode("utf-8", errors="replace")
                else:
                    data = resp.get_data(as_text=True)
                # Presence of a role frame (assistant) and the [DONE] sentinel
                assert "role" in data
                assert "[DONE]" in data

def test_single_request_middleware_present():
    app = make_flask_app()
    # Ensure that app is wrapped with SingleRequestMiddleware
    assert isinstance(app.wsgi_app, server.SingleRequestMiddleware)
