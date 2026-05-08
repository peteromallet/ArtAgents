import importlib.util
import unittest

from astrid.core.executor import ExecutorDefinition, ExecutorRegistry, load_default_registry as load_executor_registry
from astrid.core.orchestrator import OrchestratorDefinition, OrchestratorRegistry, load_default_registry as load_orchestrator_registry
import astrid.elements as legacy_elements


class CanonicalAliasTest(unittest.TestCase):
    def test_orchestrator_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(OrchestratorDefinition.__module__, "astrid.core.orchestrator.schema")
        self.assertEqual(OrchestratorRegistry.__module__, "astrid.core.orchestrator.registry")

        registry = load_orchestrator_registry()

        self.assertIn("builtin.hype", registry.as_mapping())
        self.assertIsInstance(registry, OrchestratorRegistry)

    def test_executor_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(ExecutorDefinition.__module__, "astrid.core.executor.schema")
        self.assertEqual(ExecutorRegistry.__module__, "astrid.core.executor.registry")

        registry = load_executor_registry()

        self.assertIn("builtin.transcribe", registry.as_mapping())
        self.assertIn("external.vibecomfy.run", registry.as_mapping())
        self.assertIsInstance(registry, ExecutorRegistry)

    def test_legacy_public_packages_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("astrid.performers"))
        self.assertIsNone(importlib.util.find_spec("astrid.conductors"))
        self.assertIsNone(importlib.util.find_spec("astrid.executors"))
        self.assertIsNone(importlib.util.find_spec("astrid.orchestrators"))

    def test_element_framework_api_exports(self) -> None:
        self.assertEqual(legacy_elements.ElementRegistry.__module__, "astrid.core.element.registry")
        self.assertEqual(legacy_elements.ElementDefinition.__module__, "astrid.core.element.schema")

    def test_top_level_orchestrator_modules_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("astrid.event_talks"))
        self.assertIsNone(importlib.util.find_spec("astrid.thumbnail_maker"))
        self.assertIsNone(importlib.util.find_spec("astrid.understand"))


if __name__ == "__main__":
    unittest.main()
