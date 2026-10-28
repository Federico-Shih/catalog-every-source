"""record_source: the entry is in catalog.json, where the output says."""

from .catalog import read_catalog
from .checks import CATALOG, SOURCE_ID, result


def verify_input(value):
    if not SOURCE_ID.fullmatch(value.entry.id):
        return result(False, f"{value.entry.id!r} is not a catalog source id")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    if output_value.recorded != input_value.entry or output_value.path != CATALOG:
        return result(False, f"the output is not the requested entry in {CATALOG}")
    entries, problem = read_catalog(workspace)
    if problem:
        return result(False, problem)
    count = output_value.count
    wanted = (input_value.entry.id, input_value.entry.access_method.value)
    if not 1 <= count <= len(entries) or entries[count - 1] != wanted:
        return result(False, f"{CATALOG} does not hold the entry at position {count}")
    return result(True, "the entry is recorded", count=count)
