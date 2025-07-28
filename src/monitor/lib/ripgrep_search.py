
import subprocess

def ripgrep_search(term, filetype=None, search_path='.'):
    """
    Search for the term using ripgrep ('rg').
    Args:
        term (str): The search term (regex or plain text).
        filetype (str, optional): A file extension or language type (e.g., 'py', 'js').
        search_path (str, optional): Path to search (default=current directory).
    Returns:
        str: The raw ripgrep search output.
    Raises:
        FileNotFoundError: If ripgrep is not installed.
        subprocess.CalledProcessError: For non-zero exit codes except 'no matches'.
    """
    cmd = ['rg', '--pretty', '--context=6', term, search_path]
    if filetype:
        cmd.extend(['-t', filetype])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # don't raise error if no matches
        )
        if result.returncode == 2:
            raise FileNotFoundError("Quote your search pattern if it contains spaces.")
        # Check for unknown filetype error
        if result.stderr:
            if ("unknown file type:" in result.stderr) or ("Unknown file type:" in result.stderr):
                return ("Error: Unknown file type '{}'. Please use a valid ripgrep file type (like 'py', 'js', etc) "
                        "or quote your search pattern if it contains spaces.").format(filetype)
        return result.stdout if result.stdout else "No matches found."
    except Exception as e:
        return f"Error running ripgrep: {e}"

import shlex

def grep_command(args):
    """
    Command handler for :rg or :grep
    Usage: :rg <pattern> [filetype]
           :rg \"<multi word pattern>\" [filetype]
           :rg '<multi word pattern>' [filetype]
    Pattern can be quoted or unquoted; if unquoted and multiple tokens, last token is filetype.
    Note: If you specify an invalid filetype, you will receive an error like:
      Error: Unknown file type '<filetype>'. Please use a valid ripgrep file type (like 'py', 'js', etc) or quote your search pattern if it contains spaces.
    """
    args = args.strip()
    if not args:
        print("Usage: :rg <pattern> [filetype]\n"
              "       :rg \"<multi word pattern>\" [filetype]\n"
              "       :rg '<multi word pattern>' [filetype]\n"
              "  (If unquoted and more than one token, last token is interpreted as the filetype.)")
        return

    # Use shlex to intelligently split arguments with quotes handling
    try:
        tokens = shlex.split(args)
    except Exception:
        print("Usage: :rg <pattern> [filetype]\n"
              "       :rg \"<multi word pattern>\" [filetype]\n"
              "       :rg '<multi word pattern>' [filetype]\n"
              "  (If unquoted and more than one token, last token is interpreted as the filetype.)")
        return

    pattern = None
    filetype = None

    if not tokens:
        print("Usage: :rg <pattern> [filetype]\n"
              "       :rg \"<multi word pattern>\" [filetype]\n"
              "       :rg '<multi word pattern>' [filetype]\n"
              "  (If unquoted and more than one token, last token is interpreted as the filetype.)")
        return

    if len(tokens) == 1:
        pattern = tokens[0]
        filetype = None
    else:
        # Check if original args string used quotes for first token(s)
        # If tokens[0] is quoted, shlex will have taken out the quotes, but that's fine:
        # If args starts with a quote, everything until matching unescaped quote is the pattern.
        # Otherwise: If no quotes, treat last token as filetype, rest as pattern
        if args[0] == '"' or args[0] == "'":
            # Quoted pattern
            pattern = tokens[0]
            filetype = tokens[1] if len(tokens) > 1 else None
        else:
            # Not quoted, treat last as filetype
            pattern = ' '.join(tokens[:-1])
            filetype = tokens[-1]

    output = ripgrep_search(pattern, filetype)
    return output


