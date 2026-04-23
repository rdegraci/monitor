import logging

from monitor.lib.voice_to_text import VoiceToText

LOGGER = logging.getLogger(__name__)

VOICE_TO_TEXT = None
FUNCTION_KEY_INSERTIONS = {}


def configure_voice_to_text():
    """Initialize the shared voice-to-text instance."""
    global VOICE_TO_TEXT
    VOICE_TO_TEXT = VoiceToText()  # Configure with device/model as needed


def configure_function_key_insertions(function_key_insertions):
    """Store validated function-key text insertions.

    Args:
        function_key_insertions: Mapping of function-key names to text values.
    """
    global FUNCTION_KEY_INSERTIONS
    FUNCTION_KEY_INSERTIONS = {}
    for key, value in function_key_insertions.items():
        if not isinstance(key, str):
            continue
        key = key.lower()
        if not key.startswith("f"):
            continue
        if not key[1:].isdigit():
            continue
        if not 1 <= int(key[1:]) <= 24:
            continue

        if isinstance(value, dict):
            value = value.get("text")
        if isinstance(value, str):
            FUNCTION_KEY_INSERTIONS[key] = value


def register_function_key_handlers(key_bindings):
    """Register f1-f24 insertion handlers for configured function keys.

    Args:
        key_bindings: Prompt Toolkit key bindings object.
    """
    bound_keys = 0
    for key_name in (f"f{i}" for i in range(1, 25)):
        if key_name not in FUNCTION_KEY_INSERTIONS:
            continue

        def handler(event, key_name=key_name):
            insert_function_key_text(event, key_name)

        key_bindings.add(key_name)(handler)
        bound_keys += 1

    LOGGER.debug("registered %d function key handler(s)", bound_keys)


def insert_function_key_text(event, key_name):
    """Insert configured text for a validated function key.

    Args:
        event: The keyboard event.
        key_name: Validated function key name such as "f1" or "f10".
    """
    buffer = event.app.current_buffer
    text = FUNCTION_KEY_INSERTIONS.get(key_name, "")
    if not text:
        return
    LOGGER.info("function key triggered: %s -> %r", key_name, text)
    if buffer.text:
        text = " " + text
    buffer.insert_text(text)


# Define the handler for Ctrl + Left Arrow
def ctrl_left_handler(event):
    pass


# Define the handler for Ctrl + Right Arrow
def ctrl_right_handler(event):
    pass


# F10 handler toggles voice record/stop and inserts transcript
def f10_voice_handler(event, config_obj):
    """
    Start or stop voice recording and insert transcript into the prompt.

    Args:
        event: The keyboard event.
        config_obj: Configuration object to set LAST_INPUT_WAS_VOICE flag.
    """
    buffer = event.app.current_buffer
    if not hasattr(f10_voice_handler, "recording"):
        f10_voice_handler.recording = False

    if not f10_voice_handler.recording:
        f10_voice_handler.recording = True
        VOICE_TO_TEXT.start_recording()
    else:
        f10_voice_handler.recording = False
        VOICE_TO_TEXT.stop_recording()
        transcript = VOICE_TO_TEXT.transcribe_async()
        # Insert into buffer at cursor; triggers input-accepted events
        buffer.insert_text(transcript)
        # Set a "voice flag" for next input
        config_obj.LAST_INPUT_WAS_VOICE = True
