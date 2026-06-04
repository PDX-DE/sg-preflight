from __future__ import annotations

from pathlib import Path
import sys

__path__ = [str(Path(__file__).with_suffix(""))]

from sg_preflight.cli import _common as _common

if __name__ == "sg_preflight.cli":
    _common.__path__ = __path__
    sys.modules[__name__] = _common
    parent = sys.modules.get("sg_preflight")
    if parent is not None:
        setattr(parent, "cli", _common)

if __name__ == "__main__":
    raise SystemExit(_common.main())
