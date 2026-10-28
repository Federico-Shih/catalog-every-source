from __future__ import annotations

import json
from pathlib import Path

import pytest

import verifier.ledger
from plugin.engine import LEDGER, RateLimited, RateLimiter, Session, page

ITEMS = list(range(7))


def test_the_limiter_refuses_the_call_past_the_limit_until_the_window_turns() -> None:
    limiter = RateLimiter(limit=2, window=10)
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(RateLimited) as refused:
        limiter.acquire()
    assert refused.value.retry_after == 10
    limiter.wait(4)
    with pytest.raises(RateLimited) as refused:
        limiter.acquire()
    assert refused.value.retry_after == 6
    limiter.wait(6)
    limiter.acquire()


def test_waiting_inside_the_window_restores_nothing_and_negative_waits_fail() -> None:
    limiter = RateLimiter(limit=1, window=10)
    limiter.acquire()
    limiter.wait(9)
    with pytest.raises(RateLimited):
        limiter.acquire()
    with pytest.raises(ValueError):
        limiter.wait(-1)
    with pytest.raises(ValueError):
        RateLimiter(limit=0, window=10)


def test_paging_returns_every_item_once_and_ends_with_no_cursor() -> None:
    seen, cursor = [], None
    while True:
        items, cursor = page(ITEMS, cursor, 3)
        seen += items
        if cursor is None:
            break
    assert seen == ITEMS
    # An exact multiple of the page size still ends on the last full page, never on an empty one.
    assert page(list(range(6)), "cursor-3", 3) == ([3, 4, 5], None)
    assert page([], None, 3) == ([], None)


@pytest.mark.parametrize("cursor", ["cursor-7", "cursor-x", "3", "cursor--1"])
def test_paging_refuses_a_cursor_it_never_issued(cursor: str) -> None:
    with pytest.raises(ValueError, match="unknown cursor"):
        page(ITEMS, cursor, 3)


def test_the_ledger_records_every_call_in_order_and_survives_a_restart(tmp_path: Path) -> None:
    session = Session(tmp_path)
    assert session.begin() == "call-0001"
    session.finish("list_sources", {"cursor": None}, response={"items": [1]})
    assert session.begin() == "call-0002"
    session.finish("list_sources", {"cursor": "x"}, error="ValueError: unknown cursor")

    restarted = Session(tmp_path)
    assert restarted.begin() == "call-0003"
    lines = [json.loads(line) for line in (tmp_path / LEDGER).read_text().splitlines()]
    assert [line["call_id"] for line in lines] == ["call-0001", "call-0002"]
    assert lines[0]["response"] == {"items": [1]} and "error" not in lines[0]
    assert lines[1]["error"].startswith("ValueError") and "response" not in lines[1]


def test_the_verifier_reads_the_ledger_the_engine_writes(tmp_path: Path) -> None:
    assert verifier.ledger.read_calls(tmp_path) == []
    session = Session(tmp_path)
    session.begin()
    session.finish("wait", {"seconds": 5}, response={"now": 5})
    assert verifier.ledger.calls_by_id(tmp_path)["call-0001"]["response"] == {"now": 5}
    (tmp_path / LEDGER).write_text("not json\n")
    with pytest.raises(ValueError, match="line 1"):
        verifier.ledger.read_calls(tmp_path)
