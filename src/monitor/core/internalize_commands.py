from monitor.core.command_processing import internalize_command
from monitor.lib.ripgrep_search import grep_command
import logging
from monitor import config

from monitor.lib.display_output import print_colored_info

logger = logging.getLogger(__name__)

def rip_grep_command(arg, print_func=print):
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
        print_colored_info(f"File search {arg} no matches found.")
        return None

    # Determine safe truncation limit: use MODEL_CONTEXT_WINDOW // 10 if available, else fallback to MAX_TOKEN_COUNT
    try:
        model_ctx = getattr(config, "MODEL_CONTEXT_WINDOW", None)
        if isinstance(model_ctx, int) and model_ctx > 0:
            SAFE_LIMIT = model_ctx // 10
        else:
            SAFE_LIMIT = getattr(config, "MAX_TOKEN_COUNT", 0)
            if not isinstance(SAFE_LIMIT, int):
                SAFE_LIMIT = int(SAFE_LIMIT) if SAFE_LIMIT else 0
    except Exception:
        SAFE_LIMIT = getattr(config, "MAX_TOKEN_COUNT", 0)
        try:
            SAFE_LIMIT = int(SAFE_LIMIT)
        except Exception:
            SAFE_LIMIT = 0

    # Truncate if needed
    if isinstance(grep_result, str) and SAFE_LIMIT > 0 and len(grep_result) > SAFE_LIMIT:
        original_bytes = len(grep_result.encode("utf-8"))
        truncated_part = grep_result[:SAFE_LIMIT]
        truncated_bytes = len(truncated_part.encode("utf-8"))
        bytes_removed = max(0, original_bytes - truncated_bytes)
        grep_result = f"{truncated_part}\n\n[TRUNCATED {bytes_removed} bytes of output]"
        logger.warning(
            "Truncated grep result: original %d bytes, after truncation %d bytes, removed %d bytes",
            original_bytes,
            truncated_bytes,
            bytes_removed,
        )

    print_func(grep_result)

    prompt = (
        f"Given the <search_key>{arg}</search_key>\n"
        f"And given the result:\n"
        f"<search_results>{grep_result}</search_results>\n\n"
        f"Explain how {arg} is used in the code of the search result."
    )

    return internalize_command(prompt)
