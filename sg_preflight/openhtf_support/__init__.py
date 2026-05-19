"""OpenHTF support for the SGFX station MVP.

The package keeps OpenHTF imports lazy so the regular CLI remains usable in
fresh checkouts where the station dependency has not been installed yet.
"""

from __future__ import annotations

__all__ = [
    "dependency",
    "outcomes",
    "phases",
    "plugs",
    "station",
]
