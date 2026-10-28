"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    LIST_SOURCES = "list_sources"
    WAIT = "wait"
    RECORD_SOURCE = "record_source"
    CATALOG_TRUTH = "catalog_truth"


class Task(Enum):
    CATALOG_EVERY_SOURCE = "catalog-every-source"


class AccessMethod(Enum):
    """How a source is read; mirrors Empiric's AccessKind (src/empiric/contracts/sources.py)."""

    REST = "rest"
    FILE = "file"
    HUB = "hub"
    SQL = "sql"


class Domain(Enum):
    CLIMATE = "climate"
    HEALTH = "health"
    FINANCE = "finance"
    TRANSPORT = "transport"
    EDUCATION = "education"
    ENERGY = "energy"


class Format(Enum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"
    XML = "xml"


class License(Enum):
    CC_BY = "cc-by"
    CC0 = "cc0"
    ODBL = "odbl"
    PROPRIETARY = "proprietary"


SOURCE_ID = "The source's catalog id, e.g. src-007"
ACCESS_METHOD = "How the source is read: rest, file, hub or sql"
CURSOR = "Where the page starts: null for the first page, else the next_cursor the previous page returned"


@dataclass
class SourceFilter(Output):
    domains: Annotated[list[Domain], "Keep sources in one of these domains; empty keeps every domain"]
    formats: Annotated[list[Format], "Keep sources in one of these formats; empty keeps every format"]
    access_methods: Annotated[list[AccessMethod], "Keep sources read one of these ways; empty keeps every way"]
    licenses: Annotated[list[License], "Keep sources under one of these licenses; empty keeps every license"]
    updated_since: Annotated[int, "Keep sources last updated in this year or later; 0 keeps every year"]


@dataclass
class Source(Output):
    id: Annotated[str, SOURCE_ID]
    name: Annotated[str, "The source's name"]
    domain: Annotated[Domain, "The source's subject area"]
    format: Annotated[Format, "The format its records come in"]
    access_method: Annotated[AccessMethod, ACCESS_METHOD]
    license: Annotated[License, "The license it is published under"]
    updated: Annotated[int, "The year it was last updated"]
    superseded_by: Annotated[
        str | None, "The id of the listing that replaces this outdated one; null when this listing is current"
    ]


@dataclass
class CatalogEntry(Output):
    id: Annotated[str, SOURCE_ID]
    access_method: Annotated[AccessMethod, ACCESS_METHOD]


@dataclass
class CatalogInput(Output):
    filter: Annotated[SourceFilter, "Which sources of the catalog to record"]


@dataclass
class CatalogOutput(Output):
    total: Annotated[int, "How many current sources match the filter: the number recorded in catalog.json"]


@dataclass
class ListSourcesInput(Output):
    domains: Annotated[
        list[Domain], "List only sources in one of these domains; empty lists every domain. Pass the same for every page"
    ]
    cursor: Annotated[str | None, CURSOR]


@dataclass
class ListSourcesOutput(Output):
    sources: Annotated[
        list[Source], "This page's sources in those domains, in catalog order, outdated listings included"
    ]
    next_cursor: Annotated[str | None, "The cursor of the next page; null when this page is the last"]


@dataclass
class WaitInput(Output):
    seconds: Annotated[int, "How many seconds to wait, 0 to 3600: the retry_after a rate-limited call named"]


@dataclass
class WaitOutput(Output):
    now: Annotated[int, "The catalog's clock after waiting, in seconds since the run began"]


@dataclass
class RecordSourceInput(Output):
    entry: Annotated[CatalogEntry, "The source to add to catalog.json, as list_sources listed it"]


@dataclass
class RecordSourceOutput(Output):
    recorded: Annotated[CatalogEntry, "The entry added to catalog.json"]
    count: Annotated[int, "How many entries catalog.json holds now"]
    path: Annotated[str, "The catalog file, relative to the plugin workspace: catalog.json"]


@dataclass
class CatalogTruthOutput(Output):
    sources: Annotated[list[CatalogEntry], "Every current source that matches the filter, in catalog order"]
    total: Annotated[int, "How many current sources match the filter"]


TOOLS = {
    Tool.LIST_SOURCES: (ListSourcesInput, ListSourcesOutput),
    Tool.WAIT: (WaitInput, WaitOutput),
    Tool.RECORD_SOURCE: (RecordSourceInput, RecordSourceOutput),
    Tool.CATALOG_TRUTH: (CatalogInput, CatalogTruthOutput),
}
TASKS = {Task.CATALOG_EVERY_SOURCE: (CatalogInput, CatalogOutput)}
