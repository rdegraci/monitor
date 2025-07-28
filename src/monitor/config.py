"""
config.py

This module contains application configuration and state.

This module is the exclusive configuration loader and default provider for the application.
All default values, config settings, and paths are ONLY set here. Any logic that needs to read a
config value or determine a default MUST import it directly from this file.
There must be NO config defaulting or scattered setting logic in any other module.
If a config value is missing or cannot be constructed from app.yaml or env,
this module will raise errors immediately, never silently.
"""

import yaml
import os
import argparse
import time
import logging
import logging.handlers
import sys
import json

from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)

# --- MODEL CONFIGURATION (SINGLE SOURCE OF TRUTH) ---

# Dictionary to map shorthand keys to full model names
model_mapping = {
    "sonnet4": "anthropic/claude-sonnet-4-20250514",
    "sonnet35": "anthropic/claude-3-5-sonnet-20241022",
    "sonnet37": "anthropic/claude-3-7-sonnet-20250219",
    "claude35": "anthropic/claude-3-5-sonnet-20241022",
    "claude37": "anthropic/claude-3-7-sonnet-20250219",
    "4o-mini": "openai/gpt-4o-mini",
    "gpt4o": "openai/gpt-4o-2024-08-06",
    "o3-mini": "openai/o3-mini-2025-01-31",
    "gemini20": "gemini/gemini-2.0-flash",
    "gpt41": "openai/gpt-4.1-2025-04-14",
    "o3": "openai/o3-2025-04-16",
    "grok4": "xai/grok-4-0709",
    "grok3": "xai/grok-3",
}

conversation_history_mapping = {
    "sonnet4": 25,
    "sonnet35": 25,
    "sonnet37": 25,
    "4o-mini": 25,
    "gpt4o": 20,
    "o3-mini": 25,
    "gemini20": 150,
    "gpt41": 150,
    "o3": 25,
    "grok4": 35,    # 32000 TPM
    "grok3": 20,    # Unknown TPM
}

context_window_mapping = {
    "sonnet4": 200000,
    "sonnet35": 200000,
    "sonnet37": 200000,
    "4o-mini": 200000,
    "gpt4o": 128000,
    "o3-mini": 200000,
    "gemini20": 1048576, #out 8192
    "gpt41": 1048576,
    "o3": 200000,
    "grok4": 256000,
    "grok3": 131072,
}

output_window_mapping = {
    "sonnet4": 64000,
    "sonnet35": 8192,
    "sonnet37": 64000,
    "4o-mini": 16384,
    "gpt4o": 16384,
    "o3-mini": 100000,
    "gemini20": 8192,
    "gpt41": 32768,
    "o3": 100000,
    "grok4": 128000,
    "grok3": 64000,
}

model_max_tpm = {
    "sonnet4": 1,
    "sonnet35": 1,
    "sonnet37": 1,
    "4o-mini": 1,
    "gpt4o": 1,
    "o3-mini": 1,
    "gpt41": 1,
    "o3": 1,
}

# --- CONFIGURATION LOADING ---

def get_yaml_config(file_path='app.yaml'):
    base_dir = os.path.dirname(__file__)
    yaml_path = os.path.join(base_dir, file_path)

    try:
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        # Check for command-line or environment variable override
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--model", type=str, help="LLM model to use (overrides config)")
        args, _ = parser.parse_known_args()

        override_model = args.model or os.getenv("MODEL_OVERRIDE")

        if override_model:
            config["MODEL"] = model_mapping.get(override_model, override_model)
            config["CONVERSATION_MAX_SIZE"] = conversation_history_mapping.get(override_model, 10)
            config["MODEL_CONTEXT_WINDOW"] = context_window_mapping.get(override_model, 128000)
            config["MODEL_OUTPUT_WINDOW"] = output_window_mapping.get(override_model, 16384)
            config["MODEL_MAX_TPM"] = model_max_tpm.get(override_model, 30000)

        return config
    except FileNotFoundError:
        print(f"Configuration file {yaml_path} not found.")
        return {}
    except yaml.YAMLError as exc:
        print(f"Error parsing YAML file: {exc}")
        return {}

yaml_config = get_yaml_config()

