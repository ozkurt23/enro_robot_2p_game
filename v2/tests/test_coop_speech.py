"""Local ASR cannot dispatch actions or leave player recordings behind."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from enro_terminal.coop_speech import Speech


def test_missing_speech_runtime_has_explicit_fallback(tmp_path):
    speech = Speech(tmp_path / "missing", tmp_path / "model")
    assert not speech.available
    with pytest.raises(RuntimeError, match="hazır görev"):
        speech.start(0)


def test_transcript_is_local_turkish_draft_and_temporary_audio_is_removed(tmp_path, monkeypatch):
    binary, model = tmp_path / "whisper", tmp_path / "model"
    binary.touch()
    model.touch()
    speech = Speech(binary, model, ("mic-a", "mic-b"))
    calls = []
    audio_path = []

    class Recorder:
        def __init__(self, argv, **kwargs):
            calls.append(argv)
            audio_path.append(Path(argv[-1]))
            Path(argv[-1]).write_bytes(b"x" * 4000)
        def poll(self):
            return 0
        def communicate(self, timeout):
            return b"", b""
    class Decoder:
        returncode = 0
        def __init__(self, argv, **kwargs):
            calls.append(argv)
            output = Path(argv[argv.index("-of") + 1]).with_suffix(".txt")
            output.write_text("Lütfen mavi cismi getir.")
        def communicate(self, timeout): return b"", b""
        def poll(self): return 0

    monkeypatch.setattr("enro_terminal.coop_speech.shutil.which", lambda _: "/usr/bin/arecord")
    monkeypatch.setattr("enro_terminal.coop_speech.subprocess.Popen",
                        lambda argv, **kw: Recorder(argv, **kw) if argv[0] == "arecord" else Decoder(argv, **kw))
    speech.start(1)
    assert speech.finish(0) == ""
    assert speech.finish(1) == "Lütfen mavi cismi getir."
    assert calls[0][calls[0].index("-D") + 1] == "mic-b"
    assert calls[1][calls[1].index("-l") + 1] == "tr"
    assert not audio_path[0].exists()
    assert speech.recording is None


def test_decoder_failure_also_removes_audio(tmp_path, monkeypatch):
    binary, model = tmp_path / "whisper", tmp_path / "model"
    binary.touch()
    model.touch()
    speech = Speech(binary, model)
    paths = []

    class Recorder:
        def __init__(self, argv, **kwargs):
            paths.append(Path(argv[-1]))
            paths[-1].write_bytes(b"x" * 4000)
        def poll(self): return 0
        def communicate(self, timeout): return b"", b""

    def fail(argv, **kwargs):
        if argv[0] == "arecord":
            return Recorder(argv, **kwargs)
        raise RuntimeError("decoder failed")
    monkeypatch.setattr("enro_terminal.coop_speech.shutil.which", lambda _: "/usr/bin/arecord")
    monkeypatch.setattr("enro_terminal.coop_speech.subprocess.Popen", fail)
    speech.start(0)
    with pytest.raises(RuntimeError, match="decoder failed"):
        speech.finish(0)
    assert not paths[0].exists()


def test_close_terminates_decoder_and_removes_its_temporary_audio(tmp_path):
    import tempfile
    speech = Speech(tmp_path / "whisper", tmp_path / "model")
    directory = tempfile.TemporaryDirectory(prefix="enro-test-")
    path = Path(directory.name)
    calls = []
    speech.processing_directory = directory
    speech.transcriber = SimpleNamespace(kill=lambda: calls.append("kill"), wait=lambda: calls.append("wait"))
    speech.close()
    assert calls == ["kill", "wait"]
    assert not path.exists()
    assert speech.transcriber is None
