"""
src/monitor/lib/server.py

Flask server functionality extracted from app.py for modularity, maintenance,
and testability. Provides factories for creating and running the CLI API server.

This module also introduces a WSGI middleware that serializes all incoming HTTP
requests using a threading.Lock, ensuring only one request is processed at a time.
This is intended for single-user or test scenarios where deterministic, in-order
processing is desired.
"""
import logging
import threading
import os
import time
import traceback
from flask import Flask, request, jsonify
from monitor.core.command_processing import internalize_command
logger = logging.getLogger(__name__)

class SingleRequestMiddleware:
    """
    WSGI middleware that serializes all HTTP requests using a threading.Lock.

    This ensures that only one request is processed at a time, providing
    single-user, single-threaded behavior even if the underlying WSGI server
    supports concurrency.

    The lock is held for the full lifetime of the request, including iteration
    over the response iterable, to ensure true serialization.
    """
    def __init__(self, app, logger: logging.Logger | None = None):
        self.app = app
        self._lock = threading.Lock()
        self._logger = logger or logging.getLogger(__name__)

    def __call__(self, environ, start_response):
        self._logger.debug("Awaiting request lock for serialized processing.")
        self._lock.acquire()
        self._logger.debug("Acquired request lock; processing request.")
        try:
            result = self.app(environ, start_response)

            def releasing_iter():
                try:
                    for item in result:
                        yield item
                finally:
                    try:
                        close = getattr(result, "close", None)
                        if callable(close):
                            close()
                    finally:
                        self._logger.debug("Releasing request lock after processing.")
                        self._lock.release()

            return releasing_iter()
        except Exception:
            self._logger.debug("Exception encountered while handling request; releasing lock.")
            self._lock.release()
            raise

def make_flask_app():
    """
    Create and configure the Flask application for the CLI API.

    Returns:
        Flask: The configured Flask application, with WSGI middleware applied
               to serialize (single-thread) all incoming HTTP requests.
    """
    app = Flask(__name__)

    @app.route("/cli", methods=["POST"])
    def cli():
        data = request.get_json(silent=True) or {}
        command = data.get("command")
        if not command:
            return jsonify({"error": "Missing 'command' field"}), 400
        normalized_command = command.lower().strip()
        if normalized_command in ("/exit", "exit"):
            logger.info("Received exit command via API; initiating shutdown sequence.")
            # Capture the shutdown callback from the current request context.
            shutdown_callback = request.environ.get("werkzeug.server.shutdown")
            def _shutdown_server(cb):
                if cb is not None:
                    try:
                        cb()
                        logger.debug("Called werkzeug.server.shutdown() successfully.")
                    except Exception as exc:
                        logger.error(f"Error calling werkzeug shutdown: {exc}")
                else:
                    logger.warning("werkzeug.server.shutdown not available; forcing exit.")
                time.sleep(0.2)
                os._exit(0)
            threading.Thread(target=_shutdown_server, args=(shutdown_callback,), daemon=True).start()
            return jsonify({"message": "Server shutting down..."}), 200
        try:
            result = internalize_command(command)
            return jsonify(result), 200
        except Exception as exc:
            logger.error(f"Error processing command via API: {exc}", exc_info=True)
            if app.debug or app.env == 'development':
                tb = traceback.format_exc()
                return jsonify({"error": str(exc), "traceback": tb}), 500
            else:
                return jsonify({"error": str(exc)}), 500

    # Wrap the Flask app with middleware to ensure single-request processing.
    app.wsgi_app = SingleRequestMiddleware(app.wsgi_app, logger=logger)
    logger.info("SingleRequestMiddleware enabled: requests will be processed one at a time.")
    return app

def create_flask_server(host: str, port: int):
    """
    Create and run the Flask development server for the CLI API.

    Args:
        host (str): Host interface to bind the server to.
        port (int): Port number to listen on.

    Returns:
        Flask: The Flask application instance (after the server stops).
    """
    local_hosts = {"127.0.0.1", "localhost"}
    if host not in local_hosts:
        warning_header = "!!! SECURITY WARNING !!!"
        if host == "0.0.0.0":
            warning_detail = (
                f"Flask server is listening on '0.0.0.0', which exposes the /cli API "
                f"on ALL network interfaces. This can be very insecure if not protected!"
            )
        else:
            warning_detail = (
                f"Flask server is listening on '{host}', which may be accessible from outside localhost. "
                f"The /cli endpoint receives arbitrary CLI commands and could be exploited if publicly reachable."
            )
        warning_footer = "Restrict the host address to 127.0.0.1 or use proper network security controls!"
        full_warning = (
            f"\n{warning_header}\n{warning_detail}\n{warning_footer}\n"
            "-------------------------------------------------------"
        )
        print(full_warning)
        logger.warning(full_warning)

    single_user_banner = (
        "\n=== SINGLE-USER SERIALIZED MODE ===\n"
        "All HTTP requests will be processed one at a time.\n"
        "Intended for single-user or test scenarios.\n"
        "-----------------------------------------------"
    )
    print(single_user_banner)
    logger.info(single_user_banner)

    app = make_flask_app()
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, use_reloader=False)
    logger.info("Flask server stopped.")
    return app
