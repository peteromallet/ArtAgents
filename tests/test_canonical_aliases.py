import importlib.util
import unittest

from artagents.core.executor import ExecutorDefinition, ExecutorRegistry, load_default_registry as load_executor_registry
from artagents.core.orchestrator import OrchestratorDefinition, OrchestratorRegistry, load_default_registry as load_orchestrator_registry
import artagents.elements as legacy_elements
import artagents.executors as legacy_executors
import artagents.orchestrators as legacy_orchestrators


class CanonicalAliasTest(unittest.TestCase):
    def test_orchestrator_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(OrchestratorDefinition.__module__, "artagents.core.orchestrator.schema")
        self.assertEqual(OrchestratorRegistry.__module__, "artagents.core.orchestrator.registry")

        registry = load_orchestrator_registry()

        self.assertIn("builtin.hype", registry.as_mapping())
        self.assertIsInstance(registry, OrchestratorRegistry)

    def test_executor_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(ExecutorDefinition.__module__, "artagents.core.executor.schema")
        self.assertEqual(ExecutorRegistry.__module__, "artagents.core.executor.registry")

        registry = load_executor_registry()

        self.assertIn("builtin.transcribe", registry.as_mapping())
        self.assertIn("external.vibecomfy.run", registry.as_mapping())
        self.assertIsInstance(registry, ExecutorRegistry)

    def test_legacy_public_packages_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("artagents.performers"))
        self.assertIsNone(importlib.util.find_spec("artagents.conductors"))

    def test_content_packages_keep_framework_api_exports(self) -> None:
        self.assertEqual(legacy_executors.ExecutorRunRequest.__module__, "artagents.core.executor.runner")
        self.assertEqual(legacy_executors.ExecutorRegistry.__module__, "artagents.core.executor.registry")
        self.assertIs(legacy_executors.load_default_registry, load_executor_registry)
        self.assertEqual(legacy_orchestrators.OrchestratorRunRequest.__module__, "artagents.core.orchestrator.runner")
        self.assertEqual(legacy_orchestrators.OrchestratorRegistry.__module__, "artagents.core.orchestrator.registry")
        self.assertIs(legacy_orchestrators.load_default_registry, load_orchestrator_registry)
        self.assertEqual(legacy_elements.ElementRegistry.__module__, "artagents.core.element.registry")
        self.assertEqual(legacy_elements.ElementDefinition.__module__, "artagents.core.element.schema")

    def test_top_level_orchestrator_modules_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("artagents.event_talks"))
        self.assertIsNone(importlib.util.find_spec("artagents.thumbnail_maker"))
        self.assertIsNone(importlib.util.find_spec("artagents.understand"))


if __name__ == "__main__":
    unittest.main()
