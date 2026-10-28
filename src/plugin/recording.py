from __future__ import annotations

import json
from pathlib import Path

from contract import CatalogEntry, RecordSourceInput, RecordSourceOutput
from plugin.sources import known_ids

# The catalog the agent builds, relative to the workspace: {"entries": [{"id": ..., "access_method": ...}]}.
CATALOG = "catalog.json"


def read_entries(workspace: Path) -> list[dict[str, str]]:
    path = workspace / CATALOG
    return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.is_file() else []


def record_source(given: RecordSourceInput, workspace: Path) -> RecordSourceOutput:
    """Append one entry to catalog.json; an unknown or already recorded id raises."""
    entry: CatalogEntry = given.entry
    if entry.id not in known_ids():
        raise ValueError(f"unknown source id: {entry.id!r}; record ids exactly as list_sources lists them")
    entries = read_entries(workspace)
    if any(recorded["id"] == entry.id for recorded in entries):
        raise ValueError(f"source {entry.id!r} is already in {CATALOG}; record each source once")
    entries.append({"id": entry.id, "access_method": entry.access_method.value})
    (workspace / CATALOG).write_text(json.dumps({"entries": entries}, indent=2) + "\n", encoding="utf-8")
    return RecordSourceOutput(recorded=entry, count=len(entries), path=CATALOG)
