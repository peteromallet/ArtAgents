import io
import json
import urllib.error
from pathlib import Path

import pytest

from artagents import reigh_data


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_reigh_data_posts_pat_authenticated_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"ok": True})

    monkeypatch.setattr(reigh_data.urllib.request, "urlopen", fake_urlopen)

    data = reigh_data.fetch_reigh_data(
        project_id="project-1",
        shot_id="shot-1",
        task_id="task-1",
        timeline_id="timeline-1",
        api_url="https://example.functions.supabase.co/functions/v1/reigh-data-fetch",
        pat="pat-token",
        timeout=12,
    )

    assert data == {"ok": True}
    assert captured["url"] == "https://example.functions.supabase.co/functions/v1/reigh-data-fetch"
    assert captured["timeout"] == 12
    assert captured["headers"]["Authorization"] == "Bearer pat-token"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {
        "project_id": "project-1",
        "shot_id": "shot-1",
        "task_id": "task-1",
        "timeline_id": "timeline-1",
    }


def test_resolve_api_url_from_supabase_url_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")

    assert (
        reigh_data.resolve_api_url()
        == "https://example.supabase.co/functions/v1/reigh-data-fetch"
    )


def test_resolve_pat_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("REIGH_PAT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("REIGH_PERSONAL_ACCESS_TOKEN='secret-token'\n", encoding="utf-8")

    assert reigh_data.resolve_pat(env_file=env_file) == "secret-token"


def test_fetch_reigh_data_reports_http_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs={},
            fp=io.BytesIO(b'{"error":"Forbidden"}'),
        )

    monkeypatch.setattr(reigh_data.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match='HTTP 403: \\{"error":"Forbidden"\\}'):
        reigh_data.fetch_reigh_data(
            project_id="project-1",
            api_url="https://example.functions.supabase.co/functions/v1/reigh-data-fetch",
            pat="pat-token",
        )


def test_cli_writes_output(tmp_path, monkeypatch):
    out = tmp_path / "reigh.json"
    monkeypatch.setattr(
        reigh_data,
        "fetch_reigh_data",
        lambda **kwargs: {"project_id": kwargs["project_id"], "shot_count": 1},
    )

    assert reigh_data.main(["--project-id", "project-1", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "project_id": "project-1",
        "shot_count": 1,
    }