# If config is broken or empty, print a warning and exit for safety
if not yaml_config:
    print("WARNING: The configuration file could not be loaded (not found or malformed YAML). Exiting.")
    sys.exit(1)


# --- MODEL CONFIGURATION ---

openai_model_tpm_tier = {
    1: 30000,
    2: 450000,
    3: 800000,
    4: 2000000,
    5: 30000000
}

openai_tpm_tier = openai_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]

anthropic_model_tpm_tier = {
    1: 20000,
    2: 40000,
    3: 80000,
    4: 200000
}

anthropic_tpm_tier = anthropic_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]

# xAI has no tiers, default to 2000000
xai_model_tpm_tier = {
    1: 2000000,
    2: 2000000,
    3: 2000000,
    4: 2000000
}

xai_tpm_tier = xai_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]

google_model_tpm_tier = {
    1: 80000,
    2: 80000,
    3: 80000,
    4: 80000
}

google_tpm_tier = google_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]

model_max_tpm.update({
    "sonnet4": anthropic_tpm_tier,
    "sonnet35": anthropic_tpm_tier,
    "sonnet37": anthropic_tpm_tier,
    "4o-mini": openai_tpm_tier,
    "gpt4o": openai_tpm_tier,
    "o3-mini": openai_tpm_tier,
    "gpt41": openai_tpm_tier,
    "o3": openai_tpm_tier,
    "gemini20": google_tpm_tier,
    "grok4": xai_tpm_tier,
    "grok3": xai_tpm_tier, 
})

MODEL = yaml_config.get("MODEL")
MODEL_CONTEXT_WINDOW = yaml_config.get("MODEL_CONTEXT_WINDOW")
MODEL_OUTPUT_WINDOW = yaml_config.get("MODEL_OUTPUT_WINDOW")
MODEL_MAX_TPM = yaml_config.get("MODEL_MAX_TPM")
CONVERSATION_MAX_SIZE = yaml_config.get("CONVERSATION_MAX_SIZE")

def set_model(model_key: str):
    """
    Changes the active model configuration at runtime.
    
    set_model(model_key: str) updates and sets
    - MODEL
    - MODEL_CONTEXT_WINDOW
    - MODEL_OUTPUT_WINDOW
    - MODEL_MAX_TPM
    - CONVERSATION_MAX_SIZE

    according to the mappings defined at the top of config.py. model_key may be a shorthand mapping key,
    or a full model string (e.g. "openai/gpt-4o-2024-08-06"). If model_key is not in the mapping,
    it is presumed to be a full model string and sensible defaults are applied.
    
    This function updates the above globals in-place for use throughout the application. It logs all changes for audit.
    Call this function to dynamically select a model and propagate its config.
    """
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_MAX_TPM, CONVERSATION_MAX_SIZE

    # Determine mapping values
    mapped_key = None
    if model_key in model_mapping:
        mapped_key = model_key
        model_full = model_mapping[model_key]
    else:
        if model_key in model_mapping.values():
            model_full = model_key
            mapped_key = next((k for k, v in model_mapping.items() if v == model_key), None)
        else:
            model_full = model_key
            mapped_key = None

    if mapped_key:
        MODEL = model_full
        MODEL_CONTEXT_WINDOW = context_window_mapping.get(mapped_key, 128000)
        MODEL_OUTPUT_WINDOW = output_window_mapping.get(mapped_key, 8192)
        MODEL_MAX_TPM = model_max_tpm.get(mapped_key, 30000)
        CONVERSATION_MAX_SIZE = conversation_history_mapping.get(mapped_key, 50)

    logger.info(
        f"set_model: Activated model '{MODEL}' "
        f"(CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW}, OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW}, "
        f"MAX_TPM={MODEL_MAX_TPM}, CONVERSATION_MAX_SIZE={CONVERSATION_MAX_SIZE})"
    )

initial_model_key = yaml_config.get('MODEL', 'openai/gpt-4o')
set_model(initial_model_key)

# --- FILESYSTEM AND DIRECTORY SETUP ---

def ensure_directory_exists(path):
    try:
        os.makedirs(path, exist_ok=True)
        logger.info(f"Directory created or already exists: {path}")
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}", exc_info=True)
        raise

