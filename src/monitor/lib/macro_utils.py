"""Contains stateless macro helpers for loading, updating, and recursive expansion. No macro state, config, or CLI integration here.

TRUST MODEL (see also: monitor.lib.macros docstring)
---------------------------------------------------
``tcl_macro_expand`` invokes ``tkinter.Tcl().eval(...)`` on macro bodies, which
is full Tcl code execution — not a sandboxed templating language. Tcl scripts
can ``exec`` shell commands, touch the filesystem, and read environment
variables. Treat any macros file or runtime-added macro as executable code,
not configuration. This is the single boundary to gate if you ever need to
expand macros from a less-trusted source.
"""

import json
import logging
import os
import re

from monitor.lib.colors import print_blue

logger = logging.getLogger(__name__)

# MAC-3: tkinter is imported lazily inside tcl_macro_expand so that environments
# without python3-tk installed (headless servers, slim Docker images, CI
# containers) can still use the macro subsystem for non-Tcl macros. Module-level
# import here previously broke the entire CLI startup chain on those systems.
#
# MAC-8: Cached Tcl interpreter. tkinter.Tcl() allocation is non-trivial, and
# re-creating one per macro evaluation is wasteful. We cache one interpreter
# and re-bind the `puts` command on each call (because the result_output
# closure differs per call). State (variables, procs) set by user Tcl code
# persists between macro evaluations — same as a long-running tclsh session.
_TCL_INTERP = None
_TCL_IMPORT_ERROR = None  # cached so we surface the import failure once, clearly


def _get_tcl_interpreter():
    """Return a cached tkinter.Tcl() interpreter, importing tkinter lazily.

    Returns None and logs a clear error if tkinter is not available. Callers
    must handle the None return gracefully.
    """
    global _TCL_INTERP, _TCL_IMPORT_ERROR
    if _TCL_INTERP is not None:
        return _TCL_INTERP
    if _TCL_IMPORT_ERROR is not None:
        return None
    try:
        import tkinter
    except Exception as e:
        _TCL_IMPORT_ERROR = e
        logger.error(
            "tkinter (Python Tk bindings) is required for {{tcl ...}} macros "
            "but could not be imported: %s. Install your platform's python3-tk "
            "package, or avoid Tcl macros. Non-Tcl macros continue to work.",
            e,
        )
        return None
    try:
        _TCL_INTERP = tkinter.Tcl()
        return _TCL_INTERP
    except Exception as e:
        _TCL_IMPORT_ERROR = e
        logger.error("Failed to create Tcl interpreter: %s", e, exc_info=True)
        return None


def _load_raw_macro_file_object(macro_file_path):
    """Load and validate the raw top-level JSON object from a macros file.

    Missing files are treated as an empty object. Malformed JSON is logged and
    echoed to stderr, then treated as an empty object. Non-dict top-level JSON
    values are rejected and treated as an empty object.

    Args:
        macro_file_path (str): The path to the JSON macro file.

    Returns:
        dict: The raw top-level JSON object, or an empty dict if the file is
            missing, invalid, or not a JSON object.
    """
    logger.debug(
        "Entering _load_raw_macro_file_object with file path: %s", macro_file_path
    )
    expanded_path = os.path.expanduser(macro_file_path)
    try:
        with open(expanded_path, "r") as f:
            loaded = json.load(f)
    except FileNotFoundError:
        logger.debug("Macros file not found at %s; using empty macro set", expanded_path)
        return {}
    except json.JSONDecodeError as e:
        msg = (
            f"Macros file at {expanded_path} has invalid JSON ({e.msg} at "
            f"line {e.lineno} col {e.colno}); no custom macros loaded. "
            f"Run :edit_macros to fix."
        )
        logger.error(msg)
        try:
            import sys

            print(msg, file=sys.stderr)
        except Exception:
            pass
        return {}

    if not isinstance(loaded, dict):
        msg = (
            f"Macros file at {expanded_path} must contain a top-level JSON "
            f"object; no custom macros loaded. Run :edit_macros to fix."
        )
        logger.error(msg)
        try:
            import sys

            print(msg, file=sys.stderr)
        except Exception:
            pass
        return {}

    return loaded


