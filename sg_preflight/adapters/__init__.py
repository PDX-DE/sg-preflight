"""Adapters that discover SG/BMW source data and materialize it into normalized preflight bundles."""

from sg_preflight.adapters.discovery import default_search_roots, probe_workspace
from sg_preflight.adapters.materialize import MaterializeResult, materialize_bundle

__all__ = [
    "MaterializeResult",
    "default_search_roots",
    "materialize_bundle",
    "probe_workspace",
]