def ensure_parent_dir_exists_for_path(path_value, description=None):
    expanded = os.path.expanduser(path_value)
    parent_dir = os.path.dirname(expanded)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
            if description:
                logger.info(f"Auto-created parent directory for {description}: {parent_dir}")
            else:
                logger.info(f"Auto-created parent directory: {parent_dir}")
        except Exception as e:
            logger.error(f"Failed to create parent directory {parent_dir} for {path_value}: {e}", exc_info=True)
            raise

MONITOR_ASSISTANT_HOME = os.path.expanduser('~/.config/monitor')
ensure_directory_exists(MONITOR_ASSISTANT_HOME)

MONITOR_ASSISTANT_LOGS = os.path.join(MONITOR_ASSISTANT_HOME, 'logs')
ensure_directory_exists(MONITOR_ASSISTANT_LOGS)

macro_file_path = yaml_config.get("MACRO_FILE", "~/.config/monitor/macros.json")
ensure_parent_dir_exists_for_path(macro_file_path, "MACRO_FILE")

preference_file_path = yaml_config.get("PREFERENCE_PROMPT_FILE", "~/.config/monitor/preferences.prompt")
ensure_parent_dir_exists_for_path(preference_file_path, "PREFERENCE FILE")

history_file_path = yaml_config.get('history', {}).get('file', '~/.config/monitor/chat_history')
ensure_parent_dir_exists_for_path(history_file_path, "HISTORY FILE")

jokes_file_path = yaml_config.get("JOKES_FILE", "~/.config/monitor/jokes.txt")
ensure_parent_dir_exists_for_path(jokes_file_path, "JOKES_FILE")

# --- PUBLIC COMMANDS CONFIGURATION ---
public_commands_path_cfg = yaml_config.get("PUBLIC_COMMANDS_PATH", "core/public_commands.json")
PUBLIC_COMMANDS_PATH = os.path.expanduser(public_commands_path_cfg)
ensure_parent_dir_exists_for_path(PUBLIC_COMMANDS_PATH, "PUBLIC_COMMANDS_PATH")
# --- end PUBLIC COMMANDS CONFIGURATION ---

