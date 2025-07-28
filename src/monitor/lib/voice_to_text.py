import whisper
import pyaudio
import numpy as np
import threading

class VoiceToText:
    """Encapsulates Whisper STT and microphone recording for press-to-record workflows."""

    def __init__(self, model_name="base", rate=16000, channels=1, chunk=1024):
        """
        Initialize Whisper model and PyAudio parameters.

        Args:
            model_name (str): Which Whisper model to load (default 'base').
            rate (int): Audio sample rate (Hz).
            channels (int): Number of microphone channels (default 1: mono).
            chunk (int): Audio buffer size per read (samples).
        """
        self.model = whisper.load_model(model_name)
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self._recording = False
        self._audio = None
        self._thread = None

    def _record_worker(self):
        """
        Thread worker for audio capture, runs while self._recording is True.
        """
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=self.channels, rate=self.rate,
                        input=True, frames_per_buffer=self.chunk)
        frames = []
        print("Voice input: Recording... Press hotkey again to stop.")
        while self._recording:
            data = stream.read(self.chunk, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.int16))
        stream.stop_stream()
        stream.close()
        p.terminate()
        if frames:
            self._audio = np.concatenate(frames).astype(np.float32) / 32768.0
        else:
            self._audio = None
        print("Voice input: Recording stopped.")

    def start_recording(self):
        """
        Start audio recording in a background thread. No effect if already recording.
        """
        if self._recording:
            print("Already recording.")
            return
        self._audio = None
        self._recording = True
        self._thread = threading.Thread(target=self._record_worker)
        self._thread.start()

    def stop_recording(self):
        """
        Stop audio recording if active. Does not transcribe. Use before calling transcribe_async.
        """
        if not self._recording:
            print("Not recording.")
            return
        self._recording = False
        self._thread.join()

    def transcribe_async(self):
        """
        Transcribe captured audio using Whisper and return the text.
        Returns:
            str: Transcribed text, or empty string if no audio was captured.
        """
        if self._audio is not None and len(self._audio) > 0:
            print("Voice input: Transcribing...")
            audio_trim = whisper.pad_or_trim(self._audio)
            mel = whisper.log_mel_spectrogram(audio_trim).to(self.model.device)
            options = whisper.DecodingOptions(fp16=False)
            result = whisper.decode(self.model, mel, options)
            print(f"Voice input: {result.text}")
            return result.text.strip()
        else:
            print("Voice input: No audio data captured.")
            return ""
