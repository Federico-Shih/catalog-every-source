"""list_sources: a page of at most PAGE_SIZE sources, each in the requested domains, each replacement a catalog id."""

from .checks import CURSOR, PAGE_SIZE, SOURCE_ID, duplicates, in_domains, result


def verify_input(value):
    if value.cursor is not None and not CURSOR.fullmatch(value.cursor):
        return result(False, f"cursor {value.cursor!r} is not one a page returned")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    sources = output_value.sources
    if len(sources) > PAGE_SIZE:
        return result(False, f"a page holds at most {PAGE_SIZE} sources, not {len(sources)}")
    strays = [source.id for source in sources if not in_domains(source, input_value.domains)]
    if strays:
        return result(False, "the page lists sources outside the requested domains", ids=strays)
    replaced = [source.id for source in sources if source.superseded_by is not None]
    if any(not SOURCE_ID.fullmatch(source.superseded_by) for source in sources if source.superseded_by is not None):
        return result(False, "a listing is superseded by something that is not a catalog id", ids=replaced)
    ids = [source.id for source in sources]
    if duplicates(ids) or ids != sorted(ids):
        return result(False, "the page's sources are repeated or out of catalog order", ids=ids)
    following = output_value.next_cursor
    if following is not None:
        given = CURSOR.fullmatch(input_value.cursor or "cursor-0")
        found = CURSOR.fullmatch(following)
        start = int(given.group(1)) if given else -1
        if not found or int(found.group(1)) != start + PAGE_SIZE or len(sources) != PAGE_SIZE:
            return result(False, f"next_cursor {following!r} does not follow a full page")
    return result(True, f"a page of {len(sources)} sources", last=following is None, superseded=replaced)
