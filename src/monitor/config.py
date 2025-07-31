import yaml
import os
import argparse
import time
import logging
import logging.handlers
import sys
import json
import shutil
import appdirs
import importlib.resources
import importlib.util

from dotenv import find_dotenv, load_dotenv

from monitor.lib.rate_limiter import configure_rate_limiter
from monitor.core.tools import configure_tools
from monitor.lib.redis_utils import configure_redis_utils
from monitor.lib.preferences import load_user_preferences
from monitor.lib.external_services import configure_external_services
from monitor.lib.protocol_engine import configure_protocol_engine
from monitor.lib.logging import configure_logging

logger = logging.getLogger(__name__)

def find_config_file(filename):
    """
    Search for 'filename' in system (site) config dir first, then in user config dir.
    If found in both, return the user config dir version.
    If found only in site config dir, return that.
    If not found in either, raise FileNotFoundError.
    """
    site_config_dir = appdirs.site_config_dir("monitor")
    user_config_dir = appdirs.user_config_dir("monitor")
    site_path = os.path.join(site_config_dir, filename)
    user_path = os.path.join(user_config_dir, filename)

    user_exists = os.path.exists(user_path)
    site_exists = os.path.exists(site_path)

    if user_exists:
        return user_path
    elif site_exists:
        return site_path
    else:
        raise FileNotFoundError(
            f"{filename} not found in either {user_path} or {site_path}"
        )

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

def load_yaml_config(file_path=find_config_file("app.yaml")):
    yaml_path = file_path
    try:
        with open(yaml_path) as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        print(f"Configuration file {yaml_path} not found.")
        return {}
    except yaml.YAMLError as exc:
        print(f"Error parsing YAML file: {exc}")
        return {}

def get_logging_config():
    """
    Retrieves logging configuration from the YAML config with sensible defaults.
    """
    config = load_yaml_config().get('logging', {})
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

model_reverse_mapping = {
    "anthropic/claude-sonnet-4-20250514": "sonnet4",
    "anthropic/claude-3-5-sonnet-20241022": "sonnet35",
    "anthropic/claude-3-7-sonnet-20250219": "sonnet37",
    "anthropic/claude-3-5-sonnet-20241022": "claude35",
    "anthropic/claude-3-7-sonnet-20250219": "claude37",
    "openai/gpt-4o-mini": "4o-mini",
    "openai/gpt-4o-2024-08-06": "gpt4o",
    "openai/o3-mini-2025-01-31": "o3-mini",
    "gemini/gemini-2.0-flash": "gemini20",
    "openai/gpt-4.1-2025-04-14": "gpt41",
    "openai/o3-2025-04-16": "o3",
    "xai/grok-4-0709": "grok4",
    "xai/grok-3": "grok3",
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
    "grok4": 1,
    "grok3": 1,
    "gemini20": 1,
}

openai_model_tpm_tier = {
    1: 30000,
    2: 450000,
    3: 800000,
    4: 2000000,
    5: 30000000
}

anthropic_model_tpm_tier = {
    1: 20000,
    2: 40000,
    3: 80000,
    4: 200000
}

# xAI has no tiers, default to 2000000
xai_model_tpm_tier = {
    1: 2000000,
    2: 2000000,
    3: 2000000,
    4: 2000000
}

google_model_tpm_tier = {
    1: 80000,
    2: 80000,
    3: 80000,
    4: 80000
}

model_tpm_mapping = {
    "sonnet4": anthropic_model_tpm_tier,
    "sonnet35": anthropic_model_tpm_tier,
    "sonnet37": anthropic_model_tpm_tier,
    "4o-mini": openai_model_tpm_tier,
    "gpt4o": openai_model_tpm_tier,
    "o3-mini": openai_model_tpm_tier,
    "gpt41": openai_model_tpm_tier,
    "o3": openai_model_tpm_tier,
    "grok3": xai_model_tpm_tier,
    "grok4": xai_model_tpm_tier,
    "gemini20": google_model_tpm_tier
}

MODEL=None
MODEL_CONTEXT_WINDOW=None 
MODEL_OUTPUT_WINDOW=None
MODEL_INPUT_TIER=None
MODEL_MAX_TPM=None 
CONVERSATION_MAX_SIZE=None
RATE_LIMITING_CONFIG=None 
MEMORY_SERVICES=None 
STARTUP_TIME=None 
HISTORY_FILE=None
CONVERSATION_HISTORY = [] 
MAX_TOKEN_COUNT=None 
OLD_MAX_TOKEN_COUNT=None 
MACRO_DELIMITER_OPEN=None 
MACRO_DELIMITER_CLOSE=None 
MACRO_DELIMITER_ESCAPE=None 
MACRO_FILE_PATH=None 
SUMMARIZATION_CONFIG=None
EXTERNAL_SERVICES=None
MEMORY_SERVICES=None
OLLAMA_CONFIG=None
TOTAL_TOKEN_COUNT = 0 
PUBLIC_COMMANDS_PATH=None
REDIS_HOST=None
REDIS_PORT=6379
REDIS_DB=0
REDIS_MAX_RETRIES=3
REDIS_RETRY_INTERVAL=1
PREFERENCE_PROMPT_FILE=None
REASONING_MODEL_PREFIX=None
REASONING_EFFORT=None
REASONING_MAX_COMPLETION_TOKENS=None
LAST_INPUT_WAS_VOICE = False
ARTIFACT_SERVER=None
CODE_LENS_HOST=None
CODE_LENS_PORT=None
JOKES_FILE=None
DIRECTIVES_DIR=None
ECS_HOST=None
ECS_PORT=None 

