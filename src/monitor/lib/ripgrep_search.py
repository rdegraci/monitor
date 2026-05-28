import logging
import subprocess

from monitor import config

logger = logging.getLogger(__name__)

# Send up to 15% of the input token window
SEARCH_EVALUATION_DIVISOR = 15

# Cap search runtime so a ripgrep/grep over a huge tree can't hang the
# request-serialized harness indefinitely.
SEARCH_TIMEOUT_SECONDS = 30

DEFAULT_EXCLUDE_EXTENSIONS = []
DEFAULT_EXCLUDE_GLOBS = []

def _coerce_to_list(value: list[str] | tuple[str, ...] | str | None) -> list[str]:
    """Coerce a value into a list of strings.

    - None -> []
    - list/tuple -> list(...) (shallow copy)
    - single string -> split on commas, trim whitespace around each item,
      and return a list of non-empty strings.

    Examples:
        None -> []
        ["a", "b"] -> ["a", "b"]
        ("a", "b") -> ["a", "b"]
        "a,b, c ,  d" -> ["a", "b", "c", "d"]
        " single " -> ["single"]

    This helper is intentionally permissive and performs minimal transformation
    to ensure callers always receive a list for iteration/extension.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, str):
        # Split on commas, trim whitespace, and exclude empty items
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
    # Fallback: coerce any other scalar to string and return as single-item list
    return [str(value)]


def configure_rip_grep(default_exclude_extensions, default_exclude_globs):
    global DEFAULT_EXCLUDE_EXTENSIONS, DEFAULT_EXCLUDE_GLOBS

    # Note: Default excludes are always applied unless explicitly disabled.
    DEFAULT_EXCLUDE_EXTENSIONS = _coerce_to_list(default_exclude_extensions)
    DEFAULT_EXCLUDE_GLOBS = _coerce_to_list(default_exclude_globs)

def _normalize_exclude_extensions(exclude_extensions: list[str] | None) -> list[str]:
    """Normalize exclude extensions into ripgrep-compatible glob patterns.

    Converts a list of extensions (with or without leading dots) into a list of
    ripgrep exclude globs using negation, e.g. ["pyc", ".log"] -> ["!*.pyc", "!*.log"].

    Args:
        exclude_extensions: File extensions to exclude. Each item is coerced to string,
            stripped, and normalized (leading '.' removed). Empty and None values are
            ignored.

    Returns:
        A list of ripgrep-compatible exclude patterns (negated globs).
    """
    if not exclude_extensions:
        return []

    patterns: list[str] = []
    for ext in exclude_extensions:
        if ext is None:
            continue
        s = str(ext).strip()
        if not s:
            continue
        if s.startswith("."):
            s = s[1:]
        if not s:
            continue
        patterns.append(f"!*." f"{s}")
    return patterns


def _normalize_exclude_globs(exclude_globs: list[str] | None) -> list[str]:
    """Normalize exclude globs into ripgrep-compatible negated glob patterns.

    Ensures each glob begins with '!' to represent exclusion to ripgrep. If a glob
    already begins with '!', it is used as-is (after stripping). Empty and None values
    are ignored.

    Args:
        exclude_globs: Glob patterns to exclude. Each item is coerced to string and
            stripped. Empty and None values are ignored.

    Returns:
        A list of ripgrep-compatible exclude patterns (negated globs).
    """
    if not exclude_globs:
        return []

    patterns: list[str] = []
    for glob in exclude_globs:
        if glob is None:
            continue
        s = str(glob).strip()
        if not s:
            continue
        if s.startswith("!"):
            patterns.append(s)
        else:
            patterns.append(f"!{s}")
    return patterns


def _safe_truncate_output(tool_name: str, stdout: str) -> str:
    """Safely truncate large outputs to avoid exceeding model context windows.

    This uses config.MODEL_CONTEXT_WINDOW if available, otherwise falls back to
    config.MAX_TOKEN_COUNT. It keeps approximately 1/SEARCH_EVALUATION_DIVISOR of the
    window and converts token budget to a rough character budget by multiplying by 4.

    Args:
        tool_name: Name of the tool emitting the output (for log messages).
        stdout: The output to potentially truncate.

    Returns:
        The original output if within the safe limit, otherwise the truncated output
        with a truncation notice.
    """
    if not stdout:
        return stdout

    try:
        model_window = getattr(config, "MODEL_CONTEXT_WINDOW", None)
        if model_window:
            base_limit = int(model_window)
        else:
            base_limit = int(getattr(config, "MAX_TOKEN_COUNT", 0) or 0)
    except Exception:
        base_limit = int(getattr(config, "MAX_TOKEN_COUNT", 0) or 0)

    safe_limit_chars = (int(base_limit) // SEARCH_EVALUATION_DIVISOR) * 4 if base_limit else 0
    if safe_limit_chars <= 0:
        return stdout

    if len(stdout) <= safe_limit_chars:
        return stdout

    try:
        num_bytes_truncated = len(stdout[safe_limit_chars:].encode("utf-8"))
    except Exception:
        num_bytes_truncated = max(0, len(stdout) - safe_limit_chars)

    logger.warning(
        "%s output size %d exceeds SAFE_LIMIT %d; truncating to %d characters.",
        tool_name,
        len(stdout),
        safe_limit_chars,
        safe_limit_chars,
    )
    return stdout[:safe_limit_chars] + f"\n\n[TRUNCATED {num_bytes_truncated} bytes of output]"


def ripgrep_search_tool(
    term: str,
    filetype: str | None = None,
    word: bool = False,
    exclude_extensions: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    use_default_excludes: bool = True,
) -> str:
    """Run a ripgrep search as a tool-friendly wrapper.

    Args:
        term: The search term as literal text (not a regex).
        filetype: A file extension or language type (e.g., "py", "js").
        word: If True, restrict matches to word boundaries.
        exclude_extensions: List of file extensions to exclude (e.g., ["pyc", ".log"]).
        exclude_globs: List of globs to exclude (e.g., ["node_modules/**", "!*.min.js"]).
        use_default_excludes: If True, always apply DEFAULT_EXCLUDE_EXTENSIONS and
            DEFAULT_EXCLUDE_GLOBS in addition to any user-provided excludes.

    Returns:
        The raw search output (possibly truncated).
    """
    result = ripgrep_search(
        term,
        filetype=filetype,
        directory=".",
        word=word,
        exclude_extensions=exclude_extensions,
        exclude_globs=exclude_globs,
        use_default_excludes=use_default_excludes,
    )
    print(result)
    return result


def ripgrep_search(
    term: str,
    filetype: str | None = None,
    directory: str = ".",
    word: bool = False,
    exclude_extensions: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    use_default_excludes: bool = True,
) -> str:
    """Search for a literal term using ripgrep ("rg") with fixed-string matching.

    This performs a literal search: the pattern is not treated as a regular expression.

    Behavior:
        - Uses fixed-string matching (-F).
        - Uses "--context=6".
        - Adds exclude patterns via "-g" using negated globs.
        - Returns a friendlier error for unknown ripgrep filetype.
        - Returns stderr details for ripgrep usage/option errors (exit code 2).
        - Safely truncates very large output.

    Args:
        term: The search term as literal text (not a regex).
        filetype: A file extension or language type (e.g., "py", "js").
        directory: Directory to search.
        word: If True, restrict matches to word boundaries (passes "-w").
        exclude_extensions: List of file extensions to exclude (e.g., ["pyc", ".log"]).
        exclude_globs: List of globs to exclude (e.g., ["node_modules/**", "!*.min.js"]).
        use_default_excludes: If True, always apply DEFAULT_EXCLUDE_EXTENSIONS and
            DEFAULT_EXCLUDE_GLOBS in addition to any user-provided excludes.

    Returns:
        The raw ripgrep output (possibly truncated) or a friendly no-matches message.
        If ripgrep is not available, falls back to grep.

    Raises:
        subprocess.CalledProcessError: Not raised (subprocess.run check=False). Included
            for API compatibility expectations.
    """
    cmd = ["rg", "-F", "--pretty", "--context=6"]
    if filetype:
        cmd.extend(["-t", filetype])
    if word:
        cmd.append("-w")

    effective_exclude_extensions: list[str] = []
    effective_exclude_globs: list[str] = []
    if use_default_excludes:
        effective_exclude_extensions.extend(DEFAULT_EXCLUDE_EXTENSIONS or [])
        effective_exclude_globs.extend(DEFAULT_EXCLUDE_GLOBS or [])
    if exclude_extensions:
        effective_exclude_extensions.extend(exclude_extensions)
    if exclude_globs:
        effective_exclude_globs.extend(exclude_globs)

    exclude_patterns = _normalize_exclude_extensions(
        effective_exclude_extensions or None
    ) + _normalize_exclude_globs(effective_exclude_globs or None)
    for pat in exclude_patterns:
        cmd.extend(["-g", pat])

    # Use '--' to ensure patterns starting with '-' are not treated as options, and
    # place flags before pattern/path.
    cmd.extend(["--", term, directory])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,  # don't raise error if no matches
            timeout=SEARCH_TIMEOUT_SECONDS,
        )

        # Provide a clearer message than raw ripgrep output when filetype is unknown.
        if result.stderr and (
            ("unknown file type:" in result.stderr) or ("Unknown file type:" in result.stderr)
        ):
            return (
                "Error: Unknown file type '{}'. Please use a valid ripgrep file type (like 'py', 'js', etc) "
                "or quote your search pattern if it contains spaces."
            ).format(filetype)

        # ripgrep exit code 2 indicates usage/option errors; surface stderr details.
        if result.returncode == 2:
            stderr = result.stderr.strip() if result.stderr else ""
            details = stderr if stderr else "ripgrep reported a usage or option error (exit code 2)."
            return f"Error running ripgrep: {details}"

        stdout = result.stdout if result.stdout else ""
        stdout = _safe_truncate_output("ripgrep", stdout)

        if stdout:
            return stdout
        return f"No matches found. Searched for: {term}"
    except subprocess.TimeoutExpired:
        return f"Error running ripgrep: search timed out after {SEARCH_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        # Fallback to grep if ripgrep is unavailable.
        try:
            return grep_search(
                term,
                filetype=filetype,
                directory=directory,
                word=word,
                exclude_extensions=exclude_extensions,
                exclude_globs=exclude_globs,
                use_default_excludes=use_default_excludes,
            )
        except FileNotFoundError:
            return (
                "Error: neither ripgrep ('rg') nor grep is available. "
                "Please install ripgrep (preferred) or grep and ensure it is on your PATH."
            )
    except Exception as e:
        return f"Error running ripgrep: {e}"


def grep_search(
    term: str,
    filetype: str | None = None,
    directory: str = ".",
    word: bool = False,
    exclude_extensions: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    use_default_excludes: bool = True,
) -> str:
    """Search for a literal term using grep with recursive fixed-string matching.

    This performs a literal search: the pattern is not treated as a regular expression.

    Behavior:
        - Uses fixed-string matching (-F) and includes line numbers (-n).
        - Uses "-C 6" for context.
        - Supports include filtering based on filetype (extension or glob).
        - Supports exclusions via --exclude patterns (from extension and globs).
        - Safely truncates very large output.
        - Returns friendly no-matches message for exit code 1.

    Args:
        term: The search term as literal text (not a regex).
        filetype: A file extension or glob to include. If it does not contain wildcards,
            it is interpreted as an extension and converted to an include glob like
            "*.ext". For example, "py" or ".py" becomes "*.py".
        directory: Directory to search.
        word: If True, restrict matches to word boundaries (passes "-w").
        exclude_extensions: List of file extensions to exclude (e.g., ["pyc", ".log"]).
        exclude_globs: List of globs to exclude (e.g., ["node_modules/**", "!*.min.js"]).
        use_default_excludes: If True, always apply DEFAULT_EXCLUDE_EXTENSIONS and
            DEFAULT_EXCLUDE_GLOBS in addition to any user-provided excludes.

    Returns:
        The raw grep output (possibly truncated) or a friendly message if no matches.

    Raises:
        FileNotFoundError: If the "grep" executable is not available.
    """
    cmd = ["grep", "-R", "-n", "-F", "-I", "-C", "6"]

    if filetype:
        ftype = str(filetype).strip()
        if "*" in ftype or "?" in ftype:
            include_glob = ftype
        elif ftype.startswith("."):
            include_glob = f"*{ftype}"
        else:
            include_glob = f"*.{ftype}"
        cmd.extend(["--include", include_glob])

    effective_exclude_extensions: list[str] = []
    effective_exclude_globs: list[str] = []
    if use_default_excludes:
        effective_exclude_extensions.extend(DEFAULT_EXCLUDE_EXTENSIONS or [])
        effective_exclude_globs.extend(DEFAULT_EXCLUDE_GLOBS or [])
    if exclude_extensions:
        effective_exclude_extensions.extend(exclude_extensions)
    if exclude_globs:
        effective_exclude_globs.extend(exclude_globs)

    exclude_patterns = _normalize_exclude_extensions(
        effective_exclude_extensions or None
    ) + _normalize_exclude_globs(effective_exclude_globs or None)
    for pat in exclude_patterns:
        normalized = pat[1:] if pat.startswith("!") else pat
        if normalized:
            cmd.extend(["--exclude", normalized])

    if word:
        cmd.append("-w")

    # Use '-e' to ensure patterns starting with '-' are not treated as options.
    # Use '--' to end option parsing before the search path.
    cmd.extend(["-e", term, "--", directory])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )

        if result.returncode == 1:
            return f"No matches found. Searched for: {term}"
        if result.returncode not in (0, 1):
            stderr = result.stderr.strip() if result.stderr else ""
            details = stderr if stderr else "grep reported an error."
            return f"Error running grep: {details}"

        stdout = result.stdout if result.stdout else ""
        stdout = _safe_truncate_output("grep", stdout)

        if stdout:
            return stdout
        return f"No matches found. Searched for: {term}"
    except subprocess.TimeoutExpired:
        return f"Error running grep: search timed out after {SEARCH_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        raise
    except Exception as e:
        return f"Error running grep: {e}"


def build_usage_text() -> str:
    """Build the usage and notes help text for the :rg command.

    Returns:
        A formatted multi-line string describing usage, notes, and examples.
    """
    return (
        "Usage:\n"
        "  :rg [-w|--word-regexp] [--no-default-excludes] [--exclude-ext <comma-separated>] [--exclude-glob <glob>] <pattern> [filetype]\n"
        '  :rg [-w|--word-regexp] [--no-default-excludes] [--exclude-ext <comma-separated>] [--exclude-glob <glob>] "<multi word pattern>" [filetype]\n'
        "  :rg [-w|--word-regexp] [--no-default-excludes] [--exclude-ext <comma-separated>] [--exclude-glob <glob>] '<multi word pattern>' [filetype]\n"
        '  :rg [--no-default-excludes] [--exclude-ext <comma-separated>] [--exclude-glob <glob>] -- <pattern tokens that may look like options>\n'
        "\n"
        "Notes:\n"
        '  - Flags like -w/--word-regexp and --no-default-excludes can appear anywhere BEFORE an unquoted "--".\n'
        "  - By default, common binary/large extensions and common build/venv directories are excluded.\n"
        "  - Exclude flags (--exclude-ext/--exclude-glob) can be repeated and apply whether or not filetype "
        "inference is used.\n"
        '  - Using "--" disables filetype inference: all non-flag tokens before and after "--" are treated as part '
        "of the pattern; do not provide a filetype when using \"--\".\n"
        '  - Use the end-of-options marker "--" to stop option parsing; everything after an unquoted "--" is treated '
        "as a literal non-option argument (pattern), even if it looks like a flag.\n"
        '  - Quoted tokens are never treated as flags. For example, "\'-w\'" or \'"--word-regexp"\' will be taken '
        "literally.\n"
        '  - If the pattern is unquoted and there are multiple non-option tokens (and you are not using "--"), the '
        "last token is interpreted as the filetype.\n"
        "    Otherwise, if the first non-option token is quoted, it is the entire pattern and the next token (if "
        "any) is the filetype.\n"
        "\n"
        "Examples:\n"
        "  :rg -w foo py\n"
        '  :rg "foo bar" py\n'
        "  :rg --exclude-ext pyc,log foo\n"
        "  :rg --exclude-glob node_modules/** --exclude-glob '*.min.js' foo js\n"
        "  :rg --no-default-excludes foo\n"
        '  :rg -- "--word-regexp"\n'
        '  :rg -- "-w" "a b"\n'
        '  :rg -- "foo bar baz"\n'
    )


def grep_command(args: str) -> str | None:
    """Run a ripgrep/grep search parsed from a :rg pseudo-command.

    Parses flags and pattern/filetype tokens to run ripgrep with fixed-string matching
    and safe output truncation.

    Supported flags:
        - -w / --word-regexp
        - --no-default-excludes
        - --exclude-ext <comma-separated> (repeatable)
        - --exclude-glob <glob> (repeatable)
        - -- end-of-options marker (unquoted)

    Parsing rules:
        - Flags can appear anywhere before an unquoted "--".
        - Quoted tokens are never treated as flags.
        - Without "--":
            - If multiple unquoted non-flag tokens remain, the last token is treated as
              filetype and the preceding tokens form the pattern.
            - If the first remaining token is quoted, that token is the whole pattern
              and the next token (if any) is the filetype.
        - With "--":
            - All remaining tokens (before/after "--") are treated as part of the
              literal pattern; filetype inference is disabled.

    Args:
        args: Raw argument string after ":rg".

    Returns:
        Raw search output, or None if only usage/help was printed.
    """
    args = args.strip() if args is not None else ""
    if not args:
        print(build_usage_text())
        return None

    try:
        # posix=False retains quote characters in tokens so we can distinguish quoted
        # tokens from unquoted flags.
        import shlex

        tokens = shlex.split(args, posix=False)
    except Exception:
        print(build_usage_text())
        return None

    def is_quoted(tok: str) -> bool:
        return len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"')

    def unquote(tok: str) -> str:
        if is_quoted(tok):
            return tok[1:-1]
        return tok

    eo_index: int | None = None
    for i, t in enumerate(tokens):
        if t == "--":
            eo_index = i
            break

    pre = tokens[:eo_index] if eo_index is not None else tokens
    post = tokens[eo_index + 1 :] if eo_index is not None else []

    word = False
    use_default_excludes = True
    exclude_extensions: list[str] = []
    exclude_globs: list[str] = []
    remaining_pre: list[str] = []

    i = 0
    while i < len(pre):
        t = pre[i]

        if not is_quoted(t) and t in ("-w", "--word-regexp"):
            word = True
            i += 1
            continue

        if not is_quoted(t) and t == "--no-default-excludes":
            use_default_excludes = False
            i += 1
            continue

        if not is_quoted(t) and t == "--exclude-ext":
            if i + 1 >= len(pre):
                print(build_usage_text())
                return None
            value = pre[i + 1]
            raw = unquote(value)
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            exclude_extensions.extend(parts)
            i += 2
            continue

        if not is_quoted(t) and t == "--exclude-glob":
            if i + 1 >= len(pre):
                print(build_usage_text())
                return None
            value = pre[i + 1]
            exclude_globs.append(unquote(value))
            i += 2
            continue

        remaining_pre.append(t)
        i += 1

    remaining_tokens = remaining_pre + post
    if not remaining_tokens:
        print(build_usage_text())
        return None

    if eo_index is not None:
        pattern = " ".join(unquote(t) for t in remaining_tokens)
        filetype = None
    else:
        if len(remaining_tokens) == 1:
            pattern = unquote(remaining_tokens[0])
            filetype = None
        else:
            if is_quoted(remaining_tokens[0]):
                pattern = unquote(remaining_tokens[0])
                filetype = unquote(remaining_tokens[1]) if len(remaining_tokens) > 1 else None
            else:
                filetype = unquote(remaining_tokens[-1])
                pattern = " ".join(unquote(t) for t in remaining_tokens[:-1])

    output = ripgrep_search(
        pattern,
        filetype=filetype,
        directory=".",
        word=word,
        exclude_extensions=exclude_extensions or None,
        exclude_globs=exclude_globs or None,
        use_default_excludes=use_default_excludes,
    )
    return output
