"""Optional, local-only push-to-talk. Transcripts are drafts, never commands."""
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading


class Speech:
    def __init__(self, binary, model, devices=("default", "default")):
        self.binary, self.model = Path(binary), Path(model)
        self.devices = devices
        self.recording = None
        self.directory = None
        self.player = None
        self.transcriber = None
        self.processing_directory = None
        self.generation = 0
        self.lock = threading.Lock()

    @property
    def available(self):
        return self.binary.is_file() and self.model.is_file() and bool(shutil.which("arecord"))

    def start(self, player):
        with self.lock:
            if not self.available:
                raise RuntimeError("Yerel ses paketi yok; ./setup_coop_speech.sh çalıştırın veya hazır görev kullanın.")
            if self.recording:
                raise RuntimeError("Diğer oyuncunun ses kaydı devam ediyor.")
            self.directory = tempfile.TemporaryDirectory(prefix="enro-voice-")
            self.generation += 1
            path = Path(self.directory.name) / "input.wav"
            try:
                self.recording = subprocess.Popen([
                    "arecord", "-q", "-D", self.devices[player], "-t", "wav", "-f", "S16_LE",
                    "-r", "16000", "-c", "1", "-d", "12", str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self.player = player
            except Exception:
                self.directory.cleanup()
                self.directory = None
                raise

    def finish(self, player):
        with self.lock:
            if not self.recording or self.player != player:
                return ""
            recorder, directory = self.recording, self.directory
            generation = self.generation
            self.processing_directory = directory
            self.recording = self.directory = self.player = None
        try:
            if recorder.poll() is None:
                recorder.send_signal(signal.SIGINT)
            _, error = recorder.communicate(timeout=3)
            audio = Path(directory.name) / "input.wav"
            if not audio.exists() or audio.stat().st_size < 3244:
                raise RuntimeError("Mikrofon kaydı alınamadı: " + error.decode(errors="replace")[:200])
            output = Path(directory.name) / "transcript"
            with self.lock:
                if generation != self.generation:
                    raise RuntimeError("Ses işlemi iptal edildi")
                decoder = subprocess.Popen([
                    str(self.binary), "-m", str(self.model), "-f", str(audio),
                    "-l", "tr", "-t", "4", "-ng", "-nt", "-otxt", "-of", str(output)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self.transcriber = decoder
            try:
                _, error = decoder.communicate(timeout=45)
                if decoder.returncode != 0:
                    raise RuntimeError("Yerel ses çözümleme başarısız: " + error.decode(errors="replace")[-200:])
            finally:
                if decoder.poll() is None:
                    decoder.kill()
                    decoder.wait()
                with self.lock:
                    if self.transcriber is decoder:
                        self.transcriber = None
            return output.with_suffix(".txt").read_text().strip()[:500]
        finally:
            if recorder.poll() is None:
                recorder.kill()
                recorder.wait()
            directory.cleanup()
            with self.lock:
                if self.processing_directory is directory:
                    self.processing_directory = None

    def close(self):
        with self.lock:
            self.generation += 1
            if self.recording:
                self.recording.terminate()
                try:
                    self.recording.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.recording.kill()
                    self.recording.wait()
                self.recording = None
            if self.directory:
                self.directory.cleanup()
                self.directory = None
            if self.transcriber:
                self.transcriber.kill()
                self.transcriber.wait()
                self.transcriber = None
            if self.processing_directory:
                self.processing_directory.cleanup()
                self.processing_directory = None