macro_file_abspath = os.path.expanduser(macro_file_path)
if not os.path.exists(macro_file_abspath):
    try:
        os.makedirs(os.path.dirname(macro_file_abspath), exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            with os.fdopen(os.open(macro_file_abspath, flags, 0o600), "w") as f:
                json.dump({}, f)
            logger.info(f"Created missing macro file with empty JSON dictionary: {macro_file_abspath}")
        except FileExistsError:
            logger.info(f"Macro file already exists upon attempted creation: {macro_file_abspath}")
    except Exception as e:
        logger.error(f"Failed to ensure macro file exists at {macro_file_abspath}: {e}", exc_info=True)
        raise

preference_prompt_file = os.path.expanduser(
    yaml_config.get("PREFERENCE_PROMPT_FILE", os.path.join("~", ".config/monitor", "preferences.prompt"))
)
if not os.path.exists(preference_prompt_file):
    try:
        os.makedirs(os.path.dirname(preference_prompt_file), exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            with os.fdopen(os.open(preference_prompt_file, flags, 0o600), "w") as f:
                f.write('# Line based supplemental prompt\n')
            logger.info(f"Created missing preference prompt file with comment: {preference_prompt_file}")
        except FileExistsError:
            logger.info(f"Preference prompt file already exists upon attempted creation: {preference_prompt_file}")
    except Exception as e:
        logger.error(f"Failed to ensure preference prompt file exists at {preference_prompt_file}: {e}", exc_info=True)
        raise

# --- LOGGING CONFIGURATION ---

STARTUP_TIME = time.strftime("%Y_%m_%d_%H_%M")

def get_logging_config():
    """
    Retrieves logging configuration from the YAML config with sensible defaults.
    """
    config = yaml_config.get('logging', {})
    default_log_dir = os.path.join(os.path.expanduser("~"), ".config/monitor", "logs")
    log_dir = os.path.expanduser(config.get('log_dir', default_log_dir))
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create log directory {log_dir}: {e}", exc_info=True)
        raise

    app_log_filename = config.get('app_log_filename', 'app.log')
    conversation_log_filename = config.get('conversation_log_filename', 'conversation.log')
    file_path = os.path.join(log_dir, f"{STARTUP_TIME}_{app_log_filename}")
    log_config = {
        'level': config.get('level', 'INFO'),
        'format': config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        'date_format': config.get('date_format', '%Y-%m-%d %H:%M:%S'),
        'log_dir': log_dir,
        'app_log_filename': app_log_filename,
        'conversation_log_filename': conversation_log_filename,
        'console_logging_enabled': config.get('console_logging_enabled', True),
        'max_bytes': config.get('max_bytes', 10485760),
        'backup_count': config.get('backup_count', 5),
        'file_path': file_path,
        'encoding': config.get('encoding', 'utf-8')
    }
    return log_config

logging_config = get_logging_config()

if not logging_config['log_dir']:
    raise RuntimeError("LOG_DIR (log_dir) is missing in app.yaml and no default could be set.")
if not logging_config['app_log_filename']:
    raise RuntimeError("APP_LOG_FILENAME (app_log_filename) is missing in app.yaml and no default could be set.")
if not logging_config['format']:
    raise RuntimeError("LOG_FORMAT (format) is missing in app.yaml and no default could be set.")
if not logging_config['level']:
    raise RuntimeError("LOGGING_LEVEL (level) is missing in app.yaml and no default could be set.")

LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", logging_config['level']).upper()
LOG_FORMAT = logging_config['format']
LOG_DATE_FORMAT = logging_config['date_format']
LOG_MAX_BYTES = logging_config['max_bytes']
LOG_BACKUP_COUNT = logging_config['backup_count']
CONSOLE_LOGGING_ENABLED = (
    logging_config['console_logging_enabled']
    if logging_config['console_logging_enabled'] is not None
    else True
)
LOG_DIR = logging_config['log_dir']
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
LOG_FILE_PATH = logging_config['file_path']
CONVERSATION_LOG_FILENAME = os.path.join(LOG_DIR, f"{STARTUP_TIME}_{logging_config['conversation_log_filename']}")
CONVERSATION_LOG_FILE = open(CONVERSATION_LOG_FILENAME, "a")


# --- ENVIRONMENT VARIABLE LOADING (.env) ---

def _load_one_dotenv(dotenv_path, description=None, verbose=False):
    """
    Attempt to load a single .env file, logging success/failure. Used in load_environment_variables.
    Returns True if loaded, False otherwise.
    """
    if dotenv_path and os.path.exists(dotenv_path):
        load_dotenv(dotenv_path, override=True)
        if description:
            logger.info(f"{description} loaded successfully from {dotenv_path}.")
        else:
            logger.info(f".env file loaded successfully from {dotenv_path}.")
        return True
    else:
        if verbose:
            if description:
                logger.info(f"{description} not found at {dotenv_path}.")
            else:
                logger.info(f".env file not found at {dotenv_path}.")
        return False

def load_environment_variables(verbose=False):
    """
    Loads environment variables from these .env files in this order (if present):
    1. .env discovered via find_dotenv (nearest up the directory tree from CWD)
    2. ~/.config/monitor/.env

    ~/.config/monitor/.env variables will override variables set by project .env.
    Logs .env loading for audit/debug; does not exit if missing (defaults/secrets may be used).
    Returns:
        dict: {"cwd_env_loaded": bool, "home_env_loaded": bool}
    """
    status = {"cwd_env_loaded": False, "home_env_loaded": False}
    cwd_dotenv_path = find_dotenv()
    status["cwd_env_loaded"] = _load_one_dotenv(cwd_dotenv_path, description="Project .env", verbose=verbose)
    home_dotenv_path = os.path.expanduser(os.path.join("~", ".config/monitor", ".env"))
    status["home_env_loaded"] = _load_one_dotenv(home_dotenv_path, description="Home secrets .env", verbose=verbose)
    if not status["cwd_env_loaded"] and not status["home_env_loaded"]:
        logger.warning("No .env files found/loaded: neither project .env nor ~/.config/monitor/.env was found. Falling back to defaults and system environment only.")
    return status

# --- MISCELLANEOUS CONFIG & SUBSYSTEMS ---

macro_delims = yaml_config.get('macro_delimiters', {})
MACRO_DELIMITER_OPEN = macro_delims.get('open', '(')
MACRO_DELIMITER_CLOSE = macro_delims.get('close', ')')
MACRO_DELIMITER_ESCAPE = macro_delims.get('escape', '\\')
MACRO_FILE_PATH = yaml_config.get("MACRO_FILE", "~/.config/monitor/macros.json")

SUMMARIZATION_CONFIG = yaml_config.get('summarization', {
    'triggers': {
        'token_threshold': 0.8,
        'memory_limit_mb': 100,
        'time_limit_seconds': 3600,
        'token_reduction_factor': 0.5,
        'safety_margin': 0.8
    },
    'prompt': {
        'template': "Summarize the following conversation concisely, always using file paths that start in the current directory, for example ./, when capturing the main points and context: {messages}"
    }
})

EXTERNAL_SERVICES = yaml_config.get('EXTERNAL_SERVICES', False)
MEMORY_SERVICES = yaml_config.get('MEMORY_SERVICES', False)
history_config = yaml_config.get('history', {})
HISTORY_FILE = os.path.expanduser(history_config.get('file', '~/.config/monitor/chat_history'))
OLLAMA_CONFIG = yaml_config.get('ollama', {
    'host': 'http://localhost:11434/api/generate',
    'model': 'llama3.1:latest'
})

ECS_HOST = (
    yaml_config.get('ECS_HOST') or
    yaml_config.get('config', {}).get('ECS_HOST') or
    yaml_config.get('config.ECS_HOST') or
    'localhost'
)
ECS_PORT = (
    yaml_config.get('ECS_PORT') or
    yaml_config.get('config', {}).get('ECS_PORT') or
    yaml_config.get('config.ECS_PORT') or
    5010
)
try:
    ECS_PORT = int(ECS_PORT)
except (TypeError, ValueError):
    logger.warning(f"Invalid ECS_PORT value '{ECS_PORT}' in config; falling back to 5010.")
    ECS_PORT = 5010
ECS_TIMEOUT = (
    yaml_config.get('ECS_TIMEOUT') or
    yaml_config.get('config', {}).get('ECS_TIMEOUT') or
    yaml_config.get('config.ECS_TIMEOUT') or
    10
)
try:
    ECS_TIMEOUT = int(ECS_TIMEOUT)
except (TypeError, ValueError):
    logger.warning(f"Invalid ECS_TIMEOUT value '{ECS_TIMEOUT}' in config; falling back to 10.")
    ECS_TIMEOUT = 10

# --- EXPORT KEY CONFIG VALUES ---

TOTAL_TOKEN_COUNT = 0
MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
OLD_MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
LAST_INPUT_WAS_VOICE = False
CONVERSATION_HISTORY = []

RATE_LIMITING_CONFIG = yaml_config.get('rate_limiting', {
 'safety_factor': 0.6,
 'window_seconds': 60,
})

REASONING_MODEL_PREFIX = yaml_config.get('REASONING_MODEL_PREFIX', 'openai/o3')
REASONING_EFFORT = yaml_config.get('REASONING_EFFORT', "medium")
REASONING_MAX_COMPLETION_TOKENS = yaml_config.get('REASONING_MAX_COMPLETION_TOKENS', 25000)
last_summary_time = time.time()

_summary_token_ratio = None
try:
    _summary_token_ratio = (
        yaml_config.get('summarization', {})
        .get('triggers', {})
        .get('summary_token_ratio', None)
    )
    if _summary_token_ratio is None:
        raise KeyError
    SUMMARY_TOKEN_RATIO = float(_summary_token_ratio)
except Exception:
    SUMMARY_TOKEN_RATIO = 0.5
    logger.warning("summarization.triggers.summary_token_ratio not set in config; defaulting to 0.5.", exc_info=True)

DIRECTIVES_DIR = yaml_config.get('DIRECTIVES_DIR')
if DIRECTIVES_DIR:
    os.environ['DIRECTIVES_DIR'] = DIRECTIVES_DIR

# (End of config.py)
