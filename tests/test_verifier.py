from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import run_agent
from slimconfig import build_output, plain_output

import verifier
from contract import (
    CatalogInput,
    CatalogOutput,
    CatalogTruthOutput,
    ListSourcesInput,
    ListSourcesOutput,
    RecordSourceInput,
    RecordSourceOutput,
    WaitInput,
    WaitOutput,
)
from plugin import catalog_truth, list_sources, record_source, wait
from plugin.clock import MAX_WAIT
from plugin.engine import session_for
from plugin.listing import CURSOR_TTL, PAGE_SIZE
from plugin.recording import CATALOG
from verifier import checks
from verifier.catalog import CONSTRAINTS, INTEGRITY, MAX_PARTIAL, WRONG_TOTAL_FACTOR, score_catalog

TASK = "catalog-every-source"
EVERY = {"domains": [], "formats": [], "access_methods": [], "licenses": [], "updated_since": 0}
# 11 listed over 3 pages, 3 of them outdated: 8 current matches, the last on the last page, src-053
HEALTH = {**EVERY, "domains": ["health"]}
# The README's example: 21 listed over 5 pages, so the 4th call is rate-limited. 6 current matches, 3 of them
# after the rate limit; 3 outdated listings (src-006, src-024, src-038) also pass the filter.
EXAMPLE = {**EVERY, "domains": ["health", "energy"], "formats": ["csv", "parquet"], "updated_since": 2019}
NOTHING = {**EVERY, "updated_since": 2030}


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def task(wanted: dict) -> CatalogInput:
    return build_output({"filter": wanted}, CatalogInput)


def truth(given: CatalogInput, scratch: Path) -> CatalogTruthOutput:
    return build_output(plain_output(catalog_truth(given, scratch)), CatalogTruthOutput)


def total(count: int) -> CatalogOutput:
    return build_output({"total": count}, CatalogOutput)


def judge(workspace: Path, wanted: dict, output: CatalogOutput) -> dict:
    given = task(wanted)
    verdict = verifier.verify_task(TASK, given, output, truth(given, workspace / "scratch"), str(workspace))
    # The README's promises, checked on every verdict: score 1.0 exactly when valid; every check in order with
    # the same keys; valid exactly when all hold; a failing integrity check scores 0.
    assert (verdict["score"] == 1.0) is verdict["valid"]
    entries = verdict["details"]["checks"]
    assert [entry["id"] for entry in entries] == list(CONSTRAINTS)
    assert all(set(entry) == {"id", "constraint", "ok", "expected", "actual", "message"} for entry in entries)
    assert verdict["valid"] is all(entry["ok"] is True for entry in entries)
    if any(entry["ok"] is False for entry in entries if entry["id"] in INTEGRITY):
        assert verdict["score"] == 0.0
    return verdict


def write_catalog(workspace: Path, text: str) -> None:
    (workspace / CATALOG).write_text(text)


def test_the_verifier_mirrors_the_plugin_constants() -> None:
    assert (checks.PAGE_SIZE, checks.MAX_WAIT, checks.CATALOG, checks.CURSOR_TTL) == (
        PAGE_SIZE,
        MAX_WAIT,
        CATALOG,
        CURSOR_TTL,
    )


# Correct
def test_approves_a_complete_catalog(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, run_agent(tmp_path, task(HEALTH)))
    assert verdict["valid"] is True and verdict["score"] == 1.0
    assert verdict["details"]["true_total"] == 8


def test_approves_the_example_filtered_by_the_agent(tmp_path: Path) -> None:
    verdict = judge(tmp_path, EXAMPLE, run_agent(tmp_path, task(EXAMPLE)))
    assert verdict["valid"] is True and verdict["details"]["true_total"] == 6
    # task-input names each filter the task sets and what it means; the empty lists are left out.
    task_input = next(entry for entry in verdict["details"]["checks"] if entry["id"] == "task-input")
    assert task_input["actual"] == {
        "domains": {"value": ["health", "energy"], "means": "The source's domain is health or energy"},
        "formats": {"value": ["csv", "parquet"], "means": "The source is published as csv or parquet"},
        "updated_since": {"value": 2019, "means": "The source was last updated in 2019 or later"},
    }


def test_a_filter_that_keeps_every_source_names_no_filter(tmp_path: Path) -> None:
    verdict = judge(tmp_path, EVERY, run_agent(tmp_path, task(EVERY)))
    task_input = next(entry for entry in verdict["details"]["checks"] if entry["id"] == "task-input")
    assert task_input["actual"] is None


