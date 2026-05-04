from __future__ import annotations

import struct
import wave
from pathlib import Path

from artagents.verify import (
    all_of,
    audio_duration_min,
    canonical_check_params,
    file_nonempty,
    image_dimensions,
    json_file,
    json_schema,
)


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_file_nonempty_sentinel_flag_and_empty_vs_byte(tmp_path: Path) -> None:
    check = file_nonempty()
    assert check.sentinel is True
    empty = _write(tmp_path / "empty.bin", b"")
    nonempty = _write(tmp_path / "byte.bin", b"x")
    assert check.run(empty).ok is False
    assert check.run(nonempty).ok is True


def test_json_file_rejects_invalid_accepts_valid(tmp_path: Path) -> None:
    check = json_file()
    assert check.sentinel is False
    bad = _write(tmp_path / "bad.json", b"{not json")
    good = _write(tmp_path / "good.json", b'{"a": 1}')
    assert check.run(bad).ok is False
    assert check.run(good).ok is True


def test_json_schema_required_keys_enforced(tmp_path: Path) -> None:
    check = json_schema({"required": ["a"]})
    assert check.sentinel is False
    missing = _write(tmp_path / "missing.json", b'{"b": 1}')
    present = _write(tmp_path / "present.json", b'{"a": 1}')
    assert check.run(missing).ok is False
    assert "missing required key: a" in check.run(missing).reason
    assert check.run(present).ok is True


def test_audio_duration_min_wav_accepts_long_rejects_short(tmp_path: Path) -> None:
    check = audio_duration_min(2.0)
    assert check.sentinel is False
    long_wav = tmp_path / "long.wav"
    with wave.open(str(long_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * (8000 * 5 // 2))  # 2.5 seconds
    short_wav = tmp_path / "short.wav"
    with wave.open(str(short_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)  # 1 second
    assert check.run(long_wav).ok is True
    assert check.run(short_wav).ok is False


def _make_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr_data
    return sig + struct.pack(">I", 13) + ihdr_chunk + b"\x00" * 4


def test_image_dimensions_rejects_small_png(tmp_path: Path) -> None:
    check = image_dimensions(min_w=64)
    assert check.sentinel is False
    tiny = _write(tmp_path / "tiny.png", _make_png(32, 32))
    big = _write(tmp_path / "big.png", _make_png(128, 128))
    assert check.run(tiny).ok is False
    assert check.run(big).ok is True


def test_all_of_sentinel_is_false_when_any_constituent_is_semantic() -> None:
    composite = all_of(file_nonempty(), json_file())
    assert composite.sentinel is False
    composite_pure_sentinel = all_of(file_nonempty(), file_nonempty())
    assert composite_pure_sentinel.sentinel is True


def test_all_of_runs_each_check_short_circuits_on_failure(tmp_path: Path) -> None:
    composite = all_of(file_nonempty(), json_file())
    bad = _write(tmp_path / "bad.json", b"not json")
    empty = _write(tmp_path / "empty.bin", b"")
    good = _write(tmp_path / "good.json", b'{"a":1}')
    assert composite.run(empty).ok is False
    assert composite.run(bad).ok is False
    assert composite.run(good).ok is True


def test_canonical_check_params_orders_keys_recursively() -> None:
    a = canonical_check_params({"a": 1, "b": 2})
    b = canonical_check_params({"b": 2, "a": 1})
    assert a == b
    assert list(a.keys()) == ["a", "b"]
    nested_a = canonical_check_params({"x": {"q": 1, "p": 2}, "y": 3})
    nested_b = canonical_check_params({"y": 3, "x": {"p": 2, "q": 1}})
    assert nested_a == nested_b


def test_json_schema_canonical_params_equality() -> None:
    a = json_schema({"a": 1, "b": 2})
    b = json_schema({"b": 2, "a": 1})
    assert a.params == b.params
