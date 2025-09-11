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
import os  # Added for forced process exit fallback.
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
from monitor.core.query_service import register_query_function  # Ensure query is registered for server mode.
from monitor.core.conversation import query as conversation_query  # Alias to avoid naming clash with local variable.
from monitor.lib.server import create_flask_server  # Import create_flask_server for server mode.

logger = logging.getLogger(__name__)

def _reset_config(force: bool = False):
    """Reset and optionally back up per-user config files to Monitor package defaults.

    This function replaces user config files with packaged defaults from the 'monitor'
    Python package. If a file exists, it is backed up before replacement. In interactive
    mode, the user is prompted to confirm backup and overwrite unless 'force' is True.
    In non-interactive shells, --force must be specified or the operation is aborted.

    Args:
        force (bool): If True, do not prompt and overwrite existing files after backing up.

    Behavior:
        - Backs up any existing config files in the user's config directory.
        - Overwrites the file with the default version in the 'monitor' package.
        - Prompts interactively to confirm for each file unless 'force' is set or stdin is non-interactive.
        - If not 'force' and not a TTY, aborts with explanation.
        - Summarizes the result of each file operation and exits.

    Returns:
        None. Exits the process after reset attempt.
    """
    user_config_dir = appdirs.user_config_dir('monitor')
    files_to_reset = [
        "app.yaml",
        "macros.json",
        "model_config.json",
        "preferences.prompt",
        "public_commands.json"
    ]
    reset_results = []
    os.makedirs(user_config_dir, exist_ok=True)

    for filename in files_to_reset:
        user_path = os.path.join(user_config_dir, filename)
        exists = os.path.isfile(user_path)
        user_input = "y"
        if exists:
            if force:
                user_input = "y"
            else:
                if not sys.stdin.isatty():
                    print(
                        f"ERROR: Config file '{filename}' exists in your config directory ({user_config_dir}).\n"
                        "Cannot prompt for confirmation in a non-interactive session.\n"
                        "If you intend to overwrite existing config files in a non-interactive\n"
                        "environment, re-run with the --force flag to back up and replace files.\n"
                        "Aborting reset-config operation."
                    )
                    sys.exit(1)
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
            try:
                with importlib.resources.path("monitor", filename) as default_path:
                    shutil.copy(default_path, user_path)
                print(f"Reset '{filename}' with default configuration.")
                reset_results.append(f"{filename}: reset to default")
            except Exception as e:
                print(f"ERROR: Failed to copy default '{filename}': {e}")
                reset_results.append(f"{filename}: ERROR during copy - {e}")
        else:
            print(f"Skipped '{filename}'.")
            reset_results.append(f"{filename}: skipped (user declined)")
    print("\n-- Config Reset Summary --")
    for msg in reset_results:
        print(f"- {msg}")
    print("\nReset operation complete. Exiting.")
    sys.exit(0)

def main():
    """Main entry point.

    Parses CLI arguments, loads configuration and environment, initializes logging
    and signal handlers, configures subsystems, and runs either the interactive
    chat loop or the Flask server.

    Returns:
        None
    """
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reset without prompting (useful in non-interactive shells).",
    )

    args, unknown = parser.parse_known_args()

    if getattr(args, "reset_config", False):
        _reset_config(getattr(args, "force", False))

    load_model_config()
    load_environment_globals()
    start_logging()

    # Register clean SIGINT handler after logging is configured to ensure
    # any logging performed by the handler works as expected.
    setup_sigint_handler()
    logger.info("Loading configuration...")

    # Apply --model CLI override as early as possible before dependency components are initialized.
    if hasattr(args, "model") and args.model is not None:
        ok = set_model(args.model)
        if ok:
            resolved_model = config.MODEL
            logger.info(f"Model override applied via CLI: {args.model} -> {resolved_model}")
            logger.info(f"Effective model is now: {resolved_model}")
            print(f"Effective model: {resolved_model}")
        else:
            model_mapping = getattr(config, "MODEL_MAPPING", None)
            if isinstance(model_mapping, dict):
                model_key_list = list(model_mapping.keys())
                model_value_list = list(model_mapping.values())
                available_keys = ',\n'.join(map(str, model_key_list)) if model_key_list else '(none found)'
                available_values = ',\n'.join(map(str, model_value_list)) if model_value_list else '(none found)'
                warning_msg = (
                    f"Warning: Could not apply model override '{args.model}'.\n"
                    f"Available models (keys): {available_keys}\n"
                    f"Available models (values): {available_values}"
                )
            else:
                warning_msg = (
                    f"Warning: Could not apply model override '{args.model}'. "
                    "MODEL_MAPPING is unavailable or invalid; cannot list available models."
                )
            user_msg = (
                f"\nCould not apply model override '{args.model}'\n\n"
                f"Available models:\n{available_keys}\n\n"
                f"Defaulting to {config.MODEL}\n\n"
            )
            print(user_msg)
            logger.info(warning_msg)

    configure_subsystems()


    # Built-ins 
    configure_built_ins()

    # Prompt Macros - For great justice, all your base are belong to us
    configure_macros()

    try:
        if args.server is not None:
            config.SERVER_MODE = True
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
