"""NiceGUI dashboard support for the SGFX operator surface.

The package keeps NiceGUI imports behind the dashboard command so the regular
CLI stays usable in fresh checkouts before the dashboard dependency is present.
"""

__all__ = ["dependency", "main"]