def test_approves_the_whole_catalog_through_several_rate_limits(tmp_path: Path) -> None:
    verdict = judge(tmp_path, EVERY, run_agent(tmp_path, task(EVERY)))
    assert verdict["valid"] is True and verdict["details"]["true_total"] == 48


# Wrong: the traps the task sets
def test_trusting_the_listing_records_what_the_filter_drops(tmp_path: Path) -> None:
    # The API filters by domain only; an agent that records every listed source records all 21.
    verdict = judge(tmp_path, EXAMPLE, run_agent(tmp_path, task(EXAMPLE), trust_the_listing=True))
    assert verdict["valid"] is False and len(verdict["details"]["extra"]) == 15
    # The message names the first failing check and counts the rest.
    assert verdict["message"].startswith("no-extra: 15 sources recorded that the filter drops or that are outdated")
    assert verdict["message"].endswith(" and 10 more (+1 more)")
    assert verdict["details"]["total"] == 21 and verdict["score"] < WRONG_TOTAL_FACTOR


def test_outdated_listings_that_pass_the_filter_are_extras(tmp_path: Path) -> None:
    verdict = judge(tmp_path, EXAMPLE, run_agent(tmp_path, task(EXAMPLE), keep_outdated=True))
    assert verdict["valid"] is False and verdict["details"]["extra"] == ["src-006", "src-024", "src-038"]
    assert verdict["details"]["missing"] == []


