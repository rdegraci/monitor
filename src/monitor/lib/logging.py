"""
Centralized logging configuration for the application.

This module configures logging by reading logging-related globals defined in monitor.config
(e.g., LOGGING_LEVEL, LOG_FILE_PATH, LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES,
LOG_BACKUP_COUNT, CONSOLE_LOGGING_ENABLED, LOG_ENCODING). These globals may be absent; in
that case documented defaults are applied and a warning is emitted.

EXPECTED GLOBALS in monitor.config:
    - LOGGING_LEVEL: Logging level as string or int, e.g., 'INFO', 'DEBUG', or 20, etc.
    - LOG_FILE_PATH: String path to the log file. This path may contain '{pid}' which will
      be replaced with the current process PID. If not present, the PID will be injected by
      default before the file extension.

OPTIONAL GLOBALS (defaults will be used if not provided):
    - LOG_FORMAT: '%(asctime)s %(levelname)s %(name)s %(message)s'
    - LOG_DATE_FORMAT: '%Y-%m-%d %H:%M:%S'
    - LOG_MAX_BYTES: 5 * 1024 * 1024 (5 MB)
    - LOG_BACKUP_COUNT: 3
    - CONSOLE_LOGGING_ENABLED: Bool, enable console logging. Default: True
    - LOG_ENCODING: 'utf-8'

Any missing expected globals will result in a warning and use of safest sensible defaults.
This file does not read config.yaml directly. It consumes logging-related globals from
monitor.config and falls back to a small built-in default logging configuration when those
globals are missing or empty.

No test code or run-on-main logic will be present in this file.
"""

import atexit
import logging
import os
from logging.handlers import RotatingFileHandler

from monitor._stubs import appdirs

from monitor import config

DEFAULT_LOGGING = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'date_format': '%Y-%m-%d %H:%M:%S',
    'log_dir': os.path.join(appdirs.user_config_dir('monitor'), 'logs'),
    'app_log_filename': 'app.log',
    'conversation_log_filename': 'conversation.log',
    'console_logging_enabled': True,
    'max_bytes': 5 * 1024 * 1024,  # 5 MB
    'backup_count': 3,
    'encoding': 'utf-8',
}

# Ensure file_path exists in DEFAULT_LOGGING to avoid KeyError in _load_logging_config.
DEFAULT_LOGGING['file_path'] = os.path.join(
    str(DEFAULT_LOGGING['log_dir']), str(DEFAULT_LOGGING['app_log_filename'])
)


def _load_logging_config():
    """
    Load the logging configuration dictionary.

    Returns:
        dict: A merged logging configuration dictionary combining config.py globals and defaults.
    """
    loaded_config = {}

    # Mapping of config keys to corresponding config.py global variable names.
    override_map = {
        'level': 'LOGGING_LEVEL',
        'file_path': 'LOG_FILE_PATH',
        'format': 'LOG_FORMAT',
        'date_format': 'LOG_DATE_FORMAT',
        'max_bytes': 'LOG_MAX_BYTES',
        'backup_count': 'LOG_BACKUP_COUNT',
        'console_logging_enabled': 'CONSOLE_LOGGING_ENABLED',
    }

    # Populate loaded_config with values from config.py globals if available, otherwise use defaults.
    for key, var in override_map.items():
        if hasattr(config, var):
            loaded_config[key] = getattr(config, var)
        else:
            loaded_config[key] = DEFAULT_LOGGING[key]
            logging.warning(
                f"Logging config: missing '{var}', using default '{DEFAULT_LOGGING[key]}'"
            )

    # LOG_ENCODING is optional and defaults silently to utf-8.
    loaded_config['encoding'] = getattr(config, 'LOG_ENCODING', DEFAULT_LOGGING['encoding'])

    # Ensure required settings are present; fallback to defaults if missing or empty.
    for required in ['level', 'file_path']:
        if loaded_config[required] is None or loaded_config[required] == '':
            logging.warning(
                f"Logging config: required variable '{required}' is missing or empty. Using default '{DEFAULT_LOGGING[required]}'"
            )
            loaded_config[required] = DEFAULT_LOGGING[required]

    return loaded_config


