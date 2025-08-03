
from monitor.lib.voice_to_text import VoiceToText

VOICE_TO_TEXT=None

def configure_voice_to_text():
    global VOICE_TO_TEXT
    VOICE_TO_TEXT = VoiceToText()  # Configure with device/model as needed


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


