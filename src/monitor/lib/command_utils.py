import subprocess
import logging

try:
    from termcolor import colored
except ImportError:
    def colored(text, color):
        return text

def get_first_word(command: str) -> str:
    """Extracts the first word from a shell command string.

    Args:
        command (str): The input command string. May be empty, None, or contain multiple blank lines.

    Returns:
        str: The first word in the command, or an empty string if command is empty, None, or only whitespace.
    """
    if not command:
        return ""
    split_line = command.split()
    if not split_line:
        return ""
    return split_line[0]


def handle_error(
    error_msg, exception=None, error_type="Error", log_level="error", display=True
):
    """
    Standardized error handling function.

    Args:
        error_msg (str): The main error message to display and log
        exception (Exception, optional): The exception object if available
        error_type (str, optional): Type of error (e.g., "Error", "Warning")
        log_level (str, optional): Logging level to use ("error", "warning", "debug", "info")
        display (bool, optional): Whether to display the error to the user

    Returns:
        None
    """
    logger = logging.getLogger(__name__)
    full_message = error_msg
    if exception:
        full_message = f"{error_msg}: {exception}"
    if log_level == "error":
        logger.error(full_message, exc_info=True)
    elif log_level == "warning":
        logger.warning(full_message)
    elif log_level == "debug":
        logger.debug(full_message)
    elif log_level == "info":
        logger.info(full_message)
    if display:
        print(colored(f"{error_type}: {error_msg}", "red"))
        if exception:
            print(colored(f"Details: {exception}", "red"))


def run_subprocess(
    command_string,
    interactive=False,
    shell=True,
    preexec_fn=None,
    text=True,
    fetch_output=True,
    cwd=None,
):
    """
    Helper function to run a subprocess, handling errors and optionally fetching output.

    Args:
        command_string (str): The shell command to execute.
        interactive (bool): If True, does not capture stdout/stderr and leaves them connected to user terminal.
        shell (bool): Whether to run the process within a shell.
        preexec_fn (callable, optional): Function to run in the child process prior to execution.
        text (bool): If True, decode output as text.
        fetch_output (bool): If True and not interactive, capture stdout and stderr.
        cwd (str, optional): Working directory for the command.

    Returns:
        tuple: (exit_code, stdout, stderr, process) where
               exit_code (int): The process exit code, or None if process didn't terminate
               stdout (str or None): Captured stdout, or None
               stderr (str or None): Captured stderr, or None
               process (subprocess.Popen): The process object
               If interactive=True, stdout and stderr will be None, and caller should handle terminal I/O.
    """
    popen_kwargs = {
        "shell": shell,
        "text": text,
    }
    if preexec_fn is not None:
        popen_kwargs["preexec_fn"] = preexec_fn
    if cwd is not None:
        popen_kwargs["cwd"] = cwd
    if not interactive and fetch_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    try:
        process = subprocess.Popen(command_string, **popen_kwargs)
    except Exception as ex_start:
        handle_error(
            f"Unable to start subprocess: '{command_string}'",
            exception=ex_start,
            error_type="Error",
            log_level="error",
            display=True,
        )
        return None, None, None, None
    stdout, stderr = None, None
    exit_code = None
    try:
        if not interactive and fetch_output:
            stdout, stderr = process.communicate()
            exit_code = process.returncode
        else:
            process.wait()
            exit_code = process.returncode
    except Exception as ex_run:
        handle_error(
            f"Exception while running command: '{command_string}'",
            exception=ex_run,
            error_type="Error",
            log_level="error",
            display=True,
        )
        return None, None, None, process
    return exit_code, stdout, stderr, process
