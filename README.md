# Catalog Every Source

A `nanoagent.plugin/v0001` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source).

An agent pages through a rate-limited mock catalog of 56 data source listings,
records every current source that matches a structured filter in `catalog.json`
with its access method (`rest`, `file`, `hub` or `sql`, as Empiric's
`AccessKind`), and reports the exact total. The catalog ships in
`src/plugin/fixtures/catalog.json` and the rate limit runs on a virtual clock, so
every run is the same and needs no network.

The catalog does not do the work for the agent:

- `list_sources` filters by domain only. The agent applies the rest of the
  filter (formats, access methods, licenses, `updated_since`, inclusive) to
  every listed source itself.
- 8 listings are outdated: their `superseded_by` names the current listing that
  replaces them, which comes later in the catalog and may or may not match the
  filter. An outdated listing is never part of the answer, even when it matches.
- A `next_cursor` is valid only for the domains it paged, and only for 120
  virtual seconds after its page. Waiting out a rate limit keeps it; waiting far
  longer than told expires it, and the agent must list again from the start.

## Tools

| Tool | Does | Code |
|---|---|---|
| `list_sources` | Lists one page (5 sources) of the sources in some domains, outdated listings included; at most 3 calls per 60 virtual seconds, else it raises `rate limited: wait N seconds`; an unknown or expired cursor raises | `src/plugin/listing.py` |
| `wait` | Moves the run's virtual clock forward by 0 to 3600 seconds | `src/plugin/clock.py` |
| `record_source` | Appends a source's id and access method to `catalog.json`; an unknown or repeated id raises | `src/plugin/recording.py` |
| `catalog_truth` | The hidden reference: every current source the filter matches, and their count | `src/plugin/truth.py` |

### Tasks

| Task | Does | Runner |
|---|---|---|
| `catalog-every-source` | Records every current source that matches the filter in `catalog.json` and submits the total; checked against `catalog_truth` | `agent`, with `list_sources`, `wait` and `record_source` |

### Checks

`verify_task` (`verifier/catalog.py`) judges the run against 9 checks, in
order. Each entry of the verdict's `details.checks` has the same keys:
`{id, constraint, ok, expected, actual, message}`. `ok` is `true` (holds),
`false` (fails) or `null` (not checked, because an integrity check failed:
`"Not checked: reference did not hold."`). `expected` and `actual` hold only
the ids concerned, and are `null` otherwise. `task-input` is the exception:
its `actual` lists each filter the task sets, with its value and what it means,
and is `null` when the filter keeps every source. `message` is `""` when the
check holds. Checks 1 to 4 guard the run's integrity, and 5 to 9 judge the
catalog.

For the example filter, `task-input`'s `actual` is:

```json
{
  "domains": {"value": ["health", "energy"], "means": "The source's domain is health or energy"},
  "formats": {"value": ["csv", "parquet"], "means": "The source is published as csv or parquet"},
  "updated_since": {"value": 2019, "means": "The source was last updated in 2019 or later"}
}
```

| # | id | What it checks | Example failure message |
|---|---|---|---|
| 1 | `reference` | `catalog_truth` pinned the reference for this task | catalog_truth was not pinned |
| 2 | `reference-sound` | The reference lists each matching source once, and its total counts them | the reference's total is 7 for 6 sources |
| 3 | `task-input` | The task's filter is valid | updated_since must be a year, or 0 for every year |
| 4 | `catalog-file` | `catalog.json` is absent or holds `{"entries": [...]}` of `{id, access_method}` entries | catalog.json is not JSON |
| 5 | `no-repeats` | No source is recorded twice | 1 source recorded more than once: src-014 |
| 6 | `no-extra` | Every recorded id is a current source the filter matches | 3 sources recorded that the filter drops or that are outdated: src-006, src-024, src-038 |
| 7 | `none-missing` | Every current source the filter matches is recorded | 4 sources that match are not recorded: src-048, src-049, src-051, src-052 |
| 8 | `access-methods` | Each recorded matching source has its right access method | wrong access_method for src-014 (rest, not sql) |
| 9 | `total` | The submitted total is the number of current matching sources | the submitted total is 5, but 6 sources match |

A source that the filter drops, or an outdated listing, counts as an extra id.

### How it is scored

- **Valid** only when all 9 checks hold. The score is then 1.0.
- **Score 0** when any of checks 1 to 4 fails.
- **Otherwise**, the score is the F1 over the recorded entries, times 0.5 when
  the total is wrong, capped at 0.99.
  - A hit is a matching id recorded with its right access method. A wrong
    access method counts as both a false positive and a miss, never as half a
    hit, because the agent only has to copy it from the listing.
  - Precision divides by every recorded entry, repeats included.
  - F1 fits this task because the answer is a set of ids. It costs extra ids
    (an agent that trusts the listing) and missing ids (an agent that stops at
    a rate limit) alike, so recording every source can't beat an exact
    catalog.
  - A wrong total halves the score rather than zeroing it. The count is the
    task's answer, but the catalog work was real.
