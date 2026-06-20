# Monitor Status Line

Monitor renders a live status line in the REPL and the TUI. It is a diagnostic summary of current session state, token budget, cost, and history/turn activity.

The exact string is produced by `src/monitor/lib/display_output.py` and reused by the TUI so both front ends show the same counters.

## Example

A status line can look like this:

```text
F:39725156 (95.34%) C:260972 (96%) R:180000000 U:1941510 (~T:$0.406 W:$0.2383 P:$0.0373) L:74601 H:16 (10772) RT:5
```

Not every field appears on every turn. Some values are omitted when they are zero, unavailable, or not meaningful yet.

## Field reference

| Field | Meaning | Notes |
| --- | --- | --- |
| `F:` | Remaining fuel / token budget | Tracks how much budget is left before the session runs out of room. Often shown with a percentage. |
| `C:` | Context remaining / context capacity indicator | Used to show how much prompt context is still available. Usually shown with a percentage. |
| `R:` | Remaining rate / request capacity | A rate-limit style budget indicator. |
| `U:` | Total usage so far | Includes a cost annotation in parentheses. |
| `~T:$` | Total estimated cumulative cost | The tilde marks this as an estimate. |
| `W:$` | Recent window cost | Sum of the last rolling window of turns. Useful for spotting sustained spend. |
| `P:$` | Previous-turn cost | Cost for the most recently completed turn. |
| `L:` | Last request token count | Tokens consumed by the most recent LLM request. |
| `H:` | Retained history count | Number of non-system messages kept in the active history.
| `H:(N)` | Compaction counter prefix | When one or more compactions have fired, the prefix shows how many. |
| `(10772)` | Retained-history token count | The token size of the kept history that will be re-sent on the next request. |
| `RT:` | Previous-turn round trips | Number of model round-trips in the most recently completed turn. |

## How to read it

- `F:` and `C:` are the quickest signals for token pressure.
- `U:` tells you how much this session has cost so far, and the parenthesized cost annotation breaks that into total, recent window, and previous-turn costs.
- `L:` is a per-request token figure, while `H:` is a retained-history size indicator.
- `RT:` helps identify turns that took multiple model passes.
- A nonzero `H:(N)` prefix means compaction has happened during the session.

## Exact vs estimated values

Some values are exact counts, while others are estimates or derived metrics:
- `~T:$` is explicitly estimated.
- `W:$` and `P:$` are derived from rolling turn buckets.
- `L:` and `RT:` reflect the most recent request or turn history.
- `H:` is the retained message count shown by the prompt display.

## Related code

- `src/monitor/lib/display_output.py`
- `src/monitor/core/conversation.py`
- `src/monitor/config.py`
- `src/monitor/lib/token_management.py`
- `src/monitor/lib/model_pricing.py`
