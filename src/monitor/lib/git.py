import logging

from pygments.lexers import BashLexer, DiffLexer

from .git_utils import ensure_non_empty_string, run_git_capture, print_highlight_or_empty

logger = logging.getLogger(__name__)


def perform_git_status():
    """
    Execute a git status to get the current state of the repository.

    :return: The result of git status as a string
    """
    logger.debug("Entering perform_git_status function")
    stdout, _, error = run_git_capture(['git', '--no-pager', 'status'])
    if error:
        logger.error("An error occurred while executing git status: %s", error)
        return error
    logger.info("Successfully performed git status")
    return stdout


def perform_git_diff():
    """
    Perform git diff on the repository to show changes.
    
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff function")
    stdout, _, error = run_git_capture(['git', '--no-pager', 'diff'])
    if error:
        logger.error("An error occurred while executing git diff: %s", error)
        return f"An error occurred while executing git diff: {error.split(': ', 1)[-1]}"

    logger.info("Successfully performed git diff")
    if stdout == "":
        logger.debug("No changes detected in git diff")
        print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
        return "No changes detected."

    print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
    return stdout


def perform_git_diff_file(path):
    """
    Perform git diff on a specific file.
    
    Args:
        path (str): Path to the file to perform git diff on
        
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff_file function with path: %s", path)
    try:
        ensured_path = ensure_non_empty_string(path, "Path")
        stdout, _, error = run_git_capture(['git', '--no-pager', 'diff', ensured_path])
        if error:
            logger.error("Error executing git diff on %s: %s", ensured_path, error)
            return f"An error occurred while executing git diff on {ensured_path}: {error.split(': ', 1)[-1]}"

        logger.info("Successfully performed git diff on file: %s", ensured_path)
        if stdout == "":
            logger.debug("No changes detected in file: %s", ensured_path)
            return f"No changes detected in {ensured_path}"

        print_highlight_or_empty(stdout, DiffLexer(), f"No differences found in {ensured_path}.")
        return stdout

    except ValueError as e:
        logger.error("Invalid path provided: %s", e, exc_info=True)
        return f"Invalid path provided: {e}"


def perform_git_diff_previous():
    """
    Perform git diff between HEAD and HEAD^ (previous commit).
    
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff_previous function")
    stdout, _, error = run_git_capture(['git', '--no-pager', 'diff', 'HEAD^..HEAD'])
    if error:
        logger.error("Error executing git diff HEAD^: %s", error)
        return "An error occurred while executing git diff: " + error.split(': ', 1)[-1]

    logger.info("Successfully performed git diff HEAD^")
    if stdout == "":
        logger.debug("No changes detected between current and previous commit")
        print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
        return "No changes detected."

    print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
    return stdout


def perform_git_show(ref):
    """
    Show commit or branch details using 'git --no-pager show <ref>'.

    Args:
        ref (str): The git ref (commit hash or branch name).
    Returns:
        str: Output of the git show command.
    Raises:
        Exception: If the git command fails.
    """
    logger.debug("Entering perform_git_show function with ref: %s", ref)
    try:
        ensured_ref = ensure_non_empty_string(ref, "Ref")
        stdout, _, error = run_git_capture(['git', '--no-pager', 'show', ensured_ref])
        if error:
            logger.error("Error executing git show on ref %s: %s", ensured_ref, error)
            return f"An error occurred while executing git show on {ensured_ref}: {error.split(': ', 1)[-1]}"

        logger.info("Successfully performed git show on ref: %s", ensured_ref)
        if stdout == "":
            logger.debug("No output received from git show for ref: %s", ensured_ref)
            print_highlight_or_empty(stdout, BashLexer(), f"No output found for {ensured_ref}.")
            return f"No output for {ensured_ref}"

        print_highlight_or_empty(stdout, BashLexer(), f"No output found for {ensured_ref}.")
        return stdout
    except ValueError as e:
        logger.error("Invalid ref provided: %s", e, exc_info=True)
        return f"Invalid ref provided: {e}"


def perform_git_diff_staged():
    """
    Perform git diff on the repository to show changes.
    
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff_staged function")
    stdout, _, error = run_git_capture(['git', '--no-pager', 'diff', '--staged'])
    if error:
        logger.error("An error occurred while executing git diff: %s", error)
        return f"An error occurred while executing git diff: {error.split(': ', 1)[-1]}"

    logger.info("Successfully performed git diff")
    if stdout == "":
        logger.debug("No changes detected in git diff")
        print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
        return "No changes detected."

    print_highlight_or_empty(stdout, DiffLexer(), "No differences found.")
    return stdout


