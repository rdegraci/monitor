
import os
import logging

from datetime import datetime
import yaml
from dotenv import load_dotenv
import litellm

from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer
from pygments.formatters import TerminalFormatter

from monitor.lib.macro_utils import recursive_macro_expand
from monitor.lib.git import (
    perform_git_diff_staged,
    perform_git_diff,
    perform_git_status,
    perform_git_diff_previous,
    perform_git_diff_file,
    perform_git_show,
    perform_git_log_range,
)

logger = logging.getLogger(__name__)

class CommitAnalyzer:
    """
    Analyzes Git commits within a branch to understand branch purpose and suggest next steps.
    
    This class uses canonical git wrapper functions from monitor.lib.git to access commit history,
    and LiteLLM to analyze commits and generate insights.
    """
    
    def __init__(self, branch_name, logger, main_branch="main", llm_model="anthropic/claude-3-7-sonnet-20250219"):
        """
        Initialize the CommitAnalyzer with a branch name.
        
        Args:
            branch_name (str): The name of the Git branch to analyze
            main_branch (str): The name of the main branch to compare against (default: "main")
            llm_model (str): The LLM model to use for analysis (default: "anthropic/claude-3-7-sonnet-20250219")
        """
        self.logger = logger
        self.branch_name = branch_name
        self.main_branch = main_branch
        self.llm_model = llm_model
        self.commits = []
        
        self.logger.debug(f"Initializing CommitAnalyzer with branch: {branch_name}")
        self.logger.debug(f"Using main branch: {main_branch}")
        self.logger.debug(f"Using LLM model: {llm_model}")

        try:
            self._fetch_commits_from_git()
        except Exception as e:
            self.logger.error(f"Error fetching commits: {str(e)}", exc_info=True)
    
    def _fetch_commits_from_git(self):
        """
        Fetch commits from the local Git repository from the merge base to the latest commit.
        
        Uses canonical git wrapper functions from monitor.lib.git to interact with the local Git repository and fetch commit data.
        """
        try:
            self.logger.info(f"Accessing local Git repository: branch '{self.branch_name}', main branch '{self.main_branch}'")
            # Retrieve the list of commits between main_branch and branch_name exclusively via canonical functions.
            # Assumes perform_git_show returns commit info and perform_git_diff returns the diff for a commit.
            # There is no subprocess/gitpython use here.

            commits_info = perform_git_log_range(self.main_branch, self.branch_name)
            if not commits_info or not isinstance(commits_info, list):
                self.logger.warning("No commits returned from canonical git log range function.")
                return

            for commit in commits_info:
                commit_hash = commit.get('hash')
                commit_message = commit.get('message', '').strip()
                commit_timestamp = commit.get('timestamp')
                commit_diff = perform_git_show(commit_hash)
                timestamp_iso = ""
                if commit_timestamp:
                    try:
                        timestamp_iso = datetime.fromtimestamp(int(commit_timestamp)).isoformat()
                    except Exception:
                        timestamp_iso = commit_timestamp
                self.commits.append({
                    'message': commit_message,
                    'diff': commit_diff,
                    'timestamp': timestamp_iso
                })

            self.logger.info(f"Fetched {len(self.commits)} commits from canonical git log wrapper")
            self.commits.reverse()
        except Exception as e:
            self.logger.error(f"Unexpected error accessing Git repository: {str(e)}", exc_info=True)


    def analyze_commits(self):
        """
        Analyze the commits to generate a summary of the branch's purpose.
        
        Uses LiteLLM to send commit data to an LLM and get a summary.
        
        Returns:
            str: A concise summary of the branch's purpose (2-3 sentences)
        """
        if not self.commits:
            self.logger.warning("No commits to analyze")
            return "No commits found for analysis. Make sure you're on a topic branch that branches off of main/master.", "No diff available."
        
        commit_data = "\n".join([
            f"Commit: {commit['message']}\nTimestamp: {commit['timestamp']}\nDiff: {commit['diff']}\n"
            for commit in self.commits
        ])
        
        colored_output = color_diff(commit_data)

        prompt = f"""Summarize what this branch is doing based on these commits:

{commit_data}

Provide a 2-3 sentence summary that captures the purpose and progress of this development branch.
"""
      
        try:
            self.logger.debug(f"Sending commit data to LLM ({self.llm_model}) for analysis")
            response = litellm.completion(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}]
            )
            summary = response.choices[0].message.content.strip()
            self.logger.info("Successfully generated summary using LLM")
            return summary, colored_output
        
        except Exception as e:
            self.logger.error(f"Error communicating with LLM: {str(e)}", exc_info=True)
            return "None", "None"


    def suggest_next_steps(self, summary):
        """
        Generate suggested next steps based on the analyzed commits and summary.
        
        Uses LiteLLM to send the summary and commit data to an LLM and get suggestions.
        
        Args:
            summary (str): The summary generated by analyze_commits
            
        Returns:
            list: A list of suggested next actions (2-5 items)
        """
        if not self.commits:
            self.logger.warning("No commits available for suggesting next steps")
            return ["Add initial implementation", "Create documentation"]
        
        commit_data = "\n".join([
            f"Commit: {commit['message']}\nTimestamp: {commit['timestamp']}\nDiff: {commit['diff']}\n"
            for commit in self.commits
        ])
        
        prompt = f"""Based on this summary:
"{summary}"

And these commits:
{commit_data}

Suggest 2-5 logical next steps for development. Return the suggestions as a numbered list formatted like:
1. First suggestion
2. Second suggestion
...and so on.
"""

        try:
            self.logger.debug(f"Sending summary and commit data to LLM ({self.llm_model}) for next steps")
            response = litellm.completion(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}]
            )
            suggestions_text = response.choices[0].message.content.strip()
            self.logger.info("Successfully generated next steps using LLM")
            
            suggestions = []
            for line in suggestions_text.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() and '. ' in line):
                    suggestion = line.split('. ', 1)[1].strip()
                    suggestions.append(suggestion)
            
            if not suggestions and suggestions_text:
                self.logger.warning("Failed to parse numbered list, returning raw text")
                return [suggestions_text]
                
            return suggestions
            
        except Exception as e:
            self.logger.error(f"Error communicating with LLM: {str(e)}", exc_info=True)
            return [
                "Write unit tests for the implemented functionality",
                "Add input validation",
                "Update documentation to reflect recent changes",
                "Consider refactoring for better maintainability"
            ]

