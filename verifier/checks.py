"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import re

# These mirror src/plugin (the verifier may import only the standard library and the contract);
# tests/test_verifier.py holds them equal.
PAGE_SIZE = 5
MAX_WAIT = 3600
CURSOR_TTL = 120
CATALOG = "catalog.json"
CURSOR = re.compile(r"cursor-(\d+)")
SOURCE_ID = re.compile(r"src-\d{3}")


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def check(id, constraint, ok, *, expected=None, actual=None, message=""):
    """One entry of a task verdict's ``details.checks``: ok is True (holds), False (fails) or None (not checked)."""
    return {"id": id, "constraint": constraint, "ok": ok, "expected": expected, "actual": actual, "message": message}


def skipped(id, constraint, waiting_on):
    return check(id, constraint, None, message=f"Not checked: {waiting_on} did not hold.")


def first_failure(checks):
    """The id of the first check that fails, or None."""
    return next((entry["id"] for entry in checks if entry["ok"] is False), None)


def checked(checks, valid_message, score, **details):
    """A task verdict over ``checks``: valid when every one holds; the message names the first that fails."""
    failing = [entry for entry in checks if entry["ok"] is not True]
    failed = [entry for entry in checks if entry["ok"] is False]
    if not failing:
        return result(True, valid_message, score=1.0, checks=checks, **details)
    first = failed[0] if failed else failing[0]
    more = f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""
    return result(False, f"{first['id']}: {first['message']}{more}", score=score, checks=checks, **details)


def listed(items, limit=5):
    """``items`` as "a, b, c", the first ``limit`` named and the rest counted."""
    items = list(items)
    shown = ", ".join(items[:limit])
    return f"{shown} and {len(items) - limit} more" if len(items) > limit else shown


def in_domains(source, domains):
    """Whether the contract Source ``source`` is in one of ``domains`` (empty: every domain)."""
    return not domains or source.domain in domains


def _one_of(values):
    names = [value.value for value in values]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def filter_terms(wanted):
    """The filters ``wanted`` sets, as {name: {"value", "means"}}, or None when it keeps every source.

    A filter left empty (or a year of 0 or below) keeps every source, so it is left out.
    """
    terms = {
        "domains": (wanted.domains, "The source's domain is {}"),
        "formats": (wanted.formats, "The source is published as {}"),
        "access_methods": (wanted.access_methods, "The source is read through {}"),
        "licenses": (wanted.licenses, "The source is under the {} license"),
    }
    shown = {
        name: {"value": [value.value for value in values], "means": means.format(_one_of(values))}
        for name, (values, means) in terms.items()
        if values
    }
    if wanted.updated_since > 0:
        shown["updated_since"] = {
            "value": wanted.updated_since,
            "means": f"The source was last updated in {wanted.updated_since} or later",
        }
    return shown or None


def filter_problem(wanted):
    if wanted.updated_since < 0:
        return "updated_since must be a year, or 0 for every year"
    return None


def duplicates(ids):
    return sorted({item for item in ids if ids.count(item) > 1})
