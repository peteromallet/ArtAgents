import importlib
import importlib.util
import subprocess
import sys
import unittest

from artagents.pipeline import STEP_ORDER


STEP_MODULES = {
    "render": "render_remotion",
    **{name: name for name in STEP_ORDER if name != "render"},
}


def _find_spec(name: str):
    try:
        return importlib.util.find_spec(name)
    except ModuleNotFoundError:
        return None


class ExecutorMoveWrapperTest(unittest.TestCase):
    def test_old_action_import_paths_are_absent_and_folder_entrypoints_work(self) -> None:
        for name in ("audio_understand", "visual_understand", "video_understand"):
            self.assertIsNone(_find_spec(f"artagents.{name}"))
            folder_entrypoint = importlib.import_module(f"artagents.executors.{name}.run")
            self.assertTrue(hasattr(folder_entrypoint, "main"))
            self.assertIsNone(_find_spec(f"artagents.executors.actions.{name}"))

    def test_old_step_import_paths_are_absent_and_folder_entrypoints_work(self) -> None:
        for step_name, module_name in STEP_MODULES.items():
            with self.subTest(step=step_name):
                self.assertIsNone(_find_spec(f"artagents.{module_name}"))
                folder_name = "render" if step_name == "render" else step_name
                folder_entrypoint = importlib.import_module(f"artagents.executors.{folder_name}.run")
                self.assertTrue(hasattr(folder_entrypoint, "main"))

    def test_step_order_executor_modules_do_not_live_under_builtin_package(self) -> None:
        for step_name, module_name in STEP_MODULES.items():
            with self.subTest(step=step_name):
                self.assertIsNone(_find_spec(f"artagents.executors.builtin.{module_name}"))

    def test_bin_launchers_still_reach_moved_modules(self) -> None:
        commands = [
            [sys.executable, "bin/audio_understand.py", "--audio", "missing.wav", "--dry-run"],
            [sys.executable, "bin/visual_understand.py", "--image", "missing.png", "--query", "x", "--dry-run"],
            [sys.executable, "bin/video_understand.py", "--video", "missing.mp4", "--dry-run"],
        ]
        for command in commands:
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotIn("ModuleNotFoundError", result.stderr + result.stdout)

    def test_step_order_bin_launchers_still_reach_executor_folders(self) -> None:
        for step_name, module_name in STEP_MODULES.items():
            with self.subTest(step=step_name):
                result = subprocess.run(
                    [sys.executable, f"bin/{module_name}.py", "--help"],
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertNotIn("ModuleNotFoundError", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
