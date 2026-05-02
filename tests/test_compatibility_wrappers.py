import runpy
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class CompatibilityWrapperTest(unittest.TestCase):
    def test_event_talks_launcher_calls_canonical_orchestrator_main(self) -> None:
        with mock.patch("artagents.orchestrators.event_talks.run.main", return_value=0) as package_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "bin" / "event_talks.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        package_main.assert_called_once_with()

    def test_thumbnail_maker_launcher_calls_canonical_orchestrator_main(self) -> None:
        with mock.patch("artagents.orchestrators.thumbnail_maker.run.main", return_value=0) as package_main:
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "bin" / "thumbnail_maker.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        package_main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
