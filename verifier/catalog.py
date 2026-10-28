"""The catalog-every-source task: workspace/catalog.json and the submitted total against the pinned truth."""

import json
from pathlib import Path

from .checks import (
    CATALOG,
    check,
    checked,
    duplicates,
    filter_problem,
    filter_terms,
    first_failure,
    listed,
    skipped,
)

# The score's multiplier when the submitted total is not the true count.
WRONG_TOTAL_FACTOR = 0.5


def read_catalog(workspace):
    """catalog.json's entries as (id, access method) pairs, and a problem or None. No file: no entries."""
    path = Path(workspace) / CATALOG
    if not path.is_file():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], f"{CATALOG} is not JSON"
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], f'{CATALOG} is not {{"entries": [...]}}'
    pairs = []
    for entry in entries:
        if not (
            isinstance(entry, dict)
            and set(entry) == {"id", "access_method"}
            and isinstance(entry["id"], str)
            and isinstance(entry["access_method"], str)
        ):
            return [], f"{CATALOG} holds an entry that is not {{id, access_method}}: {entry!r}"
        pairs.append((entry["id"], entry["access_method"]))
    return pairs, None


# The task's checks, in order: integrity first (any failing scores 0), then the outcome.
CONSTRAINTS = {
    "reference": "catalog_truth pinned the reference for this task",
    "reference-sound": "The reference lists each matching source once and its total counts them",
    "task-input": "The task's filter is valid",
    "catalog-file": f'{CATALOG} is absent or holds {{"entries": [...]}} of {{id, access_method}} entries',
    "no-repeats": "No source is recorded twice",
    "no-extra": "Every recorded id is a current source the filter matches",
    "none-missing": "Every current source the filter matches is recorded",
    "access-methods": "Each recorded matching source has its right access method",
    "total": "The submitted total is the number of current matching sources",
}
INTEGRITY = ("reference", "reference-sound", "task-input", "catalog-file")
# The most the score of an invalid catalog can reach.
MAX_PARTIAL = 0.99


def _check(id, ok, **fields):
    return check(id, CONSTRAINTS[id], ok, **fields)


def _sources(count):
    return f"{count} source" if count == 1 else f"{count} sources"


def outcome_checks(recorded, truth, total, true_total):
    """The outcome checks of a recorded catalog, and the F1 over it.

    ``recorded``: (id, access method) pairs in catalog.json, in order; ``truth``: {id: access method} of
    every matching source; ``total``: the submitted count; ``true_total``: the true count.
    """
    # A hit is a true id with its right access method; a wrong method is a false positive and a miss, never
    # half a hit, since the agent only has to copy it from the listing. Precision divides by every recorded
    # entry, repeats included.
    ids = [source for source, _method in recorded]
    repeated = duplicates(ids)
    methods = dict(recorded)
    extra = sorted(set(methods) - set(truth))
    missing = sorted(set(truth) - set(methods))
    wrong_access = sorted(source for source in set(methods) & set(truth) if methods[source] != truth[source])
    found = len(set(methods) & set(truth)) - len(wrong_access)
    if not truth and not ids:
        f1 = 1.0
    elif found == 0:
        f1 = 0.0
    else:
        precision, recall = found / len(ids), found / len(truth)
        f1 = 2 * precision * recall / (precision + recall)
    checks = [
        _check(
            "no-repeats",
            not repeated,
            actual=repeated or None,
            message=f"{_sources(len(repeated))} recorded more than once: {listed(repeated)}" if repeated else "",
        ),
        _check(
            "no-extra",
            not extra,
            actual=extra or None,
            message=f"{_sources(len(extra))} recorded that the filter drops or that are outdated: {listed(extra)}"
            if extra
            else "",
        ),
        _check(
            "none-missing",
            not missing,
            expected=missing or None,
            message=f"{_sources(len(missing))} that match are not recorded: {listed(missing)}" if missing else "",
        ),
        _check(
            "access-methods",
            not wrong_access,
            expected={source: truth[source] for source in wrong_access} or None,
            actual={source: methods[source] for source in wrong_access} or None,
            message="wrong access_method for "
            + listed(f"{source} ({methods[source]}, not {truth[source]})" for source in wrong_access)
            if wrong_access
            else "",
        ),
        _check(
            "total",
            total == true_total,
            expected=true_total,
            actual=total,
            message="" if total == true_total else f"the submitted total is {total}, but {_sources(true_total)} match",
        ),
    ]
    details = {
        "f1": round(f1, 4),
        "extra": extra,
        "missing": missing,
        "repeated": repeated,
        "wrong_access": wrong_access,
    }
    return checks, f1, details


def score_catalog(recorded, truth, total, true_total, integrity=()):
    """The verdict on a recorded catalog, after ``integrity`` checks that all hold.

    Valid only when the ids equal the truth exactly (no extra, missing or repeated id), every access method
    is right and the total is exact (docs/PLUGINS_PLAN.md §3). score = F1 over the catalog x the total
    factor (a wrong total halves it: the count is the task's answer, but the catalog work was real), at most
    MAX_PARTIAL when invalid, so it is 1.0 exactly when the catalog is valid.
    """
    outcomes, f1, details = outcome_checks(recorded, truth, total, true_total)
    total_factor = 1.0 if total == true_total else WRONG_TOTAL_FACTOR
    score = min(round(f1 * total_factor, 4), MAX_PARTIAL)
    return checked(
        [*integrity, *outcomes],
        f"all {true_total} matching sources are recorded",
        score,
        **details,
        total_factor=total_factor,
        total=total,
        true_total=true_total,
        expected=sorted(truth),
    )


def verify_task(arguments, output, reference, workspace):
    """``output``: a contract CatalogOutput; ``reference``: the pinned CatalogTruthOutput."""
    recorded, catalog_problem = read_catalog(workspace)
    problem = filter_problem(arguments.filter)
    if reference is None:
        sound = skipped("reference-sound", CONSTRAINTS["reference-sound"], "reference")
    else:
        truth_ids = [entry.id for entry in reference.sources]
        repeats = duplicates(truth_ids)
        sound = _check(
            "reference-sound",
            not repeats and reference.total == len(truth_ids),
            expected=len(truth_ids),
            actual=reference.total,
            message=""
            if not repeats and reference.total == len(truth_ids)
            else f"the reference's total is {reference.total} for {_sources(len(truth_ids))}"
            + (f", repeating {listed(repeats)}" if repeats else ""),
        )
    integrity = [
        _check("reference", reference is not None, message="" if reference else "catalog_truth was not pinned"),
        sound,
        _check("task-input", problem is None, actual=filter_terms(arguments.filter), message=problem or ""),
        _check("catalog-file", catalog_problem is None, message=catalog_problem or ""),
    ]
    failed = first_failure(integrity)
    if failed is not None:
        outcomes = [skipped(id, CONSTRAINTS[id], failed) for id in CONSTRAINTS if id not in INTEGRITY]
        return checked([*integrity, *outcomes], "", 0.0)
    truth = {entry.id: entry.access_method.value for entry in reference.sources}
    return score_catalog(recorded, truth, output.total, reference.total, integrity)