def configure_globals():
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_MAX_TPM, MODEL_INPUT_TIER
    global CONVERSATION_MAX_SIZE, RATE_LIMITING_CONFIG, MEMORY_SERVICES, STARTUP_TIME
    global HISTORY_FILE, MAX_TOKEN_COUNT, OLD_MAX_TOKEN_COUNT
    global MACRO_DELIMITER_OPEN, MACRO_DELIMITER_CLOSE, MACRO_DELIMITER_ESCAPE, MACRO_FILE_PATH
    global SUMMARIZATION_CONFIG
    global EXTERNAL_SERVICES, MEMORY_SERVICES, OLLAMA_CONFIG
    global PUBLIC_COMMANDS_PATH, REDIS_HOST, PREFERENCE_PROMPT_FILE
    global REASONING_MODEL_PREFIX, REASONING_EFFORT, REASONING_MAX_COMPLETION_TOKENS
    global ARTIFACT_SERVER, CODE_LENS_HOST, CODE_LENS_PORT, JOKES_FILE, DIRECTIVES_DIR
    global ECS_HOST, ECS_PORT

    yaml_config = load_yaml_config()

    MODEL = yaml_config.get("MODEL")
    MODEL_CONTEXT_WINDOW = yaml_config.get("MODEL_CONTEXT_WINDOW")
    MODEL_OUTPUT_WINDOW = yaml_config.get("MODEL_OUTPUT_WINDOW")

    MODEL_INPUT_TIER = yaml_config.get("MODEL_INPUT_TIER")
    MODEL_MAX_TPM = yaml_config.get("MODEL_MAX_TPM")
    if MODEL_MAX_TPM is None:
        reversed_model = model_reverse_mapping.get(MODEL) # gpt41
        model_tpm = model_tpm_mapping.get(reversed_model)    # openai_model_tpm_tier
        assert(MODEL_INPUT_TIER is not None)
        MODEL_MAX_TPM = model_tpm.get(MODEL_INPUT_TIER) # 4 = 2000000

    assert(MODEL_MAX_TPM is not None)

    CONVERSATION_MAX_SIZE = yaml_config.get("CONVERSATION_MAX_SIZE")
    RATE_LIMITING_CONFIG = yaml_config.get('rate_limiting', {
     'safety_factor': 0.6,
     'window_seconds': 60,
    })
    STARTUP_TIME = time.strftime("%Y_%m_%d_%H_%M")
    

    history_config = yaml_config.get('history', {})
    HISTORY_FILE = os.path.expanduser(history_config.get('file', '~/.config/monitor/chat_history'))
    MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
    OLD_MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW

    macro_delims = yaml_config.get('macro_delimiters', {})
    MACRO_DELIMITER_OPEN = macro_delims.get('open', '(')
    MACRO_DELIMITER_CLOSE = macro_delims.get('close', ')')
    MACRO_DELIMITER_ESCAPE = macro_delims.get('escape', '\\')
    MACRO_FILE_PATH = yaml_config.get("MACRO_FILE")

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
    OLLAMA_CONFIG = yaml_config.get('ollama', {
        'host': 'http://localhost:11434/api/generate',
        'model': 'llama3.1:latest'
    })

    public_commands_path_cfg = yaml_config.get("PUBLIC_COMMANDS_PATH")
    PUBLIC_COMMANDS_PATH = os.path.expanduser(public_commands_path_cfg)
    REDIS_HOST = yaml_config.get("REDIS_HOST")

    PREFERENCE_PROMPT_FILE = yaml_config.get("PREFERENCE_PROMPT_FILE")

    REASONING_MODEL_PREFIX = yaml_config.get('REASONING_MODEL_PREFIX', 'openai/o3')
    REASONING_EFFORT = yaml_config.get('REASONING_EFFORT', "medium")
    REASONING_MAX_COMPLETION_TOKENS = yaml_config.get('REASONING_MAX_COMPLETION_TOKENS', 25000)

    ARTIFACT_SERVER = yaml_config.get('ARTIFACT_SERVER', 'http://localhost:2323/')
    CODE_LENS_HOST = yaml_config.get('CODE_LENS_HOST', 'localhost')
    CODE_LENS_PORT = yaml_config.get('CODE_LENS_PORT', '5000')

    # Global list to store jokes told previously
    JOKES_FILE = yaml_config.get('JOKES_FILE', '/Users/rdegraci/.monitor-jokes')

    DIRECTIVES_DIR = yaml_config.get('DIRECTIVES_DIR')
    if DIRECTIVES_DIR:
        os.environ['DIRECTIVES_DIR'] = DIRECTIVES_DIR

    ECS_HOST = yaml_config.get('ECS_HOST')
    ECS_PORT = yaml_config.get('ECS_PORT')

