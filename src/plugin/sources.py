"""The bundled mock catalog (fixtures/catalog.json) and how a filter picks its sources.

The catalog lists outdated sources next to the current versions that supersede them. The API filters by domain
only; the rest of a task's filter, and dropping outdated listings, is the agent's job.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from slimconfig import build_output

from contract import Domain, Source, SourceFilter

FIXTURE = Path(__file__).with_name("fixtures") / "catalog.json"


@cache
def catalog() -> tuple[Source, ...]:
    """Every source in the mock catalog, in catalog (id) order."""
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["sources"]
    return tuple(build_output(row, Source) for row in rows)


def matches(source: Source, wanted: SourceFilter) -> bool:
    return (
        (not wanted.domains or source.domain in wanted.domains)
        and (not wanted.formats or source.format in wanted.formats)
        and (not wanted.access_methods or source.access_method in wanted.access_methods)
        and (not wanted.licenses or source.license in wanted.licenses)
        and source.updated >= wanted.updated_since
    )


def matching(wanted: SourceFilter) -> list[Source]:
    """Every current source the filter matches: the task's answer."""
    return [source for source in catalog() if source.superseded_by is None and matches(source, wanted)]


def in_domains(domains: list[Domain]) -> list[Source]:
    """What the API lists for these domains (empty: every domain), outdated listings included."""
    return [source for source in catalog() if not domains or source.domain in domains]


def known_ids() -> frozenset[str]:
    return frozenset(source.id for source in catalog())
