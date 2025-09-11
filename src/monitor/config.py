# CONFIG FILE IO POLICY:
# All file and directory operations that perform IO (e.g. open, os.makedirs, os.path.exists) must be wrapped in try/except blocks.
# Any IO failure must be logged via logger.error with exc_info=True for full stacktrace, and an exception must be raised to abort execution.
# Failures in reading/loading config do NOT return defaults or fall back: they are fatal errors.
# Path manipulations not touching disk (e.g. os.path.expanduser, os.path.join) may be left unwrapped unless they interact with the filesystem.
# Environment variable assignments (os.environ, etc.) are not IO and do not need exception wrapping.
# The intent: All config file IO errors are logged and detected immediately, never silently handled or ignored.

import yaml
import os
import time
import logging
import json
import appdirs
import importlib.resources
import uuid
import shutil

from dotenv import find_dotenv, load_dotenv

from monitor.lib.rate_limiter import configure_rate_limiter
from monitor.core.tools import configure_tools
from monitor.core.llm_responses_adapter import configure_responses_adapter
from monitor.lib.redis_utils import configure_redis_utils
from monitor.lib.preferences import load_user_preferences_prompt
from monitor.lib.external_services import configure_external_services
from monitor.lib.protocol_engine import configure_protocol_engine
from monitor.lib.logging import configure_logging
from monitor.lib.keyboard import configure_voice_to_text

logger = logging.getLogger(__name__)

def _safe_expanduser(path):
    """
    Safely expand user path (os.path.expanduser) only for str inputs.
    - If path is None: returns None.
    - If path is a str: returns os.path.expanduser(path), raising RuntimeError (chained) on expansion errors.
    - If path is not a str: returns None (coerce non-string values to None) and logs a warning indicating coercion.
    Any unexpected exception is logged and re-raised as RuntimeError to abort execution.
    """
    try:
        if path is None:
            return None
        if not isinstance(path, str):
            logger.warning(f"_safe_expanduser: Coercing non-string path {path!r} to None.")
            return None
        try:
            return os.path.expanduser(path)
        except Exception as e:
            logger.error(f"Path expansion failed for path '{path}': {e}", exc_info=True)
            raise RuntimeError(f"Error expanding path: {path}") from e
    except Exception as e:
        logger.error(f"Unexpected error in _safe_expanduser for path '{path}': {e}", exc_info=True)
        raise RuntimeError("Unexpected error in _safe_expanduser") from e

def find_config_file(filename):
    """
    Search for 'filename' in system (site) config dir first, then in user config dir.
    If found in both, return the user config dir version.
    If found only in site config dir, return that.
    If not found in either, raise FileNotFoundError.
    All file/directory existence checks are IO and errors are always logged and raised.
    """
    try:
        site_config_dir = appdirs.site_config_dir("monitor")
        user_config_dir = appdirs.user_config_dir("monitor")
        site_path = os.path.join(site_config_dir, filename)
        user_path = os.path.join(user_config_dir, filename)

        try:
            user_exists = os.path.exists(user_path)
        except Exception as e:
            logger.error(f"File existence check failed for {user_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to check if user config exists: {user_path}") from e

        try:
            site_exists = os.path.exists(site_path)
        except Exception as e:
            logger.error(f"File existence check failed for {site_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to check if site config exists: {site_path}") from e

        if user_exists:
            return user_path
        elif site_exists:
            return site_path
        else:
            raise FileNotFoundError(
                f"{filename} not found in either {user_path} or {site_path}"
            )
    except Exception as e:
        logger.error(f"Error locating config file {filename}: {e}", exc_info=True)
        raise

# ===== New helper for model_config.json loading and validation =====