def load_additional_macro_metadata(macro_file_path):
    """Load reserved metadata sections from a macros JSON file.

    Reserved top-level keys are:
      - ``_groups`` -> returned as ``groups``
      - ``_macro_meta`` -> returned as ``macro_meta``

    Missing reserved keys, or keys with non-dict values, are returned as empty
    dictionaries.

    Args:
        macro_file_path (str): The path to the JSON macro file.

    Returns:
        dict: A dictionary with keys ``groups`` and ``macro_meta``.
    """
    logger.debug(
        "Entering load_additional_macro_metadata with file path: %s",
        macro_file_path,
    )
    raw_macros = _load_raw_macro_file_object(macro_file_path)

    groups = raw_macros.get("_groups", {})
    if not isinstance(groups, dict):
        logger.warning(
            "Ignoring reserved _groups metadata in %s because it is not a JSON object",
            os.path.expanduser(macro_file_path),
        )
        groups = {}

    macro_meta = raw_macros.get("_macro_meta", {})
    if not isinstance(macro_meta, dict):
        logger.warning(
            "Ignoring reserved _macro_meta metadata in %s because it is not a JSON object",
            os.path.expanduser(macro_file_path),
        )
        macro_meta = {}

    return {"groups": groups, "macro_meta": macro_meta}


def load_additional_macros(macro_file_path):
    """Load executable macros from a specified JSON file.

    Reserved metadata keys beginning with ``_`` are excluded from the returned
    macro set. Only string-valued entries are treated as executable macros to
    avoid accidentally loading structured metadata as macro bodies.

    MAC-7: a missing file is silently treated as "no additional macros" (the
    common case for users who haven't created one). A *malformed* file is
    surfaced to stderr in addition to the log so the user notices that their
    custom macros disappeared because of a syntax error.

    Args:
        macro_file_path (str): The path to the JSON macro file.

    Returns:
        dict: Dictionary of executable macros loaded from the JSON macro file,
            or an empty dictionary if loading failed.
    """
    logger.debug(
        "Entering load_additional_macros with file path: %s", macro_file_path
    )
    raw_macros = _load_raw_macro_file_object(macro_file_path)
    executable_macros = {
        key: value
        for key, value in raw_macros.items()
        if not key.startswith("_") and isinstance(value, str)
    }
    return executable_macros


def update_macros(store, macros):
    """Update an existing macros store in-place with new macro entries.

    WARNING: This function modifies the store dictionary in place.

    Args:
        store (dict): The target dictionary to update with new macros.
        macros (dict): The new macro definitions to merge into store.

    Returns:
        None
    """
    logger.debug("Entering update_macros with %d macro items", len(macros))
    store.update(macros)


