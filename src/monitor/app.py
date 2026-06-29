"""
Monitor entry point.

Sets up logging, configuration, built-ins, macros, and signal handlers before
delegating execution to the chat conversation loop. Adds an optional Flask
server mode that exposes an HTTP API for sending CLI commands.

When executed as a script, this file also ensures that any conversation log file
is gracefully closed, even when the program is interrupted by the user (e.g.,
Ctrl-C).
"""

import argparse  # Added for command-line argument parsing.
from monitor._stubs import appdirs  # Import appdirs for user config directory
from datetime import datetime  # For backup filename timestamps
import importlib.resources  # For accessing package resource defaults
import logging
import os  # Added for forced process exit fallback.
import shutil  # For config file backup/copy
import sys

from monitor import config
from monitor.config import configure_subsystems, load_environment_globals, load_model_config, set_model, start_logging
from monitor.core.built_ins import configure_built_ins
from monitor.core.conversation import chat
from monitor.core.conversation import process_input  # Import process_input to feed lines through the conversation input pipeline.
from monitor.core.conversation import query as conversation_query  # Alias to avoid naming clash with local variable.
from monitor.core.query_service import register_query_function  # Ensure query is registered for server mode.
from monitor.core.version import VERSION
from monitor.lib.lexer import create_prompt_session  # Import PromptSession factory for emulated typing in scripts.
from monitor.lib.macros import configure_macros
from monitor.lib.monitor_wiki import configure_project_wiki_paths
from monitor.lib.server import create_flask_server  # Import create_flask_server for server mode.
from monitor.lib.signal_handler import setup_sigint_handler  # Import SIGINT handler for clean KeyboardInterrupt handling.
from monitor.lib.system_prompt import configure_runtime_prompt_paths

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
        "config.yaml",
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
                dt = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
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