- **The message** names the first failing check, why it fails, and how many
  more fail. For example: `no-extra: 3 sources recorded that the filter drops
  or that are outdated: src-006, src-024, src-038 (+1 more)`. A valid verdict
  says `all 6 matching sources are recorded`.
- **`details`** also holds `f1`, `total_factor`, `total`, `true_total`,
  `expected` (the reference's ids), and the `extra`, `missing`, `repeated` and
  `wrong_access` ids.

The example run (`tests/examples/catalog-every-source.json`) asks for
health and energy sources in csv or parquet, updated in 2019 or later. The API
lists 21 sources over 5 pages, so the agent is rate-limited once. 6 are the
answer: `src-048` is updated exactly in 2019, and `src-051` only matches as the
newer version of `src-008`. 3 outdated listings (`src-006`, `src-024`,
`src-038`) pass the filter but are not, and `src-024`'s replacement is json.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, one module per tool, engine.py
│   └── fixtures/    # the mock catalog, catalog.json
├── tests/
│   ├── run_agent.sh # one agent run on OpenRouter: config, nanoagent plugin agent, verdict
│   ├── examples/    # the task's example arguments, <id>.json
│   └── results/     # one folder per agent run (git-ignored)
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. Its `Output`
classes are the JSON Schemas the server offers and the agent sees, and every
input and output is built into its class on the way in and out: the server,
NanoAgent and the verifier all get typed values, never loose dicts. A tool
that fails raises; NanoAgent sees an MCP error.

To add a tool: add a `Tool` member, its input and output classes and its
`TOOLS` entry to `contract.py` (a snake_case name, classes named `...Input`
and `...Output`); write its implementation in `src/plugin/`, taking its input
and the workspace and returning its output; write its `verify_input` /
`verify_output` in `verifier/`, and tests for both. Then register it in
`src/plugin/__main__.py` (`IMPLEMENTATIONS`), `verifier/__init__.py` (`TOOLS`),
`nanoagent.yaml` (`tools`) and this README's Tools table; a task goes in its
Tasks table.

`LICENSE` stays the template's MIT license under your name, `.gitignore`
keeps its entries, and this README keeps its title and sections: NanoAgent refuses a plugin
that changes them (rule 10 of `nanoagent.plugin.manifest`). Renaming the
plugin means renaming it in `nanoagent.yaml` and this title together.

To add a task, add a `Task` member (a kebab-case id) and its `TASKS` input and
output classes to `contract.py`, and declare it in `nanoagent.yaml` with its `runner` (`tool`,
`agent` or `decide`) and a `reference` tool, or `null` if it has none. A `tool`
task's classes are its tool's; an `agent` task's agent ends by calling `submit`
with the task's output; a `decide` task's model only chooses, and every tool
argument and output field is an Enum or bool, or copied from a value of exactly
its type in the task's input or an earlier tool output. Then add the check of
its output, `verify_task(arguments, output, reference, workspace)`, to `TASKS`
in `verifier/__init__.py`. People use the plugin by chatting with its agent,
which runs its tasks and shows each output on the page (see `ui/`).

## Develop and run

```bash
uv sync --extra dev
uv run pytest && uv run ruff check . && uv lock --check
```

Run the task with `nanoagent plugin agent`: its run config names this plugin,
the `catalog-every-source` task and its `filter` argument, e.g. domains
`[climate]` with every other list empty and `updated_since: 2020`.

To run the agent, with NanoAgent on `PATH` and an OpenRouter key:

```bash
export OPENROUTER_API_KEY=...          # or ENV_FILE=path/to/keys.env
tests/run_agent.sh                     # tests/examples/catalog-every-source.json
tests/run_agent.sh path/to/arguments.json
```

The script writes a NanoAgent run config (`PluginOpenRouterAgentConfig`), runs
`nanoagent plugin agent`, prints the verdict and exits 0 only when it is
valid. Each run goes to `tests/results/<time>/`, next to the config it ran as
`tests/results/<time>.yaml`: `result.json` (what the agent submitted),
`verdict.json`, `reference.json` (the pinned reference), `messages.json` (the
trajectory), `run.log` and `workspace/` with `.ledger/calls.jsonl`. `MODEL`,
`MAX_STEPS` and `TIMEOUT` override the defaults (`deepseek/deepseek-v4-flash`,
80 steps, 60 seconds per tool call).

Publishing checks every plugin rule: push the plugin to a public GitHub
repository and run `rush publish <server> <github-url>`.
