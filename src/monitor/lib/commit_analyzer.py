import logging
import re
from textwrap import dedent

import litellm

from monitor.lib.pygments_stubs import DiffLexer, TerminalFormatter, highlight

from monitor.lib.macro_utils import recursive_macro_expand
from monitor.lib.git_utils import run_git_capture

logger = logging.getLogger(__name__)

# Cap on the commit-log text sent to the LLM, so a long branch can't blow the
# model's context window or cost.
MAX_COMMIT_LOG_CHARS = 20000
# Cap on how many commits the single `git log -p` call walks.
MAX_COMMITS = 50

# Leading list markers the model might emit: "1.", "2)", "-", "*", "•".
_STEP_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")


class CommitAnalyzer:
    """
    Analyze Git commits within a branch to understand branch purpose and suggest next steps.

    This class uses canonical git wrapper functions from monitor.lib.git to access commit
    history, and LiteLLM to analyze commits and generate insights.
    """

    def __init__(self, branch_name, logger, main_branch="main", llm_model=None):
        """Initialize the CommitAnalyzer and fetch the branch's commit log.

        Args:
            branch_name (str): The Git branch to analyze.
            logger (logging.Logger): Logger instance for diagnostics.
            main_branch (str): The main branch to compare against. Defaults to "main".
            llm_model (str): The LLM model to use; required by the caller.

        After construction, ``fetch_error`` is set to a message if the git fetch
        failed (e.g. unknown branch), and ``has_commits`` indicates whether the
        range contained any commits. These let callers distinguish a git error
        from a genuinely empty range.
        """
        self.logger = logger
        self.branch_name = branch_name
        self.main_branch = main_branch
        self.llm_model = llm_model
        self.commit_log = ""
        self.has_commits = False
        self.fetch_error = None

        self.logger.debug(
            "Initializing CommitAnalyzer: branch=%s main=%s model=%s",
            branch_name, main_branch, llm_model,
        )
        self._fetch_commit_log()

    def _fetch_commit_log(self):
        """Fetch the branch's commits-with-diffs in a single ``git log -p`` call.

        One subprocess (not one per commit), capped to MAX_COMMITS and
        MAX_COMMIT_LOG_CHARS. Records ``fetch_error`` on git failure so a bad
        branch is not silently reported as "no commits".
        """
        stdout, _, error = run_git_capture([
            "git", "--no-pager", "log", "-p",
            f"--max-count={MAX_COMMITS}",
            f"{self.main_branch}..{self.branch_name}",
        ])
        if error:
            self.fetch_error = error
            self.logger.warning("git log failed for %s..%s: %s", self.main_branch, self.branch_name, error)
            return

        text = (stdout or "").strip()
        if not text:
            self.logger.info("No commits in range %s..%s", self.main_branch, self.branch_name)
            return

        self.has_commits = True
        if len(text) > MAX_COMMIT_LOG_CHARS:
            text = text[:MAX_COMMIT_LOG_CHARS] + "\n... [commit log truncated] ..."
        self.commit_log = text

    def analyze_commits(self):
        """Summarize the branch's purpose from its commit log.

        Returns:
            tuple[str, str]: (summary, colorized diff). For an empty range,
                returns a clear "no commits" message and "No diff available.".

        Raises:
            Exception: Propagates any LLM/transport error instead of returning
                a placeholder, so the caller can surface the real failure.
        """
        if not self.has_commits:
            self.logger.warning("No commits to analyze")
            return (
                "No commits found for analysis. Make sure you're on a topic branch that branches off of the main branch.",
                "No diff available.",
            )

        colored_output = color_diff(self.commit_log)
        prompt = (
            "Summarize what this branch is doing based on these commits:\n\n"
            f"{self.commit_log}\n\n"
            "Provide a 2-3 sentence summary that captures the purpose and progress of this development branch."
        )
        self.logger.debug("Sending commit log to LLM (%s) for analysis", self.llm_model)
        response = litellm.completion(
            model=self.llm_model, messages=[{"role": "user", "content": prompt}]
        )
        summary = (response.choices[0].message.content or "").strip()
        self.logger.info("Successfully generated summary using LLM")
        return summary, colored_output

    def suggest_next_steps(self, summary):
        """Suggest next steps from the summary alone.

        The summary already distills the commits, so the diff is not re-sent
        (it was sent once during analyze_commits).

        Returns:
            list[str]: Suggested next actions, or [] when there are no commits.

        Raises:
            Exception: Propagates any LLM/transport error instead of returning
                fabricated generic advice.
        """
        if not self.has_commits:
            return []

        prompt = (
            f'Based on this summary of a development branch:\n"{summary}"\n\n'
            "Suggest 2-5 logical next steps for development. Return them as a numbered list:\n"
            "1. First suggestion\n2. Second suggestion\n...and so on."
        )
        self.logger.debug("Sending summary to LLM (%s) for next steps", self.llm_model)
        response = litellm.completion(
            model=self.llm_model, messages=[{"role": "user", "content": prompt}]
        )
        suggestions_text = (response.choices[0].message.content or "").strip()
        self.logger.info("Successfully generated next steps using LLM")
        return _parse_steps(suggestions_text)


def _parse_steps(text):
    """Parse a list of next-steps, tolerating '1.', '2)', '-', '*', '•' markers."""
    steps = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _STEP_MARKER.match(line)
        if match:
            steps.append(line[match.end():].strip())
    if not steps and text.strip():
        # Model didn't use a recognizable list format; hand back the raw text.
        return [text.strip()]
    return steps


def color_diff(diff_text):
    """Colorize diff text for terminal output using pygments DiffLexer.

    Args:
        diff_text (str): Unified diff text.

    Returns:
        str: Highlighted diff text for terminal output.
    """
    return highlight(diff_text, DiffLexer(), TerminalFormatter(reset=True))


def analyze_branch_for_summary_and_steps(branch, logger, model, main_branch="main"):
    """Run commit analysis and generate summary and next steps for a branch.

    Args:
        branch (str): Branch name to analyze.
        logger (logging.Logger): Logger instance.
        model (str): LLM model name.
        main_branch (str): Name of the main branch. Defaults to "main".

    Returns:
        tuple[str, str, list[str]]: A tuple of
            (summary, diff_output, next_steps).
    """
    analyzer = CommitAnalyzer(branch, logger, main_branch, model)
    if analyzer.fetch_error:
        raise RuntimeError(analyzer.fetch_error)
    summary, diff_output = analyzer.analyze_commits()
    next_steps_list = analyzer.suggest_next_steps(summary)
    return summary, diff_output, next_steps_list


def build_commit_message_query_input(
    diff, macro_values, macro_delim_open, macro_delim_close, macro_delim_escape
):
    """Build the macro-expanded prompt for generating a commit message from a diff.

    Args:
        diff (str): The git diff string.
        macro_values (dict): Macro values to expand.
        macro_delim_open (str): Macro opening delimiter.
        macro_delim_close (str): Macro closing delimiter.
        macro_delim_escape (str): Macro escape delimiter.

    Returns:
        str: The macro-expanded query input.
    """
    macro = dedent(
        f"""
        {macro_delim_open}create_git_entry{macro_delim_close}
        """
    ).strip()
    git_entry_macro_expanded = recursive_macro_expand(
        macro,
        macro_values,
        macro_delim_open,
        macro_delim_close,
        macro_delim_escape,
    )
    query_input = (
        f"Given:\n\n<git_diff_staged>{diff}</git_diff_staged>\n\n"
        f"{git_entry_macro_expanded}"
    )
    return query_input