def run_script(script_path: str) -> int:
    """Execute commands from a script file, one command per non-empty, non-comment line.

    The script file is read line-by-line. Lines that are empty or begin with the '#'
    character are ignored. Each remaining line is treated as a single command and is
    passed through the conversation input pipeline to emulate interactive typing.

    NOTE: This implementation emulates typing by creating a PromptSession via
    monitor.lib.lexer.create_prompt_session and calling the conversation input
    processor (process_input) for each line: process_input(line, history_file, session).

    The function tries to be tolerant of different return shapes from process_input.
    If process_input returns:
      - a dict containing an 'exit' (or 'should_exit'/'quit') truthy value, processing stops;
      - a tuple where the second element is a boolean exit flag, that flag is checked;
      - a bare boolean, it is treated as the exit flag;
      - an object with an 'exit' attribute, that attribute is checked.

    Args:
        script_path: Path to the script file to execute.

    Returns:
        int: Exit code. 0 on success or if a command requested application exit,
             non-zero for read/execute errors.
    """
    try:
        with open(script_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        logger.error("Script file not found: %s", script_path)
        print(f"ERROR: Script file not found: {script_path}")
        return 2
    except Exception as e:
        logger.error("Failed to read script file %s: %s", script_path, e, exc_info=True)
        print(f"ERROR: Failed to read script file {script_path}: {e}")
        return 3

    # Create a PromptSession to emulate interactive typing for the script commands.
    try:
        session = create_prompt_session()
    except Exception as e:
        logger.error("Failed to create prompt session for script execution: %s", e, exc_info=True)
        print(f"ERROR: Failed to initialize prompt session: {e}")
        return 5

    history_file = getattr(config, "HISTORY_FILE", None)

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        logger.info("Executing script command (line %d): %s", lineno, line)
        try:
            # Feed the line through the conversation input pipeline, emulating interactive input.
            if line == ":version":
                print(f"monitor {VERSION}")
                return 0
            result = process_input(line, history_file, session)
        except Exception as e:
            logger.error("Error executing command on line %d: %s", lineno, e, exc_info=True)
            print(f"ERROR: Exception while executing command on line {lineno}: {e}")
            return 4
        # Determine whether the command indicates the application should exit.
        exit_flag = False
        if isinstance(result, dict):
            exit_flag = bool(result.get("exit") or result.get("should_exit") or result.get("quit"))
        elif isinstance(result, tuple):
            if len(result) >= 2 and isinstance(result[1], bool):
                exit_flag = result[1]
            elif len(result) >= 1 and isinstance(result[0], bool):
                exit_flag = result[0]
        elif isinstance(result, bool):
            exit_flag = result
        elif hasattr(result, "exit"):
            try:
                exit_flag = bool(getattr(result, "exit"))
            except Exception:
                exit_flag = False
        if exit_flag:
            logger.info("Script requested exit after line %d.", lineno)
            return 0
    return 0


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
    parser.add_argument(
        "--models",
        action="store_true",
        help="List available models and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"monitor {VERSION}",
        help="Print the Monitor version and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging level.",
    )
    parser.add_argument(
        "--script",
        type=str,
        help="Path to a script file containing commands to execute, one per line. If present, the script is run and the program exits.",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Enable agent mode (sets config.AGENT to True).",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch the full-screen TUI front-end instead of the REPL.",
    )

    args, unknown = parser.parse_known_args()

    if getattr(args, "reset_config", False):
        _reset_config(getattr(args, "force", False))

    load_model_config()
    load_environment_globals()
    start_logging()

    if getattr(args, "debug", False):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.info("Debug logging enabled via --debug flag.")

    if getattr(args, "models", False):
        model_mapping = getattr(config, "MODEL_MAPPING", None)
        if isinstance(model_mapping, dict):
            if model_mapping:
                print("Available models:")
                for key, value in model_mapping.items():
                    print(f"  {key} -> {value}")
                sys.exit(0)
            else:
                print("No models are currently configured in MODEL_MAPPING.")
                sys.exit(0)
        else:
            print("MODEL_MAPPING is unavailable or invalid; cannot list available models.")
            sys.exit(1)

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
            # Ensure available_keys and available_values are always defined to avoid a NameError
            # when MODEL_MAPPING is not a dict. This preserves existing behavior while preventing
            # an exception when constructing the user-facing message below.
            available_keys = '(none found)'
            available_values = '(none found)'
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

    # Apply --agent CLI flag: set config.AGENT to True and log when enabled.
    if getattr(args, "agent", False):
        try:
            config.AGENT = True
            logger.info("Agent mode enabled via --agent flag.")
        except Exception:
            logger.exception("Failed to set config.AGENT via --agent flag.")

    # Role-based model selection (smart orchestration): now that config.AGENT is
    # resolved, switch to ORCHESTRATOR_MODEL / SUBAGENT_MODEL if configured. Must
    # precede configure_subsystems() (the rate limiter reads MODEL_MAX_TPM).
    # Skipped when --model was explicit so a deliberate user override always wins.
    if not (hasattr(args, "model") and args.model is not None):
        try:
            config.apply_role_model_override()
        except Exception:
            logger.exception("Failed to apply role-based model override.")

    configure_subsystems()

    # PLAN Phase 0.5: when spawned as a sub-agent (MONITOR_AGENT_SOCKET set by
    # the orchestrator), connect back and report over the frame protocol.
    # from_env() returns None for a normal (non-spawned) instance and degrades
    # to a no-op on connection failure, so this never breaks a plain launch.
    try:
        import atexit
        from monitor.lib import agent_reporter
        reporter = agent_reporter.from_env()
        if reporter is not None:
            agent_reporter.set_active(reporter)
            reporter.start_heartbeat()
            reporter.status("agent ready")
            atexit.register(lambda: reporter.close(0))
            logger.info("Agent reporter active (agent_id=%s)", reporter.agent_id)
    except Exception:
        logger.exception("Failed to start agent reporter")

    # Snapshot the startup cwd to resolve any per-project prompt overrides
    # (MONITOR.md / MONITOR_CONVENTIONS.md in the cwd). Frozen for the rest
    # of the session — :cd later does NOT re-resolve.
    startup_cwd = os.getcwd()
    configure_runtime_prompt_paths(startup_cwd)
    configure_project_wiki_paths(startup_cwd)

    # Built-ins
    configure_built_ins()

    # Prompt Macros - For great justice, all your base are belong to us
    configure_macros()

    # If a script was provided, execute it and exit (do not start server or interactive loop).
    if getattr(args, "script", None):
        script_path = args.script
        logger.info("Running script: %s", script_path)
        # Register the conversation query function before running scripts so that any
        # script-executed components or imported modules that rely on the query API
        # can look it up via the query service. This mirrors the registration done
        # for server mode.
        _registration_doc = """Registers the conversation query function so that server endpoints
and scripts can access the conversation query API during execution."""
        register_query_function(conversation_query)
        logger.info("Registered conversation query function for external use (script mode).")
        rc = run_script(script_path)
        if rc == 0:
            sys.exit(0)
        else:
            sys.exit(rc)

    try:
        if args.server is not None:
            config.SERVER_MODE = True
            host_address = args.server if args.server else "127.0.0.1"
            # Register the query function so that external modules can access it in server mode.
            register_query_function(conversation_query)
            create_flask_server(host_address, args.port)
            # After the Flask server stops (e.g., via /exit), exit the program.
            sys.exit(0)
        elif getattr(args, "tui", False):
            # --tui (PLAN_MONITOR_TUI): full-screen front-end instead of the
            # REPL. Launched HERE (not earlier) so it goes through the same
            # setup as chat() — built-ins, macros, and per-project prompt
            # overrides are all configured first. The spike remains at
            # monitor.tui.spike for reference.
            logger.info("Monitor started (TUI)...")
            from monitor.tui.app import run as run_tui
            run_tui()
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
