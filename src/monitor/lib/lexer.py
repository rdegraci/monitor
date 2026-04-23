import logging
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.formatted_text import to_plain_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style

from monitor.lib.keyboard import register_function_key_handlers

logger = logging.getLogger(__name__)

history_file = os.path.expanduser("~/.chat_session_history")
history = FileHistory(history_file)


class RedAfter120Lexer(Lexer):
    """Custom lexer for red text after 120 characters."""

    def lex_document(self, document):
        def get_line(lineno):
            line = document.lines[lineno]
            if len(line) <= 120:
                return [("", line)]
            else:
                return [("", line[:120]), ("class:red", line[120:])]

        return get_line


style = Style.from_dict(
    {
        "red": "ansired",
    }
)


class CommandCompleter(Completer):
    """Custom completer for multi-word input and path completion."""

    def __init__(self):
        self.path_completer = PathCompleter()
        self.last_completions = []
        logger.debug("CommandCompleter initialized.")

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        cursor_pos = document.cursor_position
        text_before_cursor = text[:cursor_pos]
        words = text_before_cursor.split()
        logger.debug(
            "get_completions called: cursor_pos=%d, words_count=%d",
            cursor_pos,
            len(words),
        )

        if not words or not text_before_cursor.strip():
            logger.debug("No words for completion.")
            self.last_completions = []
            return []

        last_word = words[-1]
        try:
            self.last_completions = list(
                self.path_completer.get_completions(
                    document.__class__(last_word, len(last_word)), complete_event
                )
            )
        except Exception as e:
            logger.error("Completion error: %s", str(e), exc_info=True)
            self.last_completions = []
            return []
        logger.debug("Completions found: %d", len(self.last_completions))
        return self.last_completions


bindings = KeyBindings()

completer_instance = None


@bindings.add("tab")
def _(event):
    buffer = event.app.current_buffer
    text = buffer.text[: buffer.cursor_position]
    words = text.split()
    logger.debug("Tab pressed, buffer length: %d", len(buffer.text))
    if not words:
        logger.debug("No words in buffer for tab completion.")
        return

    last_word = words[-1]

    if not buffer.complete_state:
        logger.debug("Starting completion.")
        buffer.start_completion(select_first=False)
    elif completer_instance and completer_instance.last_completions:
        completion = completer_instance.last_completions[0]
        completion_text = completion.text
        replace_start = buffer.cursor_position + completion.start_position
        logger.debug(
            "Applying completion '%s' at cursor position %d; replace_start=%d start_position=%d",
            completion_text,
            buffer.cursor_position,
            replace_start,
            completion.start_position,
        )
        buffer.text = (
            buffer.text[:replace_start]
            + completion_text
            + buffer.text[buffer.cursor_position :]
        )
        buffer.cursor_position = replace_start + len(completion_text)
        buffer.cancel_completion()


def create_prompt_session(additional_bindings=None):
    """Create and return a configured PromptSession.

    Function key handlers are registered before creating the session.
    """
    global completer_instance
    if additional_bindings:
        for keys, handler in additional_bindings.items():
            bindings.add(keys)(handler)
            logger.debug("Custom binding added: %s", keys)

    register_function_key_handlers(bindings)
    logger.debug("Prompt session prepared with function key bindings.")

    completer_instance = CommandCompleter()
    logger.info("Prompt session created. History file: %s", history_file)

    return PromptSession(
        lexer=RedAfter120Lexer(),
        style=style,
        history=history,
        key_bindings=bindings,
        completer=completer_instance,
        complete_while_typing=False,
    )


if __name__ == "__main__":
    session = create_prompt_session()
    while True:
        try:
            result = session.prompt(">> ")
            logger.info("User entered line of length: %d", len(result))
            print(f"You entered: {result}")
        except KeyboardInterrupt:
            logger.info("Session interrupted by user (KeyboardInterrupt). Exiting.")
            break
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            break