def perform_git_log(ref_or_args=None):
    """
    Run git log to display commit history.

    Args:
        ref_or_args (str or None): Optional git reference/args (e.g. '--oneline', a commit hash, or branch).
    Returns:
        str: The log output or an error message/status.
    """
    logger.debug("Entering perform_git_log function with ref_or_args: %s", ref_or_args)
    cmd = ['git', '--no-pager', 'log']
    if ref_or_args:
        if isinstance(ref_or_args, str):
            cmd.extend(ref_or_args.split())
        elif isinstance(ref_or_args, list):
            cmd.extend(ref_or_args)
    stdout, _, error = run_git_capture(cmd)
    if error:
        logger.error("Error executing git log: %s", error)
        return f"An error occurred while executing git log: {error.split(': ', 1)[-1]}"

    logger.info("Successfully performed git log")
    if not stdout:
        return "No log output."
    print_highlight_or_empty(stdout, BashLexer(), "No log output.")
    return stdout


def perform_git_commit(message):
    """
    Run git commit with a commit message.

    Args:
        message (str): Commit message for git commit -m
    Returns:
        str: Commit output or error message/status
    """
    logger.debug("Entering perform_git_commit function with message: %s", message)
    try:
        ensured_message = ensure_non_empty_string(message, "Commit message")
    except ValueError:
        logger.error("Invalid commit message provided: must be non-empty string")
        return "Commit message must be a non-empty string."

    stdout, stderr, error = run_git_capture(['git', 'commit', '-m', ensured_message])
    if error:
        logger.error("Error executing git commit: %s", error)
        return f"An error occurred while executing git commit: {error.split(': ', 1)[-1]}"

    logger.info("Successfully performed git commit")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    return stdout or stderr or "Commit executed with no output."


def perform_git_stash(subcommand=None):
    """
    Run git stash with a subcommand (e.g. 'push', 'pop', 'apply', 'list').

    Args:
        subcommand (str or list or None): Stash subcommand as a string (e.g., 'push', 'pop', 'apply', 'list')
            or a non-empty list of arguments. If None, empty, or whitespace-only, no git command is executed.
    Returns:
        str: Stash output or error message/status.
    """
    logger.debug("Entering perform_git_stash with subcommand: %s", subcommand)

    # Validate subcommand before building the command or invoking git
    invalid = False
    if subcommand is None:
        invalid = True
    elif isinstance(subcommand, str):
        if subcommand.strip() == "":
            invalid = True
    elif isinstance(subcommand, list):
        if len(subcommand) == 0:
            invalid = True
    else:
        invalid = True

    if invalid:
        logger.warning("Invalid stash subcommand provided: %r", subcommand)
        return "Invalid stash subcommand. Provide a subcommand like 'push', 'pop', 'apply', or 'list'."

    cmd = ['git', 'stash']
    if isinstance(subcommand, str):
        cmd.append(subcommand)
    elif isinstance(subcommand, list):
        cmd.extend(subcommand)

    stdout, stderr, error = run_git_capture(cmd)
    if error:
        logger.error("Error executing git stash: %s", error)
        return f"An error occurred while executing git stash: {error.split(': ', 1)[-1]}"

    logger.info("Successfully performed git stash with subcommand: %s", subcommand)
    if not stdout and not stderr:
        return "No output from git stash."
    output = ""
    if stdout:
        output += stdout
        print(stdout)
    if stderr:
        output += stderr
        print(stderr)
    return output or f"git stash {subcommand or ''} executed with no output."


def perform_git_log_range(main_branch, topic_branch):
    """
    Get commits from the merge base between main_branch and topic_branch to topic_branch's HEAD.
    Returns a list of dicts: { 'hash', 'message', 'timestamp' }
    """
    logger.debug("Entering perform_git_log_range: %s..%s", main_branch, topic_branch)
    try:
        merge_base_cmd = ['git', 'merge-base', main_branch, topic_branch]
        merge_stdout, _, merge_error = run_git_capture(merge_base_cmd)
        if merge_error:
            raise RuntimeError(merge_error)
        merge_base = merge_stdout.strip()

        log_cmd = ['git', '--no-pager', 'log', '--format=%H%x1f%s%x1f%ct', f'{merge_base}..{topic_branch}']
        log_stdout, _, log_error = run_git_capture(log_cmd)
        if log_error:
            raise RuntimeError(log_error)

        commits = []
        for line in log_stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split('\x1f')
            if len(parts) != 3:
                logger.debug("Skipping malformed git log line: %r", line)
                continue
            hash_, message, timestamp = parts
            commits.append({
                'hash': hash_,
                'message': message,
                'timestamp': timestamp
            })
        return commits
    except Exception as e:
        logger.error("Error in perform_git_log_range: %s", e, exc_info=True)
        return []
