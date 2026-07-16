import re
import shutil
import subprocess
import tempfile
import os
import sys
import threading

from monitor.lib.optional_deps import missing_extra_message


class TextToSpeech:
    """
    Encapsulates text-to-speech using Coqui TTS CLI and system audio playback.
    All speech methods are non-blocking and return immediately; synthesis and playback are executed in a background thread.
    TTS engine subprocess output (stdout and stderr) is suppressed for a quieter user experience.
    """
    def __init__(self, model_name="tts_models/en/ljspeech/tacotron2-DDC_ph", speaker=None):
        """
        Initializes the TextToSpeech engine with a specific Coqui TTS model and speaker (optional).
        Args:
            model_name (str): Coqui TTS model name or path.
            speaker (str/int/None): Speaker ID or name if the model supports multispeaker.
        """
        self.model_name = model_name
        self.speaker = speaker

    @staticmethod
    def strip_code_blocks(text):
        """
        Remove markdown code blocks and inline code from the given text.
        Args:
            text (str): Original text containing code and/or prose.
        Returns:
            str: Cleaned text with only natural language for speech.
        """
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"^( {4}.*\n?)+", "", text, flags=re.MULTILINE)
        text = re.sub(r"`[^`\n]+`", "", text)
        return text

    def _tts_worker(self, speakable):
        """
        Worker function to perform TTS synthesis (with suppressed output), audio playback, and cleanup in a background thread.
        TTS engine subprocess output (stdout and stderr) is redirected to os.devnull for a quieter user experience.
        Args:
            speakable (str): Cleaned text to speak.
        """
        if shutil.which("tts") is None:
            print(missing_extra_message("tts", feature="text-to-speech"))
            return

        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmpfile:
                wav_path = tmpfile.name

            cmd = [
                "tts",
                "--text", speakable,
                "--model_name", self.model_name,
                "--out_path", wav_path,
            ]
            if self.speaker is not None:
                cmd.extend(["--speaker_idx", str(self.speaker)])

            try:
                # Suppress all output (stdout and stderr) from TTS subprocess for quieter user experience
                with open(os.devnull, "wb") as devnull:
                    subprocess.run(cmd, check=True, stdout=devnull, stderr=devnull)
            except subprocess.CalledProcessError as e:
                print(f"Error running TTS: {e}")
                if wav_path and os.path.exists(wav_path):
                    os.remove(wav_path)
                return

            # Audio playback (cross-platform)
            try:
                if sys.platform == "darwin":
                    subprocess.run(["afplay", wav_path], check=True)
                elif sys.platform.startswith("linux"):
                    subprocess.run(["aplay", wav_path], check=True)
                elif sys.platform.startswith("win"):
                    import winsound
                    winsound.PlaySound(wav_path, winsound.SND_FILENAME)
                else:
                    print("Automatic audio playback not supported on this platform.")
            except Exception as e:
                print(f"Playback failed: {e}")

        finally:
            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)

    def speak(self, text):
        """
        Speak the cleaned text using the Coqui TTS CLI and system audio player.
        Non-blocking: Returns immediately; speech synthesis and playback run in a background thread.
        TTS engine subprocess output is suppressed for quieter user experience.
        Args:
            text (str): Text to voice. Code will be removed automatically.
        """
        speakable = self.strip_code_blocks(text)
        if not speakable.strip():
            return
        t = threading.Thread(target=self._tts_worker, args=(speakable,), daemon=True)
        t.start()

    def speak_response_filtered(self, text):
        """
        Non-blocking alias for speak(), provided for API parity with other modules.
        Speech synthesis and playback are executed in a background thread and this method returns immediately.
        TTS engine subprocess output is suppressed for quieter user experience.
        Args:
            text (str): Assistant reply text to filter and read aloud.
        """
        self.speak(text)
