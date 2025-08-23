import logging

from monitor.lib.colors import red, blue, yellow, reset
from typing import Optional, List

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI

logger = logging.getLogger(__name__)


def handle_single_line(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle single line input mode"""
    logger.debug("Processing single line input...")
    return [first_line]

def handle_multi_command(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle multi-command input mode with semicolon separator"""
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
    
    while True:
        try:
            line = session.prompt(ANSI(";;;"))
            if line == "EOF":
                print(f"{blue}EOF{reset}")
                break
            lines.append(line + ";;;")
        except EOFError:
            logger.debug("EOFError received, ending input")
            print(f"{blue}EOF{reset}")
            print()  # Print newline for cleaner output
            break
        except Exception as e:
            logger.error(f"Error reading multi-command line: {str(e)}", exc_info=True)
            break
    
    logger.debug(f"Collected lines in multi-command mode: {lines}")
    return lines

def handle_backslash_continuation(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle backslash line continuation input mode"""
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
        except Exception as e:
            logger.error(f"Error reading continuation line: {str(e)}", exc_info=True)
            break
    
    logger.debug(f"Collected lines in backslash mode: {lines}")
    return lines

def handle_pipeline_command(first_line: str, session: Optional[PromptSession] = None) -> List[str]:
    """Handle pipeline (|) input mode, collecting directives for chaining."""
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

    lines: List[str] = [first_line[1:].lstrip()] if first_line[1:].strip() else []
    while True:
        try:
            line = session.prompt(ANSI("|| "))
            if line.strip().upper() == "EOF" or line.strip() == "":
                if line.strip().upper() == "EOF":
                    print(f"{blue}Input ended by user (EOF in pipeline mode).{reset}")
                break
            lines.append(line)
        except EOFError:
            logger.debug("EOF in pipeline mode")
            print(f"{blue}Input ended by user (EOF in pipeline mode).{reset}")
            break
        except Exception as e:
            logger.error(f"Error reading pipeline line: {str(e)}", exc_info=True)
            break
    logger.debug(f"Collected in pipeline mode: {lines}")
    return lines

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

def determine_input_mode(first_line: str, session: Optional[PromptSession] = None) -> str:
    logger.debug(f"Determining input mode for line: {first_line}")
    if first_line.endswith("\\"):
        return "backslash"
    elif first_line.startswith(";"):
        return "multi-command"
    elif first_line.startswith("|"):
        return "pipeline"
    else:
        return "single"
