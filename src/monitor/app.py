"""
Monitor entry point.

Sets up logging, configuration, built-ins, macros, and signal handlers before
delegating execution to the chat conversation loop. Adds an optional Flask
server mode that exposes an HTTP API for sending CLI commands.

When executed as a script, this file also ensures that any conversation log file
is gracefully closed, even when the program is interrupted by the user (e.g.,
Ctrl-C).
"""

import logging
import sys
import argparse  # Added for command-line argument parsing.
import threading  # Added for enhanced shutdown reliability.
import os  # Added for forced process exit fallback.
import time  # Added for small delay before forced exit.

from monitor import config
from monitor.config import load_configuration, configure_logging
from monitor.config import set_model  # Import set_model for CLI model override.
from monitor.lib.signal_handler import setup_sigint_handler  # Import SIGINT handler for clean KeyboardInterrupt handling.

from monitor.core.built_ins import configure_built_ins
from monitor.lib.macros import configure_macros
from monitor.core.conversation import chat
from flask import Flask, request, jsonify  # Flask imports for server mode.
from monitor.core.command_processing import internalize_command  # Command processing for server requests.
from monitor.core.query_service import register_query_function  # Ensure query is registered for server mode.
from monitor.core.conversation import query as conversation_query  # Alias to avoid naming clash with local variable.

try:
    from monitor.config import model_mapping
except ImportError:
    model_mapping = {}

logger = logging.getLogger(__name__)

# Register clean SIGINT handler early to ensure graceful shutdown on interrupt signals.
setup_sigint_handler()

# Load configuration
logger.info("Loading configuration...")

def make_flask_app():
    app = Flask(__name__)
    @app.route("/cli", methods=["POST"])
    def cli():
        """
        HTTP endpoint for processing CLI commands.

        Expects JSON of the form { "command": "<string>" }.
        """
        data = request.get_json(silent=True) or {}
        command = data.get("command")
        if not command:
            return jsonify({"error": "Missing 'command' field"}), 400

        # Normalize for comparison.
        normalized_command = command.lower().strip()

        # --- Graceful shutdown handling --------------------------------------------------
        if normalized_command in ("/exit", "exit"):
            logger.info("Received exit command via API; initiating shutdown sequence.")

            # Capture the shutdown callback from the current request context.
            shutdown_callback = request.environ.get("werkzeug.server.shutdown")

            def _shutdown_server(cb):
                """Attempt to gracefully shut down the Flask development server, then fall back to os._exit."""
                if cb is not None:
                    try:
                        cb()
                        logger.debug("Called werkzeug.server.shutdown() successfully.")
                    except Exception as exc:
                        logger.error(f"Error calling werkzeug shutdown: {exc}")
                else:
                    logger.warning("werkzeug.server.shutdown not available; forcing exit.")

                # Ensure process termination even if the server does not stop within a grace period.
                time.sleep(0.2)
                os._exit(0)

            # Run shutdown in a separate thread so the current request can return a response.
            threading.Thread(target=_shutdown_server, args=(shutdown_callback,), daemon=True).start()
            return jsonify({"message": "Server shutting down..."}), 200

        # Process command normally.
        try:
            result = internalize_command(command)
            return jsonify({"result": result}), 200
        except Exception as exc:
            logger.error(f"Error processing command via API: {exc}", exc_info=True)
            return jsonify({"error": str(exc)}), 500
    return app

def create_flask_server(host: str, port: int):
    app = make_flask_app()
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, use_reloader=False)
    logger.info("Flask server stopped.")
    return app

def main():
    parser = argparse.ArgumentParser(description="Monitor")
    parser.add_argument(
        "--server",
        nargs="?",
        const="127.0.0.1",
        help="Start in server mode with optional host address (default 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for server mode (default 5000)",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Select model key to use (e.g., grok4, o3)",
    )

    args, unknown = parser.parse_known_args()

    load_configuration()


    # Apply --model CLI override as early as possible before dependency components are initialized.
    if hasattr(args, "model") and args.model is not None:
        # Enhanced validation logic for --model
        valid_model = False
        model_key_list = list(getattr(model_mapping, "keys", lambda: [])())
        if model_key_list and args.model in model_key_list:
            valid_model = True
        else:
            # Accept if the value is also a full model string in the model mapping values
            if model_key_list and args.model in model_mapping.values():
                valid_model = True

        if valid_model:
            set_model(args.model)
            logger.info(f"Model override applied via CLI: {args.model}")
            logger.info(f"Effective model is now: {args.model}")
            print(f"Effective model: {args.model}")
        else:
            # Invalid model: print and log warning, show available models
            available_models = ', '.join(model_key_list) if model_key_list else '(none found)'
            warning_msg = (
                f"Warning: Unknown model '{args.model}'. No override applied.\n"
                f"Available models: {available_models}"
            )
            logger.warning(warning_msg)
            print(warning_msg)

    configure_logging()

    # Prepare built-ins and macros that the rest of the application relies on.
    configure_built_ins()
    configure_macros()

    try:
        if args.server is not None:
            host_address = args.server if args.server else "127.0.0.1"
            # Register the query function so that external modules can access it in server mode.
            register_query_function(conversation_query)
            create_flask_server(host_address, args.port)
            # After the Flask server stops (e.g., via /exit), exit the program.
            sys.exit(0)
        else:
            logger.info("Monitor started...")
            print("Monitor ready!")
            chat()
    except KeyboardInterrupt:
        logger.info("Monitor interrupted by KeyboardInterrupt.")
        sys.exit("Monitor interrupted")
    finally:
        # Always attempt to close the conversation log file when running as main.
        try:
            if hasattr(config, "CONVERSATION_LOG_FILE") and config.CONVERSATION_LOG_FILE:
                config.CONVERSATION_LOG_FILE.close()
                logger.info("Closed conversation log file.")
        except Exception as e:
            logger.error(f"Error closing conversation log file: {e}", exc_info=True)
            
if __name__ == "__main__":
    main()
