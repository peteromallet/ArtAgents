import os
import tempfile
import unittest
from pathlib import Path

from artagents.conductors import FolderConductorError, discover_folder_conductor_roots, load_folder_conductor, load_folder_conductors


class ConductorFolderTest(unittest.TestCase):
    def test_folder_conductor_discovery_extracts_metadata_out_of_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conductor_root = root / "curated" / "example"
            conductor_root.mkdir(parents=True)
            (conductor_root / "requirements.txt").write_text("example-package\n", encoding="utf-8")
            (conductor_root / "SKILL.md").write_text("# Example\n", encoding="utf-8")
            leak_key = "ARTAGENTS_FOLDER_CONDUCTOR_IMPORT_LEAK"
            os.environ.pop(leak_key, None)
            (conductor_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "import os",
                        "from artagents.conductors import ConductorSpec, RuntimeSpec",
                        f"os.environ[{leak_key!r}] = 'child-only'",
                        "conductor = ConductorSpec(",
                        "    id='external.folder_example',",
                        "    name='Folder Example',",
                        "    runtime=RuntimeSpec(kind='python', module='example.runtime', function='run'),",
                        "    child_performers=['builtin.transcribe'],",
                        "    child_conductors=['external.child'],",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            roots = discover_folder_conductor_roots(root)
            conductors = load_folder_conductors(root)

        self.assertEqual(roots, (conductor_root.resolve(),))
        self.assertEqual(len(conductors), 1)
        self.assertEqual(conductors[0].id, "external.folder_example")
        self.assertEqual(conductors[0].runtime.module, "example.runtime")
        self.assertEqual(conductors[0].child_performers, ("builtin.transcribe",))
        self.assertEqual(conductors[0].child_conductors, ("external.child",))
        self.assertEqual(conductors[0].metadata["source"], "folder")
        self.assertEqual(conductors[0].metadata["conductor_root"], str(conductor_root.resolve()))
        self.assertEqual(conductors[0].metadata["requirements_file"], str((conductor_root / "requirements.txt").resolve()))
        self.assertEqual(conductors[0].metadata["skill_file"], str((conductor_root / "SKILL.md").resolve()))
        self.assertNotEqual(os.environ.get(leak_key), "child-only")

    def test_folder_conductor_discovery_flattens_conductors_with_shared_package_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conductor_root = root / "curated" / "multi_package"
            conductor_root.mkdir(parents=True)
            (conductor_root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (conductor_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors import ConductorSpec",
                        "PACKAGE_ID = 'shared-example'",
                        "CONDUCTORS = [",
                        "    ConductorSpec(",
                        "        id='external.multi.alpha',",
                        "        name='Alpha',",
                        "        runtime={'kind': 'command', 'command': {'argv': ['echo', 'alpha']}},",
                        "        cache={'mode': 'none'},",
                        "    ),",
                        "    ConductorSpec(",
                        "        id='external.multi.beta',",
                        "        name='Beta',",
                        "        runtime={'kind': 'command', 'command': {'argv': ['echo', 'beta']}},",
                        "        cache={'mode': 'none'},",
                        "    ),",
                        "]",
                    ]
                ),
                encoding="utf-8",
            )

            conductors = load_folder_conductors(root)

        self.assertEqual([conductor.id for conductor in conductors], ["external.multi.alpha", "external.multi.beta"])
        for item in conductors:
            self.assertEqual(item.metadata["source"], "folder")
            self.assertEqual(item.metadata["conductor_root"], str(conductor_root.resolve()))
            self.assertEqual(item.metadata["conductor_file"], str((conductor_root / "conductor.py").resolve()))
            self.assertEqual(item.metadata["folder_id"], "multi_package")
            self.assertEqual(item.metadata["package_id"], "shared-example")
            self.assertEqual(item.metadata["pyproject_file"], str((conductor_root / "pyproject.toml").resolve()))

    def test_folder_conductor_decorator_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor_root = Path(tmp) / "decorated"
            conductor_root.mkdir()
            (conductor_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors import conductor",
                        "",
                        "@conductor(",
                        "    id='external.decorated.example',",
                        "    name='Decorated Example',",
                        "    runtime={'kind': 'python', 'module': 'example.runtime', 'function': 'run'},",
                        "    cache={'mode': 'none'},",
                        ")",
                        "def run():",
                        "    pass",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = load_folder_conductor(conductor_root)

        self.assertEqual(loaded.id, "external.decorated.example")
        self.assertEqual(loaded.runtime.function, "run")
        self.assertEqual(loaded.metadata["folder_id"], "decorated")

    def test_folder_conductor_requires_top_level_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor_root = Path(tmp) / "missing_metadata"
            conductor_root.mkdir()
            (conductor_root / "conductor.py").write_text("VALUE = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(FolderConductorError, "top-level conductor or CONDUCTOR"):
                load_folder_conductor(conductor_root)


if __name__ == "__main__":
    unittest.main()
