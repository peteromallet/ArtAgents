"""Tests for the post-T11 project CLI.

The pre-T10 CLI exposed `place-source` / `place-run` / `remove` / `materialize`
subcommands against a parallel placement schema; T10 deleted that schema and
T11 reinstated `list <project_id>` / `edit <project_id>` over reigh-app
``timelines`` rows. These tests cover:

* `create` / `show` / `source add` baseline behavior (no timeline.json write).
* `list` POSTs to reigh-data-fetch with PAT auth and prints per-timeline rows.
* `edit add-clip` / `move-clip` / `set-theme` shell out to ops_helper.mjs and
  call SupabaseDataProvider.save_timeline with the EXACT 3-param RPC shape
  ({p_timeline_id, p_expected_version, p_config}) and PAT auth by default,
  service-role only with the explicit --service-role flag.
* Version-mismatch retries through the mutator path (exhausts at N=3 with
  TimelineVersionConflictError).
* The save_timeline contract refuses expected_version=None unless force=True.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from artagents.core.project import paths
from artagents.core.project import cli as project_cli
from artagents.core.reigh import data_provider as dp_mod
from artagents.core.reigh import timeline_io as tio
from artagents.core.reigh.errors import TimelineVersionConflictError
from artagents.core.reigh.supabase_client import SupabaseHTTPError


ROOT = Path(__file__).resolve().parents[1]


def _canonical_timeline() -> dict[str, Any]:
    return {
        "theme": "banodoco-default",
        "clips": [
            {
                "id": "c1",
                "at": 0,
                "track": "main",
                "clipType": "text",
                "text": {"content": "hi"},
                "hold": 1.0,
            }
        ],
    }


class _ProjectsRoot:
    """Per-test helper that points ARTAGENTS_PROJECTS_ROOT at a temp dir."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="t12-cli-", dir=ROOT))

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class CreateShowSourceCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _ProjectsRoot()
        self.addCleanup(self.root.cleanup)
        self._patch = patch.dict("os.environ", {paths.PROJECTS_ROOT_ENV: str(self.root.tmp)})
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_create_project_does_not_write_timeline_json(self) -> None:
        rc = project_cli.main(["create", "demo", "--name", "Demo", "--json"])
        self.assertEqual(rc, 0)
        project_dir = self.root.tmp / "demo"
        self.assertTrue((project_dir / "project.json").is_file())
        self.assertTrue((project_dir / "sources").is_dir())
        self.assertTrue((project_dir / "runs").is_dir())
        self.assertFalse((project_dir / "timeline.json").exists())

    def test_create_with_project_id_persists_uuid(self) -> None:
        rc = project_cli.main(
            ["create", "demo2", "--project-id", "00000000-1111-2222-3333-444455556666"]
        )
        self.assertEqual(rc, 0)
        payload = json.loads((self.root.tmp / "demo2" / "project.json").read_text("utf-8"))
        self.assertEqual(payload["project_id"], "00000000-1111-2222-3333-444455556666")

    def test_show_includes_project_id_when_set(self) -> None:
        project_cli.main(["create", "demo", "--project-id", "abc-uuid"])
        rc = project_cli.main(["show", "--project", "demo", "--json"])
        self.assertEqual(rc, 0)


class ListCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _ProjectsRoot()
        self.addCleanup(self.root.cleanup)

    def test_list_posts_to_reigh_data_fetch_with_pat(self) -> None:
        captured: list[dict[str, Any]] = []

        def fake_post(url, payload, *, auth, timeout=None, **_):
            captured.append({"url": url, "payload": dict(payload or {}), "auth": auth})
            return {
                "timelines": [
                    {"id": "tl-1", "name": "Demo", "config_version": 7, "updated_at": "2026-05-04"},
                ]
            }

        with patch(
            "artagents.core.reigh.supabase_client.post_json", side_effect=fake_post
        ), patch("artagents.core.reigh.env.resolve_pat", return_value="pat-token"), patch(
            "artagents.core.reigh.env.resolve_api_url",
            return_value="https://x/functions/v1/reigh-data-fetch",
        ):
            rc = project_cli.main(["list", "proj-1", "--json"])

        self.assertEqual(rc, 0, msg=captured)
        self.assertEqual(captured[0]["url"], "https://x/functions/v1/reigh-data-fetch")
        self.assertEqual(captured[0]["payload"]["project_id"], "proj-1")
        self.assertEqual(captured[0]["auth"], ("pat", "pat-token"))


