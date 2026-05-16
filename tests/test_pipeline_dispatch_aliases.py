import contextlib
import io
import sys
import unittest
from unittest import mock

from astrid import pipeline


class PipelineDispatchAliasTest(unittest.TestCase):
    def test_root_help_explains_canonical_gateway(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(pipeline.main(["--help"]), 0)

        help_text = stdout.getvalue()
        self.assertIn("Astrid command gateway", help_text)
        self.assertIn("python3 -m astrid orchestrators {list,search,inspect,validate,run}", help_text)
        self.assertIn("python3 -m astrid executors {new,list,search,inspect,validate,install,run}", help_text)
        self.assertIn("python3 -m astrid elements {list,search,inspect,validate,fork,install}", help_text)
        self.assertIn("python3 -m astrid is the package entry point", help_text)
        self.assertNotIn("pipeline.py", help_text)
        self.assertNotIn("conductors", help_text)
        self.assertNotIn("performers", help_text)

    def test_elements_dispatches_before_pipeline_validation(self) -> None:
        from astrid.core.element import cli as elements_cli

        with mock.patch.object(elements_cli, "main", return_value=31) as elements_main:
            self.assertEqual(pipeline.main(["elements", "list"]), 31)
            elements_main.assert_called_once_with(["list"])

    def test_legacy_public_dispatch_tokens_are_rejected(self) -> None:
        for token in ("performers", "instruments", "conductors", "primitives"):
            with self.subTest(token=token):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    pipeline.main([token, "list"])
                self.assertEqual(raised.exception.code, 2)

    def test_doctor_and_setup_dispatch_before_legacy_validation(self) -> None:
        from astrid import doctor, setup_cli

        with mock.patch.object(doctor, "main", return_value=41) as doctor_main:
            self.assertEqual(pipeline.main(["doctor", "--help"]), 41)
            doctor_main.assert_called_once_with(["--help"])

        with mock.patch.object(setup_cli, "main", return_value=42) as setup_main:
            self.assertEqual(pipeline.main(["setup", "--help"]), 42)
            setup_main.assert_called_once_with(["--help"])

    def test_publish_dispatch_uses_package_relative_imports(self) -> None:
        from astrid.packs.builtin.executors.publish import run as publish
        from astrid.packs.upload.executors.youtube import run as publish_youtube

        with mock.patch.object(publish, "main", return_value=51) as publish_main:
            self.assertEqual(pipeline.main(["publish", "--help"]), 51)
            publish_main.assert_called_once_with(["--help"])

        with mock.patch.object(publish_youtube, "main", return_value=52) as youtube_main:
            self.assertEqual(pipeline.main(["publish-youtube", "--help"]), 52)
            youtube_main.assert_called_once_with(["--help"])

        with mock.patch.object(publish_youtube, "main", return_value=53) as youtube_main:
            self.assertEqual(pipeline.main(["upload-youtube", "--help"]), 53)
            youtube_main.assert_called_once_with(["--help"])

    def test_package_is_executable(self) -> None:
        import runpy

        old_argv = sys.argv
        stdout = io.StringIO()
        try:
            sys.argv = ["python3 -m astrid", "elements", "list", "--kind", "effects"]
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_module("astrid", run_name="__main__")
        finally:
            sys.argv = old_argv

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("effects\ttext-card", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