def recursive_macro_expand(macro, values, delim_open, delim_close, delim_escape):
    """Recursively expand macros within an expression using configurable delimiters.

    Now supports special TCL macro syntax: a macro string of the form (/tcl ...), with
    optional whitespace, will have its "..." body recursively expanded for further
    macros, then evaluated as TCL code using an embedded interpreter. Output from
    'puts' will be used as the result of the macro substitution. TCL macro expansion
    result is then substituted into enclosing macros as usual. If TCL execution fails,
    the error message is reported as [TCL ERROR: ...].

    Also supports bare 'tcl ...' form at the beginning of a macro value, without need for
    surrounding parens.

    Escape delimiters (delim_escape) will cause the immediate subsequent delimiters to
    be treated as literals, not as macro boundaries.

    The macro start and end delimiters, as well as escape prefix, are provided
    externally as arguments. Macro expansion logic is fully generic to handle any
    delimiter strings (not just single characters).

    Supports literal delimiter escape sequences in macro expansions: any instance of delim_escape
    followed by delim_open or delim_close  is treated as a literal character rather than as
    a macro boundary, and macro expansion is NOT performed inside such escape sequences.

    Args:
        macro (str): The macro expression to expand.
        values (dict): Dictionary of macro definitions to use for expansion.
        delim_open (str): String marking start of macro.
        delim_close (str): String marking end of macro.
        delim_escape (str): Escape sequence for literals.

    Returns:
        str: The fully expanded macro expression, including TCL macro evaluation when encountered.
    """
    logger.debug("Entering recursive_macro_expand with macro: %s", macro)

    open_escaped = re.escape(delim_open)
    close_escaped = re.escape(delim_close)
    TCL_MACRO_MAIN_REGEX = re.compile(
        rf"^\s*(?:{open_escaped}tcl\s+(.+){close_escaped}|tcl\s+(.+))\s*$",
        re.DOTALL,
    )

    def _looks_like_tcl_macro(text, pos):
        """Return True iff text starting at pos begins with whitespace+'tcl'+(whitespace or end).

        Used by the outer brace scanner to decide whether to switch from
        macro-delimiter nesting to Tcl-aware brace nesting at the macro
        boundary.
        """
        n = len(text)
        # Skip leading whitespace
        while pos < n and text[pos] in " \t\n\r":
            pos += 1
        if not text.startswith("tcl", pos):
            return False
        after = pos + 3
        return after == n or text[after] in " \t\n\r"

    def _find_tcl_aware_close(body, start_pos, dclose, descape):
        """Find the macro close `dclose` at Tcl-brace-depth 0 from start_pos.

        Walks `body` tracking Tcl `{` / `}` nesting. Honors backslash escapes:
          - `\\{` and `\\}` are literal Tcl braces (no depth change).
          - `\\<dclose>` is a literal macro-close (not a real close).
        Returns the index where `dclose` begins, or -1 if no balanced close.

        Limitation: braces inside Tcl double-quoted strings ARE counted toward
        depth. Practical Tcl macros with balanced braces in strings still work;
        only unbalanced braces inside strings would fail. Real Tcl parsing
        treats string-internal braces as literal, but that requires a full
        Tcl tokenizer; this heuristic covers the common cases.
        """
        depth = 0
        i = start_pos
        n = len(body)
        close_len = len(dclose)
        while i < n:
            # Macro-engine escape on the close delim: \}}
            if (
                body[i : i + len(descape)] == descape
                and body[i + len(descape) : i + len(descape) + close_len] == dclose
            ):
                i += len(descape) + close_len
                continue
            # Tcl-style backslash escape on a single brace: \{ or \}
            if body[i] == "\\" and i + 1 < n and body[i + 1] in "{}":
                i += 2
                continue
            # Macro close at Tcl depth 0?
            if depth == 0 and body[i : i + close_len] == dclose:
                return i
            # Tcl brace tracking
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth < 0:
                    # Malformed: more } than { before reaching macro close.
                    return -1
            i += 1
        return -1

    def unescape_literal_parens(text):
        """Unescape any delim-escaped parentheses and general delimiters, converting them to literal characters.
        Macro recursion/expansion is NEVER done inside these escapes.
        """
        # Replace instances of delim_escape + delim_open with literal delim_open.
        # Replace instances of delim_escape + delim_close with literal delim_close.
        text = text.replace(delim_escape + delim_open, delim_open)
        text = text.replace(delim_escape + delim_close, delim_close)
        return text

    def count_balanced_escaped_delims(text):
        """Return True if escaped delimiters (delim_escape+delim_open, delim_escape+delim_close) are balanced; else False.

        Also returns specific counts for error messages.
        """
        count_open = 0
        count_close = 0
        idx = 0
        while idx < len(text):
            if text.startswith(delim_escape + delim_open, idx):
                count_open += 1
                idx += len(delim_escape + delim_open)
            elif text.startswith(delim_escape + delim_close, idx):
                count_close += 1
                idx += len(delim_escape + delim_close)
            else:
                idx += 1
        return (count_open == count_close), count_open, count_close

    def find_next_delim(s, delim, start=0):
        """Return (pos, False) for the next instance of delim >= start (not counting escaped).

        Will skip delim occurrences that are preceded by delim_escape.
        """
        while True:
            idx = s.find(delim, start)
            if idx == -1:
                return -1, False
            if (
                idx >= len(delim_escape)
                and s[idx - len(delim_escape) : idx] == delim_escape
            ):
                start = idx + len(delim)
                continue
            return idx, False

    def tcl_macro_expand(tcl_code_body, log_info=None, macro_for_logging=None):
        # INPUT VALIDATION: check balance of escaped delimiters in tcl_code_body
        balanced, open_count, close_count = count_balanced_escaped_delims(
            tcl_code_body
        )
        if not balanced:
            logger.error(
                "Unbalanced escaped delimiters in TCL macro body. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                open_count,
                delim_escape + delim_open,
                close_count,
                delim_escape + delim_close,
                tcl_code_body,
            )
            return "[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]".format(
                tcl_code_body
            )
        try:
            # Only unescape delim_escape+delim_open and delim_escape+delim_close to literal delimiters in TCL.
            # Do NOT perform any macro expansion within the TCL macro body itself; all other escapes are left untouched.
            tcl_code_inner = tcl_code_body.replace(
                delim_escape + delim_open, delim_open
            )
            tcl_code_inner = tcl_code_inner.replace(
                delim_escape + delim_close, delim_close
            )

            # INPUT VALIDATION: check balance again after unescaping
            balanced2, open_count2, close_count2 = count_balanced_escaped_delims(
                tcl_code_inner
            )
            if not balanced2:
                logger.error(
                    "Unbalanced escaped delimiters after unescaping in TCL macro. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                    open_count2,
                    delim_escape + delim_open,
                    close_count2,
                    delim_escape + delim_close,
                    tcl_code_inner,
                )
                return "[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]".format(
                    tcl_code_inner
                )

            # GUARD: Skip TCL evaluation if code is empty, whitespace, or just '...'
            if not tcl_code_inner.strip() or tcl_code_inner.strip() == "...":
                logger.error(
                    "Skipping TCL macro evaluation: code is empty or a placeholder ('...') (code: %r, in macro: %r)",
                    tcl_code_inner,
                    macro_for_logging,
                )
                return ""

            try:
                tk_interp = _get_tcl_interpreter()
                if tk_interp is None:
                    return "[TCL ERROR: Tcl interpreter unavailable (tkinter not installed)]"
                result_output = []

                def python_puts(*args):
                    # Concatenate given arguments like standard TCL puts
                    joined = " ".join(str(a) for a in args)
                    result_output.append(joined)

                # Re-bind on every call so the closure captures THIS call's
                # result_output list. tkinter.createcommand overwrites an
                # existing command with the same name, which is the behavior
                # we want with a cached interpreter.
                tk_interp.createcommand("puts", python_puts)

                try:
                    if log_info:
                        logger.info(log_info)
                    else:
                        logger.info(
                            "Expanding macro as TCL (bare or (/tcl ...)): %s",
                            tcl_code_inner,
                        )
                    tk_interp.eval(tcl_code_inner)
                except Exception as e_inner:
                    logger.error(
                        "TCL execution error: %s", str(e_inner), exc_info=True
                    )
                    return "[TCL ERROR: {}]".format(str(e_inner))
                joined_output = "\n".join(result_output)
                return joined_output
            except Exception as e:
                logger.error("TCL execution failed: %s", str(e), exc_info=True)
                return "[TCL ERROR: {}]".format(str(e))
        except Exception as e_outer:
            logger.error(
                "Error doing TCL macro expansion: %s", str(e_outer), exc_info=True
            )
            return "[TCL ERROR: {}]".format(str(e_outer))

    # MAC-9: bound on nested-delimiter recursion depth. Pathological inputs
    # like 100k nested `{{...}}` would otherwise blow the Python stack with
    # RecursionError. 64 is well above any legitimate use case.
    MAX_RECURSION_DEPTH = 64

    def expand_inner_expression(expression, macro_context=None, _depth=0):
        """Main recursive parser for macro expanding innermost occurrence.

        Args:
            expression (str): The macro expression.
            macro_context: Original macro string for error logging.
            _depth (int): Internal recursion depth counter; bail at MAX_RECURSION_DEPTH.

        Returns:
            tuple[str, bool, bool]: (New expression, whether any expansion occurred, is_terminal)
        """
        if _depth > MAX_RECURSION_DEPTH:
            logger.error(
                "Macro expansion exceeded recursion depth %d; aborting. Expression head: %r",
                MAX_RECURSION_DEPTH,
                expression[:120],
            )
            return (
                "[MACRO ERROR: max recursion depth {} exceeded]".format(
                    MAX_RECURSION_DEPTH
                ),
                True,
                True,
            )
        try:
            idx_open, _ = find_next_delim(expression, delim_open)
            if idx_open == -1:
                expr_stripped = expression.strip()

                # TCL macro detection -- legacy parens or bare form
                tcl_match = TCL_MACRO_MAIN_REGEX.match(expr_stripped)
                if tcl_match:
                    # Extract inner code, supporting both (/tcl ...) and tcl ... (bare)
                    tcl_body = (
                        tcl_match.group(1)
                        if tcl_match.group(1) is not None
                        else tcl_match.group(2)
                    )
                    log_detail = "Detected TCL macro via {} syntax. TCL body: {}".format(
                        "(tcl ...)"
                        if tcl_match.group(1) is not None
                        else "bare tcl ...",
                        tcl_body,
                    )
                    logger.debug(log_detail)
                    tcl_result = tcl_macro_expand(
                        tcl_body,
                        log_info=log_detail,
                        macro_for_logging=(
                            macro if macro_context is None else macro_context
                        ),
                    )
                    final_expanded = tcl_result
                    return final_expanded, True, True

                # Normal macro value: look up in macro store and check for TCL
                expanded = values.get(expr_stripped, expr_stripped)
                expanded_stripped = str(expanded).strip()
                # Detect TCL macro form after expansion as well!
                tcl_match_after = TCL_MACRO_MAIN_REGEX.match(expanded_stripped)
                if tcl_match_after:
                    tcl_body = (
                        tcl_match_after.group(1)
                        if tcl_match_after.group(1) is not None
                        else tcl_match_after.group(2)
                    )
                    log_detail = "Detected TCL macro in macro store value via {} syntax. TCL body: {}".format(
                        "(tcl ...)"
                        if tcl_match_after.group(1) is not None
                        else "bare tcl ...",
                        tcl_body,
                    )
                    logger.debug(log_detail)
                    tcl_result = tcl_macro_expand(
                        tcl_body,
                        log_info=log_detail,
                        macro_for_logging=(
                            macro if macro_context is None else macro_context
                        ),
                    )
                    final_expanded = tcl_result
                    return final_expanded, True, True

                final_expanded = expanded
                return final_expanded, final_expanded != expression, False

            search_start = idx_open + len(delim_open)

            # MAC-OUT-2: for Tcl macros, scan with Tcl-aware brace nesting so
            # the macro close delimiter isn't confused with a Tcl block's
            # closing `}`. Without this, a body like `if {a} {b} else {c}`
            # followed by `}}` (macro close) sees the FIRST `}}` pair as
            # end-of-{c} + first-`}`-of-`}}`, truncating the captured body
            # by one brace.
            if _looks_like_tcl_macro(expression, search_start):
                idx_close_current = _find_tcl_aware_close(
                    expression, search_start, delim_close, delim_escape
                )
                if idx_close_current == -1:
                    logger.error(
                        "Missing closing macro delimiter (%s) in TCL macro expression: %s",
                        delim_close,
                        expression,
                    )
                    return expression, False, False
            else:
                nesting = 1
                idx = search_start
                while nesting > 0:
                    idx_next_open, _ = find_next_delim(expression, delim_open, idx)
                    idx_close, _ = find_next_delim(expression, delim_close, idx)
                    if idx_close == -1:
                        logger.error(
                            "Missing closing macro delimiter (%s) in expression: %s",
                            delim_close,
                            expression,
                        )
                        return expression, False, False
                    if idx_next_open != -1 and idx_next_open < idx_close:
                        nesting += 1
                        idx = idx_next_open + len(delim_open)
                    else:
                        nesting -= 1
                        if nesting == 0:
                            idx_close_current = idx_close
                            break
                        idx = idx_close + len(delim_close)
                else:
                    logger.error(
                        "Mismatched macro delimiters in expression: %s", expression
                    )
                    return expression, False, False

            macro_body = expression[idx_open + len(delim_open) : idx_close_current]

            # Check if this macro_body represents a TCL macro
            macro_body_stripped = macro_body.strip()
            tcl_match = TCL_MACRO_MAIN_REGEX.match(macro_body_stripped)
            if tcl_match:
                # Extract inner code, supporting both (/tcl ...) and tcl ... (bare)
                tcl_body = (
                    tcl_match.group(1)
                    if tcl_match.group(1) is not None
                    else tcl_match.group(2)
                )
                log_detail = "Detected TCL macro via {} syntax. TCL body: {}".format(
                    "(tcl ...)"
                    if tcl_match.group(1) is not None
                    else "bare tcl ...",
                    tcl_body,
                )
                logger.debug(log_detail)
                expanded_inner = tcl_macro_expand(
                    tcl_body,
                    log_info=log_detail,
                    macro_for_logging=(
                        macro if macro_context is None else macro_context
                    ),
                )
                inner_changed = True
                is_terminal = True
            else:
                # INPUT VALIDATION: check balance of escaped delimiters in the current macro_body
                balanced, open_count, close_count = count_balanced_escaped_delims(
                    macro_body
                )
                if not balanced:
                    logger.error(
                        "Unbalanced escaped delimiters in macro body. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                        open_count,
                        delim_escape + delim_open,
                        close_count,
                        delim_escape + delim_close,
                        macro_body,
                    )
                    error_str = "[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]".format(
                        macro_body
                    )
                    new_expression = (
                        expression[:idx_open]
                        + error_str
                        + expression[idx_close_current + len(delim_close) :]
                    )
                    return new_expression, True, False

                expanded_inner, inner_changed, _ = expand_inner_expression(
                    macro_body,
                    macro_context=macro if macro_context is None else macro_context,
                    _depth=_depth + 1,
                )
                logger.debug("Expanding inner macro: %s", macro_body)
                is_terminal = False

            new_expression = (
                expression[:idx_open]
                + expanded_inner
                + expression[idx_close_current + len(delim_close) :]
            )
            return (
                new_expression,
                inner_changed or (new_expression != expression),
                is_terminal,
            )

        except Exception as e:
            logger.error(
                "Error while expanding macro expression: %s", str(e), exc_info=True
            )
            return expression, False, False

    try:
        # INPUT VALIDATION: check balance at high level before any expansion
        balanced0, open_count0, close_count0 = count_balanced_escaped_delims(macro)
        if not balanced0:
            logger.error(
                "Unbalanced escaped delimiters at initial macro level. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                open_count0,
                delim_escape + delim_open,
                close_count0,
                delim_escape + delim_close,
                macro,
            )
            return "[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]".format(
                macro
            )
        # MAC-2: cap the expansion loop so cyclic macro references (e.g.
        # "foo": "{{bar}}", "bar": "{{foo}}") can't infinite-loop. 64 is more
        # than enough for any legitimate nesting depth; the inner-expansion
        # recursion handles deep nesting within a single pass.
        MAX_EXPANSION_ITERATIONS = 64
        any_expansions = False
        macro_to_expand = macro
        iterations = 0
        while iterations < MAX_EXPANSION_ITERATIONS:
            iterations += 1
            new_macro, changed, is_terminal = expand_inner_expression(
                macro_to_expand, macro_context=macro
            )
            any_expansions = any_expansions or changed
            # MAC-OUT-1: always capture the new expansion before checking break
            # conditions. The previous code broke FIRST and only assigned in
            # the loop-continuation branch, which silently discarded Tcl macro
            # results (is_terminal=True for Tcl evaluations, which means break
            # fires before the assignment).
            if changed and new_macro != macro_to_expand:
                macro_to_expand = new_macro
            if not changed or is_terminal:
                break
        else:
            logger.error(
                "Macro expansion exceeded %d iterations; likely a cycle. Original macro: %r",
                MAX_EXPANSION_ITERATIONS,
                macro,
            )
            return "[MACRO ERROR: cycle detected after {} iterations]".format(
                MAX_EXPANSION_ITERATIONS
            )

        logger.debug("Expanded macro: %s", macro_to_expand)

        # Final processing: handle escaped delimiters by converting them to literals
        macro_expansion = unescape_literal_parens(macro_to_expand)

        return macro_expansion

    except Exception as e:
        logger.error("Error in macro expansion: %s", str(e), exc_info=True)
        return macro
