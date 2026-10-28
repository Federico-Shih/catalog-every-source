from __future__ import annotations

import json
from pathlib import Path

import pytest
from slimconfig import build_output

from contract import (
    AccessMethod,
    CatalogEntry,
    CatalogInput,
    ListSourcesInput,
    RecordSourceInput,
    Tool,
    WaitInput,
)
from plugin import catalog_truth, list_sources, record_source, wait
from plugin.__main__ import IMPLEMENTATIONS
from plugin.engine import RateLimited
from plugin.listing import CURSOR_TTL, PAGE_SIZE, RATE_LIMIT, RATE_WINDOW
from plugin.sources import catalog

EVERY = {"domains": [], "formats": [], "access_methods": [], "licenses": [], "updated_since": 0}


def task(**wanted) -> CatalogInput:
    return build_output({"filter": {**EVERY, **wanted}}, CatalogInput)


def listing(cursor: str | None = None, domains: list[str] | None = None) -> ListSourcesInput:
    return build_output({"domains": domains or [], "cursor": cursor}, ListSourcesInput)


def record(source_id: str, method: str = "rest") -> RecordSourceInput:
    return build_output({"entry": {"id": source_id, "access_method": method}}, RecordSourceInput)


def test_every_tool_is_implemented() -> None:
    assert set(IMPLEMENTATIONS) == set(Tool)


def test_the_fixture_holds_56_unique_sources_8_of_them_outdated() -> None:
    ids = [source.id for source in catalog()]
    assert len(ids) == 56 and ids == sorted(set(ids)) and ids[0] == "src-001"
    assert {source.access_method for source in catalog()} == set(AccessMethod)
    by_id = {source.id: source for source in catalog()}
    outdated = [source for source in catalog() if source.superseded_by is not None]
    assert len(outdated) == 8
    for source in outdated:
        # Each outdated listing names a current one of the same name and domain, listed after it.
        current = by_id[source.superseded_by]
        assert current.superseded_by is None and source.id < current.id
        assert (current.name, current.domain) == (source.name, source.domain)


def test_list_sources_pages_through_its_domains_outdated_listings_included(tmp_path: Path) -> None:
    pages = [list_sources(listing(domains=["health"]), tmp_path)]
    while pages[-1].next_cursor is not None:
        pages.append(list_sources(listing(pages[-1].next_cursor, domains=["health"]), tmp_path))
    listed = [source for page in pages for source in page.sources]
    assert len(pages[0].sources) == PAGE_SIZE and pages[0].next_cursor == "cursor-5"
    assert len(listed) == 11 and listed[-1].id == "src-053"
    assert all(source.domain.value == "health" for source in listed)
    # The API does not drop outdated listings: that is the agent's job.
    assert [source.id for source in listed if source.superseded_by] == ["src-006", "src-012", "src-024"]


def test_list_sources_refuses_a_cursor_no_page_of_its_domains_returned(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown cursor"):
        list_sources(listing("page-2"), tmp_path)
    # A well-formed cursor it never issued, and one issued for other domains, are just as unknown.
    with pytest.raises(ValueError, match="unknown cursor"):
        list_sources(listing("cursor-5"), tmp_path)
    issued = list_sources(listing(domains=["health"]), tmp_path).next_cursor
    with pytest.raises(ValueError, match="unknown cursor"):
        list_sources(listing(issued, domains=["energy"]), tmp_path)


def test_a_cursor_survives_a_rate_limit_wait_but_not_a_longer_one(tmp_path: Path) -> None:
    cursor = list_sources(listing(), tmp_path).next_cursor
    wait(WaitInput(seconds=RATE_WINDOW), tmp_path)
    kept = list_sources(listing(cursor), tmp_path)
    wait(WaitInput(seconds=CURSOR_TTL + 1), tmp_path)
    with pytest.raises(ValueError, match="expired"):
        list_sources(listing(kept.next_cursor), tmp_path)
    assert list_sources(listing(), tmp_path).next_cursor == "cursor-5"


def test_list_sources_is_rate_limited_until_the_agent_waits(tmp_path: Path) -> None:
    for _ in range(RATE_LIMIT):
        list_sources(listing(), tmp_path)
    with pytest.raises(RateLimited) as limited:
        list_sources(listing(), tmp_path)
    assert limited.value.retry_after == RATE_WINDOW
    assert wait(WaitInput(seconds=limited.value.retry_after), tmp_path).now == RATE_WINDOW
    list_sources(listing(), tmp_path)


def test_wait_refuses_negative_or_huge_waits(tmp_path: Path) -> None:
    for seconds in (-1, 3601):
        with pytest.raises(ValueError, match="seconds"):
            wait(WaitInput(seconds=seconds), tmp_path)


def test_record_source_appends_to_the_catalog_file(tmp_path: Path) -> None:
    output = record_source(record("src-001"), tmp_path)
    assert output.recorded == CatalogEntry(id="src-001", access_method=AccessMethod.REST)
    assert (output.count, output.path) == (1, "catalog.json")
    record_source(record("src-002", "hub"), tmp_path)
    assert json.loads((tmp_path / "catalog.json").read_text()) == {
        "entries": [{"id": "src-001", "access_method": "rest"}, {"id": "src-002", "access_method": "hub"}]
    }


def test_record_source_refuses_unknown_and_repeated_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown source id"):
        record_source(record("src-999"), tmp_path)
    record_source(record("src-001"), tmp_path)
    with pytest.raises(ValueError, match="already"):
        record_source(record("src-001", "sql"), tmp_path)


def test_catalog_truth_lists_every_current_match_without_rate_limit(tmp_path: Path) -> None:
    for _ in range(RATE_LIMIT + 2):
        truth = catalog_truth(task(), tmp_path)
    assert truth.total == len(truth.sources) == 48
    health = catalog_truth(task(domains=["health"]), tmp_path)
    assert health.total == 8 and health.sources[-1].id == "src-053"
    assert catalog_truth(task(updated_since=2030), tmp_path).total == 0


def test_the_example_task_has_six_current_matches(tmp_path: Path) -> None:
    # The README's example run: two domains, two formats, updated in 2019 or later.
    truth = catalog_truth(task(domains=["health", "energy"], formats=["csv", "parquet"], updated_since=2019), tmp_path)
    # src-048 is updated exactly in 2019; src-051 matches only as the newer version of src-008; src-006, src-024
    # and src-038 match but are outdated, and src-024's replacement src-050 is json.
    assert [(entry.id, entry.access_method.value) for entry in truth.sources] == [
        ("src-014", "sql"),
        ("src-030", "rest"),
        ("src-048", "rest"),
        ("src-049", "sql"),
        ("src-051", "sql"),
        ("src-052", "sql"),
    ]
