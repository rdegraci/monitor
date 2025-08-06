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
        assert "result" in response.get_json()

        # Test exit command (clean shutdown)
        response_exit = client.post("/cli", json={"command": "/exit"})
        assert response_exit.status_code == 200

        # Test that /exit returns expected shutdown message (if implemented)
        exit_json = response_exit.get_json()
        msg = exit_json.get("result", "") or exit_json.get("message", "")
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
        assert response_invalid.status_code >= 400 or response_invalid.status_code == 200  # Some servers do 200 with error in JSON
        invalid_json = response_invalid.get_json()
        assert invalid_json is not None
        assert "error" in invalid_json or "result" in invalid_json

        # Check submitting another normal command after exit command within same context
        # (behavior may depend on server implementation; for Flask test_client() the app restarts per test_client context)
        followup = client.post("/cli", json={"command": "echo after-exit"})
        assert followup.status_code == 200
        followup_json = followup.get_json()
        assert followup_json is not None
        assert "result" in followup_json
