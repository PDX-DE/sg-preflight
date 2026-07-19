"""Re-exports every symbol from `sg_preflight.cli._common` as this package's public surface,
so command-handler modules can `import sg_preflight.cli as common`."""

from __future__ import annotations

import sys
from types import ModuleType

from sg_preflight.cli import _common as _common


def _export_common_symbols() -> None:
    for name in dir(_common):
        if name.startswith("__"):
            continue
        globals()[name] = getattr(_common, name)


class _CliPackageModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        return getattr(_common, name)

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in {"_common", "__class__"}:
            return
        if hasattr(_common, name):
            setattr(_common, name, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        if hasattr(_common, name):
            delattr(_common, name)


_export_common_symbols()
__all__ = tuple(name for name in dir(_common) if not name.startswith("__"))
sys.modules[__name__].__class__ = _CliPackageModule
