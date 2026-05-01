from __future__ import annotations

import json

import pytest

from artagents.generate_image import load_api_key, main
from artagents.llm_clients import _load_api_key


def test_generate_image_dry_run_multiple_variants(capsys, tmp_path):
    out_dir = tmp_path / "images"
    code = main(
        [
            "--prompt",
            "red triangle on white background",
            "--n",
            "2",
            "--size",
            "1024x1024",
            "--quality",
            "low",
            "--output-format",
            "webp",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "gpt-image-2"
    assert payload["n"] == 2
    assert payload["size"] == "1024x1024"
    assert payload["quality"] == "low"
    assert payload["output_format"] == "webp"
    assert payload["outputs"] == [
        str(out_dir / "001-red-triangle-on-white-background-1.webp"),
        str(out_dir / "001-red-triangle-on-white-background-2.webp"),
    ]


def test_generate_image_rejects_invalid_gpt_image_2_size():
    with pytest.raises(SystemExit):
        main(["--prompt", "bad size", "--size", "1000x1000", "--dry-run"])


def test_load_api_key_reads_this_env_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / "this.env").write_text("OPENAI_API_KEY=from-this-env\n", encoding="utf-8")

    assert load_api_key() == "from-this-env"


def test_load_api_key_prefers_process_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "from-process-env")
    (tmp_path / "this.env").write_text("OPENAI_API_KEY=from-this-env\n", encoding="utf-8")

    assert load_api_key() == "from-process-env"


def test_llm_client_key_loader_reads_this_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "this.env").write_text("ANTHROPIC_API_KEY=from-this-env\n", encoding="utf-8")

    assert _load_api_key(None, "ANTHROPIC_API_KEY") == "from-this-env"
