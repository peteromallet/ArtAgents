import importlib
import importlib.util
import unittest

from artagents.pipeline import STEP_ORDER


STEP_MODULES = {name: name for name in STEP_ORDER}


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
                folder_entrypoint = importlib.import_module(f"artagents.executors.{step_name}.run")
                self.assertTrue(hasattr(folder_entrypoint, "main"))

    def test_step_order_executor_modules_do_not_live_under_builtin_package(self) -> None:
        for step_name, module_name in STEP_MODULES.items():
            with self.subTest(step=step_name):
                self.assertIsNone(_find_spec(f"artagents.executors.builtin.{module_name}"))


if __name__ == "__main__":
    unittest.main()