def _resolve_log_level(level):
    """
    Resolve a logging level specification into a numeric logging level.

    Args:
        level (str | int): Logging level provided as a string name (e.g., 'INFO', 'DEBUG')
            or an integer value.

    Returns:
        int: A valid numeric logging level constant. Defaults to logging.INFO if the input
        is unrecognized.
    """
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        s = level.strip().upper()
        if s.isdigit():
            try:
                return int(s)
            except Exception:
                pass
        mapping = {
            'CRITICAL': logging.CRITICAL,
            'FATAL': logging.CRITICAL,
            'ERROR': logging.ERROR,
            'WARNING': logging.WARNING,
            'WARN': logging.WARNING,
            'INFO': logging.INFO,
            'DEBUG': logging.DEBUG,
            'NOTSET': logging.NOTSET,
        }
        if s in mapping:
            return mapping[s]
    return logging.INFO


def _inject_pid_into_logfile_path(log_path, pid=None):
    """
    Inject current process PID into filename unless '{pid}' is already present.
    - If '{pid}' is in the path, replaces with str.format(pid=...).
    - If not present, inserts '_{pid}' before the extension.
    """
    if pid is None:
        try:
            pid = os.getpid()
        except Exception:
            pid = 0
    if '{pid}' in log_path:
        # User-supplied format string: substitute
        try:
            log_path = log_path.format(pid=pid)
        except Exception:
            # Fallback: just ignore formatting error, use raw string
            pass
    else:
        # Default: insert _{pid} before file extension
        dirname, filename = os.path.split(log_path)
        if '.' in filename:
            base, ext = filename.rsplit('.', 1)
            filename = f"{base}_{pid}.{ext}"
        else:
            filename = f"{filename}_{pid}"
        log_path = os.path.join(dirname, filename)
    return log_path


def _shutdown_logging_safely():
    """Shut down logging while stdlib modules are still available.

    This prevents late interpreter-finalization logging from hitting a
    RotatingFileHandler after parts of the ``os`` module have been cleared.
    """
    logging.shutdown()


def configure_logging():
    """
    Configure the root logger using logging-related globals from monitor.config.

    Missing fields are replaced with documented defaults and logged as warnings.
    The log file path includes the process PID: if the file path contains
    '{pid}', it is replaced; otherwise the PID is injected between the
    filename and extension automatically. This avoids file conflicts when
    running multiple instances.

    This function is idempotent and safe to call more than once. It removes
    all existing root handlers before reconfiguring them.

    Expected globals in monitor.config:
        - LOGGING_LEVEL (str | int)
        - LOG_FILE_PATH (str)
    Optional globals:
        - LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES, LOG_BACKUP_COUNT,
          CONSOLE_LOGGING_ENABLED, LOG_ENCODING
    """
    log_cfg = _load_logging_config()

    # --- Inject the current process PID into the log file path for uniqueness ---
    # If the configured path has '{pid}', substitute; else inject _{pid} before file extension.
    log_cfg['file_path'] = _inject_pid_into_logfile_path(log_cfg['file_path'])

    formatter = logging.Formatter(log_cfg['format'], log_cfg['date_format'])

    root_logger = logging.getLogger()
    resolved_level = _resolve_log_level(log_cfg['level'])
    # Keep the root logger permissive so the file handler can capture every
    # record, while the console handler applies the user-facing WARNING filter.
    root_logger.setLevel(logging.DEBUG)

    # Remove all existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Ensure log file directory exists
    try:
        log_dir = os.path.dirname(log_cfg['file_path'])
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_cfg['file_path'],
            maxBytes=log_cfg['max_bytes'],
            backupCount=log_cfg['backup_count'],
            encoding=log_cfg.get('encoding', 'utf-8'),
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to set up file logging: {e}")
        raise

    logging.getLogger("LiteLLM").setLevel(logging.WARNING)

    # Console logging if enabled
    if log_cfg.get('console_logging_enabled', True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Log INFO after all handlers are added so both console and file see this message
    root_logger.info(f"Application log file initialized at: {os.path.abspath(log_cfg['file_path'])}")


def get_logger(name):
    """
    Returns a logger configured for the specified module name.

    Args:
        name (str): Name of the module requesting the logger

    Returns:
        Logger: Configured logger instance
    """
    return logging.getLogger(name)


atexit.register(_shutdown_logging_safely)