# Wrong
def test_refuses_an_extra_id(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    record_source(build_output({"entry": {"id": "src-001", "access_method": "rest"}}, RecordSourceInput), tmp_path)
    verdict = judge(tmp_path, HEALTH, total(9))
    assert verdict["valid"] is False and verdict["details"]["extra"] == ["src-001"]
    assert 0 < verdict["score"] < 1
    assert judge(tmp_path, HEALTH, output)["valid"] is False


def test_refuses_a_missing_id(tmp_path: Path) -> None:
    write_catalog(tmp_path, json.dumps({"entries": [{"id": "src-006", "access_method": "sql"}]}))
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and "src-048" in verdict["details"]["missing"]


def test_refuses_a_wrong_access_method(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    entries = json.loads((tmp_path / CATALOG).read_text())["entries"]
    entries[0]["access_method"] = "file" if entries[0]["access_method"] != "file" else "rest"
    write_catalog(tmp_path, json.dumps({"entries": entries}))
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and verdict["details"]["wrong_access"] == [entries[0]["id"]]
    assert verdict["score"] < 1


def test_refuses_a_wrong_total_even_with_a_complete_catalog(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    verdict = judge(tmp_path, HEALTH, total(7))
    assert verdict["message"] == "total: the submitted total is 7, but 8 sources match"
    total_check = verdict["details"]["checks"][-1]
    assert (total_check["ok"], total_check["expected"], total_check["actual"]) == (False, 8, 7)
    assert verdict["score"] == WRONG_TOTAL_FACTOR and verdict["details"]["f1"] == 1.0


def test_refuses_a_repeated_id(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    entries = json.loads((tmp_path / CATALOG).read_text())["entries"]
    write_catalog(tmp_path, json.dumps({"entries": [*entries, entries[0]]}))
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and verdict["details"]["repeated"] == [entries[0]["id"]]


# Missing
def test_refuses_a_missing_catalog_file(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and len(verdict["details"]["missing"]) == 8 and verdict["score"] == 0.0


def test_refuses_a_task_without_a_reference(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    verdict = verifier.verify_task(TASK, task(HEALTH), total(8), None, str(tmp_path))
    assert (verdict["valid"], verdict["score"]) == (False, 0.0)
    assert verdict["message"] == "reference: catalog_truth was not pinned"
    # Every check that needs the reference waits on it, not checked.
    waiting = [entry for entry in verdict["details"]["checks"] if entry["ok"] is None]
    assert [entry["id"] for entry in waiting] == [
        "reference-sound",
        "no-repeats",
        "no-extra",
        "none-missing",
        "access-methods",
        "total",
    ]
    assert {entry["message"] for entry in waiting} == {"Not checked: reference did not hold."}


# Malformed
@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"entries": {}}',
        '{"entries": [{"id": "src-006"}]}',
        '{"entries": [{"id": 6, "access_method": "sql"}]}',
        '{"entries": [{"id": "src-006", "access_method": "sql", "note": "x"}]}',
    ],
)
def test_refuses_a_malformed_catalog_file(tmp_path: Path, text: str) -> None:
    write_catalog(tmp_path, text)
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["message"].startswith(f"catalog-file: {CATALOG} ")


# Boundary
def test_an_empty_match_needs_no_catalog_and_a_zero_total(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(NOTHING))
    assert output.total == 0 and not (tmp_path / CATALOG).exists()
    assert judge(tmp_path, NOTHING, output)["valid"] is True
    write_catalog(tmp_path, '{"entries": []}')
    assert judge(tmp_path, NOTHING, output)["valid"] is True
    assert judge(tmp_path, NOTHING, total(1))["valid"] is False


def test_stopping_before_the_last_page_misses_its_last_match(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, run_agent(tmp_path, task(HEALTH), pages=2))
    assert verdict["valid"] is False and verdict["details"]["missing"] == ["src-053"]


def test_a_rate_limit_before_the_last_matches_must_be_waited_out(tmp_path: Path) -> None:
    done = tmp_path / "done"
    done.mkdir()
    verdict = judge(done, EXAMPLE, run_agent(done, task(EXAMPLE)))
    assert verdict["valid"] is True and session_for(done).limiter.now > 0
    quit_early = tmp_path / "quit"
    quit_early.mkdir()
    verdict = judge(quit_early, EXAMPLE, run_agent(quit_early, task(EXAMPLE), give_up_on_rate_limit=True))
    assert verdict["valid"] is False
    assert verdict["details"]["missing"] == ["src-048", "src-049", "src-051", "src-052"]


def test_waiting_far_longer_than_told_expires_the_cursor(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expired"):
        run_agent(tmp_path, task(EXAMPLE), overwait=CURSOR_TTL)
    # What the agent recorded before its cursor expired is a partial catalog.
    assert judge(tmp_path, EXAMPLE, total(2))["details"]["missing"] == ["src-048", "src-049", "src-051", "src-052"]


# The scoring policy (verifier/catalog.py): strict validity, score = F1 over the catalog x the total factor.
def test_a_partial_catalog_is_invalid_with_a_graded_score(tmp_path: Path) -> None:
    # 9 of 12 pages: the 37 current sources among src-001..src-045 recorded, of 48, and the agent submits 37.
    verdict = judge(tmp_path, EVERY, run_agent(tmp_path, task(EVERY), pages=9))
    assert verdict["valid"] is False and verdict["details"]["f1"] == round(74 / 85, 4)
    assert verdict["score"] == round(74 / 85 * WRONG_TOTAL_FACTOR, 4)


TRUTH = {"a": "rest", "b": "file", "c": "sql", "d": "hub"}
EXACT = list(TRUTH.items())
BIG = [(f"s{i}", "rest") for i in range(200)]


@pytest.mark.parametrize(
    ("recorded", "truth_", "submitted", "valid", "score"),
    [
        pytest.param(EXACT, TRUTH, 4, True, 1.0, id="exact"),
        pytest.param(EXACT, TRUTH, 3, False, 0.5, id="exact catalog, wrong total"),
        pytest.param(EXACT[:3], TRUTH, 4, False, 0.8571, id="one missing, total still right"),
        pytest.param(EXACT[:3], TRUTH, 3, False, 0.4286, id="one missing, total counts the catalog"),
        pytest.param([*EXACT, ("e", "rest")], TRUTH, 4, False, 0.8889, id="one extra"),
        pytest.param([*EXACT, EXACT[0]], TRUTH, 4, False, 0.8889, id="one repeated"),
        pytest.param([("a", "file"), *EXACT[1:]], TRUTH, 4, False, 0.75, id="one wrong access method"),
        pytest.param([(i, "sql") for i in "abd"], {i: "rest" for i in "abd"}, 3, False, 0.0, id="no hit"),
        pytest.param([], TRUTH, 0, False, 0.0, id="nothing recorded"),
        pytest.param([], {}, 0, True, 1.0, id="empty match, empty catalog"),
        pytest.param([], {}, 1, False, 0.5, id="empty match, wrong total"),
        pytest.param([("a", "rest")], {}, 1, False, 0.0, id="empty match, something recorded"),
        pytest.param(BIG[1:], dict(BIG), 200, False, MAX_PARTIAL, id="one of 200 missing: capped"),
    ],
)
def test_the_score_follows_the_policy(recorded, truth_, submitted, valid, score) -> None:
    verdict = score_catalog(recorded, truth_, submitted, len(truth_))
    assert (verdict["valid"], verdict["score"]) == (valid, score)
    # The score is 1.0 exactly when the catalog is valid, and always within [0, 1].
    assert (verdict["score"] == 1.0) is verdict["valid"] and 0.0 <= verdict["score"] <= 1.0


def test_a_wrong_access_method_scores_below_a_missing_source() -> None:
    wrong = score_catalog([("a", "file"), *EXACT[1:]], TRUTH, 4, 4)["score"]
    missing = score_catalog(EXACT[1:], TRUTH, 4, 4)["score"]
    assert wrong < missing < 1.0


def test_recording_every_source_cannot_beat_an_exact_catalog() -> None:
    everything = [*EXACT, *((f"x{i}", "rest") for i in range(20))]
    assert score_catalog(everything, TRUTH, 4, 4)["score"] < 0.5


# Tools
def test_list_sources_checks(tmp_path: Path) -> None:
    given = build_output({"domains": ["health"], "cursor": None}, ListSourcesInput)
    made = build_output(plain_output(list_sources(given, tmp_path)), ListSourcesOutput)
    assert verifier.verify_input("list_sources", given)["valid"] is True
    verdict = verifier.verify_output("list_sources", given, made, str(tmp_path))
    assert verdict["valid"] is True and verdict["details"]["superseded"] == ["src-006", "src-012", "src-024"]
    bad_cursor = build_output({"domains": ["health"], "cursor": "page-2"}, ListSourcesInput)
    assert verifier.verify_input("list_sources", bad_cursor)["valid"] is False
    stray = build_output({"domains": ["energy"], "cursor": None}, ListSourcesInput)
    assert verifier.verify_output("list_sources", stray, made, str(tmp_path))["valid"] is False
    last_page = build_output({"domains": ["health"], "cursor": "cursor-5"}, ListSourcesInput)
    assert verifier.verify_output("list_sources", last_page, made, str(tmp_path))["valid"] is False
    renamed = plain_output(made)
    renamed["sources"][0]["superseded_by"] = "the new one"
    renamed_page = build_output(renamed, ListSourcesOutput)
    assert verifier.verify_output("list_sources", given, renamed_page, str(tmp_path))["valid"] is False


def test_wait_checks(tmp_path: Path) -> None:
    given = build_output({"seconds": 30}, WaitInput)
    made = build_output(plain_output(wait(given, tmp_path)), WaitOutput)
    assert verifier.verify_input("wait", given)["valid"] is True
    assert verifier.verify_output("wait", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("wait", build_output({"seconds": MAX_WAIT + 1}, WaitInput))["valid"] is False


def test_record_source_checks(tmp_path: Path) -> None:
    given = build_output({"entry": {"id": "src-006", "access_method": "sql"}}, RecordSourceInput)
    made = build_output(plain_output(record_source(given, tmp_path)), RecordSourceOutput)
    assert verifier.verify_input("record_source", given)["valid"] is True
    assert verifier.verify_output("record_source", given, made, str(tmp_path))["valid"] is True
    bad_id = build_output({"entry": {"id": "health-6", "access_method": "sql"}}, RecordSourceInput)
    assert verifier.verify_input("record_source", bad_id)["valid"] is False
    write_catalog(tmp_path, '{"entries": [{"id": "src-006", "access_method": "rest"}]}')
    assert verifier.verify_output("record_source", given, made, str(tmp_path))["valid"] is False


def test_catalog_truth_checks(tmp_path: Path) -> None:
    given = task(HEALTH)
    made = truth(given, tmp_path)
    assert verifier.verify_input("catalog_truth", given)["valid"] is True
    assert verifier.verify_output("catalog_truth", given, made, str(tmp_path))["valid"] is True
    miscounted = build_output({**plain_output(made), "total": 9}, CatalogTruthOutput)
    assert verifier.verify_output("catalog_truth", given, miscounted, str(tmp_path))["valid"] is False
    # The task refuses to judge against a reference that miscounts itself.
    verdict = verifier.verify_task(TASK, given, total(9), miscounted, str(tmp_path))
    assert verdict["message"] == "reference-sound: the reference's total is 9 for 8 sources" and verdict["score"] == 0.0
    assert verifier.verify_input("catalog_truth", task({**EVERY, "updated_since": -1}))["valid"] is False
