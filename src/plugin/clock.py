from __future__ import annotations

from pathlib import Path

from contract import WaitInput, WaitOutput
from plugin.engine import session_for
from plugin.listing import RATE_LIMIT, RATE_WINDOW

MAX_WAIT = 3600


def wait(given: WaitInput, workspace: Path) -> WaitOutput:
    """Move the run's virtual clock forward; no wall time passes."""
    if not 0 <= given.seconds <= MAX_WAIT:
        raise ValueError(f"seconds must be 0 to {MAX_WAIT}")
    return WaitOutput(now=session_for(workspace).rate_limit(RATE_LIMIT, RATE_WINDOW).wait(given.seconds))
