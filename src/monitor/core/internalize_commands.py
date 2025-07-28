from monitor.core.command_processing import internalize_command
from monitor.lib.ripgrep_search import grep_command
def rip_grep_command(arg):
    grep_result = grep_command(arg)
    print(grep_result)
    result =internalize_command(f"Given the <search_key>{arg}</search_key>\nAnd given the result: \n<search_results>{grep_result}</search_results>\n\n Explain the how {arg} is used in the code of the search result.")
    print(result)