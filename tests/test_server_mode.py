import time
import requests
import os
import signal
import socket
import pytest

from monitor.app import make_flask_app

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