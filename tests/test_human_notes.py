import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astrid.packs.builtin.arrange import run as arrange
from astrid.packs.builtin.editor_review import run as editor_review
from astrid.packs.builtin.human_notes import run as human_notes
from astrid import timeline


class FakeClaudeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.payload)


class HumanNotesTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="human-notes-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def pool(self) -> dict:
        return {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "src",
            "entries": [
                self.pool_entry("pool_d_0001", "dialogue", 0.0, 8.0, text="Hook quote"),
                self.pool_entry("pool_d_0002", "dialogue", 10.0, 18.0, text="Build quote"),
                self.pool_entry("pool_d_0003", "dialogue", 20.0, 28.0, text="Better quote"),
                self.pool_entry("pool_v_0001", "visual", 30.0, 38.0, subject="Speaker"),
                self.pool_entry("pool_v_0002", "visual", 40.0, 48.0, subject="Cutaway"),
                self.pool_entry("pool_v_0003", "reaction", 50.0, 53.0, subject="Reaction"),
            ],
        }

    def pool_entry(self, entry_id: str, category: str, start: float, end: float, **extra) -> dict:
        return {
            "id": entry_id,
            "kind": "source",
            "category": category,
            "asset": "main",
            "src_start": start,
            "src_end": end,
            "duration": end - start,
            "source_ids": {},
            "scores": {"triage": 0.8},
            "excluded": False,
            **extra,
        }

    def arrangement(self) -> dict:
        return {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Make it sharp.",
            "target_duration_sec": 80.0,
            "clips": [
                {
                    "order": 1,
                    "uuid": "00000001",
                    "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 8.0]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": "Hook.",
                },
                {
                    "order": 2,
                    "uuid": "00000002",
                    "audio_source": {"pool_id": "pool_d_0002", "trim_sub_range": [10.0, 18.0]},
                    "visual_source": {"pool_id": "pool_v_0001", "role": "primary"},
                    "text_overlay": None,
                    "rationale": "Build.",
                },
            ],
        }

    def write_inputs(self, tmp_dir: Path) -> dict[str, Path]:
        pool = self.pool()
        arrangement = self.arrangement()
        pool_path = tmp_dir / "pool.json"
        arrangement_path = tmp_dir / "arrangement.json"
        instructions_path = tmp_dir / "instructions.txt"
        timeline.save_pool(pool, pool_path)
        timeline.save_arrangement(arrangement, arrangement_path, {entry["id"] for entry in pool["entries"]})
        instructions_path.write_text("Make the opener tighter and swap clip two.", encoding="utf-8")
        return {
            "pool": pool_path,
            "arrangement": arrangement_path,
            "instructions": instructions_path,
            "out": tmp_dir / "out",
        }

    def argv(self, paths: dict[str, Path], *extra: str) -> list[str]:
        return [
            "--instructions",
            str(paths["instructions"]),
            "--arrangement",
            str(paths["arrangement"]),
            "--pool",
            str(paths["pool"]),
            "--out",
            str(paths["out"]),
            *extra,
        ]

    def note(self, **overrides) -> dict:
        note = {
            "clip_order": 1,
            "clip_uuid": "00000001",
            "observation": "Trim the pause.",
            "brief_impact": "Improves pace.",
            "action": "micro-fix",
            "action_detail": {"trim_delta_start_sec": 0.1, "trim_delta_end_sec": -0.2, "reason": "Tighter."},
            "priority": "medium",
            "candidate_pool_id": None,
        }
        note.update(overrides)
        return note

    def payload(self, notes: list[dict] | None = None) -> dict:
        return {
            "iteration": 1,
            "verdict": "iterate",
            "ship_confidence": 0.6,
            "notes": notes if notes is not None else [self.note()],
        }

    def apply_base(self, tmp_dir: Path, paths: dict[str, Path], *, include_hype: bool = True) -> dict[str, Path]:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        brief = tmp_dir / "brief.txt"
        brief_dir = tmp_dir / "brief-dir"
        run_dir = tmp_dir / "run-dir"
        video = tmp_dir / "video.mp4"
        asset = tmp_dir / "asset.mov"
        brief.write_text("Make it sharp.", encoding="utf-8")
        brief_dir.mkdir()
        run_dir.mkdir()
        video.write_bytes(b"video")
        asset.write_bytes(b"asset")
        if include_hype:
            for name in ("hype.timeline.json", "hype.assets.json", "hype.metadata.json"):
                (brief_dir / name).write_text("{}", encoding="utf-8")
        (run_dir / "scenes.json").write_text("{}", encoding="utf-8")
        (run_dir / "transcript.json").write_text("{}", encoding="utf-8")
        return {
            **paths,
            "brief": brief,
            "brief_dir": brief_dir,
            "run_dir": run_dir,
            "video": video,
            "asset": asset,
        }

    def apply_args(self, paths: dict[str, Path], *extra: str) -> list[str]:
        return self.argv(
            paths,
            "--apply",
            "--brief",
            str(paths["brief"]),
            "--brief-dir",
            str(paths["brief_dir"]),
            "--run-dir",
            str(paths["run_dir"]),
            *extra,
        )

    def test_happy_path_writes_editor_review_json(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        notes = [
            self.note(),
            self.note(
                clip_order=2,
                clip_uuid="00000002",
                observation="Use the better line.",
                action="swap",
                action_detail={"candidate_pool_id": "pool_d_0003", "role": "dialogue", "reason": "Sharper."},
                candidate_pool_id="pool_d_0003",
            ),
            self.note(action="accept", action_detail=None, observation="This beat works."),
        ]
        fake = FakeClaudeClient(self.payload(notes))

        out_path = human_notes.main(self.argv(paths, "--iteration", "2"), client=fake)

        self.assertEqual(out_path, paths["out"] / "editor_review.json")
        self.assertTrue(out_path.exists())
        written = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(written["iteration"], 2)
        self.assertIs(fake.calls[0]["response_schema"], editor_review.RESPONSE_SCHEMA)

    def test_rejects_clip_uuid_not_in_arrangement(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(self.payload([self.note(clip_uuid="ffffffff")]))

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

        self.assertFalse((paths["out"] / "editor_review.json").exists())

    def test_rejects_clip_uuid_order_mismatch(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(self.payload([self.note(clip_order=1, clip_uuid="00000002")]))

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_rejects_malformed_action_detail_micro_fix(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(
            self.payload(
                [
                    self.note(
                        action_detail={"trim_delta_start_sec": 0.1, "reason": "Missing end delta."},
                    )
                ]
            )
        )

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_rejects_malformed_action_detail_swap(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(
            self.payload(
                [
                    self.note(
                        action="swap",
                        action_detail={"candidate_pool_id": "pool_d_0003", "reason": "Missing role."},
                        candidate_pool_id="pool_d_0003",
                    )
                ]
            )
        )

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_rejects_malformed_action_detail_reorder(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(
            self.payload([self.note(action="reorder", action_detail={"reason": "Missing new order."})])
        )

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_rejects_malformed_action_detail_insert_stinger(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(
            self.payload(
                [
                    self.note(
                        action="insert-stinger",
                        action_detail={
                            "after_clip_order": 99,
                            "candidate_pool_id": "pool_v_0003",
                            "duration_sec": 2.0,
                            "reason": "Add a reaction.",
                        },
                    )
                ]
            )
        )

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_rejects_accept_with_non_null_action_detail(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        fake = FakeClaudeClient(
            self.payload([self.note(action="accept", action_detail={"reason": "Should be null."})])
        )

        with self.assertRaises(ValueError):
            human_notes.main(self.argv(paths), client=fake)

    def test_prompt_contains_arrangement_listing_and_pool_digest_and_instructions(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        pool = timeline.load_pool(paths["pool"])
        arrangement = timeline.load_arrangement(paths["arrangement"], {entry["id"] for entry in pool["entries"]})
        instructions_text = paths["instructions"].read_text(encoding="utf-8")
        fake = FakeClaudeClient(self.payload())

        human_notes.main(self.argv(paths), client=fake)

        system = fake.calls[0]["system"]
        self.assertIn(editor_review.arrangement_summary(arrangement), system)
        self.assertIn(arrange.pool_digest(pool), system)
        self.assertIn(instructions_text, system)

    def test_apply_requires_brief_brief_dir_run_dir_and_source_asset(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        apply_paths = self.apply_base(tmp_dir, paths)
        fake = FakeClaudeClient(self.payload())

        with self.assertRaises(SystemExit):
            human_notes.main(self.apply_args(apply_paths), client=fake)
        with self.assertRaises(SystemExit):
            human_notes.main(
                self.argv(
                    apply_paths,
                    "--apply",
                    "--brief-dir",
                    str(apply_paths["brief_dir"]),
                    "--run-dir",
                    str(apply_paths["run_dir"]),
                    "--video",
                    str(apply_paths["video"]),
                ),
                client=fake,
            )
        with self.assertRaises(SystemExit):
            human_notes.main(
                self.argv(
                    apply_paths,
                    "--apply",
                    "--brief",
                    str(apply_paths["brief"]),
                    "--run-dir",
                    str(apply_paths["run_dir"]),
                    "--video",
                    str(apply_paths["video"]),
                ),
                client=fake,
            )
        with self.assertRaises(SystemExit):
            human_notes.main(
                self.argv(
                    apply_paths,
                    "--apply",
                    "--brief",
                    str(apply_paths["brief"]),
                    "--brief-dir",
                    str(apply_paths["brief_dir"]),
                    "--video",
                    str(apply_paths["video"]),
                ),
                client=fake,
            )

        no_hype_paths = self.apply_base(tmp_dir / "no-hype", paths, include_hype=False)
        with self.assertRaises(SystemExit):
            human_notes.main(
                self.apply_args(no_hype_paths, "--video", str(no_hype_paths["video"])),
                client=fake,
            )

        self.assertEqual(fake.calls, [])

    def test_apply_invokes_subprocess_chain_in_pipeline_order(self) -> None:
        tmp_dir = self.make_tempdir()
        paths = self.write_inputs(tmp_dir)
        apply_paths = self.apply_base(tmp_dir, paths)
        fake = FakeClaudeClient(self.payload())
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))

        with mock.patch("subprocess.run", side_effect=fake_run):
            human_notes.main(
                self.apply_args(
                    apply_paths,
                    "--video",
                    str(apply_paths["video"]),
                    "--asset",
                    f"broll={apply_paths['asset']}",
                    "--primary-asset",
                    "main",
                ),
                client=fake,
            )

        self.assertEqual(len(calls), 4)
        self.assertEqual(
            [call[0][2] for call in calls],
            [
                "astrid.packs.builtin.arrange.run",
                "astrid.packs.builtin.cut.run",
                "astrid.packs.builtin.refine.run",
                "astrid.packs.builtin.render.run",
            ],
        )
        for _, kwargs in calls:
            self.assertTrue(kwargs["check"])
        cut_cmd = calls[1][0]
        for flag in ("--scenes", "--transcript", "--pool", "--arrangement", "--brief", "--video", "--out"):
            self.assertIn(flag, cut_cmd)
        self.assertIn("--asset", cut_cmd)
        self.assertNotIn("--render", cut_cmd)
        refine_cmd = calls[2][0]
        for flag in ("--timeline", "--assets", "--metadata"):
            self.assertIn(flag, refine_cmd)


if __name__ == "__main__":
    unittest.main()
