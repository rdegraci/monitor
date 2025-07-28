
import logging

from monitor import config
from monitor.lib.macros import MACRO_VALUES

logger = logging.getLogger(__name__)

from monitor.lib.colors import red, yellow, blue, reset

from monitor.lib.commit_analyzer import analyze_branch_for_summary_and_steps, build_commit_message_query_input

def next_steps(branch):
    """
    Prints the diff output, branch summary, and suggested next steps for the given branch.
    """
    summary, diff_output, next_steps_list = analyze_branch_for_summary_and_steps(
        branch=branch,
        logger=logger,
        main_branch="main",
        model=config.MODEL
    )
    print(diff_output)
    print(f"{blue}Branch Summary:{reset}")
    print(f"{yellow}{summary}{reset}")
    print(f"{blue}Suggested Next Steps:{reset}")
    items = [f"{i + 1}. {item}" for i, item in enumerate(next_steps_list)]
    next_steps_formatted = '\n'.join(items)
    print(f"{yellow}{next_steps_formatted}{reset}")




