import subprocess
import time
import requests
import os
import signal
import socket
import pytest

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
    server = subprocess.Popen(
        ["python", "app.py", "--server", "127.0.0.1", "--port", "5678"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    try:
        server_ready = wait_for_server("127.0.0.1", 5678, timeout=10.0, poll_interval=0.1)
        if not server_ready:
            # print server stdout/stderr for debugging
            try:
                out, err = server.communicate(timeout=2)
            except Exception:
                out = b''
                err = b''
            print("Server failed to start.")
            print("Stdout:")
            print(out.decode('utf-8', errors='replace'))
            print("Stderr:")
            print(err.decode('utf-8', errors='replace'))
            raise RuntimeError("Server did not start successfully")

        # Test normal command
        response = requests.post(
            "http://127.0.0.1:5678/cli",
            json={"command": "echo test"}
        )
        assert response.status_code == 200
        assert "result" in response.json()

        # Test exit command (clean shutdown)
        response_exit = requests.post(
            "http://127.0.0.1:5678/cli",
            json={"command": "/exit"}
        )
        assert response_exit.status_code == 200
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.kill(server.pid, signal.SIGKILL)
