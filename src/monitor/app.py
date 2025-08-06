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
import traceback  # Added for enhanced error trace reporting in debug/development mode.
import shutil  # For config file backup/copy
from datetime import datetime  # For backup filename timestamps
import importlib.resources  # For accessing package resource defaults
import appdirs  # Import appdirs for user config directory

from monitor import config
from monitor.config import configure_subsystems, load_environment_globals, start_logging, load_model_config
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
            # Enhanced error reporting in debug or development mode
            if app.debug or app.env == 'development':
                tb = traceback.format_exc()
                return jsonify({
                    "error": str(exc),
                    "traceback": tb,
                }), 500
            else:
                return jsonify({"error": str(exc)}), 500
    return app

def create_flask_server(host: str, port: int):
    # ---- Begin Security Warning Check for Host ----
    # Provide security warnings if host is not explicitly local, or is 0.0.0.0
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
    # ---- End Security Warning Check ----

    app = make_flask_app()
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, use_reloader=False)
    logger.info("Flask server stopped.")
    return app

def _reset_config():
    """
    Implements --reset-config as follows:
    - For each config file (app.yaml, macros.json, preferences.prompt):
      - If the file exists in the user config dir, prompt user for confirmation.
      - If confirmed, move to .bak_<timestamp>; else, skip.
      - Copy default resource to user dir.
      - Print success for each file or skip message.
    - At end: print summary & exit immediately.
    """
    user_config_dir = appdirs.user_config_dir('monitor')
    files_to_reset = [
        ("app.yaml", "config", "app.yaml"),
        ("macros.json", "lib", "macros.json"),
        ("preferences.prompt", "config", "preferences.prompt"),
    ]
    reset_results = []
    os.makedirs(user_config_dir, exist_ok=True)

    for filename, pkg, resource_name in files_to_reset:
        user_path = os.path.join(user_config_dir, filename)
        exists = os.path.isfile(user_path)
        user_input = "y"
        if exists:
            # Prompt user for confirmation
            prompt_msg = (
                f"The config file '{filename}' exists in your config directory ({user_config_dir}).\n"
                f"Do you want to back up and overwrite it with the default? [y/N]: "
            )
            try:
                user_input = input(prompt_msg).strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nOperation aborted by user.")
                sys.exit(1)
        if not exists or user_input in ("y", "yes"):
            # Backup existing file if present
            backup_path = None
            if exists:
                dt = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = user_path + f".bak_{dt}"
                try:
                    shutil.move(user_path, backup_path)
                    print(f"Backed up '{filename}' to '{os.path.basename(backup_path)}'")
                    reset_results.append(f"{filename}: backed up to {os.path.basename(backup_path)}")
                except Exception as e:
                    print(f"ERROR: Failed to back up '{filename}': {e}")
                    reset_results.append(f"{filename}: ERROR during backup - {e}")
                    continue  # Do not clobber unintentionally
            # Copy default resource from package
            try:
                with importlib.resources.path(f"monitor.{pkg}", resource_name) as default_path:
                    shutil.copy(default_path, user_path)
                print(f"Reset '{filename}' with default configuration.")
                reset_results.append(f"{filename}: reset to default")
            except Exception as e:
                print(f"ERROR: Failed to copy default '{filename}': {e}")
                reset_results.append(f"{filename}: ERROR during copy - {e}")
        else:
            print(f"Skipped '{filename}'.")
            reset_results.append(f"{filename}: skipped (user declined)")
    # Print summary and exit
    print("\n-- Config Reset Summary --")
    for msg in reset_results:
        print(f"- {msg}")
    print("\nReset operation complete. Exiting.")
    sys.exit(0)

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
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Reset per-user config files to package defaults (with optional backup). Exits after completion.",
    )

    args, unknown = parser.parse_known_args()

    if getattr(args, "reset_config", False):
        _reset_config()

    load_model_config()
    load_environment_globals()
    start_logging()

    # Apply --model CLI override as early as possible before dependency components are initialized.
    if hasattr(args, "model") and args.model is not None:
        # First ensure model_mapping is a dict
        if not isinstance(model_mapping, dict):
            warning_msg = (
                "Warning: model_mapping is not a dictionary as expected; "
                "cannot validate or override model. Model override via --model ignored."
            )
            print(warning_msg)
            logger.warning(warning_msg)
        else:
            # Validate the argument by checking if it is a key or value in the dict
            model_key_list = list(model_mapping.keys())
            model_value_list = list(model_mapping.values())
            valid_model = False

            if args.model in model_key_list:
                valid_model = True
            elif args.model in model_value_list:
                valid_model = True

            if valid_model:
                set_model(args.model)
                logger.info(f"Model override applied via CLI: {args.model}")
                logger.info(f"Effective model is now: {args.model}")
                print(f"Effective model: {args.model}")
            else:
                available_keys = ', '.join(map(str, model_key_list)) if model_key_list else '(none found)'
                available_values = ', '.join(map(str, model_value_list)) if model_value_list else '(none found)'
                warning_msg = (
                    f"Warning: The supplied model '{args.model}' is not valid.\n"
                    f"No model override was applied.\n"
                    f"Available models (keys): {available_keys}\n"
                    f"Available models (values): {available_values}"
                )
                print(warning_msg)
                logger.warning(warning_msg)

    configure_subsystems()


    # Built-ins 
    configure_built_ins()

    # Prompt Macros - For great justice, all your base are belong to us
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
