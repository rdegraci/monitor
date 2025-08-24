import logging

from monitor.lib.colors import blue, reset
from typing import Optional, List

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI

logger = logging.getLogger(__name__)


def handle_single_line(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle single line input mode"""
    logger.debug("Processing single line input...")
    return [first_line]

def handle_multi_command(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle multi-command input mode.
    
    - Triggered by a leading ';' in the first input line.
    - If content exists after the leading ';', it is trimmed and captured as the first command, with ';;;' appended.
    - Prompts subsequent lines with ';;; ' (note trailing space).
    - Appends ';;;' to each collected line.
    - Terminates when the user types 'EOF' or when EOFError is raised.
    """
    logger.debug("Processing multi-command input...")
    # Ensure we have a PromptSession to use
    if session is None:
        try:
            from monitor.lib.lexer import create_prompt_session
            session = create_prompt_session()
            logger.debug("Created fallback PromptSession for multi-command mode")
        except Exception as e:
            logger.error(f"Failed to create fallback PromptSession: {e}", exc_info=True)
            # As a last resort, raise to preserve behavior visibility
            raise

    lines: List[str] = []

    # Capture any content after the leading ';' as the first command
    initial_content = first_line[1:].strip()
    if initial_content:
        lines.append(initial_content + ";;;")
        logger.debug("Captured initial multi-command from first line: %r", initial_content)
    
    while True:
        try:
            line = session.prompt(ANSI(";;; "))
            if line == "EOF":
                print(f"{blue}EOF{reset}")
                break
            lines.append(line + ";;;")
        except EOFError:
            logger.debug("EOFError received, ending input")
            print(f"{blue}EOF{reset}")
            print()  # Print newline for cleaner output
            break
        except KeyboardInterrupt:
            print(f"{blue}Interrupted by user (Ctrl-C).{reset}")
            print()  # Print newline for cleaner output
            break
        except Exception as e:
            logger.error(f"Error reading multi-command line: {str(e)}", exc_info=True)
            break
    
    logger.debug("Collected %d lines in multi-command mode", len(lines))
    return lines

def handle_backslash_continuation(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle backslash line continuation input mode.
    
    - Triggered by a trailing '\\' in the first input line.
    - Removes the trailing backslash from the first line.
    - Prefixes '!<' to the cleaned first line and to each subsequent line.
    - Prompts with '... '.
    - Terminates on user-typed 'EOF' or EOFError.
    """
    logger.debug("Processing backslash continuation input...")

    # Ensure we have a PromptSession to use
    if session is None:
        try:
            from monitor.lib.lexer import create_prompt_session
            session = create_prompt_session()
            logger.debug("Created fallback PromptSession for backslash continuation mode")
        except Exception as e:
            logger.error(f"Failed to create fallback PromptSession: {e}", exc_info=True)
            raise

    clean_line = first_line[:-1] # Remove the backslash
    lines: List[str] = []
    lines.append("!<" + clean_line)
    
    while True:
        try:
            line = session.prompt(ANSI("... "))
            if line == "EOF":
                print(f"{blue}EOF{reset}")
                break
            # Add directive to not treat parens as macros
            lines.append("!<" + line)
        except EOFError:
            logger.debug("EOFError received, ending input")
            print(f"{blue}EOF{reset}")
            print()  # Print newline for cleaner output
            break
        except KeyboardInterrupt:
            print(f"{blue}Interrupted by user (Ctrl-C).{reset}")
            print()  # Print newline for cleaner output
            break
        except Exception as e:
            logger.error(f"Error reading continuation line: {str(e)}", exc_info=True)
            break
    
    logger.debug("Collected %d lines in backslash mode", len(lines))
    return lines

def handle_pipeline_command(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle pipeline (|) input mode using a state machine to collect requests.
    
    Behavior:
    - Do not return until EOF is received: either a line 'EOF' (after strip) or EOFError (Ctrl-D).
    - Supports single-line requests and multi-line blocks started by a line that ends with a single,
      unescaped trailing backslash (line.rstrip().endswith("\\") and not line.rstrip().endswith("\\\\")).
      The trailing spaces and that single backslash are removed, and accumulation continues until an
      'EOL' marker line (after strip) is entered.
    - Inside a multi-line block, blank lines are included verbatim.
    - Lines that are only whitespace outside a multi-line block are ignored (no empty request). Inside
      a multi-line block, whitespace-only lines are included.
    - Escaped marker-like sequences (e.g., '\\EOL', '\\EOF') are treated as normal text and preserved.
    - On EOF (either 'EOF' marker line or EOFError), if currently in a multi-line block, finalize and
      include the in-progress request; then show a numbered list of collected requests and prompt:
      'Proceed? [Y/n]: '. If the answer is 'n' or 'N', exit without processing (return []). Otherwise,
      return the collected requests.
    - KeyboardInterrupt (Ctrl-C): If not in a multi-line block, exit immediately without processing
      (return []). If in a multi-line block, cancel the current request buffer, remain in pipeline mode,
      and print 'Cancelled current request (pipeline still active)'.
    - Prompts: 'pipe> ' when ready for a new request and 'pipe...> ' while in a multi-line block.
    """
    logger.debug("Processing pipeline input mode...")
    # Ensure we have a PromptSession to use
    if session is None:
        try:
            from monitor.lib.lexer import create_prompt_session
            session = create_prompt_session()
            logger.debug("Created fallback PromptSession for pipeline mode")
        except Exception as e:
            logger.error(f"Failed to create fallback PromptSession: {e}", exc_info=True)
            raise

    requests: List[str] = []

    def _has_single_trailing_backslash(s: str) -> bool:
        rs = s.rstrip()
        return rs.endswith("\\") and not rs.endswith("\\\\")

    def _remove_single_trailing_backslash_and_spaces(s: str) -> str:
        rs = s.rstrip()
        # rs is guaranteed to end with a single '\' when called
        return rs[:-1]

    in_block = False
    block_lines: List[str] = []

    # Include content after the leading '|' from the first line
    initial_content = first_line[1:].lstrip()
    if initial_content:
        if _has_single_trailing_backslash(initial_content):
            head = _remove_single_trailing_backslash_and_spaces(initial_content)
            block_lines = [head]
            in_block = True
            logger.debug("Initialized multi-line block from first line; initial head length=%d", len(head))
        else:
            requests.append(initial_content)
            logger.debug("Added initial single-line request from first line; length=%d", len(initial_content))

    while True:
        try:
            prompt_text = "pipe...> " if in_block else "pipe> "
            line = session.prompt(ANSI(prompt_text))
            stripped = line.strip()

            if in_block:
                # End of block marker
                if stripped == "EOL":
                    requests.append("\n".join(block_lines))
                    logger.debug("Finalized multi-line block with %d lines", len(block_lines))
                    block_lines = []
                    in_block = False
                    continue

                # EOF marker inside block: finalize block, then proceed to confirmation
                if stripped == "EOF":
                    requests.append("\n".join(block_lines))
                    logger.debug("EOF marker inside block; finalized block with %d lines", len(block_lines))
                    block_lines = []
                    in_block = False
                    print(f"{blue}EOF{reset}")
                    print()
                    break

                # Regular line inside block (including blank/whitespace lines)
                block_lines.append(line)
                continue

            # Outside of a block:
            # Ignore whitespace-only lines
            if stripped == "":
                continue

            # EOF marker ends collection phase
            if stripped == "EOF":
                print(f"{blue}EOF{reset}")
                print()
                break

            # Start of a new multi-line block?
            if _has_single_trailing_backslash(line):
                head = _remove_single_trailing_backslash_and_spaces(line)
                block_lines = [head]
                in_block = True
                logger.debug("Started multi-line block; initial head length=%d", len(head))
                continue

            # Single-line request
            requests.append(line)
            logger.debug("Added single-line request; length=%d", len(line))
            continue

        except EOFError:
            # Ctrl-D: finalize block if active, then proceed to confirmation
            if in_block:
                requests.append("\n".join(block_lines))
                logger.debug("EOFError: finalized in-progress block with %d lines", len(block_lines))
                block_lines = []
                in_block = False
            print(f"{blue}EOF{reset}")
            print()
            break
        except KeyboardInterrupt:
            if in_block:
                # Cancel current block and continue pipeline mode
                block_lines = []
                in_block = False
                print(f"{blue}Cancelled current request (pipeline still active){reset}")
                print()
                logger.debug("KeyboardInterrupt: cancelled current multi-line block")
                continue
            else:
                print(f"{blue}Interrupted by user (Ctrl-C).{reset}")
                print()
                logger.debug("KeyboardInterrupt: exiting pipeline mode without processing")
                return []
        except Exception as e:
            logger.error(f"Error reading pipeline line: {str(e)}", exc_info=True)
            break

    # Confirmation step after EOF or error
    logger.debug("Collected %d requests in pipeline mode before confirmation", len(requests))
    try:
        print(f"{blue}Collected {len(requests)} request(s):{reset}")
        for idx, req in enumerate(requests, 1):
            print(f"{blue}{idx}. {reset}{req}")
        while True:
            try:
                answer = session.prompt(ANSI("Proceed? [Y/n]: "))
            except EOFError:
                answer = ""
            except KeyboardInterrupt:
                print(f"{blue}Interrupted by user (Ctrl-C).{reset}")
                print()
                logger.debug("KeyboardInterrupt during confirmation; exiting without processing")
                return []
            except Exception as e:
                logger.error(f"Error during confirmation: {str(e)}", exc_info=True)
                answer = ""

            a = (answer or "").strip().lower()
            if a in ("", "y", "yes"):
                break
            if a in ("n", "no"):
                print(f"{blue}Pipeline cancelled by user.{reset}")
                logger.debug("User declined to proceed; returning empty list")
                return []
            print("Please answer 'y' or 'n'.")
    except Exception as e:
        logger.error(f"Unexpected error during confirmation loop: {str(e)}", exc_info=True)
        # Proceed by default if confirmation loop failed unexpectedly

    logger.debug("Proceeding with %d pipeline requests", len(requests))
    return requests

def validate_input(lines: List[str]) -> bool:
    """Validate the collected input lines"""
    logger.debug("Validating input lines...")
    if not lines:
        logger.warning("No input lines collected")
        return False
    
    for line in lines:
        if not isinstance(line, str):
            logger.error(f"Invalid line type: {type(line)}")
            return False
    return True

def format_final_input(lines: List[str]) -> str:
    """Format the final input string from collected lines"""
    logger.debug("Formatting final input...")
    return "\n".join(lines)

def process_input_mode(first_line: str, input_mode: str, session: Optional[PromptSession] = None) -> List[str]:
    """Process input based on determined mode"""
    logger.debug(f"Processing input in {input_mode} mode")
    
    mode_handlers = {
        "backslash": handle_backslash_continuation,
        "multi-command": handle_multi_command,
        "pipeline": handle_pipeline_command,
        "single": handle_single_line
    }
    
    handler = mode_handlers.get(input_mode)
    if not handler:
        logger.error(f"Unknown input mode: {input_mode}. Defaulting to single line mode.")
        return [first_line]  # Default to single line mode
        
    return handler(first_line, session)

def determine_input_mode(first_line: str, _session: Optional[PromptSession] = None) -> str:
    """Determine the input mode based on the first line. Note: _session is intentionally unused."""
    logger.debug("Determining input mode (len=%d, preview=%r)", len(first_line), first_line[:40])
    if first_line.startswith("|"):
        return "pipeline"
    elif first_line.startswith(";"):
        return "multi-command"
    elif first_line.endswith("\\"):
        return "backslash"
    else:
        return "single"
