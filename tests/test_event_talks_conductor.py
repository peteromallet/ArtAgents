import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import event_talks
from artagents.conductors import ConductorRunRequest, ConductorRunnerError, load_default_registry, run_conductor


class EventTalksConductorTest(unittest.TestCase):
    def test_builtin_event_talks_is_registered_without_child_performers(self) -> None:
        conductor = load_default_registry().get("builtin.event_talks")

        self.assertEqual(conductor.kind, "built_in")
        self.assertEqual(conductor.runtime.kind, "python")
        self.assertEqual(conductor.child_performers, ())

    def test_missing_subcommand_fails_before_legacy_cli(self) -> None:
        with mock.patch.object(event_talks, "main", side_effect=AssertionError("legacy CLI should not run")):
            with self.assertRaisesRegex(ConductorRunnerError, "requires a passthrough subcommand"):
                run_conductor(ConductorRunRequest("builtin.event_talks", out="runs/event", dry_run=True))

    def test_unknown_subcommand_fails_before_legacy_cli(self) -> None:
        with mock.patch.object(event_talks, "main", side_effect=AssertionError("legacy CLI should not run")):
            with self.assertRaisesRegex(ConductorRunnerError, "unknown event_talks subcommand"):
                run_conductor(
                    ConductorRunRequest(
                        "builtin.event_talks",
                        out="runs/event",
                        conductor_args=("missing",),
                        dry_run=True,
                    )
                )

    def test_dry_run_plans_required_subcommands_without_calling_legacy_cli(self) -> None:
        cases = [
            ("ados-sunday-template", "--out", "talks.json"),
            ("search-transcript", "--transcript", "transcript.json"),
            ("find-holding-screens", "--video", "event.mp4", "--out", "holding.json"),
            ("render", "--manifest", "talks.json", "--out-dir", "rendered"),
        ]

        with mock.patch.object(event_talks, "main", side_effect=AssertionError("legacy CLI should not run")):
            for args in cases:
                with self.subTest(args=args):
                    result = run_conductor(
                        ConductorRunRequest(
                            "builtin.event_talks",
                            out="runs/event",
                            conductor_args=args,
                            dry_run=True,
                        )
                    )

                self.assertTrue(result.dry_run)
                self.assertIsNone(result.returncode)
                self.assertEqual(result.planned_commands, (("event_talks.py", *args),))
                self.assertIsNotNone(result.plan)
                self.assertEqual(result.plan.steps[0].command, ("event_talks.py", *args))

    def test_real_execution_forwards_passthrough_args_to_legacy_cli(self) -> None:
        with mock.patch.object(event_talks, "main", return_value=0) as legacy_main:
            result = run_conductor(
                ConductorRunRequest(
                    "builtin.event_talks",
                    out="runs/event",
                    conductor_args=("render", "--manifest", "talks.json", "--out-dir", "rendered", "--dry-run"),
                )
            )

        self.assertEqual(result.returncode, 0)
        legacy_main.assert_called_once_with(["render", "--manifest", "talks.json", "--out-dir", "rendered", "--dry-run"])

    def test_cli_dry_run_uses_passthrough_after_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_conductor(
                ConductorRunRequest(
                    "builtin.event_talks",
                    out=root,
                    conductor_args=("ados-sunday-template", "--out", str(root / "talks.json")),
                    dry_run=True,
                )
            )

        self.assertEqual(result.planned_commands[0][0], "event_talks.py")
        self.assertEqual(result.plan.steps[0].command, result.planned_commands[0])
        self.assertIn("ados-sunday-template", result.planned_commands[0])

    def test_event_talks_dry_run_does_not_require_generic_out(self) -> None:
        with mock.patch.object(event_talks, "main", side_effect=AssertionError("legacy CLI should not run")):
            result = run_conductor(
                ConductorRunRequest(
                    "builtin.event_talks",
                    conductor_args=("ados-sunday-template", "--out", "talks.json"),
                    dry_run=True,
                )
            )

        self.assertEqual(result.planned_commands, (("event_talks.py", "ados-sunday-template", "--out", "talks.json"),))
        self.assertEqual(result.plan.steps[0].command, result.planned_commands[0])


if __name__ == "__main__":
    unittest.main()