class EditCLITest(unittest.TestCase):
    """Edit verbs go through ops_helper.mjs + SupabaseDataProvider.save_timeline."""

    def _run_edit(
        self,
        argv: list[str],
        *,
        rpc_responses: list[Any] | None = None,
        ops_helper_result: dict[str, Any] | None = None,
        load_versions: list[int] | None = None,
    ):
        rpc_responses = list(rpc_responses or [{"config_version": 8}])
        ops_helper_result = ops_helper_result or {
            "timeline": {**_canonical_timeline(), "theme": "edited"},
            "version": 7,
            "op": "set-theme",
            "changed": True,
            "detail": {"previousTheme": "banodoco-default", "nextTheme": "edited"},
        }
        load_versions = list(load_versions or [7])

        rpc_calls: list[dict[str, Any]] = []
        ops_calls: list[dict[str, Any]] = []
        fetch_calls: list[dict[str, Any]] = []

        def fake_post_json(url, payload, *, auth, timeout):
            fetch_calls.append({"url": url, "payload": dict(payload or {}), "auth": auth})
            version = load_versions.pop(0) if load_versions else 7
            return {
                "timelines": [
                    {
                        "id": payload["timeline_id"],
                        "config": _canonical_timeline(),
                        "config_version": version,
                    }
                ]
            }

        def fake_rpc(name, params, *, supabase_url, auth, timeout):
            rpc_calls.append(
                {"name": name, "params": dict(params), "auth": auth, "supabase_url": supabase_url}
            )
            response = rpc_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        class FakeCompleted:
            def __init__(self, *, returncode=0, stdout="", stderr="") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_subprocess_run(cmd, *, input, capture_output, text, check):
            ops_calls.append({"cmd": cmd, "input": json.loads(input)})
            return FakeCompleted(stdout=json.dumps(ops_helper_result) + "\n")

        with patch(
            "artagents.core.reigh.env.resolve_supabase_url", return_value="https://x"
        ), patch(
            "artagents.core.reigh.env.resolve_api_url",
            return_value="https://x/functions/v1/reigh-data-fetch",
        ), patch("artagents.core.reigh.env.resolve_pat", return_value="pat-token"), patch(
            "artagents.core.reigh.env.resolve_service_role_key", return_value="srv-key"
        ), patch.object(dp_mod, "post_json", side_effect=fake_post_json), patch.object(
            tio, "post_json", side_effect=fake_post_json
        ), patch.object(tio, "rpc", side_effect=fake_rpc), patch.object(
            project_cli, "OPS_HELPER", ROOT / "scripts" / "node" / "ops_helper.mjs"
        ), patch("shutil.which", return_value="/usr/bin/node"), patch(
            "artagents.core.project.cli.subprocess.run", side_effect=fake_subprocess_run
        ):
            rc = project_cli.main(argv)
        return rc, fetch_calls, ops_calls, rpc_calls

    def test_edit_set_theme_calls_rpc_with_three_params_via_pat_auth(self) -> None:
        rc, fetch_calls, ops_calls, rpc_calls = self._run_edit(
            [
                "edit",
                "proj-1",
                "--timeline-id",
                "tl-1",
                "set-theme",
                "--theme-id",
                "edited",
            ]
        )
        self.assertEqual(rc, 0, msg=(fetch_calls, ops_calls, rpc_calls))
        # ops_helper invoked with set-theme + correct args.
        self.assertEqual(len(ops_calls), 1)
        self.assertEqual(ops_calls[0]["input"]["op"], "set-theme")
        self.assertEqual(ops_calls[0]["input"]["args"], {"themeId": "edited"})
        # RPC called with EXACTLY 3 params, no project_id.
        self.assertEqual(len(rpc_calls), 1)
        self.assertEqual(rpc_calls[0]["name"], "update_timeline_config_versioned")
        self.assertEqual(
            set(rpc_calls[0]["params"].keys()),
            {"p_timeline_id", "p_expected_version", "p_config"},
        )
        self.assertNotIn("project_id", rpc_calls[0]["params"])
        # Default auth is PAT (SD-009).
        self.assertEqual(rpc_calls[0]["auth"][0], "pat")
        self.assertNotEqual(rpc_calls[0]["auth"][0], "service_role")

    def test_edit_service_role_flag_routes_through_service_role_auth(self) -> None:
        rc, _, _, rpc_calls = self._run_edit(
            [
                "edit",
                "proj-1",
                "--timeline-id",
                "tl-1",
                "--service-role",
                "set-theme",
                "--theme-id",
                "edited",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(rpc_calls[0]["auth"][0], "service_role")

    def test_edit_version_mismatch_retries_then_exhausts_at_three(self) -> None:
        conflict = SupabaseHTTPError(
            "conflict", status=409, body="version_conflict expected_version mismatch"
        )
        with self.assertRaises(TimelineVersionConflictError):
            self._run_edit(
                [
                    "edit",
                    "proj-1",
                    "--timeline-id",
                    "tl-1",
                    "set-theme",
                    "--theme-id",
                    "edited",
                ],
                rpc_responses=[conflict, conflict, conflict],
                load_versions=[7, 7, 7, 7],
            )

    def test_edit_add_clip_passes_clip_to_ops_helper(self) -> None:
        clip = {
            "id": "new",
            "at": 5,
            "track": "main",
            "clipType": "text",
            "text": {"content": "x"},
            "hold": 1,
        }
        rc, _, ops_calls, _ = self._run_edit(
            [
                "edit",
                "proj-1",
                "--timeline-id",
                "tl-1",
                "add-clip",
                "--clip-json",
                json.dumps(clip),
                "--position",
                "1",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(ops_calls[0]["input"]["op"], "add-clip")
        self.assertEqual(ops_calls[0]["input"]["args"]["clip"], clip)
        self.assertEqual(ops_calls[0]["input"]["args"]["position"], 1)


class SaveTimelineExpectedVersionContractTest(unittest.TestCase):
    """Worker path forbids force=True; expected_version=None is rejected."""

    def test_save_timeline_rejects_expected_version_none_unless_force(self) -> None:
        with self.assertRaises(ValueError):
            tio.save_timeline(
                timeline_id="tl-1",
                project_id="proj-1",
                mutator=lambda c, v: c,
                fetch_url="https://x",
                supabase_url="https://x",
                read_auth=("pat", "t"),
                write_auth=("service_role", "k"),
                expected_version=None,
                force=False,
            )


if __name__ == "__main__":
    unittest.main()