def color_diff(diff_text):
    """
    Colorize diff text for terminal output using pygments DiffLexer.

    Args:
        diff_text (str): Unified diff text.

    Returns:
        str: Highlighted diff text for terminal output.
    """
    return highlight(diff_text, DiffLexer(), TerminalFormatter(reset=True))

def load_config():
    """
    Load configuration from app.yaml file.
    
    Returns:
        dict: Configuration properties
    """
    default_config = {
        'branch_name': 'main',
        'main_branch': 'main',
        'llm_model': 'anthropic/claude-3-7-sonnet-20250219',
        'logging_level': 'INFO'
    }
    
    try:
        with open('app.yaml', 'r') as f:
            config = yaml.safe_load(f)
            
        if config:
            return {**default_config, **config}
        return default_config
    
    except FileNotFoundError:
        logger.warning("app.yaml not found, using default configuration")
        return default_config
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}", exc_info=True)
        return default_config

def analyze_branch_for_summary_and_steps(branch, logger, model, main_branch="main"):
    """
    Run commit analysis and generate summary and next steps for a branch.

    Args:
        branch (str): Branch name to analyze
        logger (logging.Logger): Logger instance
        model (str): LLM model name
        main_branch (str): Name of the main branch (default: "main")

    Returns:
        tuple: (summary (str), diff_output (str), next_steps (list[str]))
    """
    analyzer = CommitAnalyzer(branch, logger, main_branch, model)
    summary, diff_output = analyzer.analyze_commits()
    next_steps_list = analyzer.suggest_next_steps(summary)
    return summary, diff_output, next_steps_list

def build_commit_message_query_input(macro_values, macro_delim_open, macro_delim_close, macro_delim_escape):
    """
    Build the macro-expanded prompt for generating a commit message from a diff.

    Args:
        diff (str): The git diff string
        macro_values (dict): Macro values to expand
        macro_delim_open (str): Macro opening delimiter
        macro_delim_close (str): Macro closing delimiter
        macro_delim_escape (str): Macro escape delimiter

    Returns:
        str: The macro-expanded query input
    """
    diff = perform_git_diff_staged()
    git_entry_macro_expanded = recursive_macro_expand(
        "(git_entry)",
        macro_values,
        macro_delim_open,
        macro_delim_close,
        macro_delim_escape,
    )
    query_input = f"Given:\n\n<git_diff_staged>{diff}</git_diff_staged>\n\n{git_entry_macro_expanded}"
    return query_input
