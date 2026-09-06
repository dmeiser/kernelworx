import importlib
import sys


def _reload_module_with_no_utils(module_name: str):
    # Save any top-level 'utils' modules
    saved = {}
    for name in list(sys.modules.keys()):
        if name == "utils" or name.startswith("utils."):
            saved[name] = sys.modules.pop(name)

    try:
        module = importlib.reload(importlib.import_module(module_name))
    finally:
        # Restore saved modules
        for name, mod in saved.items():
            sys.modules[name] = mod
        # Reload again to restore original behavior
        importlib.reload(importlib.import_module(module_name))

    return module


def test_reload_campaign_operations_import_fallback():
    module = _reload_module_with_no_utils("src.handlers.campaign_operations")
    # basic sanity: functions exist (tables accessor imported)
    assert hasattr(module, "tables")


def test_reload_campaign_reporting_import_fallback():
    module = _reload_module_with_no_utils("src.handlers.campaign_reporting")
    assert hasattr(module, "_build_unit_campaign_key")
