from __future__ import annotations

from pathlib import Path

from contract import ListSourcesInput, ListSourcesOutput
from plugin.engine import page, session_for
from plugin.sources import in_domains

PAGE_SIZE = 5
# At most RATE_LIMIT list_sources calls in each RATE_WINDOW seconds of the run's virtual clock.
RATE_LIMIT = 3
RATE_WINDOW = 60
# A next_cursor stays valid for CURSOR_TTL virtual seconds after the page that returned it: waiting out a rate
# limit keeps it, a much longer wait does not.
CURSOR_TTL = 120

# workspace -> (cursor, domains it pages) -> the virtual second it was issued
ISSUED: dict[Path, dict[tuple[str, tuple[str, ...]], int]] = {}


def list_sources(given: ListSourcesInput, workspace: Path) -> ListSourcesOutput:
    """One page of the sources in the given domains, outdated ones included; raises RateLimited past the limit, and
    on a cursor no page of these domains returned or one that has expired."""
    limiter = session_for(workspace).rate_limit(RATE_LIMIT, RATE_WINDOW)
    issued = ISSUED.setdefault(workspace.resolve(), {})
    domains = tuple(sorted(domain.value for domain in given.domains))
    if given.cursor is not None:
        when = issued.get((given.cursor, domains))
        if when is None:
            raise ValueError(
                f"unknown cursor: {given.cursor!r}; pass the next_cursor a previous page of the same domains returned"
            )
        if limiter.now - when > CURSOR_TTL:
            raise ValueError(
                f"cursor {given.cursor!r} expired {CURSOR_TTL} seconds after its page; list again from cursor null"
            )
    limiter.acquire()
    sources, next_cursor = page(in_domains(given.domains), given.cursor, PAGE_SIZE)
    if next_cursor is not None:
        issued[(next_cursor, domains)] = limiter.now
    return ListSourcesOutput(sources=sources, next_cursor=next_cursor)
