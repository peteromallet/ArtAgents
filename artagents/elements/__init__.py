"""First-class render element discovery.

Elements are user-editable render building blocks such as effects, animations, and
transitions. Registry precedence is active theme, workspace overrides, managed
installs, then bundled defaults.
"""

from .registry import (
    ElementConflict,
    ElementRegistry,
    ElementRegistryError,
    ElementSource,
    load_default_registry,
)
from .install import (
    ElementInstallError,
    ElementInstallPlan,
    ElementInstallResult,
    build_element_install_plan,
    install_element,
)
from .schema import (
    ELEMENT_KINDS,
    REQUIRED_ELEMENT_FILES,
    ElementDefinition,
    ElementDependencies,
    ElementValidationError,
    load_element_definition,
    validate_element_definition,
)

__all__ = [
    "ELEMENT_KINDS",
    "REQUIRED_ELEMENT_FILES",
    "ElementConflict",
    "ElementDefinition",
    "ElementDependencies",
    "ElementInstallError",
    "ElementInstallPlan",
    "ElementInstallResult",
    "ElementRegistry",
    "ElementRegistryError",
    "ElementSource",
    "ElementValidationError",
    "load_default_registry",
    "load_element_definition",
    "build_element_install_plan",
    "install_element",
    "validate_element_definition",
]
