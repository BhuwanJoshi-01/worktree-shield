# Machine-readable output

```bash
worktree-shield scan --format json            # JSON on stdout
worktree-shield scan --strict --format json   # the same, exit 1 when a finding fails
worktree-shield report -f sarif -o worktree-shield.sarif
worktree-shield report -f markdown -o collisions.md
```

All of them are redacted like the terminal output. Home paths become `~`, other users' homes `/home/<user>`, and
credentials and tokens `<redacted>`. The `redactions` list says what was removed.

## JSON

The format is described by [json-schema-v1.json](json-schema-v1.json). Within schema version 1, fields are
added only when they are optional for readers, and never renamed or removed. Every object rejects unknown
fields in the schema, so a change shows up in the contract tests first.

For a preflight, read `summary` first:

| Field | Meaning |
| --- | --- |
| `summary.strict_failure` | `true` when `--strict` would exit with 1: a finding failed under the policy. |
| `summary.worst` | The worst status: `fail`, `warn`, `unknown`, `pass`, `not_tested` or `not_applicable`; `null` without findings. |
| `summary.counts` | The number of findings per status. |
| `summary.worktrees` | The number of worktrees Git lists; `null` when discovery failed. |

Each finding has the following fields:

- `id`: a stable rule ID; see [rules.md](rules.md).
- `status`, `severity`, `confidence`, and `certainty` (for collisions).
- `summary` and `reason`.
- `worktrees` and `sources`: the files and lines behind the finding.
- `evidence`: one item per claim.
- `recommended_action` and `verify_command`.
- `limitations`.
- `caused_by`: the finding this one follows from.

The facts behind them are also in the report:

- `repository` and its worktrees;
- the effective `policy`;
- every `claim`: kind, key, worktree, source, detail, static or runtime;
- `skipped` files and `unreadable` values;
- `runtime` (listeners outside the worktrees, and the limitations of the view);
- `probe_failures`.

A short preflight for an agent:

```bash
worktree-shield scan --strict --format json > wts.json || {
  jq -r '.findings[] | select(.status == "fail") | "\(.id): \(.summary)"' wts.json
  exit 1
}
```

## SARIF

SARIF 2.1.0, for GitHub code scanning and other viewers. Only findings that need attention and point to a
file become results:

| Status | SARIF level |
| --- | --- |
| fail | `error` |
| warn | `warning` |
| unknown | `note` |

A result's locations are the claims in the worktree being scanned, relative to it. The claims of other
worktrees are related locations, and their message names the worktree. `partialFingerprints.worktreeShield/v1`
is derived from the rule and the resource, so it stays the same from one run to the next. The CI of this
project validates a report of the example repository against the official OASIS schema.

## Markdown

The Markdown report is for an issue or a pull request: the counts, a table of every finding, and the details
of what needs attention. Collected text is escaped, so a path containing `|` or `<` cannot change the
document.