LOGGING_CONFIG=None 
LOGGING_LEVEL=None 
LOG_FORMAT=None 
LOG_DATE_FORMAT=None 
LOG_MAX_BYTES=None
LOG_BACKUP_COUNT=None 
CONSOLE_LOGGING_ENABLED=None 
LOG_DIR=None
LOG_FILE_PATH=None 
CONVERSATION_LOG_FILENAME=None 
CONVERSATION_LOG_FILE=None 

def configure_logging_globals():
    global LOGGING_CONFIG, LOGGING_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES, LOG_BACKUP_COUNT
    global CONSOLE_LOGGING_ENABLED, LOG_DIR, LOG_FILE_PATH, CONVERSATION_LOG_FILENAME, CONVERSATION_LOG_FILE

    LOGGING_CONFIG = get_logging_config()

    if not LOGGING_CONFIG['log_dir']:
        raise RuntimeError("LOG_DIR (log_dir) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['app_log_filename']:
        raise RuntimeError("APP_LOG_FILENAME (app_log_filename) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['format']:
        raise RuntimeError("LOG_FORMAT (format) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['level']:
        raise RuntimeError("LOGGING_LEVEL (level) is missing in app.yaml and no default could be set.")

    LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", LOGGING_CONFIG['level']).upper()
    LOG_FORMAT = LOGGING_CONFIG['format']
    LOG_DATE_FORMAT = LOGGING_CONFIG['date_format']
    LOG_MAX_BYTES = LOGGING_CONFIG['max_bytes']
    LOG_BACKUP_COUNT = LOGGING_CONFIG['backup_count']
    CONSOLE_LOGGING_ENABLED = (
        LOGGING_CONFIG['console_logging_enabled']
        if LOGGING_CONFIG['console_logging_enabled'] is not None
        else True
    )
    LOG_DIR = LOGGING_CONFIG['log_dir']
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    LOG_FILE_PATH = LOGGING_CONFIG['file_path']

    # Helper to generate a filename with the current PID inserted either in place of {pid} or before file extension.
    def insert_pid_into_filename(filename, pid=None):
        """
        Inserts the process PID into the filename.
        - If '{pid}' appears anywhere in filename, it is replaced.
        - Otherwise, _{pid} is inserted before the extension.
        - Example: 'foo_{pid}.log' -> 'foo_1234.log'
        - Example: 'bar.log' -> 'bar_1234.log'
        """
        if pid is None:
            pid = os.getpid()
        base, ext = os.path.splitext(filename)
        if '{pid}' in filename:
            return filename.replace('{pid}', str(pid))
        else:
            return f"{base}_{pid}{ext}"

    # The conversation log file will always include the process PID in the filename.
    conversation_log_filename = LOGGING_CONFIG['conversation_log_filename']
    pid_injected_conversation_filename = insert_pid_into_filename(conversation_log_filename, os.getpid())
    CONVERSATION_LOG_FILENAME = os.path.join(LOG_DIR, f"{STARTUP_TIME}_{pid_injected_conversation_filename}")

    CONVERSATION_LOG_FILE = open(CONVERSATION_LOG_FILENAME, "a")

def load_environment_globals():
    load_environment_variables()
    configure_globals()
    configure_logging_globals()

def start_logging():
    configure_logging()

def configure_subsystems():
    from monitor.core.commands import load_public_interactive_commands
    configure_rate_limiter(logger, MODEL_MAX_TPM, RATE_LIMITING_CONFIG['window_seconds'], RATE_LIMITING_CONFIG['safety_factor'])
    load_public_interactive_commands(PUBLIC_COMMANDS_PATH)
    configure_redis_utils(REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_MAX_RETRIES, REDIS_RETRY_INTERVAL)
    load_user_preferences(PREFERENCE_PROMPT_FILE)
    configure_tools()
    configure_external_services(ARTIFACT_SERVER, CODE_LENS_HOST, CODE_LENS_PORT, JOKES_FILE)
    configure_protocol_engine()

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
        max_tpm_tier = model_max_tpm.get(mapped_key, 30000)     # 1
        tpm_mapping = model_tpm_mapping.get(mapped_key, None)   # xai_model_tpm_tier
        MODEL_MAX_TPM = tpm_mapping.get(max_tpm_tier)
        CONVERSATION_MAX_SIZE = conversation_history_mapping.get(mapped_key, 50)

    logger.warning(
        f"set_model: Activated model '{MODEL}' "
        f"(CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW}, OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW}, "
        f"MAX_TPM={MODEL_MAX_TPM}, CONVERSATION_MAX_SIZE={CONVERSATION_MAX_SIZE})"
    )

def update_model():
    yaml_config = load_yaml_config()
    xai_tpm_tier = xai_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]
    openai_tpm_tier = openai_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]
    anthropic_tpm_tier = anthropic_model_tpm_tier[yaml_config.get("MODEL_INPUT_TIER", 1)]
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
