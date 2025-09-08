import subprocess
import logging

from monitor import config

logger = logging.getLogger(__name__)

# Send up to 15% of the input token window
SEARCH_EVALUATION_DIVISOR = 15

def ripgrep_search_tool(term, filetype=None, word=False):
    """
    A ripgrep_search wrapper, used by LLM as a tool call
    """
    result = ripgrep_search(term, filetype, '.', word)
    print(result)
    return result


def ripgrep_search(term, filetype=None, search_path='.', word=False):
    """
    Search for the term using ripgrep ('rg') with fixed-string matching (-F).

    This performs a literal search: the pattern is not treated as a regular expression.
    Regex is not supported by default; pass literal text as the search term.

    Args:
        term (str): The search term as literal text (not a regex).
        filetype (str, optional): A file extension or language type (e.g., 'py', 'js').
        search_path (str, optional): Path to search (default=current directory).
        word (bool, optional): If True, restrict matches to word boundaries (passes '-w' to ripgrep).
    Returns:
        str: The raw ripgrep search output.
    Raises:
        subprocess.CalledProcessError: For non-zero exit codes except 'no matches'.
    """
    cmd = ['rg', '-F', '--pretty', '--context=6']
    if filetype:
        cmd.extend(['-t', filetype])
    if word:
        cmd.append('-w')
    # Use '--' to ensure patterns starting with '-' are not treated as options, and place flags before pattern/path.
    cmd.extend(['--', term, search_path])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # don't raise error if no matches
        )
        # Check for unknown file type error (provide a clearer message than raw ripgrep output)
        if result.stderr:
            if ("unknown file type:" in result.stderr) or ("Unknown file type:" in result.stderr):
                return ("Error: Unknown file type '{}'. Please use a valid ripgrep file type (like 'py', 'js', etc) "
                        "or quote your search pattern if it contains spaces.").format(filetype)
        # Handle ripgrep usage/option errors with exit code 2 by returning stderr details
        if result.returncode == 2:
            stderr = result.stderr.strip() if result.stderr else ""
            details = stderr if stderr else "ripgrep reported a usage or option error (exit code 2)."
            return f"Error running ripgrep: {details}"

        # Safe truncation for very large outputs to avoid exceeding model context windows.
        stdout = result.stdout if result.stdout else ""
        try:
            # Use MODEL_CONTEXT_WINDOW if available, otherwise fall back to MAX_TOKEN_COUNT.
            model_window = getattr(config, 'MODEL_CONTEXT_WINDOW', None)
            if model_window:
                base_limit = int(model_window)
            else:
                base_limit = int(getattr(config, 'MAX_TOKEN_COUNT', 0) or 0)
        except Exception:
            base_limit = int(getattr(config, 'MAX_TOKEN_COUNT', 0) or 0)

        SAFE_LIMIT_CHARS = (int(base_limit) // SEARCH_EVALUATION_DIVISOR) * 4 if base_limit else 0

        if SAFE_LIMIT_CHARS > 0 and stdout:
            if len(stdout) > SAFE_LIMIT_CHARS:
                try:
                    num_bytes_truncated = len(stdout[SAFE_LIMIT_CHARS:].encode('utf-8'))
                except Exception:
                    num_bytes_truncated = max(0, len(stdout) - SAFE_LIMIT_CHARS)
                logger.warning(
                    "ripgrep output size %d exceeds SAFE_LIMIT %d; truncating to %d characters.",
                    len(stdout), SAFE_LIMIT_CHARS, SAFE_LIMIT_CHARS
                )
                return stdout[:SAFE_LIMIT_CHARS] + f"\n\n[TRUNCATED {num_bytes_truncated} bytes of output]"

        return result.stdout if result.stdout else f"No matches found. Searched for: {term}"
    except FileNotFoundError:
        return "Error running ripgrep: 'rg' (ripgrep) not found. Please install ripgrep and ensure it is on your PATH."
    except Exception as e:
        return f"Error running ripgrep: {e}"

import shlex

def grep_command(args):
    """
    Command handler for :rg or :grep
    Usage:
      :rg [-w|--word-regexp] <pattern> [filetype]
      :rg [-w|--word-regexp] "<multi word pattern>" [filetype]
      :rg [-w|--word-regexp] '<multi word pattern>' [filetype]
      :rg -- <pattern tokens that may look like options> [filetype]

    Notes:
      - Flags like -w/--word-regexp can appear anywhere BEFORE an unquoted "--".
      - Using "--" disables filetype inference: all non-flag tokens before and after "--" are treated as part of the pattern; do not provide a filetype when using "--".
      - Use the end-of-options marker "--" to stop option parsing; everything after an unquoted "--"
        is treated as a literal non-option argument (pattern/filetype), even if it looks like a flag.
      - Quoted tokens are never treated as flags. For example, "'-w'" or "\"--word-regexp\"" will be taken literally.
      - If the pattern is unquoted and there are multiple non-option tokens (and you are not using "--"), the last token is interpreted as the filetype.
        Otherwise, if the first non-option token is quoted, it is the entire pattern and the next token (if any) is the filetype.

    Examples:
      :rg -w foo py
      :rg "foo bar" py
      :rg -- "--word-regexp" py
      :rg -- "-w" "a b"
      :rg -- "foo bar baz"
    """
    args = args.strip()
    if not args:
        print(
            "Usage:\n"
            "  :rg [-w|--word-regexp] <pattern> [filetype]\n"
            "  :rg [-w|--word-regexp] \"<multi word pattern>\" [filetype]\n"
            "  :rg [-w|--word-regexp] '<multi word pattern>' [filetype]\n"
            "  :rg -- <pattern tokens that may look like options> [filetype]\n"
            "Notes:\n"
            "  - Flags like -w/--word-regexp can appear anywhere BEFORE an unquoted \"--\".\n"
            "  - Using \"--\" disables filetype inference: all non-flag tokens before and after \"--\" are treated as part of the pattern; do not provide a filetype when using \"--\".\n"
            "  - Use \"--\" to stop option parsing; tokens after it are treated literally.\n"
            "  - Quoted tokens are not treated as flags.\n"
            "  - If pattern is unquoted and multiple tokens are given (and you are not using \"--\"), the last token is treated as the filetype."
        )
        return

    # Use shlex with posix=False to retain quote characters in tokens for distinguishing quoted vs unquoted flags
    try:
        tokens = shlex.split(args, posix=False)
    except Exception:
        print(
            "Usage:\n"
            "  :rg [-w|--word-regexp] <pattern> [filetype]\n"
            "  :rg [-w|--word-regexp] \"<multi word pattern>\" [filetype]\n"
            "  :rg [-w|--word-regexp] '<multi word pattern>' [filetype]\n"
            "  :rg -- <pattern tokens that may look like options> [filetype]\n"
            "Notes:\n"
            "  - Flags like -w/--word-regexp can appear anywhere BEFORE an unquoted \"--\".\n"
            "  - Using \"--\" disables filetype inference: all non-flag tokens before and after \"--\" are treated as part of the pattern; do not provide a filetype when using \"--\".\n"
            "  - Use \"--\" to stop option parsing; tokens after it are treated literally.\n"
            "  - Quoted tokens are not treated as flags.\n"
            "  - If pattern is unquoted and multiple tokens are given (and you are not using \"--\"), the last token is treated as the filetype."
        )
        return

    def is_quoted(tok):
        return len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"')

    def unquote(tok):
        if is_quoted(tok):
            return tok[1:-1]
        return tok

    # Find unquoted end-of-options marker "--"
    eo_index = None
    for i, t in enumerate(tokens):
        if t == "--":
            eo_index = i
            break

    pre = tokens[:eo_index] if eo_index is not None else tokens
    post = tokens[eo_index + 1:] if eo_index is not None else []

    # Extract optional -w/--word-regexp flags only from pre, and only if not quoted
    word = False
    remaining_pre = []
    for t in pre:
        if not is_quoted(t) and t in ('-w', '--word-regexp'):
            word = True
        else:
            remaining_pre.append(t)

    # Remaining tokens: non-option args (pattern and optional filetype) or, when "--" is present, all non-flag tokens
    remaining_tokens = remaining_pre + post

    # If using "--", disable filetype inference and treat all non-flag tokens as the pattern
    if eo_index is not None:
        if not remaining_tokens:
            print(
                "Usage:\n"
                "  :rg [-w|--word-regexp] <pattern> [filetype]\n"
                "  :rg [-w|--word-regexp] \"<multi word pattern>\" [filetype]\n"
                "  :rg [-w|--word-regexp] '<multi word pattern>' [filetype]\n"
                "  :rg -- <pattern tokens that may look like options> [filetype]\n"
                "Notes:\n"
                "  - Flags like -w/--word-regexp can appear anywhere BEFORE an unquoted \"--\".\n"
                "  - Using \"--\" disables filetype inference: all non-flag tokens before and after \"--\" are treated as part of the pattern; do not provide a filetype when using \"--\".\n"
                "  - Use \"--\" to stop option parsing; tokens after it are treated literally.\n"
                "  - Quoted tokens are not treated as flags.\n"
                "  - If pattern is unquoted and multiple tokens are given (and you are not using \"--\"), the last token is treated as the filetype."
            )
            return
        pattern = ' '.join(unquote(t) for t in remaining_tokens)
        filetype = None
        output = ripgrep_search(pattern, filetype, word=word)
        return output

    if not remaining_tokens:
        print(
            "Usage:\n"
            "  :rg [-w|--word-regexp] <pattern> [filetype]\n"
            "  :rg [-w|--word-regexp] \"<multi word pattern>\" [filetype]\n"
            "  :rg [-w|--word-regexp] '<multi word pattern>' [filetype]\n"
            "  :rg -- <pattern tokens that may look like options> [filetype]\n"
            "Notes:\n"
            "  - Flags like -w/--word-regexp can appear anywhere BEFORE an unquoted \"--\".\n"
            "  - Using \"--\" disables filetype inference: all non-flag tokens before and after \"--\" are treated as part of the pattern; do not provide a filetype when using \"--\".\n"
            "  - Use \"--\" to stop option parsing; tokens after it are treated literally.\n"
            "  - Quoted tokens are not treated as flags.\n"
            "  - If pattern is unquoted and multiple tokens are given (and you are not using \"--\"), the last token is treated as the filetype."
        )
        return

    # Parse pattern and optional filetype from remaining tokens (when not using "--")
    if len(remaining_tokens) == 1:
        pattern = unquote(remaining_tokens[0])
        filetype = None
    else:
        if is_quoted(remaining_tokens[0]):
            # Quoted pattern: next token (if any) is filetype
            pattern = unquote(remaining_tokens[0])
            filetype = unquote(remaining_tokens[1]) if len(remaining_tokens) > 1 else None
        else:
            # Unquoted pattern: last token is filetype, rest (possibly mixed quoted/unquoted) form the pattern
            pattern_tokens = [unquote(t) for t in remaining_tokens[:-1]]
            pattern = ' '.join(pattern_tokens)
            filetype = unquote(remaining_tokens[-1])

    output = ripgrep_search(pattern, filetype, word=word)
    return output
