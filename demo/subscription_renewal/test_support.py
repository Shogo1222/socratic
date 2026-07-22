import importlib
import os
from types import ModuleType


DEFAULT_IMPLEMENTATION = "demo.subscription_renewal.subscription"


def load_implementation() -> ModuleType:
    module_name = os.environ.get("DEMO_IMPL", DEFAULT_IMPLEMENTATION)
    return importlib.import_module(module_name)
