from __future__ import annotations

from pathlib import Path

from contract import CatalogEntry, CatalogInput, CatalogTruthOutput
from plugin.sources import matching


def catalog_truth(given: CatalogInput, workspace: Path) -> CatalogTruthOutput:
    """The reference tool: every current source the filter matches, with its access method. The agent never sees
    it."""
    sources = [CatalogEntry(id=source.id, access_method=source.access_method) for source in matching(given.filter)]
    return CatalogTruthOutput(sources=sources, total=len(sources))
