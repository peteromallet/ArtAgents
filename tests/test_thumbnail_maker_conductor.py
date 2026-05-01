import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.conductors import ConductorRunRequest, load_default_registry, run_conductor
from artagents.conductors import cli


class ThumbnailMakerConductorTest(unittest.TestCase):
    def test_builtin_thumbnail_maker_is_registered_with_metadata(self) -> None:
        conductor = load_default_registry().get("builtin.thumbnail_maker")

        self.assertEqual(conductor.kind, "built_in")
        self.assertEqual(conductor.runtime.kind, "python")
        self.assertEqual(conductor.metadata["legacy_entrypoint"], "thumbnail_maker.py")
        self.assertFalse(next(port for port in conductor.inputs if port.name == "video").required)
        self.assertFalse(next(port for port in conductor.inputs if port.name == "query").required)

    def test_dry_run_merges_inputs_and_generic_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_conductor(
                ConductorRunRequest(
                    "builtin.thumbnail_maker",
                    out=root / "generic",
                    inputs={"video": root / "source.mp4", "query": "speaker title"},
                    dry_run=True,
                )
            )

        command = result.planned_commands[0]
        self.assertEqual(command[0], "thumbnail_maker.py")
        self.assertIn("--video", command)
        self.assertIn("--query", command)
        self.assertIn("--out", command)
        self.assertIn("--dry-run", command)

    def test_dry_run_passthrough_out_takes_precedence(self) -> None:
        result = run_conductor(
            ConductorRunRequest(
                "builtin.thumbnail_maker",
                out="/tmp/generic-dir",
                conductor_args=("--video", "/tmp/source.mp4", "--query", "speaker", "--out", "/tmp/explicit-dir"),
                dry_run=True,
            )
        )

        command = result.planned_commands[0]
        self.assertIn("/tmp/explicit-dir", command)
        self.assertNotIn("/tmp/generic-dir", command)

    def test_missing_merged_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "requires merged query values"):
            run_conductor(
                ConductorRunRequest(
                    "builtin.thumbnail_maker",
                    out="/tmp/out",
                    inputs={"video": "/tmp/source.mp4"},
                    dry_run=True,
                )
            )

    def test_cli_dry_run_invocation_with_inputs(self) -> None:
        registry = load_default_registry()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(cli, "load_default_registry", return_value=registry),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = cli.main(
                    [
                        "run",
                        "builtin.thumbnail_maker",
                        "--out",
                        str(root / "out"),
                        "--input",
                        f"video={root / 'source.mp4'}",
                        "--input",
                        "query=speaker title",
                        "--dry-run",
                    ]
                )

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("thumbnail_maker.py", stdout.getvalue())
        self.assertIn("--out", stdout.getvalue())

    def test_cli_list_inspect_and_validate_thumbnail_maker(self) -> None:
        registry = load_default_registry()

        for argv, expected in (
            (["list", "--json"], "builtin.thumbnail_maker"),
            (["inspect", "builtin.thumbnail_maker", "--json"], "thumbnail_maker.py"),
            (["validate", "builtin.thumbnail_maker"], "builtin.thumbnail_maker: ok"),
        ):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(cli, "load_default_registry", return_value=registry),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = cli.main(argv)
            self.assertEqual(result, 0, stderr.getvalue())
            self.assertIn(expected, stdout.getvalue())

    def test_cli_dry_run_invocation_with_passthrough(self) -> None:
        registry = load_default_registry()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(cli, "load_default_registry", return_value=registry),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = cli.main(
                [
                    "run",
                    "builtin.thumbnail_maker",
                    "--out",
                    "/tmp/generic",
                    "--dry-run",
                    "--",
                    "--video",
                    "/tmp/source.mp4",
                    "--query",
                    "speaker",
                    "--out",
                    "/tmp/explicit",
                ]
            )

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("/tmp/explicit", stdout.getvalue())
        self.assertNotIn("/tmp/generic", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
