from __future__ import annotations

import json
import math
import wave
from pathlib import Path

from artagents.packs.builtin.audio_understand.run import main


def _write_tone(path: Path, *, freq: float = 440.0, duration: float = 0.35, sample_rate: int = 16000) -> None:
    samples = int(duration * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(samples):
            value = int(16000 * math.sin(2 * math.pi * freq * index / sample_rate))
            frames.extend(value.to_bytes(2, "little", signed=True))
        handle.writeframes(bytes(frames))


def test_audio_understand_single_audio_dry_run(capsys, tmp_path):
    audio = tmp_path / "clip.wav"
    _write_tone(audio)

    code = main(["--audio", str(audio), "--out-dir", str(tmp_path / "out"), "--dry-run"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["models"] == ["gpt-audio-mini"]
    assert payload["source"] == [str(audio)]
    assert payload["audition_reel"] is None
    assert len(payload["windows"]) == 1
    assert Path(payload["windows"][0]["path"]).is_file()


def test_audio_understand_repeated_audio_builds_numbered_reel(capsys, tmp_path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    _write_tone(first, freq=330)
    _write_tone(second, freq=660)

    code = main(
        [
            "--audio",
            str(first),
            "--audio",
            str(second),
            "--out-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["audition_reel"]
    assert Path(payload["audition_reel"]).is_file()
    assert payload["audio_inputs"] == [{"index": 1, "path": payload["audition_reel"], "kind": "numbered_audition_reel"}]
    assert "numbered audition reel" in payload["query"].lower()
    assert "ignore the spoken number labels" in payload["query"].lower()
