import subprocess
import json
import os
import logging
from colored import fg, attr

from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer
from pygments.formatters import TerminalFormatter

logger = logging.getLogger(__name__)

blue = fg('blue')
red = fg('red')
yellow = fg('yellow')
reset = attr('reset')

def perform_git_status():
    """
    Execute a git status to get the current state of the repository.

    :return: The result of git status as a string
    """
    logger.debug("Entering perform_git_status function")
    try:
        result = subprocess.run(['git', 'status'], check=True, text=True, capture_output=True)
        logger.info("Successfully performed git status")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("An error occurred while executing git status: %s", e, exc_info=True)
        return f"An error occurred while executing git status: {e}"

def perform_git_diff():
    """
    Perform git diff on the repository to show changes.
    
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff function")
    try:
        result = subprocess.run(['git', 'diff'], check=True, text=True, capture_output=True)
        logger.info("Successfully performed git diff")  
        if result.stdout == "":
            logger.debug("No changes detected in git diff")
            return "No changes detected."

        highlighted_output = highlight(result.stdout, DiffLexer(), TerminalFormatter(reset=True))
        print(highlighted_output if result.stdout else f"{yellow}No differences found.{reset}")

        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("An error occurred while executing git diff: %s", e, exc_info=True)
        return f"An error occurred while executing git diff: {e}"

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
        # Ensure path is a string and not empty
        if not isinstance(path, str) or not path.strip():
            logger.error("Invalid path provided: path must be a non-empty string")
            raise ValueError("Path must be a non-empty string")
            
        result = subprocess.run(
            ['git', 'diff', path],
            check=True,
            text=True,
            capture_output=True
        )
        logger.info("Successfully performed git diff on file: %s", path)
        
        if result.stdout == "":
            logger.debug("No changes detected in file: %s", path)
            return f"No changes detected in {path}"
            
        highlighted_output = highlight(
            result.stdout,
            DiffLexer(),
            TerminalFormatter(reset=True)
        )
        print(highlighted_output if result.stdout else f"{yellow}No differences found in {path}.{reset}")
        
        return result.stdout
        
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git diff on %s: %s", path, e, exc_info=True)
        return f"An error occurred while executing git diff on {path}: {e}"
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
    try:
        result = subprocess.run(['git', 'diff', 'HEAD^'], check=True, text=True, capture_output=True)
        logger.info("Successfully performed git diff HEAD^")  
        if result.stdout == "":
            logger.debug("No changes detected between current and previous commit")
            return "No changes detected."

        highlighted_output = highlight(result.stdout, DiffLexer(), TerminalFormatter(reset=True))
        print(highlighted_output if result.stdout else f"{yellow}No differences found.{reset}")

        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git diff HEAD^: %s", e, exc_info=True)
        return f"An error occurred while executing git diff: {e}"

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
        if not isinstance(ref, str) or not ref.strip():
            logger.error("Invalid ref provided: ref must be a non-empty string")
            raise ValueError("Ref must be a non-empty string.")
        result = subprocess.run(
            ['git', '--no-pager', 'show', ref],
            check=True,
            text=True,
            capture_output=True
        )
        logger.info("Successfully performed git show on ref: %s", ref)
        if result.stdout == "":
            logger.debug("No output received from git show for ref: %s", ref)
            return f"No output for {ref}"

        # Use BashLexer for generic command output highlighting
        highlighted_output = highlight(
            result.stdout,
            BashLexer(),
            TerminalFormatter(reset=True)
        )
        print(highlighted_output if result.stdout else f"{yellow}No output found for {ref}.{reset}")

        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git show on ref %s: %s", ref, e, exc_info=True)
        return f"An error occurred while executing git show on {ref}: {e}"
    except ValueError as e:
        logger.error("Invalid ref provided: %s", e, exc_info=True)
        return f"Invalid ref provided: {e}"

def perform_git_diff_staged():
    """
    Perform git diff on the repository to show changes.
    
    Returns:
        str: The diff output or an error message/status
    """
    logger.debug("Entering perform_git_diff function")
    try:
        result = subprocess.run(['git', 'diff', '--staged'], check=True, text=True, capture_output=True)
        logger.info("Successfully performed git diff")  
        if result.stdout == "":
            logger.debug("No changes detected in git diff")
            return "No changes detected."

        highlighted_output = highlight(result.stdout, DiffLexer(), TerminalFormatter(reset=True))
        print(highlighted_output if result.stdout else f"{yellow}No differences found.{reset}")

        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("An error occurred while executing git diff: %s", e, exc_info=True)
        return f"An error occurred while executing git diff: {e}"

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
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info("Successfully performed git log")
        if not result.stdout:
            return "No log output."
        highlighted_output = highlight(result.stdout, BashLexer(), TerminalFormatter(reset=True))
        print(highlighted_output)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git log: %s", e, exc_info=True)
        return f"An error occurred while executing git log: {e}"


def perform_git_commit(message):
    """
    Run git commit with a commit message.

    Args:
        message (str): Commit message for git commit -m
    Returns:
        str: Commit output or error message/status
    """
    logger.debug("Entering perform_git_commit function with message: %s", message)
    if not isinstance(message, str) or not message.strip():
        logger.error("Invalid commit message provided: must be non-empty string")
        return "Commit message must be a non-empty string."
    try:
        result = subprocess.run(['git', 'commit', '-m', message], check=True, text=True, capture_output=True)
        logger.info("Successfully performed git commit")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        return result.stdout or result.stderr or "Commit executed with no output."
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git commit: %s", e, exc_info=True)
        return f"An error occurred while executing git commit: {e}"

def perform_git_stash(subcommand=None):
    """
    Run git stash with optional subcommand (e.g. 'save', 'pop', etc).

    Args:
        subcommand (str or None): Stash subcommand, e.g., 'save', 'pop', or None for just 'git stash'.
    Returns:
        str: Stash output or error message/status.
    """
    logger.debug("Entering perform_git_stash with subcommand: %s", subcommand)
    cmd = ['git', 'stash']
    if subcommand:
        if isinstance(subcommand, str):
            cmd.append(subcommand)
        elif isinstance(subcommand, list):
            cmd.extend(subcommand)
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info("Successfully performed git stash with subcommand: %s", subcommand)
        if not result.stdout and not result.stderr:
            return "No output from git stash."
        output = ""
        if result.stdout:
            output += result.stdout
            print(result.stdout)
        if result.stderr:
            output += result.stderr
            print(result.stderr)
        return output or f"git stash {subcommand or ''} executed with no output."
    except subprocess.CalledProcessError as e:
        logger.error("Error executing git stash: %s", e, exc_info=True)
        return f"An error occurred while executing git stash: {e}"

def perform_git_log_range(main_branch, topic_branch):
    """
    Get commits from the merge base between main_branch and topic_branch to topic_branch's HEAD.
    Returns a list of dicts: { 'hash', 'message', 'timestamp' }
    """
    logger.debug("Entering perform_git_log_range: %s..%s", main_branch, topic_branch)
    try:
        merge_base_cmd = ['git', 'merge-base', main_branch, topic_branch]
        merge_base_result = subprocess.run(merge_base_cmd, check=True, text=True, capture_output=True)
        merge_base = merge_base_result.stdout.strip()
        log_cmd = ['git', 'log', '--format=%H|%s|%ct', f'{merge_base}..{topic_branch}']
        log_result = subprocess.run(log_cmd, check=True, text=True, capture_output=True)
        commits = []
        for line in log_result.stdout.strip().splitlines():
            if not line.strip():
                continue
            hash_, message, timestamp = line.split('|', 2)
            commits.append({
                'hash': hash_,
                'message': message,
                'timestamp': timestamp
            })
        return commits
    except Exception as e:
        logger.error("Error in perform_git_log_range: %s", e, exc_info=True)
        return []
