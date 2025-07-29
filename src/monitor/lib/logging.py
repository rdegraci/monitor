"""
Centralized logging configuration for the application.

This module sets up logging using a unified config.logging_config dictionary provided by config.py.
This dictionary should define all logging options, both required and optional.

REQUIRED FIELDS in config.logging_config:
    - 'level': Logging level as string, e.g., 'INFO', 'DEBUG', etc.
    - 'file_path': String path to the log file. This path may now contain '{pid}' which will be replaced with the current process PID. If not present, the PID will be injected by default before the file extension.

OPTIONAL FIELDS (defaults will be used if not provided):
    - 'format': Log formatting string. Default: '%(asctime)s %(levelname)s %(name)s %(message)s'
    - 'date_format': Format for log entry dates. Default: '%Y-%m-%d %H:%M:%S'
    - 'max_bytes': Integer, file size before rotation in bytes. Default: 5 * 1024 * 1024 (5 MB)
    - 'backup_count': Integer, how many rotated log files to keep. Default: 3
    - 'console_logging_enabled': Bool, enable console logging. Default: True
    - 'encoding': Encoding for log files. Default: 'utf-8'

Legacy fallback: If logging_config is not found, individual config variables
(LOGGING_LEVEL, LOG_FILE_PATH, etc.) will be used (DEPRECATED).

Any missing required fields will result in a warning and use of safest sensible defaults.
This file MUST NOT attempt to read app.yaml, guess configuration, or set its own hardcoded
defaults except as specified above.

No test code or run-on-main logic will be present in this file.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from monitor import config

# DEFAULT_LOGGING uses '~/.config/monitor/logs/app.log' for file_path instead of a CWD 'logs/' folder.
# This ensures log output is not mixed into the application's current directory, is more appropriate for
# multi-user systems, and matches the new recommended home directory log location.
DEFAULT_LOGGING = {
    'level': 'INFO',
    'file_path': os.path.expanduser('~/.config/monitor/logs/app.log'),
    'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
    'date_format': '%Y-%m-%d %H:%M:%S',
    'max_bytes': 5 * 1024 * 1024,  # 5 MB
    'backup_count': 3,
    'console_logging_enabled': True,
    'encoding': 'utf-8',
}

def _load_logging_config():
    """
    Load the logging configuration dictionary from monitor.config.py.
    Uses config.logging_config if available, else falls back to legacy individual variables (DEPRECATED).

    Returns:
        dict: A merged logging configuration dictionary.
    """
    loaded_config = {}

    # Try unified logging_config dict from monitor.config.py
    if hasattr(config, 'logging_config'):
        for key, default in DEFAULT_LOGGING.items():
            if key in config.logging_config:
                loaded_config[key] = config.logging_config[key]
            else:
                loaded_config[key] = default
                logging.warning(f"Logging config: missing '{key}', using default '{default}'")
        # Ensure required fields present
        for required in ('level', 'file_path'):
            if loaded_config[required] is None or loaded_config[required] == '':
                logging.warning(f"Logging: required config '{required}' is missing. Using default '{DEFAULT_LOGGING[required]}'")
                loaded_config[required] = DEFAULT_LOGGING[required]
        return loaded_config

    # Fallback: legacy config variables (DEPRECATED)
    logging.warning(
        "config.logging_config dict not found. "
        "Falling back to standalone variables (LOGGING_LEVEL, LOG_FILE_PATH, etc.) -- DEPRECATED!"
    )

    legacy_map = {
        'level': 'LOGGING_LEVEL',
        'file_path': 'LOG_FILE_PATH',
        'format': 'LOG_FORMAT',
        'date_format': 'LOG_DATE_FORMAT',
        'max_bytes': 'LOG_MAX_BYTES',
        'backup_count': 'LOG_BACKUP_COUNT',
        'console_logging_enabled': 'CONSOLE_LOGGING_ENABLED',
        'encoding': 'LOG_ENCODING'
    }
    for key, var in legacy_map.items():
        if hasattr(config, var):
            loaded_config[key] = getattr(config, var)
        else:
            # Ensure default uses ~/.config/monitor/logs/app.log for file_path fallback (not logs/app.log)
            loaded_config[key] = DEFAULT_LOGGING[key]
            logging.warning(f"Legacy logging config: missing '{var}', using default '{DEFAULT_LOGGING[key]}'")
    # Required fallback
    for required in ('level', 'file_path'):
        if loaded_config[required] is None or loaded_config[required] == '':
            logging.warning(f"Logging (legacy config): required variable '{required}' is missing. Using default '{DEFAULT_LOGGING[required]}'")
            loaded_config[required] = DEFAULT_LOGGING[required]
    return loaded_config

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

def configure_logging():
    """
    Configures the root logger using unified config.logging_config dictionary.
    Uses documented defaults for missing fields and logs warnings for any missing/legacy fields.

    The log file path will include the process PID: if the file path contains '{pid}', it will be replaced.
    Otherwise, the PID will be injected between the filename and extension automatically. This avoids file
    conflicts when running multiple instances.

    This function is idempotent and safe to call more than once. It removes all existing root handlers.

    Required fields for config.logging_config:
        - 'level' (str)
        - 'file_path' (str)
    Optional fields:
        - 'format', 'date_format', 'max_bytes', 'backup_count', 'console_logging_enabled', 'encoding'

    DEPRECATED legacy fallback:
        If config.logging_config is missing, will use legacy variables LOGGING_LEVEL, LOG_FILE_PATH, etc.
    """
    log_cfg = _load_logging_config()

    # --- Inject the current process PID into the log file path for uniqueness ---
    # If the configured path has '{pid}', substitute; else inject _{pid} before file extension.
    log_cfg['file_path'] = _inject_pid_into_logfile_path(log_cfg['file_path'])

    formatter = logging.Formatter(log_cfg['format'], log_cfg['date_format'])

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_cfg['level'], logging.INFO))

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
            encoding=log_cfg.get('encoding', 'utf-8')
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to set up file logging: {e}")
        raise

    # Console logging if enabled
    if log_cfg.get('console_logging_enabled', True):
        console_handler = logging.StreamHandler()
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

# Configure logging upon import, using strictly config.logging_config as the primary source,
# falling back to legacy variables only if needed.
configure_logging()
