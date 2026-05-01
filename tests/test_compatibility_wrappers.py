import runpy
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class CompatibilityWrapperTest(unittest.TestCase):
    def test_root_pipeline_launcher_calls_package_main(self) -> None:
        with mock.patch("artagents.pipeline.main", return_value=0) as package_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "pipeline.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        package_main.assert_called_once_with()

    def test_root_event_talks_launcher_calls_package_main(self) -> None:
        with mock.patch("artagents.event_talks.main", return_value=0) as package_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "event_talks.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        package_main.assert_called_once_with()

    def test_root_thumbnail_maker_launcher_calls_package_main(self) -> None:
        with mock.patch("artagents.thumbnail_maker.main", return_value=0) as package_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "thumbnail_maker.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        package_main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
