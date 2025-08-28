from monitor.core.command_processing import internalize_command
from monitor.lib.ripgrep_search import grep_command

def rip_grep_command(arg):
    """
    Run a ripgrep search for the given arg, print the results, and
    ask the internal command processor to explain how the search key
    is used in the matching code.

    Behavior:
    - If the grep result is exactly the string "No matches found.", print it and return immediately.
    - Otherwise, print the grep result, construct a prompt embedding the search key and results,
      call internalize_command(prompt), and return its result.
    """
    grep_result = grep_command(arg)

    if grep_result == "No matches found.":
        print(grep_result)
        return None

    print(grep_result)

    prompt = (
        f"Given the <search_key>{arg}</search_key>\n"
        f"And given the result:\n"
        f"<search_results>{grep_result}</search_results>\n\n"
        f"Explain how {arg} is used in the code of the search result."
    )

    return internalize_command(prompt)
