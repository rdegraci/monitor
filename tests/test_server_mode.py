import time
import requests
import os
import signal
import socket
import pytest

from monitor.lib.server import make_flask_app

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
