"""Contains stateless macro helpers for loading, updating, and recursive expansion. No macro state, config, or CLI integration here."""

import json
import logging
import os
import re
import tkinter

logger = logging.getLogger(__name__)


def load_additional_macros(macro_file_path):
    """Load additional macros from a specified JSON file.

    Args:
        macro_file_path (str): The path to the JSON macro file.

    Returns:
        dict: Dictionary loaded from the JSON macro file, or an empty
            dictionary if loading failed.
    """
    logger.debug(
        "Entering load_additional_macros with file path: %s", macro_file_path
    )
    expanded_path = os.path.expanduser(macro_file_path)
    try:
        with open(expanded_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(
            "Error loading macros from %s: %s", expanded_path, e
        )
        return {}


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

    TCL_MACRO_MAIN_REGEX = re.compile(
        r'^\s*(?:\(tcl\s+(.+)\)|tcl\s+(.+))\s*$', re.DOTALL
    )

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
        balanced, open_count, close_count = count_balanced_escaped_delims(tcl_code_body)
        if not balanced:
            logger.error(
                "Unbalanced escaped delimiters in TCL macro body. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                open_count, delim_escape + delim_open,
                close_count, delim_escape + delim_close, tcl_code_body
            )
            return '[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]'.format(tcl_code_body)
        try:
            # Only unescape delim_escape+delim_open and delim_escape+delim_close to literal delimiters in TCL.
            # Do NOT perform any macro expansion within the TCL macro body itself; all other escapes are left untouched.
            tcl_code_inner = tcl_code_body.replace(delim_escape + delim_open, delim_open)
            tcl_code_inner = tcl_code_inner.replace(delim_escape + delim_close, delim_close)

            # INPUT VALIDATION: check balance again after unescaping
            balanced2, open_count2, close_count2 = count_balanced_escaped_delims(tcl_code_inner)
            if not balanced2:
                logger.error(
                    "Unbalanced escaped delimiters after unescaping in TCL macro. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                    open_count2, delim_escape + delim_open,
                    close_count2, delim_escape + delim_close, tcl_code_inner
                )
                return '[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]'.format(tcl_code_inner)

            # GUARD: Skip TCL evaluation if code is empty, whitespace, or just '...'
            if not tcl_code_inner.strip() or tcl_code_inner.strip() == '...':
                logger.error(
                    "Skipping TCL macro evaluation: code is empty or a placeholder ('...') (code: %r, in macro: %r)",
                    tcl_code_inner, macro_for_logging
                )
                return ''

            try:
                result_output = []
                tk_interp = tkinter.Tcl()

                def python_puts(*args):
                    # Concatenate given arguments like standard TCL puts
                    joined = ' '.join(str(a) for a in args)
                    result_output.append(joined)

                tk_interp.createcommand("puts", python_puts)

                try:
                    if log_info:
                        logger.info(log_info)
                    else:
                        logger.info("Expanding macro as TCL (bare or (/tcl ...)): %s", tcl_code_inner)
                    tk_interp.eval(tcl_code_inner)
                except Exception as e_inner:
                    logger.error("TCL execution error: %s", str(e_inner), exc_info=True)
                    return '[TCL ERROR: {}]'.format(str(e_inner))
                joined_output = '\n'.join(result_output)
                return joined_output
            except Exception as e:
                logger.error("TCL execution failed: %s", str(e), exc_info=True)
                return '[TCL ERROR: {}]'.format(str(e))
        except Exception as e_outer:
            logger.error("Error doing TCL macro expansion: %s", str(e_outer), exc_info=True)
            return '[TCL ERROR: {}]'.format(str(e_outer))


    def expand_inner_expression(expression, macro_context=None):
        """Main recursive parser for macro expanding innermost occurrence.

        Args:
            expression (str): The macro expression.

        Returns:
            tuple[str, bool, bool]: (New expression, whether any expansion occurred, is_terminal)
        """
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
                    log_detail = (
                        "Detected TCL macro via {} syntax. TCL body: {}".format(
                            "(tcl ...)" if tcl_match.group(1) is not None else "bare tcl ...", tcl_body
                        )
                    )
                    logger.debug(log_detail)
                    tcl_result = tcl_macro_expand(
                        tcl_body,
                        log_info=log_detail,
                        macro_for_logging=macro if macro_context is None else macro_context
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
                    log_detail = (
                        "Detected TCL macro in macro store value via {} syntax. TCL body: {}".format(
                            "(tcl ...)" if tcl_match_after.group(1) is not None else "bare tcl ...",
                            tcl_body
                        )
                    )
                    logger.debug(log_detail)
                    tcl_result = tcl_macro_expand(
                        tcl_body,
                        log_info=log_detail,
                        macro_for_logging=macro if macro_context is None else macro_context
                    )
                    final_expanded = tcl_result
                    return final_expanded, True, True

                final_expanded = expanded
                return final_expanded, final_expanded != expression, False

            search_start = idx_open + len(delim_open)
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

            macro_body = expression[
                idx_open + len(delim_open) : idx_close_current
            ]

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
                log_detail = (
                    "Detected TCL macro via {} syntax. TCL body: {}".format(
                        "(tcl ...)" if tcl_match.group(1) is not None else "bare tcl ...", tcl_body
                    )
                )
                logger.debug(log_detail)
                expanded_inner = tcl_macro_expand(
                    tcl_body,
                    log_info=log_detail,
                    macro_for_logging=macro if macro_context is None else macro_context
                )
                inner_changed = True
                is_terminal = True
            else:
                # INPUT VALIDATION: check balance of escaped delimiters in the current macro_body
                balanced, open_count, close_count = count_balanced_escaped_delims(macro_body)
                if not balanced:
                    logger.error(
                        "Unbalanced escaped delimiters in macro body. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                        open_count, delim_escape + delim_open,
                        close_count, delim_escape + delim_close, macro_body
                    )
                    error_str = '[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]'.format(macro_body)
                    new_expression = (
                        expression[:idx_open]
                        + error_str
                        + expression[idx_close_current + len(delim_close) :]
                    )
                    return new_expression, True, False

                expanded_inner, inner_changed, _ = expand_inner_expression(macro_body, macro_context=macro if macro_context is None else macro_context)
                logger.debug("Expanding inner macro: %s", macro_body)
                is_terminal = False

            new_expression = (
                expression[:idx_open]
                + expanded_inner
                + expression[idx_close_current + len(delim_close) :]
            )
            return new_expression, inner_changed or (new_expression != expression), is_terminal

        except Exception as e:
            logger.error(
                "Error while expanding macro expression: %s", str(e),
                exc_info=True
            )
            return expression, False, False

    try:
        # INPUT VALIDATION: check balance at high level before any expansion
        balanced0, open_count0, close_count0 = count_balanced_escaped_delims(macro)
        if not balanced0:
            logger.error(
                "Unbalanced escaped delimiters at initial macro level. Opened %d ('%s'), closed %d ('%s'). Input: %r",
                open_count0, delim_escape + delim_open,
                close_count0, delim_escape + delim_close, macro
            )
            return '[MACRO ERROR: Unbalanced escaped delimiters in expression: {}]'.format(macro)
        any_expansions = False
        macro_to_expand = macro
        while True:
            new_macro, changed, is_terminal = expand_inner_expression(macro_to_expand, macro_context=macro)
            any_expansions = any_expansions or changed
            if not changed or new_macro == macro_to_expand or is_terminal:
                break
            macro_to_expand = new_macro

        logger.debug("Expanded macro: %s", macro_to_expand)

        # Final processing: handle escaped delimiters by converting them to literals
        macro_expansion = unescape_literal_parens(macro_to_expand)

        if any_expansions or macro_expansion != macro:
            logger.info("Macro expansion: %s", str(macro_expansion))
        return macro_expansion

    except Exception as e:
        logger.error("Error in macro expansion: %s", str(e), exc_info=True)
        return macro
