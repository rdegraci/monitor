import logging

from monitor import config

logger = logging.getLogger(__name__)

from monitor.lib.colors import yellow, blue, reset

from monitor.lib.commit_analyzer import analyze_branch_for_summary_and_steps

def next_steps(branch, main_branch):
    """
    Prints the diff output, branch summary, and suggested next steps for the given branch.

    Args:
        branch: The name or identifier of the feature branch to analyze.
        main_branch: The name of the main branch to compare against.

    Returns:
        None. Output is printed to stdout.
    """
    try:
        summary, diff_output, next_steps_list = analyze_branch_for_summary_and_steps(
            branch=branch,
            logger=logger,
            main_branch=main_branch,
            model=config.MODEL
        )
    except Exception as e:
        logger.error("next_steps analysis failed: %s", e, exc_info=True)
        print(f"{yellow}Could not analyze branch '{branch}' against '{main_branch}': {e}{reset}")
        return

    print(diff_output)
    print(f"{blue}Branch Summary:{reset}")
    print(f"{yellow}{summary}{reset}")
    if next_steps_list:
        print(f"{blue}Suggested Next Steps:{reset}")
        items = [f"{i + 1}. {item}" for i, item in enumerate(next_steps_list)]
        next_steps_formatted = '\n'.join(items)
        print(f"{yellow}{next_steps_formatted}{reset}")
