"""
src/monitor/lib/server.py

Flask server functionality extracted from app.py for modularity, maintenance,
and testability. Provides factories for creating and running the CLI API server.
"""
import logging
import threading
import os
import time
import traceback
from flask import Flask, request, jsonify
from monitor.core.command_processing import internalize_command
logger = logging.getLogger(__name__)

def make_flask_app():
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
            return jsonify({"result": result}), 200
        except Exception as exc:
            logger.error(f"Error processing command via API: {exc}", exc_info=True)
            if app.debug or app.env == 'development':
                tb = traceback.format_exc()
                return jsonify({"error": str(exc), "traceback": tb}), 500
            else:
                return jsonify({"error": str(exc)}), 500
    return app

def create_flask_server(host: str, port: int):
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
    app = make_flask_app()
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, use_reloader=False)
    logger.info("Flask server stopped.")
    return app
