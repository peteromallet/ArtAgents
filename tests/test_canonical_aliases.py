import importlib.util
import unittest

import artagents.executors as executors
import artagents.orchestrators as orchestrators
from artagents.executors import ExecutorDefinition, ExecutorRegistry, load_default_registry as load_executor_registry
from artagents.orchestrators import OrchestratorDefinition, OrchestratorRegistry, load_default_registry as load_orchestrator_registry


class CanonicalAliasTest(unittest.TestCase):
    def test_orchestrator_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(OrchestratorDefinition.__module__, "artagents.orchestrators.schema")
        self.assertEqual(OrchestratorRegistry.__module__, "artagents.orchestrators.registry")
        self.assertFalse(hasattr(orchestrators, "ConductorDefinition"))
        self.assertFalse(hasattr(orchestrators, "PerformerRegistry"))

        registry = load_orchestrator_registry()

        self.assertIn("builtin.hype", registry.as_mapping())
        self.assertIsInstance(registry, OrchestratorRegistry)

    def test_executor_api_uses_canonical_implementation(self) -> None:
        self.assertEqual(ExecutorDefinition.__module__, "artagents.executors.schema")
        self.assertEqual(ExecutorRegistry.__module__, "artagents.executors.registry")
        self.assertFalse(hasattr(executors, "InstrumentDefinition"))
        self.assertFalse(hasattr(executors, "PerformerDefinition"))

        registry = load_executor_registry()

        self.assertIn("builtin.transcribe", registry.as_mapping())
        self.assertIn("external.vibecomfy.run", registry.as_mapping())
        self.assertIsInstance(registry, ExecutorRegistry)

    def test_legacy_public_packages_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("artagents.performers"))
        self.assertIsNone(importlib.util.find_spec("artagents.conductors"))

    def test_top_level_orchestrator_modules_are_absent(self) -> None:
        self.assertIsNone(importlib.util.find_spec("artagents.event_talks"))
        self.assertIsNone(importlib.util.find_spec("artagents.thumbnail_maker"))
        self.assertIsNone(importlib.util.find_spec("artagents.understand"))


if __name__ == "__main__":
    unittest.main()