def _load_and_validate_model_config():
    """
    Loads and validates the monitor/model_config.json file. Returns a dict with the expected keys.
    All IO errors are logged (fatal) and abort module import.
    """
    # Build the path to the model_config.json (look in user config, then site config)
    config_filename = "model_config.json"
    try:
        try:
            config_path = find_config_file(config_filename)
        except FileNotFoundError as fnf:
            # Attempt to copy the packaged default into the user config dir
            try:
                user_config_dir = appdirs.user_config_dir("monitor")
            except Exception as e:
                logger.error(f"Failed to determine user config dir for monitor: {e}", exc_info=True)
                raise RuntimeError("Cannot determine user config dir for monitor") from e

            try:
                os.makedirs(user_config_dir, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create user config directory {user_config_dir}: {e}", exc_info=True)
                raise RuntimeError(f"Failed to create user config directory: {user_config_dir}") from e

            dest_path = os.path.join(user_config_dir, config_filename)
            try:
                # Attempt to open the packaged default resource and copy it to dest_path
                try:
                    with importlib.resources.open_binary('monitor', config_filename) as src:
                        try:
                            with open(dest_path, 'wb') as dst:
                                try:
                                    shutil.copyfileobj(src, dst)
                                except Exception as e:
                                    logger.error(f"Failed to write default {config_filename} to {dest_path}: {e}", exc_info=True)
                                    raise RuntimeError(f"Failed to write default model config to {dest_path}") from e
                        except Exception as e:
                            logger.error(f"Failed to open destination file {dest_path} for writing: {e}", exc_info=True)
                            raise RuntimeError(f"Failed to open destination model config file: {dest_path}") from e
                except FileNotFoundError as e:
                    logger.error(f"Packaged default {config_filename} not found in package resources: {e}", exc_info=True)
                    raise RuntimeError(f"Packaged default model_config.json not found in package resources") from e
                except Exception as e:
                    logger.error(f"Failed to access packaged default {config_filename}: {e}", exc_info=True)
                    raise RuntimeError("Failed to access packaged default model_config.json") from e
            except Exception:
                # Errors already logged and wrapped above; re-raise to outer handler
                raise

            logger.info(f"Copied default model_config.json to {dest_path}")
            config_path = dest_path
        except Exception as e:
            logger.error(f"Unable to locate {config_filename}: {e}", exc_info=True)
            raise RuntimeError(f"Cannot find model config: {config_filename}") from e

    except Exception as e:
        logger.error(f"Error preparing model config path for {config_filename}: {e}", exc_info=True)
        raise

    # Attempt reading and parsing JSON
    try:
        with open(config_path, "r") as f:
            try:
                model_config = json.load(f)
            except json.JSONDecodeError as je:
                logger.error(f"model_config.json is not valid JSON: {je}", exc_info=True)
                raise RuntimeError(f"Malformed JSON in {config_filename}") from je
    except Exception as e:
        logger.error(f"Failed to load {config_filename} from {config_path}: {e}", exc_info=True)
        raise RuntimeError(f"Cannot load model config file: {config_path}") from e

    # Validation and type conversions for int keys
    # List of top-level mapping keys to load and check
    mapping_keys = [
        "conversation_history_mapping",
        "context_window_mapping",
        "output_window_mapping",
        "model_max_tpm",
        "openai_model_tpm_tier",
        "anthropic_model_tpm_tier",
        "xai_model_tpm_tier",
        "google_model_tpm_tier",
        "model_mapping",
    ]
    # Ensure these all exist in the JSON
    for key in mapping_keys:
        if key not in model_config:
            logger.error(f"{config_filename} missing required key: '{key}'")
            raise RuntimeError(f"{config_filename} missing required key: '{key}'")

    # For all *_tpm_tier mappings, convert keys to int
    for tier_name in [
        "openai_model_tpm_tier",
        "anthropic_model_tpm_tier",
        "xai_model_tpm_tier",
        "google_model_tpm_tier",
    ]:
        val = model_config[tier_name]
        if not isinstance(val, dict):
            logger.error(f"Key '{tier_name}' in {config_filename} must be a dictionary")
            raise RuntimeError(f"{tier_name} in {config_filename} must be a dict")
        # Convert string keys that are numeric to int, keep non-numeric keys as is
        int_val = {}
        for k, v in val.items():
            try:
                int_key = int(k)
            except Exception:
                int_key = k
            int_val[int_key] = v
        model_config[tier_name] = int_val

    # Optional: model_tpm_mapping
    if "model_tpm_mapping" in model_config:
        mtm = model_config["model_tpm_mapping"]
        if not isinstance(mtm, dict):
            logger.error(f"Key 'model_tpm_mapping' in {config_filename} must be a dictionary if present")
            raise RuntimeError(f"model_tpm_mapping in {config_filename} must be a dict if present")
        coerced_mtm = {}
        for mk, mv in mtm.items():
            if isinstance(mv, dict):
                # Coerce numeric-like keys to int
                int_val = {}
                for k, v in mv.items():
                    try:
                        int_key = int(k)
                    except Exception:
                        int_key = k
                    int_val[int_key] = v
                coerced_mtm[mk] = int_val
            elif isinstance(mv, str):
                # Leave as it is; will be resolved to provider tier dict later
                coerced_mtm[mk] = mv
            else:
                logger.error(f"Invalid value type for model_tpm_mapping['{mk}'] in {config_filename}: expected dict or str, got {type(mv).__name__}")
                raise RuntimeError(f"Invalid value for model_tpm_mapping['{mk}']: must be dict or str")
        model_config["model_tpm_mapping"] = coerced_mtm

    # For each mapping that is model_key -> int or str, just check they're dicts
    for k in ["conversation_history_mapping", "context_window_mapping", "output_window_mapping", "model_max_tpm", "model_mapping"]:
        if not isinstance(model_config[k], dict):
            logger.error(f"Key '{k}' in {config_filename} must be a dictionary")
            raise RuntimeError(f"{k} in {config_filename} must be a dict")

    return model_config

# ===== Initialize (on import) model mappings using new loader =====

_MODEL_CONFIG_CACHE=None
conversation_history_mapping=None
context_window_mapping=None
output_window_mapping=None
model_max_tpm=None
openai_model_tpm_tier=None
anthropic_model_tpm_tier=None
xai_model_tpm_tier=None
google_model_tpm_tier=None
model_tpm_mapping=None
MODEL_MAPPING=None 

def load_model_config():
    global _MODEL_CONFIG_CACHE
    global conversation_history_mapping, context_window_mapping, output_window_mapping
    global model_max_tpm, openai_model_tpm_tier, anthropic_model_tpm_tier, xai_model_tpm_tier
    global google_model_tpm_tier, model_tpm_mapping, MODEL_MAPPING
    try:
        _MODEL_CONFIG_CACHE = _load_and_validate_model_config()
        conversation_history_mapping = _MODEL_CONFIG_CACHE["conversation_history_mapping"]
        context_window_mapping = _MODEL_CONFIG_CACHE["context_window_mapping"]
        output_window_mapping = _MODEL_CONFIG_CACHE["output_window_mapping"]
        model_max_tpm = _MODEL_CONFIG_CACHE["model_max_tpm"]
        openai_model_tpm_tier = _MODEL_CONFIG_CACHE["openai_model_tpm_tier"]
        anthropic_model_tpm_tier = _MODEL_CONFIG_CACHE["anthropic_model_tpm_tier"]
        xai_model_tpm_tier = _MODEL_CONFIG_CACHE["xai_model_tpm_tier"]
        google_model_tpm_tier = _MODEL_CONFIG_CACHE["google_model_tpm_tier"]
        MODEL_MAPPING = _MODEL_CONFIG_CACHE["model_mapping"]

        # Resolve optional data-driven model_tpm_mapping if provided; otherwise, fallback to hard-coded mapping.
        raw_model_tpm_mapping = _MODEL_CONFIG_CACHE.get("model_tpm_mapping")
        if raw_model_tpm_mapping is not None:
            if not isinstance(raw_model_tpm_mapping, dict):
                logger.error(f"model_tpm_mapping in model_config.json is not a dict (type: {type(raw_model_tpm_mapping).__name__})")
                raise RuntimeError("model_tpm_mapping must be a dict")
            provider_map = {
                'openai': openai_model_tpm_tier,
                'anthropic': anthropic_model_tpm_tier,
                'xai': xai_model_tpm_tier,
                'google': google_model_tpm_tier,
            }
            resolved_mapping = {}
            for mk, mv in raw_model_tpm_mapping.items():
                if isinstance(mv, str):
                    if mv not in provider_map:
                        logger.error(f"Invalid provider reference '{mv}' for model_tpm_mapping['{mk}']; expected one of {list(provider_map.keys())}")
                        raise RuntimeError(f"Invalid provider reference for model_tpm_mapping['{mk}']: {mv}")
                    resolved_mapping[mk] = provider_map[mv]
                elif isinstance(mv, dict):
                    # Already coerced by loader
                    resolved_mapping[mk] = mv
                else:
                    logger.error(f"Invalid value type for model_tpm_mapping['{mk}']: expected str or dict, got {type(mv).__name__}")
                    raise RuntimeError(f"Invalid value for model_tpm_mapping['{mk}']")
            model_tpm_mapping = resolved_mapping
            logger.info("Using data-driven model_tpm_mapping from model_config.json")
        else:
            # The rest of the mappings remain hardcoded (backward-compatible fallback)
            model_tpm_mapping = {
                "sonnet4": anthropic_model_tpm_tier,
                "sonnet35": anthropic_model_tpm_tier,
                "sonnet37": anthropic_model_tpm_tier,
                "4o-mini": openai_model_tpm_tier,
                "gpt4o": openai_model_tpm_tier,
                "o3-mini": openai_model_tpm_tier,
                "gpt41": openai_model_tpm_tier,
                "gpt5": openai_model_tpm_tier,
                "o3": openai_model_tpm_tier,
                "grok3": xai_model_tpm_tier,
                "grok4": xai_model_tpm_tier,
                "gemini20": google_model_tpm_tier,
                "gpt5-mini": openai_model_tpm_tier,
            }
            logger.warning("Using fallback hard-coded model_tpm_mapping (no data-driven mapping provided)")
    except Exception as _model_config_e:
        # Already logged in loader, but abort import
        raise

def get_model_reverse_mapping():
    """
    Returns a reverse mapping of MODEL_MAPPING: from full model string -> shorthand key (as string).
    Caveat: If multiple shorthand keys alias to the same model string, only the last alias key is kept in the mapping.
    Logs a warning for each duplicate (same model string for multiple keys), listing the duplicate model and conflicting shorthand keys.
    """
    if not isinstance(MODEL_MAPPING, dict):
        logger.warning(f"MODEL_MAPPING is not a dict (type: {type(MODEL_MAPPING).__name__}); returning empty reverse mapping.")
        return {}

    reverse = {}
    value_to_keys = {}
    for k, v in MODEL_MAPPING.items():
        if v in value_to_keys:
            value_to_keys[v].append(k)
        else:
            value_to_keys[v] = [k]
        reverse[v] = k
    for v, keys in value_to_keys.items():
        if len(keys) > 1:
            logger.warning(f"Duplicate model alias detected: model string '{v}' is mapped to multiple shorthand keys {keys}")
    return reverse


MODEL=None
MODEL_CONTEXT_WINDOW=None 
MODEL_OUTPUT_WINDOW=None
MODEL_INPUT_TIER=None
MODEL_MAX_TPM=None
MODEL_INPUT_WINDOW=None 
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
ENABLE_AUTO_SUMMARIZE_ON_LIMIT=None
SESSION_ID=None
SUMMARY_TWITCH=None
SUMMARY_LINKEDIN=None
SUMMARY_TWITTER=None
SERVER_MODE=None
RESPONSES_API=None

def configure_globals():
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_MAX_TPM, MODEL_INPUT_TIER, MODEL_INPUT_WINDOW
    global CONVERSATION_MAX_SIZE, RATE_LIMITING_CONFIG, MEMORY_SERVICES, STARTUP_TIME
    global HISTORY_FILE, MAX_TOKEN_COUNT, OLD_MAX_TOKEN_COUNT
    global MACRO_DELIMITER_OPEN, MACRO_DELIMITER_CLOSE, MACRO_DELIMITER_ESCAPE, MACRO_FILE_PATH
    global SUMMARIZATION_CONFIG
    global EXTERNAL_SERVICES, MEMORY_SERVICES, OLLAMA_CONFIG
    global PUBLIC_COMMANDS_PATH, REDIS_HOST, PREFERENCE_PROMPT_FILE
    global REASONING_MODEL_PREFIX, REASONING_EFFORT, REASONING_MAX_COMPLETION_TOKENS
    global ARTIFACT_SERVER, CODE_LENS_HOST, CODE_LENS_PORT, JOKES_FILE, DIRECTIVES_DIR
    global ECS_HOST, ECS_PORT, ENABLE_AUTO_SUMMARIZE_ON_LIMIT, SESSION_ID
    global SUMMARY_TWITCH, SUMMARY_LINKEDIN, SUMMARY_TWITTER, SERVER_MODE, RESPONSES_API

    SESSION_ID = str(uuid.uuid4())

    yaml_config = load_yaml_config()

    MODEL = yaml_config.get("MODEL")
    MODEL_CONTEXT_WINDOW = yaml_config.get("MODEL_CONTEXT_WINDOW")
    MODEL_OUTPUT_WINDOW = yaml_config.get("MODEL_OUTPUT_WINDOW")

    # Safely compute input window
    MODEL_INPUT_WINDOW = None
    if isinstance(MODEL_CONTEXT_WINDOW, int) and isinstance(MODEL_OUTPUT_WINDOW, int):
        iw = MODEL_CONTEXT_WINDOW - MODEL_OUTPUT_WINDOW
        if iw > 0:
            MODEL_INPUT_WINDOW = iw
        else:
            logger.warning(
                f"Computed MODEL_INPUT_WINDOW <= 0 (context={MODEL_CONTEXT_WINDOW}, output={MODEL_OUTPUT_WINDOW}); disabling input budgeting"
            )
    else:
        logger.debug(
            f"Skipping MODEL_INPUT_WINDOW computation: MODEL_CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW!r}, MODEL_OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW!r}"
        )

    # MODEL_MAX_TPM, if it exists, will override the MODEL_INPUT_TIER
    # otherwise, MODEL_MAX_TPM will be set via MODEL_INPUT_TIER
    MODEL_INPUT_TIER = yaml_config.get("MODEL_INPUT_TIER")
    MODEL_MAX_TPM = yaml_config.get("MODEL_MAX_TPM")
    if MODEL_MAX_TPM is None:
        # Guarded lookups: ensure reverse mapping and model_tpm_mapping are dicts before accessing,
        # and fall back to None if any lookup fails. This prevents runtime errors during startup.
        try:
            reversed_model = get_model_reverse_mapping().get(MODEL)
        except Exception as e:
            logger.error(f"Failed to get reverse model mapping for MODEL '{MODEL}': {e}", exc_info=True)
            reversed_model = None

        model_tpm = None
        if isinstance(model_tpm_mapping, dict) and reversed_model in model_tpm_mapping:
            model_tpm = model_tpm_mapping.get(reversed_model)
        if isinstance(model_tpm, dict) and MODEL_INPUT_TIER in model_tpm:
            MODEL_MAX_TPM = model_tpm.get(MODEL_INPUT_TIER)
        else:
            # Could not determine MODEL_MAX_TPM from mappings; set to None to indicate unknown.
            logger.warning(
                f"Could not determine MODEL_MAX_TPM for MODEL='{MODEL}', reversed_model='{reversed_model}', "
                f"MODEL_INPUT_TIER='{MODEL_INPUT_TIER}'. MODEL_MAX_TPM set to None."
            )
            MODEL_MAX_TPM = None

    CONVERSATION_MAX_SIZE = yaml_config.get("CONVERSATION_MAX_SIZE")
    RATE_LIMITING_CONFIG = yaml_config.get('rate_limiting', {
     'safety_factor': 0.6,
     'window_seconds': 60,
    })
    STARTUP_TIME = time.strftime("%Y_%m_%d_%H_%M")
    

    history_config = yaml_config.get('history', {})
    HISTORY_FILE = _safe_expanduser(history_config.get('file', '~/.config/monitor/chat_history'))
    MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
    OLD_MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW

    macro_delims = yaml_config.get('macro_delimiters', {})
    MACRO_DELIMITER_OPEN = macro_delims.get('open', '(')
    MACRO_DELIMITER_CLOSE = macro_delims.get('close', ')')
    MACRO_DELIMITER_ESCAPE = macro_delims.get('escape', '\\')
    MACRO_FILE_PATH = _safe_expanduser(yaml_config.get("MACRO_FILE"))

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
    SUMMARY_TWITCH = yaml_config.get('SUMMARY_TWITCH', False)
    SUMMARY_LINKEDIN = yaml_config.get('SUMMARY_LINKEDIN', False)
    SUMMARY_TWITTER = yaml_config.get('SUMMARY_TWITTER', False)

    MEMORY_SERVICES = yaml_config.get('MEMORY_SERVICES', False)
    OLLAMA_CONFIG = yaml_config.get('ollama', {
        'host': 'http://localhost:11434/api/generate',
        'model': 'llama3.1:latest'
    })

    public_commands_path_cfg = yaml_config.get("PUBLIC_COMMANDS_PATH")
    PUBLIC_COMMANDS_PATH = _safe_expanduser(public_commands_path_cfg)
    REDIS_HOST = yaml_config.get("REDIS_HOST", "localhost")

    PREFERENCE_PROMPT_FILE = _safe_expanduser(yaml_config.get("PREFERENCE_PROMPT_FILE"))

    REASONING_MODEL_PREFIX = yaml_config.get('REASONING_MODEL_PREFIX')
    REASONING_EFFORT = yaml_config.get('REASONING_EFFORT', "medium")
    REASONING_MAX_COMPLETION_TOKENS = yaml_config.get('REASONING_MAX_COMPLETION_TOKENS', 25000)
    RESPONSES_API = yaml_config.get('RESPONSES_API')

    ARTIFACT_SERVER = yaml_config.get('ARTIFACT_SERVER', 'http://localhost:2323/')
    CODE_LENS_HOST = yaml_config.get('CODE_LENS_HOST', 'localhost')
    CODE_LENS_PORT = yaml_config.get('CODE_LENS_PORT', '5000')

    # Global list to store jokes told previously
    JOKES_FILE = _safe_expanduser(yaml_config.get('JOKES_FILE'))

    DIRECTIVES_DIR = _safe_expanduser(yaml_config.get('DIRECTIVES_DIR'))
    if DIRECTIVES_DIR:
        os.environ['DIRECTIVES_DIR'] = DIRECTIVES_DIR

    ECS_HOST = yaml_config.get('ECS_HOST')
    ECS_PORT = yaml_config.get('ECS_PORT')
    ENABLE_AUTO_SUMMARIZE_ON_LIMIT = yaml_config.get('ENABLE_AUTO_SUMMARIZE_ON_LIMIT')

    SERVER_MODE = yaml_config.get('SERVER_MODE')

LOGGING_CONFIG=None 
LOGGING_LEVEL=None 
LOG_FORMAT=None 
LOG_DATE_FORMAT=None 
LOG_MAX_BYTES=None
LOG_BACKUP_COUNT=None 
CONSOLE_LOGGING_ENABLED=None 
LOG_DIR=None
LOG_FILE_PATH=None
LOG_ENCODING=None
CONVERSATION_LOG_FILENAME=None 
CONVERSATION_LOG_FILE=None 

def configure_logging_globals():
    global LOGGING_CONFIG, LOGGING_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES, LOG_BACKUP_COUNT
    global CONSOLE_LOGGING_ENABLED, LOG_DIR, LOG_FILE_PATH, CONVERSATION_LOG_FILENAME, CONVERSATION_LOG_FILE

    try:
        LOGGING_CONFIG = get_logging_config()
    except Exception as e:
        logger.error(f"Failed to get logging config: {e}", exc_info=True)
        raise

    if not LOGGING_CONFIG['log_dir']:
        raise RuntimeError("LOG_DIR (log_dir) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['app_log_filename']:
        raise RuntimeError("APP_LOG_FILENAME (app_log_filename) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['format']:
        raise RuntimeError("LOG_FORMAT (format) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['level']:
        raise RuntimeError("LOGGING_LEVEL (level) is missing in app.yaml and no default could be set.")
    if not LOGGING_CONFIG['encoding']:
        raise RuntimeError("LOG_ENCODING (encoding) is missing in app.yaml and no default could be set.")

    LOG_ENCODING = LOGGING_CONFIG.get("encoding")
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
    try:
        if not os.path.exists(LOG_DIR):
            try:
                os.makedirs(LOG_DIR)
            except Exception as e:
                logger.error(f"Failed to create log directory {LOG_DIR}: {e}", exc_info=True)
                raise RuntimeError(f"Failed to create log directory: {LOG_DIR}") from e
    except Exception as e:
        logger.error(f"Error checking existence of log dir {LOG_DIR}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to check log dir existence: {LOG_DIR}") from e
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
    try:
        CONVERSATION_LOG_FILENAME = os.path.join(LOG_DIR, f"{STARTUP_TIME}_{pid_injected_conversation_filename}")
    except Exception as e:
        logger.error(f"Failed joining conversation log filename: {e}", exc_info=True)
        raise RuntimeError("Failed to create conversation log file name") from e
    try:
        CONVERSATION_LOG_FILE = open(CONVERSATION_LOG_FILENAME, "a")
    except Exception as e:
        logger.error(f"Failed to open conversation log file: {CONVERSATION_LOG_FILENAME}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to open conversation log file: {CONVERSATION_LOG_FILENAME}") from e

def load_environment_globals():
    load_environment_variables()
    configure_globals()
    configure_logging_globals()
    
def start_logging():
    configure_logging()

def configure_subsystems():
    from monitor.core.commands import load_public_interactive_commands
    from monitor.core.modes import configure_consultant

    configure_rate_limiter(logger, MODEL_MAX_TPM, RATE_LIMITING_CONFIG['window_seconds'], RATE_LIMITING_CONFIG['safety_factor'])

    # Guarded loading of public interactive commands: skip if PUBLIC_COMMANDS_PATH is None
    if PUBLIC_COMMANDS_PATH is None:
        logger.warning("PUBLIC_COMMANDS_PATH is None; skipping load_public_interactive_commands.")
    else:
        try:
            load_public_interactive_commands(PUBLIC_COMMANDS_PATH)
        except Exception as e:
            logger.error(f"Failed to load public interactive commands from {PUBLIC_COMMANDS_PATH}: {e}", exc_info=True)

    # Guarded loading of user preferences prompt: skip if PREFERENCE_PROMPT_FILE is None
    if PREFERENCE_PROMPT_FILE is None:
        logger.warning("PREFERENCE_PROMPT_FILE is None; skipping load_user_preferences_prompt.")
    else:
        try:
            load_user_preferences_prompt(PREFERENCE_PROMPT_FILE)
        except Exception as e:
            logger.error(f"Failed to load user preferences prompt from {PREFERENCE_PROMPT_FILE}: {e}", exc_info=True)

    configure_redis_utils(REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_MAX_RETRIES, REDIS_RETRY_INTERVAL)
    configure_tools()

    # configure_external_services can fail due to various non-fatal issues; log errors and continue.
    try:
        configure_external_services(ARTIFACT_SERVER, CODE_LENS_HOST, CODE_LENS_PORT, JOKES_FILE)
    except Exception as e:
        logger.error(f"Error configuring external services: {e}", exc_info=True)
        # Continue execution despite external services configuration failure.

    configure_protocol_engine()
    configure_consultant()
    configure_voice_to_text()
    configure_responses_adapter()

def set_model(model_key: str) -> bool:
    """
    Changes the active model configuration at runtime.

    Behavior:
    - Recognizes either a shorthand key present in MODEL_MAPPING keys or a full model string present in MODEL_MAPPING values.
    - If MODEL_MAPPING is missing, not a dict, or empty, logs a warning and returns False without changing any globals.
    - If the provided model_key is unknown, logs a warning listing the unknown key and available keys, returns False, and does not modify any globals (including not clearing CONVERSATION_HISTORY).
    - On success, sets MODEL to the resolved full model string and derives related settings from context_window_mapping, output_window_mapping, conversation_history_mapping, model_max_tpm, and model_tpm_mapping using the shorthand key. If model_max_tpm or model_tpm_mapping lacks the needed entries, sets MODEL_MAX_TPM to None.
    - Sets MAX_TOKEN_COUNT accordingly, resets TOTAL_TOKEN_COUNT to 0, clears CONVERSATION_HISTORY, logs an info summary, and returns True.
    """
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_MAX_TPM, CONVERSATION_MAX_SIZE, MAX_TOKEN_COUNT, TOTAL_TOKEN_COUNT
    global CONVERSATION_HISTORY

    # Validate MODEL_MAPPING
    if not isinstance(MODEL_MAPPING, dict) or not MODEL_MAPPING:
        logger.warning("set_model: MODEL_MAPPING is not available or is empty; cannot set model.")
        return False

    mapped_key = None
    model_full = None

    if model_key in MODEL_MAPPING:
        mapped_key = model_key
        model_full = MODEL_MAPPING[model_key]
    elif model_key in MODEL_MAPPING.values():
        mapped_key = next((k for k, v in MODEL_MAPPING.items() if v == model_key), None)
        model_full = model_key if mapped_key is not None else None
    else:
        available = sorted(MODEL_MAPPING.keys())
        logger.warning(f"set_model: Unknown model key '{model_key}'. Available keys: {available}")
        return False

    if mapped_key is None or model_full is None:
        available = sorted(MODEL_MAPPING.keys())
        logger.warning(f"set_model: Could not resolve model for key '{model_key}'. Available keys: {available}")
        return False

    MODEL = model_full

    MODEL_CONTEXT_WINDOW = context_window_mapping.get(mapped_key) if isinstance(context_window_mapping, dict) else None
    MODEL_OUTPUT_WINDOW = output_window_mapping.get(mapped_key) if isinstance(output_window_mapping, dict) else None

    max_tpm_tier = model_max_tpm.get(mapped_key) if isinstance(model_max_tpm, dict) else None
    tpm_mapping = model_tpm_mapping.get(mapped_key) if isinstance(model_tpm_mapping, dict) else None
    MODEL_MAX_TPM = tpm_mapping.get(max_tpm_tier) if isinstance(tpm_mapping, dict) and (max_tpm_tier in tpm_mapping if isinstance(tpm_mapping, dict) else False) else None

    CONVERSATION_MAX_SIZE = conversation_history_mapping.get(mapped_key) if isinstance(conversation_history_mapping, dict) else None

    MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
    TOTAL_TOKEN_COUNT = 0

    if isinstance(CONVERSATION_HISTORY, list):
        CONVERSATION_HISTORY.clear()
    else:
        CONVERSATION_HISTORY = []

    logger.info(
        f"set_model: Activated model '{MODEL}' "
        f"(CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW}, OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW}, "
        f"MAX_TPM={MODEL_MAX_TPM}, CONVERSATION_MAX_SIZE={CONVERSATION_MAX_SIZE}, "
        f"MAX_TOKEN_COUNT={MAX_TOKEN_COUNT}, TOTAL_TOKEN_COUNT={TOTAL_TOKEN_COUNT})"
    )

    return True

def _load_one_dotenv(dotenv_path, description=None, verbose=False):
    """
    Attempt to load a single .env file, logging success/failure. Used in load_environment_variables.
    Returns True if loaded, False otherwise.
    All file existence and load attempts are logged and exceptions are fatal.
    """
    try:
        if dotenv_path:
            try:
                dotenv_exists = os.path.exists(dotenv_path)
            except Exception as e:
                logger.error(f"Error checking .env existence at {dotenv_path}: {e}", exc_info=True)
                raise RuntimeError(f"Failed to check existence of dotenv file: {dotenv_path}") from e
            if dotenv_exists:
                try:
                    load_dotenv(dotenv_path, override=True)
                except Exception as e:
                    logger.error(f"Failed loading dotenv file at {dotenv_path}: {e}", exc_info=True)
                    raise RuntimeError(f"Failed loading dotenv: {dotenv_path}") from e
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
        else:
            if verbose:
                if description:
                    logger.info(f"{description} path is None.")
                else:
                    logger.info(".env file path is None.")
            return False
    except Exception as e:
        logger.error(f"Exception during loading dotenv file at {dotenv_path}: {e}", exc_info=True)
        raise

def load_environment_variables(verbose=False):
    """
    Loads environment variables from these .env files in this order (if present):
    1. .env discovered via find_dotenv (nearest up the directory tree from CWD)
    2. ~/.config/monitor/.env

    ~/.config/monitor/.env variables will override variables set by project .env.
    Logs .env loading for audit/debug; does not exit if missing (defaults/secrets may be used).
    Returns:
        dict: {"cwd_env_loaded": bool, "home_env_loaded": bool}
    All .env file IO errors are logged and abort with exception.
    """
    status = {"cwd_env_loaded": False, "home_env_loaded": False}
    try:
        cwd_dotenv_path = find_dotenv()
    except Exception as e:
        logger.error(f"Error finding project .env via find_dotenv: {e}", exc_info=True)
        raise RuntimeError("Failed during find_dotenv for project .env") from e
    try:
        status["cwd_env_loaded"] = _load_one_dotenv(cwd_dotenv_path, description="Project .env", verbose=verbose)
    except Exception as e:
        logger.error(f"Exception loading cwd .env file: {e}", exc_info=True)
        raise
    home_dotenv_path = os.path.expanduser(os.path.join("~", ".config/monitor", ".env"))
    try:
        status["home_env_loaded"] = _load_one_dotenv(home_dotenv_path, description="Home secrets .env", verbose=verbose)
    except Exception as e:
        logger.error(f"Exception loading home .env file: {e}", exc_info=True)
        raise

    if not status["cwd_env_loaded"] and not status["home_env_loaded"]:
        logger.warning("No .env files found/loaded: neither project .env nor ~/.config/monitor/.env was found. Falling back to defaults and system environment only.")
    return status

def load_yaml_config(file_path=None):
    """
    Load YAML configuration from a file.

    This function will load and parse a YAML configuration file. If file_path is None,
    the function will attempt to locate 'app.yaml' using find_config_file("app.yaml").
    All filesystem IO errors (finding, opening, reading, parsing) are logged via
    logger.error with exc_info=True and result in exceptions being raised to abort execution.

    Args:
        file_path (str | None): Path to the YAML file to load. If None, the function will
            try to discover 'app.yaml' via find_config_file.

    Returns:
        dict: Parsed YAML configuration mapping.

    Raises:
        RuntimeError: If the file cannot be found, opened, or parsed.
    """
    yaml_path = file_path
    try:
        if yaml_path is None:
            try:
                yaml_path = find_config_file("app.yaml")
            except Exception as e:
                logger.error(f"Unable to locate app.yaml: {e}", exc_info=True)
                raise RuntimeError("Cannot find app.yaml") from e
        try:
            with open(yaml_path) as f:
                try:
                    config = yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    logger.error(f"Error parsing YAML file: {exc}", exc_info=True)
                    raise RuntimeError(f"YAML parsing error in {yaml_path}: {exc}") from exc
        except FileNotFoundError as e:
            logger.error(f"Configuration file {yaml_path} not found.", exc_info=True)
            raise RuntimeError(f"Configuration file {yaml_path} not found.") from e
        except Exception as e:
            logger.error(f"Failed opening configuration file {yaml_path}: {e}", exc_info=True)
            raise RuntimeError(f"Open error for {yaml_path}: {e}") from e

        # Validate that the parsed YAML is a mapping (dict). If YAML is empty or not a dict,
        # treat this as a fatal configuration error.
        if config is None or not isinstance(config, dict):
            logger.error(f"YAML file {yaml_path} did not produce a mapping (dict). Parsed value: {config!r}")
            raise RuntimeError(f"YAML config {yaml_path} must contain a mapping at top level (got {type(config).__name__}).")

        return config
    except Exception as e:
        logger.error(f"Failed to load YAML config ({yaml_path}): {e}", exc_info=True)
        raise

def get_logging_config():
    """
    Retrieves logging configuration from the YAML config with sensible defaults.
    Directory creation is wrapped with exception handling.
    Any directory or file error is logged and aborts config loading.
    """
    try:
        config = load_yaml_config().get('logging', {})
    except Exception as e:
        logger.error(f"Error retrieving 'logging' config from YAML: {e}", exc_info=True)
        raise
    default_log_dir = os.path.join(os.path.expanduser("~"), ".config/monitor", "logs")
    try:
        log_dir = os.path.expanduser(config.get('log_dir', default_log_dir))
    except Exception as e:
        logger.error(f"Path expansion failed for log_dir: {e}", exc_info=True)
        raise RuntimeError("Error expanding log_dir path in logging config") from e
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create log directory {log_dir}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to create log directory {log_dir}: {e}") from e

    app_log_filename = config.get('app_log_filename', 'app.log')
    conversation_log_filename = config.get('conversation_log_filename', 'conversation.log')
    try:
        file_path = os.path.join(log_dir, f"{STARTUP_TIME}_{app_log_filename}")
    except Exception as e:
        logger.error(f"Path join failed for log file: {e}", exc_info=True)
        raise RuntimeError("Failed joining file path for log file") from e
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
