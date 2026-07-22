import importlib
import os
from types import ModuleType


DEFAULT_IMPLEMENTATION = "demo.refactor_guard.base"


def load_implementation() -> ModuleType:
    module_name = os.environ.get("DEMO_IMPL", DEFAULT_IMPLEMENTATION)
    return importlib.import_module(module_name)
