from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from artagents.executors import cli as executors_cli
from artagents.executors.folder import load_folder_executors
from artagents.executors.registry import load_default_registry


class VibeComfyStructuredMetadataTest(unittest.TestCase):
    def test_executor_inspect_exposes_structured_vibecomfy_metadata(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = executors_cli.main(["inspect", "external.vibecomfy.run", "--json"])

        self.assertEqual(result, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        metadata = payload["metadata"]

        self.assertEqual(payload["id"], "external.vibecomfy.run")
        self.assertEqual(payload["command"]["argv"], ["{python_exec}", "-m", "vibecomfy.cli", "run", "{workflow}"])
        self.assertEqual(payload["isolation"]["requirements"], ["vibecomfy"])
        self.assertTrue(payload["isolation"]["network"])
        self.assertEqual(metadata["package_id"], "vibecomfy")
        self.assertEqual(metadata["homepage"], "https://github.com/peteromallet/VibeComfy")
        self.assertEqual(metadata["cli_module"], "vibecomfy.cli")
        self.assertEqual(metadata["vibecomfy_command"], "run")
        self.assertEqual(metadata["command_names"], ["run", "validate"])
        self.assertEqual(metadata["requirements"], ["vibecomfy"])
        self.assertEqual(metadata["requirements_source"], "requirements.txt")
        self.assertEqual(
            metadata["workflow_input_contract"],
            {
                "name": "workflow",
                "type": "file",
                "required": True,
                "description": "VibeComfy workflow JSON file.",
                "format": "ComfyUI/VibeComfy workflow JSON",
            },
        )
        self.assertEqual(metadata["network_behavior"], {"run": True, "validate": False})
        self.assertEqual(metadata["catalog_source"], "none_declared")
        self.assertEqual(metadata["workflows"], [])
        self.assertEqual(metadata["nodes"], [])
        self.assertEqual(metadata["prompts"], [])

    def test_vibecomfy_validate_metadata_is_structured_and_network_false(self) -> None:
        validate = load_default_registry().get("external.vibecomfy.validate")

        self.assertFalse(validate.isolation.network)
        self.assertEqual(validate.metadata["vibecomfy_command"], "validate")
        self.assertEqual(validate.metadata["network_behavior"], {"run": True, "validate": False})
        self.assertEqual(validate.metadata["catalog_source"], "none_declared")
        self.assertEqual(validate.metadata["workflows"], [])
        self.assertEqual(validate.metadata["nodes"], [])
        self.assertEqual(validate.metadata["prompts"], [])

    def test_vibecomfy_catalogs_do_not_scrape_skill_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor_root = root / "vibecomfy"
            executor_root.mkdir()
            (executor_root / "requirements.txt").write_text("different-package\n", encoding="utf-8")
            (executor_root / "SKILL.md").write_text(
                "Fake structured catalog that must not be scraped: workflows=fake nodes=fake prompts=fake\n",
                encoding="utf-8",
            )
            (executor_root / "executor.yaml").write_text(
                "\n".join(
                    [
                        "executors:",
                        "  - id: external.vibecomfy.run",
                        "    name: VibeComfy Run",
                        "    kind: external",
                        "    version: 0.1.0",
                        "    inputs:",
                        "      - name: workflow",
                        "        type: file",
                        "    command:",
                        "      argv: [\"{python_exec}\", \"-m\", \"vibecomfy.cli\", \"run\", \"{workflow}\"]",
                        "    cache:",
                        "      mode: none",
                        "    isolation:",
                        "      mode: subprocess",
                        "      requirements: [\"vibecomfy\"]",
                        "      network: true",
                        "    metadata:",
                        "      package_id: vibecomfy",
                        "      catalog_source: none_declared",
                        "      workflows: []",
                        "      nodes: []",
                        "      prompts: []",
                    ]
                ),
                encoding="utf-8",
            )

            executors = load_folder_executors(executor_root)

        by_id = {executor.id: executor for executor in executors}
        run = by_id["external.vibecomfy.run"]
        self.assertEqual(run.metadata["catalog_source"], "none_declared")
        self.assertEqual(run.metadata["workflows"], [])
        self.assertEqual(run.metadata["nodes"], [])
        self.assertEqual(run.metadata["prompts"], [])
        self.assertNotIn("fake", json.dumps(run.metadata).lower())
        self.assertTrue(run.metadata["skill_file"].endswith("SKILL.md"))


if __name__ == "__main__":
    unittest.main()
