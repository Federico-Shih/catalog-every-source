"""A scripted agent that works the catalog-every-source task through the real tools, as an agent would."""

from __future__ import annotations

from pathlib import Path

from slimconfig import build_output, plain_output

from contract import CatalogEntry, CatalogInput, CatalogOutput, ListSourcesInput, RecordSourceInput, Source, WaitInput
from plugin import list_sources, record_source, wait
from plugin.engine import RateLimited


def keeps(source: Source, task: CatalogInput) -> bool:
    """The task's filter, as the instructions spell it out for the agent."""
    wanted = task.filter
    return (
        (not wanted.formats or source.format in wanted.formats)
        and (not wanted.access_methods or source.access_method in wanted.access_methods)
        and (not wanted.licenses or source.license in wanted.licenses)
        and source.updated >= wanted.updated_since
    )


def run_agent(
    workspace: Path,
    task: CatalogInput,
    *,
    pages: int | None = None,
    give_up_on_rate_limit: bool = False,
    trust_the_listing: bool = False,
    keep_outdated: bool = False,
    overwait: int = 0,
) -> CatalogOutput:
    """Page through the task's domains and record every current listed source that passes the rest of the filter.

    Each switch makes one mistake: ``pages`` stops after that many pages; ``give_up_on_rate_limit`` stops at the
    first rate limit; ``trust_the_listing`` records every listed source, as if the API applied the whole filter;
    ``keep_outdated`` records superseded listings too; ``overwait`` waits that many seconds more than told.
    """
    cursor: str | None = None
    recorded = 0
    seen = 0
    while True:
        try:
            listed = list_sources(ListSourcesInput(domains=task.filter.domains, cursor=cursor), workspace)
        except RateLimited as limited:
            if give_up_on_rate_limit:
                break
            wait(WaitInput(seconds=limited.retry_after + overwait), workspace)
            continue
        for source in listed.sources:
            current = source.superseded_by is None or keep_outdated
            if trust_the_listing or (current and keeps(source, task)):
                entry = CatalogEntry(id=source.id, access_method=source.access_method)
                record_source(RecordSourceInput(entry=entry), workspace)
                recorded += 1
        seen += 1
        cursor = listed.next_cursor
        if cursor is None or seen == pages:
            break
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(CatalogOutput(total=recorded)), CatalogOutput)
